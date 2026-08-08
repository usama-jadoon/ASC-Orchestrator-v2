"""Agent Lifecycle Control (AGC) v1.0.

A deterministic, stdlib-only agent lifecycle runtime that operates the
``agent_state`` ledger over PESE, manages agent registration through
release, tracks dependency environment state and heartbeat/checkpoint
references, and emits AGENT_* events to the EEF execution journal.

Per PESE v1.0 section 4.8, each agent is a 10-field record in
``agent_state.agents``.  AGC enforces its own state machine because
``AGENT_STATUS`` is not in PESE's legal-transition map (the same
pattern used by RKM's ``RISK_STATUS`` and VAL's ``VALIDATION_GATE``).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .audit import AuditError
from .execution import EEFEventJournal
from .pese import PESEOutcome, PESEStore, utc_compact, utc_now

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACTOR_ORCHESTRATOR = "AGENT:orchestrator:local"

_DEP_STATUSES = frozenset({"VERIFIED", "MISSING", "MISMATCH", "UNKNOWN"})

_DEFAULT_DEP: dict[str, Any] = {
    "status": "UNKNOWN",
    "verified_at": None,
    "tool_dependencies": {},
    "environment_dependencies": {},
}


class AGCError(RuntimeError):
    """A structured AGC precondition or contract failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.Lock] = {}


def _get_lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.Lock())


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentRecord:
    """Read-only snapshot of an agent's PESE agent_state record."""

    agent_id: str
    status: str
    mission_id: str | None
    assignment_id: str | None
    manifest_version: str | None
    last_heartbeat_at: str | None
    last_checkpoint_id: str | None
    acr_ref: str
    dep_status: str
    verified_at: str | None
    tool_dependencies: dict[str, Any]
    environment_dependencies: dict[str, Any]
    interruption: Any


@dataclass(frozen=True, slots=True)
class AgentReport:
    """Mission-level agent lifecycle summary."""

    total: int
    initializing_count: int
    registered_count: int
    ready_count: int
    busy_count: int
    blocked_count: int
    failed_count: int
    quarantined_count: int
    replaced_count: int
    released_count: int


# ---------------------------------------------------------------------------
# AGC runtime
# ---------------------------------------------------------------------------


