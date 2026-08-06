"""Execution Engine Foundation (EEF) v1.0.

A deterministic execution runtime that consumes validated MSS, PESE state, and
TBE team assignments to manage mission execution lifecycle.  All state
mutations flow through PESEStore.update(); the EEF never bypasses PESE
invariants.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .audit import AuditError, _process_lock
from .config import RuntimeConfig
from .pese import PESEOutcome, PESEStore, utc_compact, utc_now

EEF_FORMAT = "EEF/v1.0"
EEF_EXTENSION_KEY = "org.asc.eef"
SESSION_CREATED = "CREATED"
SESSION_RUNNING = "RUNNING"
SESSION_PAUSED = "PAUSED"
SESSION_CANCELLED = "CANCELLED"
SESSION_COMPLETED = "COMPLETED"
EVENT_TYPES = frozenset(
    {
        "SESSION_STARTED",
        "ASSIGNMENT_ACTIVATED",
        "ASSIGNMENT_DISPATCHED",
        "ASSIGNMENT_COMPLETED",
        "ASSIGNMENT_FAILED",
        "ASSIGNMENT_BLOCKED",
        "SCHEDULE_RESULT",
        "SESSION_PAUSED",
        "SESSION_RESUMED",
        "SESSION_CANCELLED",
        "SESSION_COMPLETED",
        "MILESTONE_ADVANCED",
        # Validation Engine (VAL v1.0) gate events.
        "GATE_STARTED",
        "GATE_PASSED",
        "GATE_FAILED",
        "GATE_BLOCKED",
        "GATE_INVALIDATED",
        # Risk Management (RKM v1.0) risk events.
        "RISK_OPENED",
        "RISK_MITIGATED",
        "RISK_ACCEPTED",
        "RISK_RESOLVED",
        "RISK_HALTED",
        # Agent Lifecycle Control (AGC v1.0) agent events.
        "AGENT_REGISTERED",
        "AGENT_ACTIVATED",
        "AGENT_READY",
        "AGENT_BUSY",
        "AGENT_BLOCKED",
        "AGENT_UNBLOCKED",
        "AGENT_FAILED",
        "AGENT_QUARANTINED",
        "AGENT_REPLACED",
        "AGENT_RELEASED",
        "AGENT_DEPENDENCY",
        "AGENT_HEARTBEAT",
        "AGENT_CHECKPOINTED",
    }
)
MISSION_INTERRUPT_RECOVERY = "MISSION_INTERRUPT_RECOVERY"

_NON_TERMINAL = frozenset({"PENDING", "READY", "IN_PROGRESS", "BLOCKED"})


class EEFError(RuntimeError):
    """A structured EEF precondition or contract failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


# ---------------------------------------------------------------------------
# Event journal — append-only, hash-chained JSONL
# ---------------------------------------------------------------------------

_EEF_JOURNAL_LOCKS: dict[Path, threading.Lock] = {}
_EEF_JOURNAL_GUARD = threading.Lock()


