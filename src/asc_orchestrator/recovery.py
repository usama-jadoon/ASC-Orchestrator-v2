"""Recovery Engine (REC) v1.0.

A deterministic, stdlib-only agent recovery runtime that automates the
multi-step recovery sequence when agents fail or stall.  REC orchestrates
AGC lifecycle calls and (read-only) AHP health checks, persists a
recovery ledger over PESE, and emits RECOVERY_* events to the EEF
execution journal.

Per the REC v1.0 specification, the recovery sequence is:
quarantine → release → register → activate → dependency VERIFIED →
ready → claim.  Recovery records are persisted under PESE
``recovery_state.recoveries`` with transition type ``RECOVERY_STATUS``.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .agent import AGCError, AgentLifecycle
from .audit import AuditError
from .execution import EEFEventJournal
from .health import HealthStore
from .pese import PESEOutcome, PESEStore, utc_compact, utc_now

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REC_FORMAT = "REC/v1.0"

RECOVERY_STATUSES = frozenset({"IN_PROGRESS", "COMPLETED", "FAILED"})

_RECOVERY_TRANSITIONS: dict[str, set[str]] = {
    "IN_PROGRESS": {"COMPLETED", "FAILED"},
}

_RECOVERY_STATUS_EVENTS: dict[str, str] = {
    "IN_PROGRESS": "RECOVERY_STARTED",
    "COMPLETED": "RECOVERY_COMPLETED",
    "FAILED": "RECOVERY_FAILED",
}

_RECOVERY_ACTIONS: tuple[str, ...] = (
    "QUARANTINED",
    "RELEASED",
    "REGISTERED",
    "ACTIVATED",
    "DEPENDENCY_VERIFIED",
    "READY",
    "CLAIMED",
)

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


def _get_lock(path: Path) -> threading.RLock:
    # RLock (not Lock) so REC's own sequences may re-enter the lock while
    # calling AGC methods (which use their own registry of per-path locks).
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.RLock())


class RecoveryError(RuntimeError):
    """A structured REC precondition or contract failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecoveryDiagnosis:
    """Read-only pre-flight assessment of a potentially failing agent."""

    agent_id: str
    agent_status: str
    health_status: str | None
    trigger: str | None
    recoverable: bool
    reason: str
    mission_id: str | None
    assignment_id: str | None
    acr_ref: str
    suggested_replacement_id: str | None