class AgentLifecycle:
    """Deterministic agent lifecycle runtime operating over PESE/EEF."""

    def __init__(
        self,
        root: str | Path,
        *,
        audit_directory: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._store = PESEStore(self.root)
        self._journal = EEFEventJournal(self.root, audit_directory=audit_directory)
        self._lock = _get_lock(self.root / ".project-os" / "PESE")

    # --- internal helpers ---------------------------------------------------

    def _load_state(self, actor: str) -> tuple[dict[str, Any], int, str] | AGCError:
        """Load PESE state and return ``(state_dict, revision, sha256)``."""
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return AGCError("STATE_LOAD_FAILED", f"PESE load failed: {loaded.code}")
        if loaded.state_revision is None or loaded.state_sha256 is None:
            return AGCError(
                "STATE_LOAD_FAILED", "PESE state missing revision or sha256"
            )
        state = loaded.data["envelope"]["state"]
        return state, loaded.state_revision, loaded.state_sha256

    def _agents(self, state: dict[str, Any]) -> dict[str, Any]:
        return state.setdefault("agent_state", {}).setdefault("agents", {})

    def _find_agent(self, state: dict[str, Any], agent_id: str) -> dict[str, Any]:
        """Find the agent record or raise AGCError."""
        agents = self._agents(state)
        agent = agents.get(agent_id)
        if agent is None or not isinstance(agent, Mapping):
            raise AGCError("AGENT_NOT_FOUND", f"agent {agent_id!r} not found")
        return dict(agent)

    def _to_record(self, agent: Mapping[str, Any]) -> AgentRecord:
        dep = agent.get("dependency_environment_state", {})
        if not isinstance(dep, Mapping):
            dep = dict(_DEFAULT_DEP)
        return AgentRecord(
            agent_id=agent.get("agent_id", ""),
            status=agent.get("status", ""),
            mission_id=agent.get("mission_id"),
            assignment_id=agent.get("assignment_id"),
            manifest_version=agent.get("manifest_version"),
            last_heartbeat_at=agent.get("last_heartbeat_at"),
            last_checkpoint_id=agent.get("last_checkpoint_id"),
            acr_ref=agent.get("acr_ref", ""),
            dep_status=dep.get("status", "UNKNOWN"),
            verified_at=dep.get("verified_at"),
            tool_dependencies=dict(dep.get("tool_dependencies", {})),
            environment_dependencies=dict(dep.get("environment_dependencies", {})),
            interruption=agent.get("interruption"),
        )

    def _require_authority(self, actor: str, agent_id: str) -> None:
        """Authorize the actor to transition the agent.

        The orchestrator may manage any agent.  An agent may manage itself.
        """
        if actor != ACTOR_ORCHESTRATOR and actor != agent_id:
            raise AGCError(
                "UNAUTHORIZED",
                f"actor {actor!r} is not authorized to manage agent {agent_id!r}",
            )

    def _transition(
        self,
        actor: str,
        agent_id: str,
        from_status: str | None,
        to_status: str,
        mutate_fn: Any,
    ) -> PESEOutcome:
        """Transition an agent through PESE.  Returns the store outcome."""
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
            transition_type="AGENT_STATUS",
            subject=agent_id,
            from_value=from_status,
            to_value=to_status,
            mutate=mutate_fn,
        )

    def _emit_event(
        self,
        event_type: str,
        mission_id: str | None,
        agent_id: str,
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
                assignment_id=agent_id,
                actor_agent_id=actor,
                pese_revision=pese_revision,
                pese_state_sha256=pese_state_sha256,
                detail=detail,
            )
        except (AuditError, Exception):
            return None

    # --- public API ---------------------------------------------------------

    def register(
        self,
        agent_id: str,
        acr_ref: str,
        actor: str,
    ) -> PESEOutcome:
        """Register a new agent in INITIALIZING status.

        The agent record is created with an ``UNKNOWN`` dependency
        environment state and no mission/assignment assignment.
        """
        if not agent_id:
            raise AGCError("INVALID_AGENT", "agent_id must not be empty")
        if agent_id.startswith("AGENT:orchestrator:"):
            # Reserve the orchestrator namespace (security review F3): no
            # registered agent may impersonate orchestrator authority.
            raise AGCError(
                "INVALID_AGENT",
                f"agent_id must not use the reserved 'AGENT:orchestrator:' "
                f"namespace, got {agent_id!r}",
            )
        if not acr_ref:
            raise AGCError("INVALID_ACR_REF", "acr_ref must not be empty")
        if actor != ACTOR_ORCHESTRATOR:
            raise AGCError(
                "UNAUTHORIZED",
                f"only the orchestrator may register agents, got {actor!r}",
            )
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agents = self._agents(state)
            if agent_id in agents:
                raise AGCError(
                    "DUPLICATE_AGENT",
                    f"agent {agent_id!r} already exists",
                )
            agent_record: dict[str, Any] = {
                "agent_id": agent_id,
                "status": "INITIALIZING",
                "mission_id": None,
                "assignment_id": None,
                "manifest_version": None,
                "last_heartbeat_at": None,
                "last_checkpoint_id": None,
                "acr_ref": acr_ref,
                "dependency_environment_state": dict(_DEFAULT_DEP),
                "interruption": None,
            }

            def mutate(target: dict[str, Any]) -> None:
                target.setdefault("agent_state", {}).setdefault("agents", {})[
                    agent_id
                ] = dict(agent_record)

            outcome = self._transition(actor, agent_id, None, "INITIALIZING", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_REGISTERED",
                    None,
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"acr_ref": acr_ref},
                )
            return outcome

    def activate(self, agent_id: str, actor: str) -> PESEOutcome:
        """Transition INITIALIZING -> REGISTERED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            if agent["status"] != "INITIALIZING":
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {agent['status']!r}, "
                    "expected INITIALIZING",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "REGISTERED"

            outcome = self._transition(
                actor, agent_id, "INITIALIZING", "REGISTERED", mutate
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_ACTIVATED",
                    None,
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                )
            return outcome

    def set_dependency(
        self,
        agent_id: str,
        status: str,
        actor: str,
        *,
        verified_at: str | None = None,
        tool_dependencies: dict[str, Any] | None = None,
        environment_dependencies: dict[str, Any] | None = None,
    ) -> PESEOutcome:
        """Set the agent's dependency_environment_state."""
        if status not in _DEP_STATUSES:
            raise AGCError(
                "INVALID_DEP_STATUS",
                f"dependency status must be one of {sorted(_DEP_STATUSES)}, "
                f"got {status!r}",
            )
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            now = utc_now()

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    dep = a["dependency_environment_state"]
                    dep["status"] = status
                    dep["verified_at"] = verified_at or (
                        now if status == "VERIFIED" else dep.get("verified_at")
                    )
                    if tool_dependencies is not None:
                        dep["tool_dependencies"] = dict(tool_dependencies)
                    if environment_dependencies is not None:
                        dep["environment_dependencies"] = dict(environment_dependencies)

            outcome = self._transition(
                actor,
                agent_id,
                agent["status"],
                agent["status"],
                mutate,
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_DEPENDENCY",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"dep_status": status},
                )
            return outcome

    def ready(self, agent_id: str, actor: str) -> PESEOutcome:
        """Transition REGISTERED -> READY (requires dependency VERIFIED)."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            if agent["status"] != "REGISTERED":
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {agent['status']!r}, "
                    "expected REGISTERED",
                )
            dep = agent.get("dependency_environment_state", {})
            if dep.get("status") != "VERIFIED":
                raise AGCError(
                    "DEPENDENCY_UNVERIFIED",
                    f"agent {agent_id!r} dependency status is "
                    f"{dep.get('status')!r}, expected VERIFIED",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "READY"

            outcome = self._transition(actor, agent_id, "REGISTERED", "READY", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_READY",
                    None,
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                )
            return outcome

    def claim(
        self,
        agent_id: str,
        mission_id: str,
        assignment_id: str,
        actor: str,
    ) -> PESEOutcome:
        """Transition READY -> BUSY (sets mission and assignment)."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            if agent["status"] != "READY":
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {agent['status']!r}, expected READY",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "BUSY"
                    a["mission_id"] = mission_id
                    a["assignment_id"] = assignment_id

            outcome = self._transition(actor, agent_id, "READY", "BUSY", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_BUSY",
                    mission_id,
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"assignment_id": assignment_id},
                )
            return outcome

    def complete(self, agent_id: str, actor: str) -> PESEOutcome:
        """Transition BUSY -> READY (clears mission/assignment)."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            if agent["status"] != "BUSY":
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {agent['status']!r}, expected BUSY",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "READY"
                    a["mission_id"] = None
                    a["assignment_id"] = None

            outcome = self._transition(actor, agent_id, "BUSY", "READY", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_READY",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"returned_from": "BUSY"},
                )
            return outcome

    def block(self, agent_id: str, actor: str, reason: str) -> PESEOutcome:
        """Transition READY/BUSY -> BLOCKED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            current = agent["status"]
            if current not in {"READY", "BUSY"}:
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {current!r}, expected READY or BUSY",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "BLOCKED"

            outcome = self._transition(actor, agent_id, current, "BLOCKED", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_BLOCKED",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"reason": reason, "blocked_from_status": current},
                )
            return outcome

    def unblock(self, agent_id: str, actor: str) -> PESEOutcome:
        """Transition BLOCKED -> READY (clears mission/assignment)."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            if agent["status"] != "BLOCKED":
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {agent['status']!r}, "
                    "expected BLOCKED",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "READY"
                    a["mission_id"] = None
                    a["assignment_id"] = None

            outcome = self._transition(actor, agent_id, "BLOCKED", "READY", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_UNBLOCKED",
                    None,
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                )
            return outcome

    def fail(self, agent_id: str, actor: str, reason: str) -> PESEOutcome:
        """Transition READY/BUSY/BLOCKED -> FAILED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            current = agent["status"]
            if current not in {"READY", "BUSY", "BLOCKED"}:
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {current!r}, "
                    "expected READY, BUSY, or BLOCKED",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "FAILED"
                    a["interruption"] = {"reason": reason, "occurred_at": utc_now()}

            outcome = self._transition(actor, agent_id, current, "FAILED", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_FAILED",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"reason": reason},
                )
            return outcome

    def quarantine(self, agent_id: str, actor: str, reason: str) -> PESEOutcome:
        """Transition READY/BUSY/BLOCKED/FAILED -> QUARANTINED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            current = agent["status"]
            if current not in {"READY", "BUSY", "BLOCKED", "FAILED"}:
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {current!r}, "
                    "expected READY, BUSY, BLOCKED, or FAILED",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "QUARANTINED"
                    a["interruption"] = {"reason": reason, "occurred_at": utc_now()}

            outcome = self._transition(actor, agent_id, current, "QUARANTINED", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_QUARANTINED",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"reason": reason, "quarantined_from_status": current},
                )
            return outcome

    def replace(self, agent_id: str, actor: str, reason: str) -> PESEOutcome:
        """Transition QUARANTINED/FAILED -> REPLACED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            current = agent["status"]
            if current not in {"QUARANTINED", "FAILED"}:
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} status is {current!r}, "
                    "expected QUARANTINED or FAILED",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "REPLACED"

            outcome = self._transition(actor, agent_id, current, "REPLACED", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_REPLACED",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"reason": reason, "replaced_from_status": current},
                )
            return outcome

    def release(self, agent_id: str, actor: str) -> PESEOutcome:
        """Transition READY/BUSY/BLOCKED/FAILED/QUARANTINED/REPLACED -> RELEASED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)
            current = agent["status"]
            if current == "RELEASED":
                raise AGCError(
                    "INVALID_TRANSITION",
                    f"agent {agent_id!r} is already RELEASED",
                )

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["status"] = "RELEASED"
                    a["mission_id"] = None
                    a["assignment_id"] = None

            outcome = self._transition(actor, agent_id, current, "RELEASED", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_RELEASED",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                )
            return outcome

    def heartbeat(
        self,
        agent_id: str,
        actor: str,
        *,
        at: str | None = None,
    ) -> PESEOutcome:
        """Update the agent's last_heartbeat_at reference in PESE state."""
        stamp = at or utc_now()
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["last_heartbeat_at"] = stamp

            outcome = self._transition(
                actor,
                agent_id,
                agent["status"],
                agent["status"],
                mutate,
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_HEARTBEAT",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"at": stamp},
                )
            return outcome

    def update_checkpoint(
        self,
        agent_id: str,
        checkpoint_id: str,
        actor: str,
    ) -> PESEOutcome:
        """Update the agent's last_checkpoint_id reference in PESE state."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AGCError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            agent = self._find_agent(state, agent_id)
            self._require_authority(actor, agent_id)

            def mutate(target: dict[str, Any]) -> None:
                a = (
                    target.setdefault("agent_state", {})
                    .setdefault("agents", {})
                    .get(agent_id)
                )
                if a is not None:
                    a["last_checkpoint_id"] = checkpoint_id

            outcome = self._transition(
                actor,
                agent_id,
                agent["status"],
                agent["status"],
                mutate,
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "AGENT_CHECKPOINTED",
                    agent.get("mission_id"),
                    agent_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"checkpoint_id": checkpoint_id},
                )
            return outcome

    def list(
        self,
        *,
        status: str | None = None,
        mission_id: str | None = None,
        actor: str = "AGENT:orchestrator:local",
    ) -> tuple[AgentRecord, ...]:
        """Read-only list of agents, optionally filtered by status/mission."""
        result = self._load_state(actor)
        if isinstance(result, AGCError):
            raise AGCError(result.code, result.detail)
        state, _, _ = result
        agents = self._agents(state)
        out: list[AgentRecord] = []
        for agent_id_key, agent in agents.items():
            if not isinstance(agent, Mapping):
                continue
            if status is not None and agent.get("status") != status:
                continue
            if mission_id is not None:
                a_mission = agent.get("mission_id")
                if a_mission is not None and a_mission != mission_id:
                    continue
            out.append(self._to_record(agent))
        out.sort(key=lambda r: r.agent_id)
        return tuple(out)

    def agent_status(
        self, agent_id: str, *, actor: str = "AGENT:orchestrator:local"
    ) -> AgentRecord:
        """Read-only single agent snapshot."""
        result = self._load_state(actor)
        if isinstance(result, AGCError):
            raise AGCError(result.code, result.detail)
        state, _, _ = result
        agent = self._find_agent(state, agent_id)
        return self._to_record(agent)

    def report(
        self,
        *,
        actor: str = "AGENT:orchestrator:local",
    ) -> AgentReport:
        """Aggregated lifecycle summary across all agents."""
        result = self._load_state(actor)
        if isinstance(result, AGCError):
            raise AGCError(result.code, result.detail)
        state, _, _ = result
        agents = self._agents(state)
        counts: dict[str, int] = {}
        for _agent_id, agent in agents.items():
            if not isinstance(agent, Mapping):
                continue
            s = agent.get("status", "INITIALIZING")
            counts[s] = counts.get(s, 0) + 1
        total = sum(counts.values())
        return AgentReport(
            total=total,
            initializing_count=counts.get("INITIALIZING", 0),
            registered_count=counts.get("REGISTERED", 0),
            ready_count=counts.get("READY", 0),
            busy_count=counts.get("BUSY", 0),
            blocked_count=counts.get("BLOCKED", 0),
            failed_count=counts.get("FAILED", 0),
            quarantined_count=counts.get("QUARANTINED", 0),
            replaced_count=counts.get("REPLACED", 0),
            released_count=counts.get("RELEASED", 0),
        )