class EEFEventJournal:
    """Append-only JSON-lines execution event journal rooted at ``.project-os/AUDIT``."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        audit_directory: str | Path | None = None,
    ) -> None:
        root = Path(project_root).resolve()
        self.directory = (
            Path(audit_directory)
            if audit_directory is not None
            else root / ".project-os" / "AUDIT"
        ).resolve()
        self.path = (self.directory / "execution-events.jsonl").resolve()
        self.lock_path = self.directory / ".execution-events.jsonl.lock"
        with _EEF_JOURNAL_GUARD:
            self._lock = _EEF_JOURNAL_LOCKS.setdefault(self.path, threading.Lock())

    @staticmethod
    def _canonical_json(record: dict[str, object]) -> str:
        return json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @classmethod
    def _event_hash(cls, record: dict[str, object]) -> str:
        material = {k: v for k, v in record.items() if k != "event_sha256"}
        return hashlib.sha256(cls._canonical_json(material).encode("utf-8")).hexdigest()

    def _last_hash(self) -> str | None:
        if not self.path.exists():
            return None
        last: str | None = None
        with self.path.open("r", encoding="utf-8", newline="") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if last is None:
            return None
        try:
            record = json.loads(last)
            value = record["event_sha256"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AuditError("invalid final EEF event journal entry") from exc
        if not isinstance(value, str) or len(value) != 64:
            raise AuditError("invalid final EEF event journal hash")
        return value

    def append(
        self,
        *,
        event_type: str,
        mission_id: str,
        assignment_id: str | None,
        actor_agent_id: str,
        pese_revision: int | None,
        pese_state_sha256: str | None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        if event_type not in EVENT_TYPES:
            raise EEFError("INVALID_EVENT_TYPE", event_type)
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with _process_lock(self.lock_path):
                sequence = self._next_sequence()
                record: dict[str, object] = {
                    "format": EEF_FORMAT,
                    "kind": "execution-event",
                    "sequence": sequence,
                    "occurred_at": utc_now(),
                    "event_type": event_type,
                    "mission_id": mission_id,
                    "assignment_id": assignment_id,
                    "actor_agent_id": actor_agent_id,
                    "pese_revision": pese_revision,
                    "pese_state_sha256": pese_state_sha256,
                    "previous_event_sha256": self._last_hash(),
                    "detail": detail or {},
                }
                record["event_sha256"] = self._event_hash(record)
                encoded = self._canonical_json(record) + "\n"
                with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(encoded)
                    fh.flush()
                    os.fsync(fh.fileno())
        return dict(record)

    def events(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        result: list[dict[str, object]] = []
        with self.path.open("r", encoding="utf-8", newline="") as fh:
            for line in fh:
                if line.strip():
                    result.append(json.loads(line))
        return result

    def verify_chain(self) -> bool:
        previous: str | None = None
        for record in self.events():
            if record.get("previous_event_sha256") != previous:
                return False
            if record.get("event_sha256") != self._event_hash(record):
                return False
            h = record.get("event_sha256")
            if not isinstance(h, str):
                return False
            previous = h
        return True

    def _next_sequence(self) -> int:
        events = self.events()
        if not events:
            return 1
        sequence = events[-1]["sequence"]
        if not isinstance(sequence, int):
            raise EEFError(
                "INVALID_SEQUENCE", "event journal sequence is not an integer"
            )
        return sequence + 1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Immutable bundle of inputs for an EEF execution session."""

    mission_id: str
    root: Path
    store: PESEStore
    manifest_path: Path
    manifest_version: int
    dependency_edges: tuple[dict[str, str], ...]
    assignments: dict[str, dict[str, Any]]
    milestones: list[dict[str, Any]]
    agent_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    """Outcome of a FIFO schedule/dispatch call."""

    code: str
    assignment_id: str | None = None
    agent_id: str | None = None
    milestone_id: str | None = None
    pese_revision: int | None = None
    findings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionStatus:
    """Read-only snapshot of the current execution lifecycle state."""

    mission_id: str
    mission_status: str
    session_status: str
    current_milestone_id: str | None
    active_assignments: int
    completed_assignments: int
    blocked_assignments: int
    next_task_candidates: tuple[str, ...]
    last_event_sequence: int | None


# ---------------------------------------------------------------------------
# Context factory
# ---------------------------------------------------------------------------


