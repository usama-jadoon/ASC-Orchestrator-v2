"""Autonomous Workflow Scheduler (AWS) v1.0.

A deterministic, stdlib-only top-level orchestration runtime that evaluates
full system state — consuming PESE, EEF, AGC, AHP, REC, RKM, VAL, CKS, and
ETR — and produces one deterministic scheduling decision per tick.  If the
scheduler is ACTIVE and the decision is actionable, AWS delegates the action
to the owning runtime and persists a cycle record under the
``org.asc.aws`` PESE extension.  All state mutations flow through
PESEStore.update() with transition_type ``SCHEDULER_STATUS``.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .aex import AEX
from .agent import AgentLifecycle
from .audit import AuditError
from .config import load_config
from .execution import (
    EEFEventJournal,
    ExecutionSession,
    ScheduleResult,
    build_context,
)
from .health import HealthStore
from .pese import PESEOutcome, PESEStore, utc_compact, utc_now
from .recovery import RecoveryEngine
from .risk import RiskEngine
from .validation import ValidationEngine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AWS_FORMAT = "AWS/v1.0"
AWS_EXTENSION_KEY = "org.asc.aws"

SCHEDULER_STATUSES = frozenset({"ACTIVE", "DISABLED"})
CYCLE_STATUSES = frozenset({"COMPLETED", "FAILED"})

DECISION_TYPES = frozenset(
    {
        "HOLD",
        "RECOVER",
        "START_MISSION",
        "DISPATCH",
        "VALIDATE",
        "COMPLETE_MISSION",
        "MONITOR_HEALTH",
        "IDLE",
    }
)

# Deterministic priority: highest number wins.
_DECISION_PRIORITIES: dict[str, int] = {
    "HOLD": 100,
    "RECOVER": 90,
    "START_MISSION": 80,
    "DISPATCH": 70,
    "VALIDATE": 60,
    "COMPLETE_MISSION": 50,
    "MONITOR_HEALTH": 40,
    "IDLE": 0,
}

# Decisions whose actions mutate state (require scheduler ENABLED).
_EXECUTABLE_DECISIONS = frozenset(
    {"RECOVER", "START_MISSION", "DISPATCH", "VALIDATE", "COMPLETE_MISSION"}
)

# Read-only decisions (always recorded even when disabled).
_READ_ONLY_DECISIONS = frozenset({"HOLD", "MONITOR_HEALTH", "IDLE"})

ACTOR_ORCHESTRATOR = "AGENT:orchestrator:local"

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


def _get_lock(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.RLock())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AwsError(RuntimeError):
    """A structured AWS precondition or contract failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SchedulingDecision:
    """One deterministic scheduling choice, highest-priority wins."""

    decision_type: str
    priority: int
    reason: str
    target_mission_id: str | None = None
    target_agent_id: str | None = None
    target_assignment_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def requires_ai(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class SchedulingAction:
    """Result of executing a scheduling decision."""

    action_code: str
    success: bool
    decision_type: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SchedulingCycle:
    """Complete record of one scheduler tick."""

    cycle_id: str
    format: str
    status: str
    decision_type: str
    priority: int
    reason: str
    action_code: str
    success: bool
    created_at: str
    completed_at: str
    mission_id: str | None
    agent_id: str | None
    assignment_id: str | None
    detail: dict[str, Any] = field(default_factory=dict)
    pese_revision: int | None = None
    pese_state_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SchedulerStatus:
    """Read-only scheduler snapshot."""

    enabled: bool
    active_mission_id: str | None
    cycle_count: int
    last_cycle_id: str | None
    last_decision_type: str | None
    last_action_code: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class SchedulerReport:
    """Aggregated scheduler summary."""

    enabled: bool
    total_cycles: int
    completed_cycles: int
    failed_cycles: int
    decision_counts: dict[str, int]
    action_counts: dict[str, int]
    last_cycle_id: str | None


# ---------------------------------------------------------------------------
# Scheduler runtime
# ---------------------------------------------------------------------------


class AutonomousScheduler:
    """Deterministic top-level orchestration runtime consuming all runtimes."""

    def __init__(
        self,
        root: str | Path,
        *,
        audit_directory: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._store = PESEStore(self.root)
        self._journal = EEFEventJournal(self.root, audit_directory=audit_directory)
        self._agc = AgentLifecycle(self.root, audit_directory=audit_directory)
        self._ahp = HealthStore(self.root)
        self._rec = RecoveryEngine(self.root, audit_directory=audit_directory)
        self._risk = RiskEngine(self.root, audit_directory=audit_directory)
        self._val = ValidationEngine(self.root, audit_directory=audit_directory)
        self._aex = AEX(self.root, audit_directory=audit_directory)
        self._lock = _get_lock(self.root / ".project-os" / "PESE")

    # --- internal helpers ---------------------------------------------------

    def _load_state(self, actor: str) -> tuple[dict[str, Any], int, str]:
        """Load PESE state and return ``(state_dict, revision, sha256)``."""
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            raise AwsError("STATE_LOAD_FAILED", f"PESE load failed: {loaded.code}")
        if loaded.state_revision is None or loaded.state_sha256 is None:
            raise AwsError("STATE_LOAD_FAILED", "PESE state missing revision or sha256")
        state = loaded.data["envelope"]["state"]
        return state, loaded.state_revision, loaded.state_sha256

    def _aws_extension(self, state: dict[str, Any]) -> dict[str, Any]:
        return state.setdefault("extensions", {}).setdefault(AWS_EXTENSION_KEY, {})

    def _scheduler_config(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._aws_extension(state).setdefault("config", {})

    def _cycles(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._aws_extension(state).setdefault("cycles", {})

    def _emit_event(
        self,
        event_type: str,
        mission_id: str | None,
        cycle_id: str,
        actor: str,
        pese_revision: int | None,
        pese_state_sha256: str | None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, object] | None:
        """Append an event to the EEF execution journal (best-effort)."""
        try:
            return self._journal.append(
                event_type=event_type,
                mission_id=mission_id or "SYSTEM",
                assignment_id=cycle_id,
                actor_agent_id=actor,
                pese_revision=pese_revision,
                pese_state_sha256=pese_state_sha256,
                detail=detail,
            )
        except (AuditError, Exception):
            return None

    def _mission_actor(
        self, state: dict[str, Any], mission_id: str, default: str
    ) -> str:
        """Resolve an authorized actor for MISSION_STATUS transitions."""
        mission = state.get("mission_state", {}).get("missions", {}).get(mission_id, {})
        assigned = tuple(mission.get("assigned_agent_ids", ()))
        if default in assigned:
            return default
        return assigned[0] if assigned else default

    def _to_cycle(self, cycle_id: str, record: Mapping[str, Any]) -> SchedulingCycle:
        return SchedulingCycle(
            cycle_id=cycle_id,
            format=record.get("format", AWS_FORMAT),
            status=record.get("status", "FAILED"),
            decision_type=record.get("decision_type", "IDLE"),
            priority=record.get("priority", 0),
            reason=record.get("reason", ""),
            action_code=record.get("action_code", "NONE"),
            success=record.get("success", False),
            created_at=record.get("created_at", ""),
            completed_at=record.get("completed_at", ""),
            mission_id=record.get("mission_id"),
            agent_id=record.get("agent_id"),
            assignment_id=record.get("assignment_id"),
            detail=record.get("detail", {}),
            pese_revision=record.get("pese_revision"),
            pese_state_sha256=record.get("pese_state_sha256"),
        )

    # --- enable / disable ---------------------------------------------------

    def _set_enabled(self, enabled: bool, actor: str) -> PESEOutcome:
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return loaded
        if loaded.state_revision is None or loaded.state_sha256 is None:
            raise AwsError("STATE_LOAD_FAILED", "PESE state missing revision or sha256")
        state = loaded.data["envelope"]["state"]
        cfg = self._scheduler_config(state)
        old_enabled = cfg.get("enabled", True)
        if old_enabled == enabled:
            now = utc_now()
            return PESEOutcome(
                "NO_CHANGE",
                f"OP-{utc_compact()}-{os.getpid()}",
                now,
                loaded.state_revision,
                loaded.state_sha256,
            )

        def mutate(target: dict[str, Any]) -> None:
            ext = target.setdefault("extensions", {}).setdefault(AWS_EXTENSION_KEY, {})
            c = ext.setdefault("config", {})
            c["enabled"] = enabled
            c["updated_at"] = utc_now()

        from_value = "ACTIVE" if old_enabled else "DISABLED"
        to_value = "ACTIVE" if enabled else "DISABLED"
        outcome = self._store.update(
            expected_revision=loaded.state_revision,
            actor=actor,
            transition_type="SCHEDULER_STATUS",
            subject="SCHEDULER",
            from_value=from_value,
            to_value=to_value,
            mutate=mutate,
        )
        if outcome.code == "UPDATED":
            self._emit_event(
                "SCHEDULER_ENABLED" if enabled else "SCHEDULER_DISABLED",
                None,
                "SCHEDULER",
                actor,
                outcome.state_revision,
                outcome.state_sha256,
            )
        return outcome

    def enable(self, *, actor: str = ACTOR_ORCHESTRATOR) -> PESEOutcome:
        """Enable autonomous scheduling."""
        with self._lock:
            return self._set_enabled(True, actor)

    def disable(self, *, actor: str = ACTOR_ORCHESTRATOR) -> PESEOutcome:
        """Disable autonomous scheduling (decisions still evaluated, actions not executed)."""
        with self._lock:
            return self._set_enabled(False, actor)

    # --- evaluation ---------------------------------------------------------

    def _blocking_risk_check(
        self, state: dict[str, Any], *, actor: str = ACTOR_ORCHESTRATOR
    ) -> str | None:
        """Return the blocking reason or None if no risk blocks."""
        try:
            check = self._risk.check(actor=actor)
        except Exception:
            return None
        if check.blocked:
            return check.reason
        return None

    def _find_failed_agent(self, state: dict[str, Any]) -> tuple[str, str] | None:
        """Find a FAILED or QUARANTINED agent (sorted deterministically)."""
        agents = state.get("agent_state", {}).get("agents", {})
        candidates: list[tuple[str, str]] = []
        for agent_id, agent in agents.items():
            if not isinstance(agent, Mapping):
                continue
            status = agent.get("status", "")
            if status in {"FAILED", "QUARANTINED"}:
                candidates.append((agent_id, status))
        candidates.sort(key=lambda c: c[0])
        return candidates[0] if candidates else None

    def _find_stalled_agents(self, state: dict[str, Any]) -> tuple[str, ...]:
        """Find agents STALLED via AHP for the active mission."""
        active = state.get("mission_state", {}).get("active_mission_id")
        if not active:
            return ()
        try:
            return self._ahp.check_stalled(active, now=utc_now())
        except Exception:
            return ()

    def _next_planned_mission(self, state: dict[str, Any]) -> str | None:
        """Find the lexicographically first PLANNED mission."""
        missions = state.get("mission_state", {}).get("missions", {})
        planned = sorted(
            mid
            for mid, m in missions.items()
            if isinstance(m, Mapping) and m.get("status") == "PLANNED"
        )
        return planned[0] if planned else None

    def _dispatch_candidate(
        self, state: dict[str, Any], mission_id: str
    ) -> tuple[str, str] | None:
        """Find the next READY assignment for the mission via EEF schedule."""
        from .execution import ExecutionSession, build_context

        try:
            config = load_config(self.root)
            ctx, err = build_context(self.root, config, mission_id, ACTOR_ORCHESTRATOR)
        except Exception:
            return None
        if err is not None or ctx is None:
            return None
        session = ExecutionSession(ctx, actor=ACTOR_ORCHESTRATOR)
        result = session.schedule()
        if isinstance(result, ScheduleResult) and result.code == "READY":
            if result.assignment_id and result.agent_id:
                return result.assignment_id, result.agent_id
        return None

    def _next_pending_gate(
        self, state: dict[str, Any], mission_id: str
    ) -> tuple[str, str] | None:
        """Find the first PENDING validation gate for the mission."""
        gates = state.get("validation_state", {}).get("gates", {})
        for gate_id in sorted(gates.keys()):
            gate = gates[gate_id]
            if not isinstance(gate, Mapping):
                continue
            if gate.get("mission_id") != mission_id:
                continue
            if gate.get("status") == "PENDING":
                validator = gate.get("validator_agent_id", ACTOR_ORCHESTRATOR)
                return gate_id, validator
        return None

    def _all_assignments_done(self, state: dict[str, Any], mission_id: str) -> bool:
        """True when every assignment in the mission is COMPLETED."""
        assignments = state.get("execution_state", {}).get("assignments", {})
        mission_assignments = [
            a
            for a in assignments.values()
            if isinstance(a, Mapping) and a.get("mission_id") == mission_id
        ]
        if not mission_assignments:
            return False
        return all(a.get("status") == "COMPLETED" for a in mission_assignments)

    def evaluate(self, *, actor: str = ACTOR_ORCHESTRATOR) -> SchedulingDecision:
        """Deterministic priority-based evaluation. Read-only."""
        with self._lock:
            state, _, _ = self._load_state(actor)
            return self._evaluate(state, actor)

    def _evaluate(self, state: dict[str, Any], actor: str) -> SchedulingDecision:
        """Evaluate system state and return the single highest-priority decision."""

        # 1. HOLD — RKM blocks autonomous execution.
        reason = self._blocking_risk_check(state, actor=actor)
        if reason is not None:
            return SchedulingDecision(
                "HOLD",
                _DECISION_PRIORITIES["HOLD"],
                reason,
                detail={"blocking_risks": [reason]},
            )

        # 2. RECOVER — a failed/quarantined/stalled agent needs recovery.
        failed = self._find_failed_agent(state)
        if failed is not None:
            agent_id, status = failed
            return SchedulingDecision(
                "RECOVER",
                _DECISION_PRIORITIES["RECOVER"],
                f"agent {agent_id!r} status is {status}",
                target_agent_id=agent_id,
                detail={"trigger": status},
            )
        stalled = self._find_stalled_agents(state)
        if stalled:
            return SchedulingDecision(
                "RECOVER",
                _DECISION_PRIORITIES["RECOVER"],
                f"agent {stalled[0]!r} is STALLED",
                target_agent_id=stalled[0],
                detail={"trigger": "STALLED"},
            )

        # 3. START_MISSION — no active mission, planned missions exist.
        if state.get("mission_state", {}).get("active_mission_id") is None:
            next_mission = self._next_planned_mission(state)
            if next_mission is not None:
                return SchedulingDecision(
                    "START_MISSION",
                    _DECISION_PRIORITIES["START_MISSION"],
                    f"no active mission; next planned is {next_mission!r}",
                    target_mission_id=next_mission,
                )

        # Active-mission decisions (4–7).
        active = state.get("mission_state", {}).get("active_mission_id")
        if active is not None:
            # 4. DISPATCH — a READY assignment is available.
            candidate = self._dispatch_candidate(state, active)
            if candidate is not None:
                assignment_id, agent_id = candidate
                return SchedulingDecision(
                    "DISPATCH",
                    _DECISION_PRIORITIES["DISPATCH"],
                    f"assignment {assignment_id!r} ready for agent {agent_id!r}",
                    target_mission_id=active,
                    target_agent_id=agent_id,
                    target_assignment_id=assignment_id,
                )

            # 5. VALIDATE — a PENDING gate exists.
            gate = self._next_pending_gate(state, active)
            if gate is not None:
                gate_id, validator = gate
                return SchedulingDecision(
                    "VALIDATE",
                    _DECISION_PRIORITIES["VALIDATE"],
                    f"gate {gate_id!r} is PENDING",
                    target_mission_id=active,
                    target_agent_id=validator,
                    target_assignment_id=gate_id,
                )

            # 6. COMPLETE_MISSION — all assignments COMPLETED.
            if self._all_assignments_done(state, active):
                return SchedulingDecision(
                    "COMPLETE_MISSION",
                    _DECISION_PRIORITIES["COMPLETE_MISSION"],
                    f"all assignments in {active!r} are COMPLETED",
                    target_mission_id=active,
                )

            # 7. MONITOR_HEALTH — active mission, nothing else to do.
            return SchedulingDecision(
                "MONITOR_HEALTH",
                _DECISION_PRIORITIES["MONITOR_HEALTH"],
                f"no actionable work for active mission {active!r}",
                target_mission_id=active,
            )

        # 8. IDLE — no planned missions, no active mission.
        return SchedulingDecision(
            "IDLE",
            _DECISION_PRIORITIES["IDLE"],
            "no missions and no actionable work",
        )

    # --- execution ----------------------------------------------------------

    def _execute_decision(
        self, decision: SchedulingDecision, actor: str
    ) -> SchedulingAction:
        """Execute the decision via the owning runtime. Caller holds self._lock."""
        dtype = decision.decision_type

        if dtype == "RECOVER":
            return self._execute_recover(decision, actor)
        if dtype == "START_MISSION":
            return self._execute_start_mission(decision, actor)
        if dtype == "DISPATCH":
            return self._execute_dispatch(decision)
        if dtype == "VALIDATE":
            return self._execute_validate(decision, actor)
        if dtype == "COMPLETE_MISSION":
            return self._execute_complete_mission(decision, actor)
        if dtype == "MONITOR_HEALTH":
            return self._execute_monitor_health(decision)
        if dtype == "HOLD":
            return SchedulingAction("NONE", True, dtype, decision.detail)
        # IDLE
        return SchedulingAction("NONE", True, dtype)

    def _execute_recover(
        self, decision: SchedulingDecision, actor: str
    ) -> SchedulingAction:
        agent_id = decision.target_agent_id
        if not agent_id:
            return SchedulingAction(
                "RECOVERY_SKIP", False, "RECOVER", {"reason": "no agent"}
            )
        trigger = decision.detail.get("trigger", "UNKNOWN")
        # Resolve mission/assignment from agent state.
        state, _, _ = self._load_state(actor)
        agents = state.get("agent_state", {}).get("agents", {})
        agent = agents.get(agent_id, {})
        mission_id = agent.get("mission_id")
        assignment_id = agent.get("assignment_id")
        try:
            result = self._rec.run(
                agent_id,
                actor,
                trigger=trigger,
                mission_id=mission_id,
                assignment_id=assignment_id,
            )
            return SchedulingAction(
                "RECOVERY_RUN",
                result.status == "COMPLETED",
                "RECOVER",
                {
                    "recovery_id": result.recovery_id,
                    "status": result.status,
                    "replacement_agent_id": result.replacement_agent_id,
                },
            )
        except Exception as exc:
            return SchedulingAction(
                "RECOVERY_RUN", False, "RECOVER", {"error": str(exc)}
            )

    def _execute_start_mission(
        self, decision: SchedulingDecision, actor: str
    ) -> SchedulingAction:
        mission_id = decision.target_mission_id
        if not mission_id:
            return SchedulingAction(
                "EXECUTION_SKIP", False, "START_MISSION", {"reason": "no mission"}
            )
        mission_actor = self._mission_actor(
            self._load_state(actor)[0], mission_id, actor
        )
        try:
            config = load_config(self.root)
            ctx, err = build_context(self.root, config, mission_id, mission_actor)
            if err is not None or ctx is None:
                return SchedulingAction(
                    "EXECUTION_START",
                    False,
                    "START_MISSION",
                    {"error": err.code if err else "CONTEXT_FAILED"},
                )
            session = ExecutionSession(ctx, actor=mission_actor)
            outcome = session.start()
            return SchedulingAction(
                "EXECUTION_START",
                outcome.code == "UPDATED",
                "START_MISSION",
                {"outcome": outcome.code, "mission_id": mission_id},
            )
        except Exception as exc:
            return SchedulingAction(
                "EXECUTION_START",
                False,
                "START_MISSION",
                {"error": str(exc), "mission_id": mission_id},
            )

    def _execute_dispatch(self, decision: SchedulingDecision) -> SchedulingAction:
        mission_id = decision.target_mission_id
        assignment_id = decision.target_assignment_id
        agent_id = decision.target_agent_id
        if mission_id is None or assignment_id is None or agent_id is None:
            return SchedulingAction(
                "ASSIGNMENT_SKIP", False, "DISPATCH", {"reason": "missing ids"}
            )
        try:
            outcome = self._aex.dispatch(mission_id, assignment_id, agent_id)
            return SchedulingAction(
                "ASSIGNMENT_DISPATCH",
                outcome.code == "UPDATED",
                "DISPATCH",
                {
                    "outcome": outcome.code,
                    "mission_id": mission_id,
                    "assignment_id": assignment_id,
                    "agent_id": agent_id,
                },
            )
        except Exception as exc:
            return SchedulingAction(
                "ASSIGNMENT_DISPATCH",
                False,
                "DISPATCH",
                {"error": str(exc), "assignment_id": assignment_id},
            )

    def _execute_validate(
        self, decision: SchedulingDecision, actor: str
    ) -> SchedulingAction:
        mission_id = decision.target_mission_id
        gate_id = decision.target_assignment_id
        validator = decision.target_agent_id or ACTOR_ORCHESTRATOR
        if mission_id is None or gate_id is None:
            return SchedulingAction(
                "GATE_SKIP", False, "VALIDATE", {"reason": "missing ids"}
            )
        try:
            outcome = self._val.start(mission_id, gate_id, validator)
            return SchedulingAction(
                "GATE_START",
                outcome.code == "UPDATED",
                "VALIDATE",
                {
                    "outcome": outcome.code,
                    "mission_id": mission_id,
                    "gate_id": gate_id,
                },
            )
        except Exception as exc:
            return SchedulingAction(
                "GATE_START",
                False,
                "VALIDATE",
                {"error": str(exc), "gate_id": gate_id},
            )

    def _execute_complete_mission(
        self, decision: SchedulingDecision, actor: str
    ) -> SchedulingAction:
        mission_id = decision.target_mission_id
        if not mission_id:
            return SchedulingAction(
                "EXECUTION_SKIP", False, "COMPLETE_MISSION", {"reason": "no mission"}
            )
        mission_actor = self._mission_actor(
            self._load_state(actor)[0], mission_id, actor
        )
        try:
            config = load_config(self.root)
            ctx, err = build_context(self.root, config, mission_id, mission_actor)
            if err is not None or ctx is None:
                return SchedulingAction(
                    "EXECUTION_COMPLETE",
                    False,
                    "COMPLETE_MISSION",
                    {"error": err.code if err else "CONTEXT_FAILED"},
                )
            session = ExecutionSession(ctx, actor=mission_actor)
            outcome = session.complete()
            return SchedulingAction(
                "EXECUTION_COMPLETE",
                outcome.code == "UPDATED",
                "COMPLETE_MISSION",
                {"outcome": outcome.code, "mission_id": mission_id},
            )
        except Exception as exc:
            return SchedulingAction(
                "EXECUTION_COMPLETE",
                False,
                "COMPLETE_MISSION",
                {"error": str(exc), "mission_id": mission_id},
            )

    def _execute_monitor_health(self, decision: SchedulingDecision) -> SchedulingAction:
        mission_id = decision.target_mission_id
        if not mission_id:
            return SchedulingAction(
                "HEALTH_CHECK", True, "MONITOR_HEALTH", {"stalled_agents": []}
            )
        try:
            health = self._ahp.mission_health(mission_id, timeout=300, now=utc_now())
            stalled = [h.agent_id for h in health if h.status == "STALLED"]
            return SchedulingAction(
                "HEALTH_CHECK",
                True,
                "MONITOR_HEALTH",
                {
                    "stalled_agents": stalled,
                    "agent_count": len(health),
                    "mission_id": mission_id,
                },
            )
        except Exception:
            return SchedulingAction(
                "HEALTH_CHECK",
                True,
                "MONITOR_HEALTH",
                {"stalled_agents": [], "mission_id": mission_id},
            )

    def _noop_action(self, decision: SchedulingDecision) -> SchedulingAction:
        """Action for disabled scheduler or non-executable decisions."""
        return SchedulingAction(
            "NONE",
            True,
            decision.decision_type,
            {"disabled": decision.decision_type in _EXECUTABLE_DECISIONS},
        )

    # --- tick (core entry point) -------------------------------------------

    def tick(self, *, actor: str = ACTOR_ORCHESTRATOR) -> SchedulingCycle:
        """Execute one deterministic scheduling cycle.

        Returns a ``SchedulingCycle`` recording the decision and action.
        """
        with self._lock:
            state, revision, sha = self._load_state(actor)
            cfg = self._scheduler_config(state)
            enabled = bool(cfg.get("enabled", True))
            decision = self._evaluate(state, actor)
            if enabled and decision.decision_type in _EXECUTABLE_DECISIONS:
                action = self._execute_decision(decision, actor)
            else:
                action = self._noop_action(decision)

            # Reload fresh state for cycle persistence.
            try:
                state2, revision2, sha2 = self._load_state(actor)
            except AwsError:
                state2, revision2, sha2 = state, revision, sha

            cycles = self._cycles(state2)
            cycle_id = f"CYCLE:{len(cycles) + 1:05d}"
            now = utc_now()
            record = {
                "cycle_id": cycle_id,
                "format": AWS_FORMAT,
                "status": "COMPLETED" if action.success else "FAILED",
                "decision_type": decision.decision_type,
                "priority": decision.priority,
                "reason": decision.reason,
                "action_code": action.action_code,
                "success": action.success,
                "created_at": now,
                "completed_at": now,
                "mission_id": decision.target_mission_id,
                "agent_id": decision.target_agent_id,
                "assignment_id": decision.target_assignment_id,
                "detail": action.detail,
                "requires_ai": decision.requires_ai,
                "enabled": enabled,
                "pese_revision": revision2,
                "pese_state_sha256": sha2,
            }

            def mutate(target: dict[str, Any]) -> None:
                ext = target.setdefault("extensions", {}).setdefault(
                    AWS_EXTENSION_KEY, {}
                )
                c = ext.setdefault("config", {})
                c["last_cycle_id"] = cycle_id
                c["last_decision_type"] = decision.decision_type
                c["last_action_code"] = action.action_code
                c["last_tick_at"] = now
                c.setdefault("cycle_count", 0)
                c["cycle_count"] = c.get("cycle_count", 0) + 1
                ext.setdefault("cycles", {})[cycle_id] = record

            outcome = self._store.update(
                expected_revision=revision2,
                actor=actor,
                transition_type="SCHEDULER_STATUS",
                subject=cycle_id,
                from_value=None,
                to_value="CYCLE",
                mutate=mutate,
            )
            if outcome.code != "UPDATED":
                # Cycle could not be persisted — record a FAILED cycle.
                return SchedulingCycle(
                    cycle_id=cycle_id,
                    format=AWS_FORMAT,
                    status="FAILED",
                    decision_type=decision.decision_type,
                    priority=decision.priority,
                    reason=decision.reason,
                    action_code=action.action_code,
                    success=False,
                    created_at=now,
                    completed_at=now,
                    mission_id=decision.target_mission_id,
                    agent_id=decision.target_agent_id,
                    assignment_id=decision.target_assignment_id,
                    detail={"persist_error": outcome.code},
                )

            self._emit_event(
                "SCHEDULER_CYCLE_COMPLETED",
                decision.target_mission_id,
                cycle_id,
                actor,
                outcome.state_revision,
                outcome.state_sha256,
                {
                    "decision_type": decision.decision_type,
                    "action_code": action.action_code,
                    "success": action.success,
                },
            )
            return self._to_cycle(cycle_id, record)

    # --- status / cycle / list / report ------------------------------------

    def status(self, *, actor: str = ACTOR_ORCHESTRATOR) -> SchedulerStatus:
        """Read-only scheduler snapshot."""
        with self._lock:
            state, _, _ = self._load_state(actor)
            cfg = self._scheduler_config(state)
            active = state.get("mission_state", {}).get("active_mission_id")
            return SchedulerStatus(
                enabled=bool(cfg.get("enabled", True)),
                active_mission_id=active,
                cycle_count=cfg.get("cycle_count", 0),
                last_cycle_id=cfg.get("last_cycle_id"),
                last_decision_type=cfg.get("last_decision_type"),
                last_action_code=cfg.get("last_action_code"),
                reason="no actionable work"
                if cfg.get("last_decision_type") == "IDLE"
                else cfg.get("last_reason", ""),
            )

    def cycle(
        self, cycle_id: str, *, actor: str = ACTOR_ORCHESTRATOR
    ) -> SchedulingCycle:
        """Read-only single cycle snapshot."""
        with self._lock:
            state, _, _ = self._load_state(actor)
            cycles = self._cycles(state)
            record = cycles.get(cycle_id)
            if record is None or not isinstance(record, Mapping):
                raise AwsError("CYCLE_NOT_FOUND", f"cycle {cycle_id!r} not found")
            return self._to_cycle(cycle_id, record)

    def list_cycles(
        self, *, actor: str = ACTOR_ORCHESTRATOR
    ) -> tuple[SchedulingCycle, ...]:
        """Read-only list of all cycles."""
        with self._lock:
            state, _, _ = self._load_state(actor)
            cycles = self._cycles(state)
            return tuple(
                self._to_cycle(cid, rec)
                for cid, rec in sorted(cycles.items())
                if isinstance(rec, Mapping)
            )

    def report(self, *, actor: str = ACTOR_ORCHESTRATOR) -> SchedulerReport:
        """Aggregated scheduler summary."""
        with self._lock:
            state, _, _ = self._load_state(actor)
            cfg = self._scheduler_config(state)
            cycles = self._cycles(state)
            total = len(cycles)
            completed = 0
            failed = 0
            decision_counts: dict[str, int] = {}
            action_counts: dict[str, int] = {}
            for rec in cycles.values():
                if not isinstance(rec, Mapping):
                    continue
                if rec.get("status") == "COMPLETED":
                    completed += 1
                elif rec.get("status") == "FAILED":
                    failed += 1
                dt = rec.get("decision_type", "IDLE")
                decision_counts[dt] = decision_counts.get(dt, 0) + 1
                ac = rec.get("action_code", "NONE")
                action_counts[ac] = action_counts.get(ac, 0) + 1
            return SchedulerReport(
                enabled=bool(cfg.get("enabled", True)),
                total_cycles=total,
                completed_cycles=completed,
                failed_cycles=failed,
                decision_counts=decision_counts,
                action_counts=action_counts,
                last_cycle_id=cfg.get("last_cycle_id"),
            )