@dataclass(frozen=True, slots=True)
class RecoveryRecord:
    """Read-only snapshot of a persisted recovery record."""

    recovery_id: str
    format: str
    agent_id: str
    trigger: str
    mission_id: str | None
    assignment_id: str | None
    acr_ref: str
    replacement_agent_id: str
    status: str
    actions: tuple[str, ...]
    created_at: str
    updated_at: str | None
    completed_at: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """Result of a recovery execution."""

    recovery_id: str
    status: str
    replacement_agent_id: str
    actions: tuple[str, ...]
    mission_id: str | None
    assignment_id: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Aggregated recovery summary."""

    total: int
    in_progress_count: int
    completed_count: int
    failed_count: int


# ---------------------------------------------------------------------------
# REC runtime
# ---------------------------------------------------------------------------


class RecoveryEngine:
    """Deterministic agent recovery runtime operating over AGC/AHP/PESE."""

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
        self._lock = _get_lock(self.root / ".project-os" / "PESE")

    # --- internal helpers ---------------------------------------------------

    def _load_state(
        self, actor: str
    ) -> tuple[dict[str, Any], int, str] | RecoveryError:
        """Load PESE state and return ``(state_dict, revision, sha256)``."""
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return RecoveryError(
                "STATE_LOAD_FAILED", f"PESE load failed: {loaded.code}"
            )
        if loaded.state_revision is None or loaded.state_sha256 is None:
            return RecoveryError(
                "STATE_LOAD_FAILED", "PESE state missing revision or sha256"
            )
        state = loaded.data["envelope"]["state"]
        return state, loaded.state_revision, loaded.state_sha256

    def _recoveries(self, state: dict[str, Any]) -> dict[str, Any]:
        return state.setdefault("recovery_state", {}).setdefault("recoveries", {})

    def _find_recovery(self, state: dict[str, Any], recovery_id: str) -> dict[str, Any]:
        """Find the recovery record or raise RecoveryError."""
        recoveries = self._recoveries(state)
        rec = recoveries.get(recovery_id)
        if rec is None or not isinstance(rec, Mapping):
            raise RecoveryError(
                "RECOVERY_NOT_FOUND", f"recovery {recovery_id!r} not found"
            )
        return dict(rec)

    def _to_record(self, rec: Mapping[str, Any]) -> RecoveryRecord:
        return RecoveryRecord(
            recovery_id=rec.get("recovery_id", ""),
            format=rec.get("format", REC_FORMAT),
            agent_id=rec.get("agent_id", ""),
            trigger=rec.get("trigger", ""),
            mission_id=rec.get("mission_id"),
            assignment_id=rec.get("assignment_id"),
            acr_ref=rec.get("acr_ref", ""),
            replacement_agent_id=rec.get("replacement_agent_id", ""),
            status=rec.get("status", ""),
            actions=tuple(rec.get("actions", ())),
            created_at=rec.get("created_at", ""),
            updated_at=rec.get("updated_at"),
            completed_at=rec.get("completed_at"),
            error=rec.get("error"),
        )

    def _transition_recovery(
        self,
        actor: str,
        recovery_id: str,
        from_status: str | None,
        to_status: str,
        mutate_fn: Any,
    ) -> PESEOutcome:
        """Transition a recovery record through PESE."""
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return PESEOutcome(
                "HALTED",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                None,
                None,
                ({"code": "STATE_LOAD_FAILED", "detail": "reload for transition"},),
            )
        if loaded.state_revision is None or loaded.state_sha256 is None:
            return PESEOutcome(
                "HALTED",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                None,
                None,
                (
                    {
                        "code": "STATE_LOAD_FAILED",
                        "detail": "revision or sha256 missing",
                    },
                ),
            )
        return self._store.update(
            expected_revision=loaded.state_revision,
            actor=actor,
            transition_type="RECOVERY_STATUS",
            subject=recovery_id,
            from_value=from_status,
            to_value=to_status,
            mutate=mutate_fn,
        )

    def _emit_event(
        self,
        event_type: str,
        mission_id: str | None,
        recovery_id: str,
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
                assignment_id=recovery_id,
                actor_agent_id=actor,
                pese_revision=pese_revision,
                pese_state_sha256=pese_state_sha256,
                detail=detail,
            )
        except (AuditError, Exception):
            return None

    def _derive_trigger(
        self, agent_status: str, health_status: str | None
    ) -> str | None:
        """Derive the recovery trigger from agent status and AHP health."""
        if agent_status in {"FAILED", "QUARANTINED"}:
            return agent_status
        if agent_status in {"READY", "BUSY", "BLOCKED"} and health_status == "STALLED":
            return "STALLED"
        return None

    def _suggested_replacement(self, state: dict[str, Any], agent_id: str) -> str:
        """Generate a unique replacement agent ID."""
        agents = state.get("agent_state", {}).get("agents", {})
        counter = 1
        while True:
            candidate = f"{agent_id}:recovery:{counter}"
            if candidate not in agents:
                return candidate
            counter += 1

    def _failed_outcome(
        self,
        recovery_id: str,
        actions: list[str],
        error_msg: str,
        mission_id: str | None,
        assignment_id: str | None,
        replacement_id: str,
    ) -> RecoveryOutcome:
        """Build a FAILED RecoveryOutcome."""
        return RecoveryOutcome(
            recovery_id=recovery_id,
            status="FAILED",
            replacement_agent_id=replacement_id,
            actions=tuple(actions),
            mission_id=mission_id,
            assignment_id=assignment_id,
            error=error_msg,
        )

    # --- public API ---------------------------------------------------------

    def diagnose(self, agent_id: str, actor: str) -> RecoveryDiagnosis:
        """Read-only pre-flight assessment of a potentially failing agent.

        Determines the recovery trigger, mission/assignment, acr_ref,
        and a suggested replacement agent ID.
        """
        try:
            agent_rec = self._agc.agent_status(agent_id, actor=actor)
        except AGCError as exc:
            raise RecoveryError(exc.code, exc.detail) from exc
        # AHP health check (best-effort; may fail if no heartbeat journals)
        health_status: str | None = None
        try:
            health = self._ahp.agent_health(agent_id)
            health_status = health.status
        except Exception:
            health_status = None

        trigger = self._derive_trigger(agent_rec.status, health_status)
        recoverable = trigger is not None
        reason = ""
        if agent_rec.status in {"RELEASED", "REPLACED"}:
            reason = f"agent is {agent_rec.status}"
        elif agent_rec.status in {"INITIALIZING", "REGISTERED"}:
            reason = "agent has not reached lifecycle activation"
        elif not recoverable and trigger is None:
            if health_status == "STALLED":
                reason = "AHP reports STALLED but agent is in non-recoverable state"
            elif agent_rec.status == "READY":
                reason = "agent is healthy and READY"
            elif agent_rec.status == "BUSY":
                reason = "agent is healthy and BUSY"
            elif agent_rec.status == "BLOCKED":
                reason = "agent is BLOCKED but heartbeat is still fresh"

        suggested: str | None = None
        if recoverable:
            result = self._load_state(actor)
            if not isinstance(result, RecoveryError):
                state, _, _ = result
                suggested = self._suggested_replacement(state, agent_id)

        return RecoveryDiagnosis(
            agent_id=agent_id,
            agent_status=agent_rec.status,
            health_status=health_status,
            trigger=trigger,
            recoverable=recoverable,
            reason=reason,
            mission_id=agent_rec.mission_id,
            assignment_id=agent_rec.assignment_id,
            acr_ref=agent_rec.acr_ref,
            suggested_replacement_id=suggested,
        )

    def run(
        self,
        agent_id: str,
        actor: str,
        *,
        trigger: str | None = None,
        replacement_agent_id: str | None = None,
        mission_id: str | None = None,
        assignment_id: str | None = None,
    ) -> RecoveryOutcome:
        """Execute the full recovery sequence against AGC.

        Creates a recovery record and runs:
        quarantine → release → register → activate → dependency VERIFIED →
        ready → claim (when mission and assignment are present).
        """
        with self._lock:
            # --- Phase 1: diagnose -------------------------------------------
            diagnosis = self.diagnose(agent_id, actor)
            if not diagnosis.recoverable:
                raise RecoveryError(
                    "NOT_RECOVERABLE",
                    diagnosis.reason or f"agent {agent_id!r} cannot be recovered",
                )
            resolved_trigger = trigger or diagnosis.trigger
            if resolved_trigger is None:
                raise RecoveryError(
                    "TRIGGER_UNKNOWN",
                    f"cannot determine trigger for agent {agent_id!r}",
                )

            # Resolve mission_id / assignment_id from diagnosis if not given.
            resolved_mission = mission_id or diagnosis.mission_id
            resolved_assignment = assignment_id or diagnosis.assignment_id
            acr_ref = diagnosis.acr_ref

            # Resolve replacement ID.
            result = self._load_state(actor)
            if isinstance(result, RecoveryError):
                return self._failed_outcome(
                    "", [], f"state load failed: {result.detail}", None, None, ""
                )
            state, _, _ = result
            replacement_id = replacement_agent_id or self._suggested_replacement(
                state, agent_id
            )

            # --- Phase 2: create recovery record (IN_PROGRESS) -------------
            recovery_count = len(self._recoveries(state))
            recovery_id = f"RECOVERY:{recovery_count + 1:04d}"
            now = utc_now()
            rec_record: dict[str, Any] = {
                "recovery_id": recovery_id,
                "format": REC_FORMAT,
                "agent_id": agent_id,
                "trigger": resolved_trigger,
                "mission_id": resolved_mission,
                "assignment_id": resolved_assignment,
                "acr_ref": acr_ref,
                "replacement_agent_id": replacement_id,
                "status": "IN_PROGRESS",
                "actions": [],
                "created_at": now,
                "updated_at": None,
                "completed_at": None,
                "error": None,
            }

            def mutate_create(target: dict[str, Any]) -> None:
                target.setdefault("recovery_state", {}).setdefault("recoveries", {})[
                    recovery_id
                ] = dict(rec_record)

            outcome = self._transition_recovery(
                actor, recovery_id, None, "IN_PROGRESS", mutate_create
            )
            if outcome.code != "UPDATED":
                return self._failed_outcome(
                    recovery_id,
                    [],
                    "failed to create recovery record",
                    resolved_mission,
                    resolved_assignment,
                    replacement_id,
                )
            self._emit_event(
                "RECOVERY_STARTED",
                resolved_mission,
                recovery_id,
                actor,
                outcome.state_revision,
                outcome.state_sha256,
                {
                    "agent_id": agent_id,
                    "trigger": resolved_trigger,
                    "replacement_agent_id": replacement_id,
                },
            )

            # --- Phase 3: execute AGC sequence ------------------------------
            actions: list[str] = []
            last_error: str | None = None

            def _step(name: str, agc_call: Any, *args: Any, **kwargs: Any) -> bool:
                """Run one AGC step; return True on success."""
                nonlocal last_error
                try:
                    out = agc_call(*args, **kwargs)
                except Exception as exc:
                    last_error = f"{name}: {exc}"
                    return False
                if isinstance(out, PESEOutcome) and out.code == "UPDATED":
                    actions.append(name)
                    return True
                if hasattr(out, "code"):
                    last_error = f"{name}: {getattr(out, 'code', 'UNKNOWN')}"
                else:
                    last_error = f"{name}: unexpected return"
                return False

            # 1. quarantine
            if not _step(
                "QUARANTINED", self._agc.quarantine, agent_id, actor, "RECOVERY"
            ):
                return self._finish_failed(
                    recovery_id,
                    actor,
                    actions,
                    last_error,
                    resolved_mission,
                    resolved_assignment,
                    replacement_id,
                )

            # 2. release
            if not _step("RELEASED", self._agc.release, agent_id, actor):
                return self._finish_failed(
                    recovery_id,
                    actor,
                    actions,
                    last_error,
                    resolved_mission,
                    resolved_assignment,
                    replacement_id,
                )

            # 3. register replacement
            if not _step(
                "REGISTERED", self._agc.register, replacement_id, acr_ref, actor
            ):
                return self._finish_failed(
                    recovery_id,
                    actor,
                    actions,
                    last_error,
                    resolved_mission,
                    resolved_assignment,
                    replacement_id,
                )

            # 4. activate replacement
            if not _step("ACTIVATED", self._agc.activate, replacement_id, actor):
                return self._finish_failed(
                    recovery_id,
                    actor,
                    actions,
                    last_error,
                    resolved_mission,
                    resolved_assignment,
                    replacement_id,
                )

            # 5. dependency VERIFIED (copy original agent's tool/env deps)
            agents = state.get("agent_state", {}).get("agents", {})
            orig_agent = agents.get(agent_id, {})
            orig_dep = orig_agent.get("dependency_environment_state", {})
            tool_deps: dict[str, Any] = {}
            env_deps: dict[str, Any] = {}
            if isinstance(orig_dep, Mapping):
                tool_deps = dict(orig_dep.get("tool_dependencies", {}))
                env_deps = dict(orig_dep.get("environment_dependencies", {}))

            if not _step(
                "DEPENDENCY_VERIFIED",
                self._agc.set_dependency,
                replacement_id,
                "VERIFIED",
                actor,
                tool_dependencies=tool_deps,
                environment_dependencies=env_deps,
            ):
                return self._finish_failed(
                    recovery_id,
                    actor,
                    actions,
                    last_error,
                    resolved_mission,
                    resolved_assignment,
                    replacement_id,
                )

            # 6. ready
            if not _step("READY", self._agc.ready, replacement_id, actor):
                return self._finish_failed(
                    recovery_id,
                    actor,
                    actions,
                    last_error,
                    resolved_mission,
                    resolved_assignment,
                    replacement_id,
                )

            # 7. claim (only when both mission_id and assignment_id present)
            if resolved_mission and resolved_assignment:
                if not _step(
                    "CLAIMED",
                    self._agc.claim,
                    replacement_id,
                    resolved_mission,
                    resolved_assignment,
                    actor,
                ):
                    return self._finish_failed(
                        recovery_id,
                        actor,
                        actions,
                        last_error,
                        resolved_mission,
                        resolved_assignment,
                        replacement_id,
                    )

            # --- Phase 4: mark COMPLETED -------------------------------------
            completed_at = utc_now()

            def mutate_complete(target: dict[str, Any]) -> None:
                rec = (
                    target.get("recovery_state", {})
                    .get("recoveries", {})
                    .get(recovery_id)
                )
                if rec is not None:
                    rec["status"] = "COMPLETED"
                    rec["actions"] = list(actions)
                    rec["updated_at"] = completed_at
                    rec["completed_at"] = completed_at

            outcome = self._transition_recovery(
                actor, recovery_id, "IN_PROGRESS", "COMPLETED", mutate_complete
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "RECOVERY_COMPLETED",
                    resolved_mission,
                    recovery_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"replacement_agent_id": replacement_id, "actions": actions},
                )

            return RecoveryOutcome(
                recovery_id=recovery_id,
                status="COMPLETED",
                replacement_agent_id=replacement_id,
                actions=tuple(actions),
                mission_id=resolved_mission,
                assignment_id=resolved_assignment,
                error=None,
            )

    def _finish_failed(
        self,
        recovery_id: str,
        actor: str,
        actions: list[str],
        error: str | None,
        mission_id: str | None,
        assignment_id: str | None,
        replacement_id: str,
    ) -> RecoveryOutcome:
        """Transition a recovery record to FAILED and emit the event."""
        now = utc_now()

        def mutate_fail(target: dict[str, Any]) -> None:
            rec = (
                target.get("recovery_state", {}).get("recoveries", {}).get(recovery_id)
            )
            if rec is not None:
                rec["status"] = "FAILED"
                rec["actions"] = list(actions)
                rec["updated_at"] = now
                rec["error"] = error

        with self._lock:
            outcome = self._transition_recovery(
                actor, recovery_id, "IN_PROGRESS", "FAILED", mutate_fail
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "RECOVERY_FAILED",
                    mission_id,
                    recovery_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"error": error, "actions_completed": actions},
                )

        return self._failed_outcome(
            recovery_id,
            actions,
            error or "",
            mission_id,
            assignment_id,
            replacement_id,
        )

    def status(
        self, recovery_id: str, *, actor: str = "AGENT:orchestrator:local"
    ) -> RecoveryRecord:
        """Read-only single recovery record."""
        result = self._load_state(actor)
        if isinstance(result, RecoveryError):
            raise RecoveryError(result.code, result.detail)
        state, _, _ = result
        rec = self._find_recovery(state, recovery_id)
        return self._to_record(rec)

    def list(
        self,
        *,
        mission_id: str | None = None,
        agent_id: str | None = None,
        status: str | None = None,
        actor: str = "AGENT:orchestrator:local",
    ) -> tuple[RecoveryRecord, ...]:
        """Read-only list of recovery records, optionally filtered."""
        result = self._load_state(actor)
        if isinstance(result, RecoveryError):
            raise RecoveryError(result.code, result.detail)
        state, _, _ = result
        recoveries = self._recoveries(state)
        out: list[RecoveryRecord] = []
        for rec_id, rec in recoveries.items():
            if not isinstance(rec, Mapping):
                continue
            if mission_id is not None and rec.get("mission_id") != mission_id:
                continue
            if agent_id is not None and rec.get("agent_id") != agent_id:
                continue
            if status is not None and rec.get("status") != status:
                continue
            out.append(self._to_record(rec))
        out.sort(key=lambda r: r.recovery_id)
        return tuple(out)

    def report(self, *, actor: str = "AGENT:orchestrator:local") -> RecoveryReport:
        """Aggregated recovery summary."""
        result = self._load_state(actor)
        if isinstance(result, RecoveryError):
            raise RecoveryError(result.code, result.detail)
        state, _, _ = result
        recoveries = self._recoveries(state)
        counts: dict[str, int] = {}
        for _rec_id, rec in recoveries.items():
            if not isinstance(rec, Mapping):
                continue
            s = rec.get("status", "IN_PROGRESS")
            counts[s] = counts.get(s, 0) + 1
        total = sum(counts.values())
        return RecoveryReport(
            total=total,
            in_progress_count=counts.get("IN_PROGRESS", 0),
            completed_count=counts.get("COMPLETED", 0),
            failed_count=counts.get("FAILED", 0),
        )