def build_context(
    root: str | Path,
    config: RuntimeConfig,
    mission_id: str,
    actor: str,
) -> tuple[ExecutionContext | None, PESEOutcome | None]:
    """Load PESE state and build an immutable execution context.

    Returns ``(context, None)`` on success or ``(None, outcome)`` on failure.
    """
    root = Path(root).resolve()
    store = PESEStore(root)
    loaded = store.load(actor=actor)
    if loaded.code != "STATE_LOADED":
        return None, loaded
    state = loaded.data["envelope"]["state"]
    missions = state["mission_state"].get("missions", {})
    mission = missions.get(mission_id)
    if mission is None:
        return None, PESEOutcome(
            "MISSION_NOT_FOUND",
            f"OP-{utc_compact()}-{os.getpid()}",
            utc_now(),
            loaded.state_revision,
            loaded.state_sha256,
            ({"code": "MISSION_NOT_FOUND", "detail": f"unknown mission {mission_id}"},),
        )
    manifest_ref = mission.get("manifest_ref", "")
    if manifest_ref:
        mpath = (root / manifest_ref).resolve()
        try:
            mpath.relative_to(root.resolve())
        except ValueError:
            return None, PESEOutcome(
                "MANIFEST_PATH_INVALID",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                loaded.state_revision,
                loaded.state_sha256,
                (
                    {
                        "code": "MANIFEST_PATH_INVALID",
                        "detail": f"unsafe reference {manifest_ref}",
                    },
                ),
            )
        if not mpath.is_file():
            return None, PESEOutcome(
                "MANIFEST_MISSING",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                loaded.state_revision,
                loaded.state_sha256,
                (
                    {
                        "code": "MANIFEST_MISSING",
                        "detail": f"TEAM.md not found at {manifest_ref}",
                    },
                ),
            )
    else:
        mpath = root
    ext_tbe = state.get("extensions", {}).get("org.asc.tbe", {}).get(mission_id, {})
    raw_edges = ext_tbe.get("dependency_edges", [])
    edges = tuple(
        {
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "type": e.get("type", ""),
        }
        for e in raw_edges
        if isinstance(e, Mapping)
    )
    exec_state = state.get("execution_state", {})
    assignments = {
        k: dict(v)
        for k, v in exec_state.get("assignments", {}).items()
        if isinstance(v, Mapping) and v.get("mission_id") == mission_id
    }
    milestones = [
        dict(m) for m in exec_state.get("milestones", []) if isinstance(m, Mapping)
    ]
    agent_ids = tuple(mission.get("assigned_agent_ids", ()))
    return ExecutionContext(
        mission_id=mission_id,
        root=root,
        store=store,
        manifest_path=mpath,
        manifest_version=mission.get("manifest_version", 1),
        dependency_edges=edges,
        assignments=assignments,
        milestones=milestones,
        agent_ids=agent_ids,
    ), None


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------


def _set_assignment_status(
    state: dict[str, Any], assignment_id: str, new_status: str
) -> None:
    assignments = state.get("execution_state", {}).get("assignments", {})
    if assignment_id in assignments:
        assignments[assignment_id]["status"] = new_status
        if new_status == "READY":
            assignments[assignment_id]["started_at"] = None
            assignments[assignment_id]["completed_at"] = None
        elif new_status == "IN_PROGRESS":
            assignments[assignment_id]["started_at"] = utc_now()
        elif new_status in {
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            "BLOCKED",
            "INTERRUPTED",
        }:
            if (
                assignments[assignment_id].get("started_at")
                and new_status == "COMPLETED"
            ):
                assignments[assignment_id]["completed_at"] = utc_now()
        if new_status in {"READY", "PENDING"}:
            assignments[assignment_id]["interruption"] = None


def _activate_root_assignments(state: dict[str, Any], mission_id: str) -> int:
    count = 0
    for aid, a in state.get("execution_state", {}).get("assignments", {}).items():
        if a.get("mission_id") != mission_id:
            continue
        if a.get("status") != "PENDING":
            continue
        if not a.get("depends_on"):
            a["status"] = "READY"
            count += 1
    return count


def _recompute_candidates(state: dict[str, Any], mission_id: str) -> list[str]:
    assignments = state.get("execution_state", {}).get("assignments", {})
    candidates = sorted(
        aid
        for aid, a in assignments.items()
        if a.get("mission_id") == mission_id
        and a.get("status") == "READY"
        and not any(
            assignments.get(dep, {}).get("status") != "COMPLETED"
            for dep in a.get("depends_on", [])
        )
    )
    state.setdefault("execution_state", {})["next_task_candidates"] = candidates
    return candidates


def _eef_extension(state: dict[str, Any], mission_id: str) -> dict[str, Any]:
    ext = state.setdefault("extensions", {})
    mission_ext = ext.setdefault(EEF_EXTENSION_KEY, {})
    mission_data = mission_ext.setdefault(mission_id, {})
    return mission_data


# ---------------------------------------------------------------------------
# Execution session
# ---------------------------------------------------------------------------


class ExecutionSession:
    """Drives the mission execution lifecycle through PESE state transitions."""

    def __init__(self, context: ExecutionContext, *, actor: str) -> None:
        self.ctx = context
        self.actor = actor
        self.journal = EEFEventJournal(context.root)

    def _update(
        self,
        *,
        transition_type: str,
        subject: str,
        from_value: str,
        to_value: str,
        mutate: Any,
        description: str,
    ) -> tuple[PESEOutcome, dict[str, object] | None]:
        loaded = self.ctx.store.load(actor=self.actor)
        if loaded.code != "STATE_LOADED":
            return PESEOutcome(
                "HALTED",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                None,
                None,
                ({"code": "STATE_LOAD_FAILED", "detail": description},),
            ), None
        if loaded.state_revision is None:
            return PESEOutcome(
                "HALTED",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                None,
                None,
                ({"code": "STATE_REVISION_MISSING", "detail": description},),
            ), None
        outcome = self.ctx.store.update(
            expected_revision=loaded.state_revision,
            actor=self.actor,
            transition_type=transition_type,
            subject=subject,
            from_value=from_value,
            to_value=to_value,
            mutate=mutate,
        )
        return outcome, None

    def start(self) -> PESEOutcome:
        loaded = self.ctx.store.load(actor=self.actor)
        if loaded.code != "STATE_LOADED":
            return loaded
        state = loaded.data["envelope"]["state"]
        mission = (
            state["mission_state"].get("missions", {}).get(self.ctx.mission_id, {})
        )
        status = mission.get("status")
        if status != "PLANNED":
            return PESEOutcome(
                "INVALID_TRANSITION",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                loaded.state_revision,
                loaded.state_sha256,
                (
                    {
                        "code": "MISSION_NOT_PLANNED",
                        "detail": f"expected PLANNED, got {status}",
                    },
                ),
            )

        def mutate(state: dict[str, Any]) -> None:
            m = state["mission_state"]["missions"][self.ctx.mission_id]
            m["status"] = "ACTIVE"
            m["started_at"] = utc_now()
            for agent_id in self.ctx.agent_ids:
                agents = state.setdefault("agent_state", {}).setdefault("agents", {})
                if agent_id in agents:
                    dep = agents[agent_id].setdefault(
                        "dependency_environment_state", {}
                    )
                    dep["status"] = "VERIFIED"
            _activate_root_assignments(state, self.ctx.mission_id)
            _recompute_candidates(state, self.ctx.mission_id)
            _eef_extension(state, self.ctx.mission_id).update(
                {
                    "session_status": SESSION_RUNNING,
                    "started_at": utc_now(),
                    "resume_count": 0,
                    "pause_count": 0,
                }
            )

        outcome, _ = self._update(
            transition_type="MISSION_STATUS",
            subject=self.ctx.mission_id,
            from_value="PLANNED",
            to_value="ACTIVE",
            mutate=mutate,
            description="start mission execution",
        )
        if outcome.code != "UPDATED":
            return outcome
        activated = [
            aid for aid, a in self.ctx.assignments.items() if not a.get("depends_on")
        ]
        activated_detail: dict[str, Any] = {"activated_assignments": sorted(activated)}
        checkpoint_data = getattr(outcome, "data", {}) or {}
        if checkpoint_data.get("checkpoint"):
            activated_detail["checkpoint_id"] = checkpoint_data["checkpoint"].get(
                "checkpoint_id"
            )
        ev = self.journal.append(
            event_type="SESSION_STARTED",
            mission_id=self.ctx.mission_id,
            assignment_id=None,
            actor_agent_id=self.actor,
            pese_revision=outcome.state_revision,
            pese_state_sha256=outcome.state_sha256,
            detail=activated_detail,
        )
        ext = _eef_extension(
            self.ctx.store.load(actor=self.actor).data["envelope"]["state"],
            self.ctx.mission_id,
        )
        ext["last_event_sequence"] = ev["sequence"]
        return outcome

    def schedule(self) -> ScheduleResult:
        loaded = self.ctx.store.load(actor=self.actor)
        if loaded.code != "STATE_LOADED":
            return ScheduleResult(
                code="HALTED", findings=({"code": "STATE_LOAD_FAILED"},)
            )
        state = loaded.data["envelope"]["state"]
        active = state["mission_state"].get("active_mission_id")
        if active != self.ctx.mission_id:
            return ScheduleResult(code="NO_ACTIVE_MISSION")
        resume_outcome = self.ctx.store.resume()
        if resume_outcome.code in {"SAFETY_HALT", "RECOVERY_REQUIRED"}:
            return ScheduleResult(
                code=resume_outcome.code,
                findings=resume_outcome.findings,
            )
        if resume_outcome.code == "NO_WORK":
            self.journal.append(
                event_type="SCHEDULE_RESULT",
                mission_id=self.ctx.mission_id,
                assignment_id=None,
                actor_agent_id=self.actor,
                pese_revision=loaded.state_revision,
                pese_state_sha256=loaded.state_sha256,
                detail={"candidates": [], "dispatched": []},
            )
            return ScheduleResult(code="NO_WORK")
        if resume_outcome.code != "RESUME_PLAN":
            return ScheduleResult(
                code=resume_outcome.code, findings=resume_outcome.findings
            )
        candidate_id = resume_outcome.data.get("next_assignment_id", "")
        if not candidate_id:
            return ScheduleResult(code="NO_WORK")
        assignments = state.get("execution_state", {}).get("assignments", {})
        candidate = assignments.get(candidate_id, {})
        if candidate.get("status") != "READY":
            return ScheduleResult(
                code="NOT_READY",
                assignment_id=candidate_id,
                findings=(
                    {
                        "code": "NOT_READY",
                        "detail": f"assignment status is {candidate.get('status')}",
                    },
                ),
            )
        if candidate.get("mission_id") != self.ctx.mission_id:
            return ScheduleResult(code="WRONG_MISSION", assignment_id=candidate_id)
        for edge in self.ctx.dependency_edges:
            if edge["target"] == candidate_id and edge["type"] in {"INPUT", "RESOURCE"}:
                src = assignments.get(edge["source"], {})
                if src.get("status") != "COMPLETED":
                    return ScheduleResult(
                        code="DEPENDENCY_NOT_SATISFIED",
                        assignment_id=candidate_id,
                        findings=(
                            {
                                "code": "DEPENDENCY_NOT_SATISFIED",
                                "detail": f"{edge['source']} is {src.get('status')}",
                            },
                        ),
                    )
        self.journal.append(
            event_type="SCHEDULE_RESULT",
            mission_id=self.ctx.mission_id,
            assignment_id=candidate_id,
            actor_agent_id=self.actor,
            pese_revision=loaded.state_revision,
            pese_state_sha256=loaded.state_sha256,
            detail={"candidates": [candidate_id], "dispatched": [candidate_id]},
        )
        return ScheduleResult(
            code="READY",
            assignment_id=candidate_id,
            agent_id=candidate.get("assigned_agent_id"),
            milestone_id=candidate.get("milestone_id"),
            pese_revision=loaded.state_revision,
        )

    def pause(self) -> PESEOutcome:
        loaded = self.ctx.store.load(actor=self.actor)
        if loaded.code != "STATE_LOADED":
            return loaded
        state = loaded.data["envelope"]["state"]
        mission = state["mission_state"]["missions"].get(self.ctx.mission_id, {})
        if mission.get("status") != "ACTIVE":
            return PESEOutcome(
                "INVALID_TRANSITION",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                loaded.state_revision,
                loaded.state_sha256,
                (
                    {
                        "code": "MISSION_NOT_ACTIVE",
                        "detail": f"expected ACTIVE, got {mission.get('status')}",
                    },
                ),
            )
        interrupted = [
            aid
            for aid, a in state.get("execution_state", {})
            .get("assignments", {})
            .items()
            if a.get("mission_id") == self.ctx.mission_id
            and a.get("status") in _NON_TERMINAL
        ]

        def mutate(state: dict[str, Any]) -> None:
            state["mission_state"]["missions"][self.ctx.mission_id]["status"] = (
                "INTERRUPTED"
            )
            for aid in interrupted:
                _set_assignment_status(state, aid, "INTERRUPTED")
            _recompute_candidates(state, self.ctx.mission_id)
            ext = _eef_extension(state, self.ctx.mission_id)
            ext["session_status"] = SESSION_PAUSED
            ext["pause_count"] = ext.get("pause_count", 0) + 1

        outcome, _ = self._update(
            transition_type="MISSION_STATUS",
            subject=self.ctx.mission_id,
            from_value="ACTIVE",
            to_value="INTERRUPTED",
            mutate=mutate,
            description="pause mission execution",
        )
        if outcome.code == "UPDATED":
            ev = self.journal.append(
                event_type="SESSION_PAUSED",
                mission_id=self.ctx.mission_id,
                assignment_id=None,
                actor_agent_id=self.actor,
                pese_revision=outcome.state_revision,
                pese_state_sha256=outcome.state_sha256,
                detail={"interrupted_assignments": sorted(interrupted)},
            )
            ext = _eef_extension(
                self.ctx.store.load(actor=self.actor).data["envelope"]["state"],
                self.ctx.mission_id,
            )
            ext["last_event_sequence"] = ev["sequence"]
        return outcome

    def resume_session(self) -> PESEOutcome:
        loaded = self.ctx.store.load(actor=self.actor)
        if loaded.code != "STATE_LOADED":
            return loaded
        state = loaded.data["envelope"]["state"]
        mission = state["mission_state"]["missions"].get(self.ctx.mission_id, {})
        if mission.get("status") != "INTERRUPTED":
            return PESEOutcome(
                "INVALID_TRANSITION",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                loaded.state_revision,
                loaded.state_sha256,
                (
                    {
                        "code": "MISSION_NOT_INTERRUPTED",
                        "detail": f"expected INTERRUPTED, got {mission.get('status')}",
                    },
                ),
            )
        interrupteds = [
            aid
            for aid, a in state.get("execution_state", {})
            .get("assignments", {})
            .items()
            if a.get("mission_id") == self.ctx.mission_id
            and a.get("status") == "INTERRUPTED"
        ]

        def mutate(state: dict[str, Any]) -> None:
            state["mission_state"]["missions"][self.ctx.mission_id]["status"] = "ACTIVE"
            for aid in interrupteds:
                _set_assignment_status(state, aid, "READY")
            _recompute_candidates(state, self.ctx.mission_id)
            ext = _eef_extension(state, self.ctx.mission_id)
            ext["session_status"] = SESSION_RUNNING
            ext["resume_count"] = ext.get("resume_count", 0) + 1

        outcome, _ = self._update(
            transition_type=MISSION_INTERRUPT_RECOVERY,
            subject=self.ctx.mission_id,
            from_value="INTERRUPTED",
            to_value="ACTIVE",
            mutate=mutate,
            description="resume interrupted execution",
        )
        if outcome.code == "UPDATED":
            ev = self.journal.append(
                event_type="SESSION_RESUMED",
                mission_id=self.ctx.mission_id,
                assignment_id=None,
                actor_agent_id=self.actor,
                pese_revision=outcome.state_revision,
                pese_state_sha256=outcome.state_sha256,
                detail={"reactivated_assignments": sorted(interrupteds)},
            )
            ext = _eef_extension(
                self.ctx.store.load(actor=self.actor).data["envelope"]["state"],
                self.ctx.mission_id,
            )
            ext["last_event_sequence"] = ev["sequence"]
        return outcome

    def cancel(self) -> PESEOutcome:
        loaded = self.ctx.store.load(actor=self.actor)
        if loaded.code != "STATE_LOADED":
            return loaded
        state = loaded.data["envelope"]["state"]
        mission = state["mission_state"]["missions"].get(self.ctx.mission_id, {})
        current_status = mission.get("status")
        if current_status not in {"ACTIVE", "INTERRUPTED"}:
            return PESEOutcome(
                "INVALID_TRANSITION",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                loaded.state_revision,
                loaded.state_sha256,
                (
                    {
                        "code": "MISSION_NOT_CANCELLABLE",
                        "detail": f"status is {current_status}",
                    },
                ),
            )
        non_terminal = [
            aid
            for aid, a in state.get("execution_state", {})
            .get("assignments", {})
            .items()
            if a.get("mission_id") == self.ctx.mission_id
            and a.get("status") in _NON_TERMINAL
        ]

        def mutate(state: dict[str, Any]) -> None:
            state["mission_state"]["missions"][self.ctx.mission_id]["status"] = (
                "CANCELLED"
            )
            for aid in non_terminal:
                _set_assignment_status(state, aid, "CANCELLED")
            _eef_extension(state, self.ctx.mission_id)["session_status"] = (
                SESSION_CANCELLED
            )

        outcome, _ = self._update(
            transition_type="MISSION_STATUS",
            subject=self.ctx.mission_id,
            from_value=current_status,
            to_value="CANCELLED",
            mutate=mutate,
            description="cancel mission execution",
        )
        if outcome.code == "UPDATED":
            self.journal.append(
                event_type="SESSION_CANCELLED",
                mission_id=self.ctx.mission_id,
                assignment_id=None,
                actor_agent_id=self.actor,
                pese_revision=outcome.state_revision,
                pese_state_sha256=outcome.state_sha256,
                detail={"cancelled_assignments": sorted(non_terminal)},
            )
        return outcome

    def complete(self) -> PESEOutcome:
        loaded = self.ctx.store.load(actor=self.actor)
        if loaded.code != "STATE_LOADED":
            return loaded
        state = loaded.data["envelope"]["state"]
        mission = state["mission_state"]["missions"].get(self.ctx.mission_id, {})
        if mission.get("status") != "ACTIVE":
            return PESEOutcome(
                "INVALID_TRANSITION",
                f"OP-{utc_compact()}-{os.getpid()}",
                utc_now(),
                loaded.state_revision,
                loaded.state_sha256,
                (
                    {
                        "code": "MISSION_NOT_ACTIVE",
                        "detail": f"expected ACTIVE, got {mission.get('status')}",
                    },
                ),
            )

        def mutate(state: dict[str, Any]) -> None:
            state["mission_state"]["missions"][self.ctx.mission_id]["status"] = (
                "VALIDATING"
            )
            _eef_extension(state, self.ctx.mission_id)["session_status"] = (
                SESSION_COMPLETED
            )

        outcome, _ = self._update(
            transition_type="MISSION_STATUS",
            subject=self.ctx.mission_id,
            from_value="ACTIVE",
            to_value="VALIDATING",
            mutate=mutate,
            description="complete mission execution",
        )
        if outcome.code == "UPDATED":
            self.journal.append(
                event_type="SESSION_COMPLETED",
                mission_id=self.ctx.mission_id,
                assignment_id=None,
                actor_agent_id=self.actor,
                pese_revision=outcome.state_revision,
                pese_state_sha256=outcome.state_sha256,
                detail={},
            )
        return outcome

    def status(self) -> ExecutionStatus | PESEOutcome:
        loaded = self.ctx.store.load(actor=self.actor)
        if loaded.code != "STATE_LOADED":
            return loaded
        state = loaded.data["envelope"]["state"]
        mission = state["mission_state"]["missions"].get(self.ctx.mission_id, {})
        mission_status = mission.get("status", "UNKNOWN")
        ext = (
            state.get("extensions", {})
            .get(EEF_EXTENSION_KEY, {})
            .get(self.ctx.mission_id, {})
        )
        session_status = ext.get("session_status", SESSION_CREATED)
        exec_state = state.get("execution_state", {})
        current_milestone = exec_state.get("current_milestone_id")
        assignments = {
            k: v
            for k, v in exec_state.get("assignments", {}).items()
            if isinstance(v, Mapping) and v.get("mission_id") == self.ctx.mission_id
        }
        active = sum(
            1
            for a in assignments.values()
            if a.get("status") in {"READY", "IN_PROGRESS"}
        )
        completed = sum(
            1 for a in assignments.values() if a.get("status") == "COMPLETED"
        )
        blocked = sum(
            1 for a in assignments.values() if a.get("status") in {"BLOCKED", "FAILED"}
        )
        candidates = tuple(exec_state.get("next_task_candidates", []))
        last_seq = ext.get("last_event_sequence")
        return ExecutionStatus(
            mission_id=self.ctx.mission_id,
            mission_status=mission_status,
            session_status=session_status,
            current_milestone_id=current_milestone,
            active_assignments=active,
            completed_assignments=completed,
            blocked_assignments=blocked,
            next_task_candidates=candidates,
            last_event_sequence=last_seq,
        )
