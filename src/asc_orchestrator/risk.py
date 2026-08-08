"""Risk Management (RKM) v1.0.

A deterministic, stdlib-only risk-management runtime that operates the risk
ledger over PESE risk_state and provides the hold mechanism that blocks
autonomous execution on unresolved CRITICAL / HALT risks.  All state
mutations flow through PESEStore.update() with transition_type RISK_STATUS;
the RKM engine never bypasses PESE invariants.

Per PESE v1.0 section 4.7, each risk is a 9-field record in
``risk_state.risks`` and the blocking rule is:

* Any ``HALT`` risk blocks.
* Any unresolved ``CRITICAL`` risk (status not in {RESOLVED, ACCEPTED}) blocks.
* Any ``HIGH`` risk whose declared block condition is met blocks (block
  conditions are stored under the ``org.asc.rkm`` extension key).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .audit import AuditError
from .execution import EEFEventJournal
from .pese import PESEOutcome, PESEStore, utc_compact, utc_now

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RKM_EXTENSION_KEY = "org.asc.rkm"

RISK_SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})


class RiskError(RuntimeError):
    """A structured RKM precondition or contract failure."""

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
class RiskRecord:
    """Read-only snapshot of a risk in the PESE risk ledger."""

    risk_id: str
    status: str
    severity: str
    description: str
    mission_id: str | None
    evidence_refs: tuple[str, ...]
    owner_agent_id: str
    opened_at: str
    resolved_at: str | None


@dataclass(frozen=True, slots=True)
class BlockingRisk:
    """A risk that is blocking autonomous execution."""

    risk_id: str
    severity: str
    status: str
    mission_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class RiskCheck:
    """Hold-mechanism evaluation: whether autonomous execution is blocked."""

    blocked: bool
    blocking_risks: tuple[BlockingRisk, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class RiskReport:
    """Mission-level risk summary."""

    mission_id: str | None
    total: int
    open_count: int
    mitigating_count: int
    accepted_count: int
    resolved_count: int
    halt_count: int
    low_count: int
    medium_count: int
    high_count: int
    critical_count: int
    critical_unresolved_count: int
    blocked: bool


# ---------------------------------------------------------------------------
# Risk engine
# ---------------------------------------------------------------------------


class RiskEngine:
    """Deterministic risk-management runtime operating over PESE/EEF."""

    def __init__(
        self,
        root: str | Path,
        *,
        audit_directory: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._store = PESEStore(self.root)
        self.live_path = self._store.live_path
        self._journal = EEFEventJournal(self.root, audit_directory=audit_directory)
        self._lock = _get_lock(self.root / ".project-os" / "PESE")

    # --- internal helpers ---------------------------------------------------

    def _load_state(self, actor: str) -> tuple[dict[str, Any], int, str] | RiskError:
        """Load PESE state and return ``(state_dict, revision, sha256)``."""
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return RiskError("STATE_LOAD_FAILED", f"PESE load failed: {loaded.code}")
        if loaded.state_revision is None or loaded.state_sha256 is None:
            return RiskError(
                "STATE_LOAD_FAILED", "PESE state missing revision or sha256"
            )
        state = loaded.data["envelope"]["state"]
        return state, loaded.state_revision, loaded.state_sha256

    def _find_risk(self, state: dict[str, Any], risk_id: str) -> dict[str, Any]:
        """Find the risk or raise RiskError."""
        risks = state.get("risk_state", {}).get("risks", {})
        risk = risks.get(risk_id)
        if risk is None or not isinstance(risk, Mapping):
            raise RiskError("RISK_NOT_FOUND", f"risk {risk_id!r} not found")
        return dict(risk)

    def _to_record(self, risk: Mapping[str, Any]) -> RiskRecord:
        return RiskRecord(
            risk_id=risk.get("risk_id", ""),
            status=risk.get("status", ""),
            severity=risk.get("severity", ""),
            description=risk.get("description", ""),
            mission_id=risk.get("mission_id"),
            evidence_refs=tuple(risk.get("evidence_refs", ())),
            owner_agent_id=risk.get("owner_agent_id", ""),
            opened_at=risk.get("opened_at", ""),
            resolved_at=risk.get("resolved_at"),
        )

    def _transition_risk(
        self,
        actor: str,
        risk_id: str,
        from_status: str | None,
        to_status: str,
        mutate_fn: Any,
    ) -> PESEOutcome:
        """Transition a risk through PESE.  Returns the store outcome."""
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
            transition_type="RISK_STATUS",
            subject=risk_id,
            from_value=from_status,
            to_value=to_status,
            mutate=mutate_fn,
        )

    def _emit_event(
        self,
        event_type: str,
        mission_id: str | None,
        risk_id: str,
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
                assignment_id=risk_id,
                actor_agent_id=actor,
                pese_revision=pese_revision,
                pese_state_sha256=pese_state_sha256,
                detail=detail,
            )
        except (AuditError, Exception):
            return None

    def _blocking_reasons(
        self, state: dict[str, Any], mission_id: str | None = None
    ) -> list[BlockingRisk]:
        """Evaluate blocking conditions per PESE section 4.7.

        Returns a list of ``BlockingRisk`` entries that block autonomous
        execution.  When *mission_id* is provided, only risks whose
        ``mission_id`` matches or is ``None`` (company-wide) are evaluated.
        """
        risks = state.get("risk_state", {}).get("risks", {})
        extensions = state.get("extensions", {})
        rkm_ext = extensions.get(RKM_EXTENSION_KEY, {})
        blocking: list[BlockingRisk] = []
        for risk_id, risk in risks.items():
            if not isinstance(risk, Mapping):
                continue
            r_mission = risk.get("mission_id")
            if (
                mission_id is not None
                and r_mission is not None
                and r_mission != mission_id
            ):
                continue
            status = risk.get("status", "")
            severity = risk.get("severity", "")
            # HALT — always blocks.
            if status == "HALT":
                blocking.append(
                    BlockingRisk(
                        risk_id=risk_id,
                        severity=severity,
                        status=status,
                        mission_id=r_mission,
                        reason="halt-risk",
                    )
                )
                continue
            # Unresolved CRITICAL — blocks.
            if severity == "CRITICAL" and status not in {"RESOLVED", "ACCEPTED"}:
                blocking.append(
                    BlockingRisk(
                        risk_id=risk_id,
                        severity=severity,
                        status=status,
                        mission_id=r_mission,
                        reason="unresolved-critical",
                    )
                )
                continue
            # HIGH with declared block condition — blocks.
            if severity == "HIGH":
                bc = rkm_ext.get(risk_id, {}).get("block_condition", {})
                if bc.get("declared"):
                    blocking.append(
                        BlockingRisk(
                            risk_id=risk_id,
                            severity=severity,
                            status=status,
                            mission_id=r_mission,
                            reason="high-block-condition-declared",
                        )
                    )
        return blocking

    # --- public API ---------------------------------------------------------

    def open(
        self,
        risk_id: str,
        severity: str,
        description: str,
        mission_id: str | None,
        owner_agent_id: str,
        *,
        evidence_refs: Sequence[str] | None = None,
        block_condition: dict[str, Any] | None = None,
    ) -> PESEOutcome:
        """Register a new risk in OPEN status.

        If *severity* is ``HIGH`` and *block_condition* is provided, the
        block condition is persisted under the ``org.asc.rkm`` extension key.
        """
        if severity not in RISK_SEVERITIES:
            raise RiskError(
                "INVALID_SEVERITY",
                f"severity must be one of {sorted(RISK_SEVERITIES)}, got {severity!r}",
            )
        if not risk_id:
            raise RiskError("INVALID_RISK_ID", "risk_id must not be empty")
        with self._lock:
            result = self._load_state(owner_agent_id)
            if isinstance(result, RiskError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            risks = state.get("risk_state", {}).get("risks", {})
            if risk_id in risks:
                raise RiskError(
                    "DUPLICATE_RISK_ID",
                    f"risk {risk_id!r} already exists",
                )
            evidence = list(evidence_refs) if evidence_refs else []
            now = utc_now()
            risk_record = {
                "risk_id": risk_id,
                "status": "OPEN",
                "severity": severity,
                "description": description,
                "mission_id": mission_id,
                "evidence_refs": evidence,
                "owner_agent_id": owner_agent_id,
                "opened_at": now,
                "resolved_at": None,
            }

            def mutate(target: dict[str, Any]) -> None:
                target.setdefault("risk_state", {}).setdefault("risks", {})[risk_id] = (
                    dict(risk_record)
                )
                if severity == "HIGH" and block_condition is not None:
                    bc = dict(block_condition)
                    bc.setdefault("declared", True)
                    bc.setdefault("declared_at", now)
                    bc.setdefault("declared_by", owner_agent_id)
                    target.setdefault("extensions", {}).setdefault(
                        RKM_EXTENSION_KEY, {}
                    )[risk_id] = {"block_condition": bc}

            outcome = self._transition_risk(
                owner_agent_id, risk_id, None, "OPEN", mutate
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "RISK_OPENED",
                    mission_id,
                    risk_id,
                    owner_agent_id,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"severity": severity, "description": description},
                )
            return outcome

    def list(
        self,
        mission_id: str | None = None,
        *,
        actor: str = "AGENT:orchestrator:local",
    ) -> tuple[RiskRecord, ...]:
        """Read-only list of risks, optionally filtered by mission."""
        result = self._load_state(actor)
        if isinstance(result, RiskError):
            raise RiskError(result.code, result.detail)
        state, _, _ = result
        risks = state.get("risk_state", {}).get("risks", {})
        out: list[RiskRecord] = []
        for risk_id, risk in risks.items():
            if not isinstance(risk, Mapping):
                continue
            r_mission = risk.get("mission_id")
            if (
                mission_id is not None
                and r_mission is not None
                and r_mission != mission_id
            ):
                continue
            out.append(self._to_record(risk))
        out.sort(key=lambda r: r.risk_id)
        return tuple(out)

    def status(
        self, risk_id: str, *, actor: str = "AGENT:orchestrator:local"
    ) -> RiskRecord:
        """Read-only single risk snapshot."""
        result = self._load_state(actor)
        if isinstance(result, RiskError):
            raise RiskError(result.code, result.detail)
        state, _, _ = result
        risk = self._find_risk(state, risk_id)
        return self._to_record(risk)

    def mitigate(self, risk_id: str, actor: str) -> PESEOutcome:
        """Transition risk OPEN -> MITIGATING."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, RiskError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            risk = self._find_risk(state, risk_id)
            owner = risk.get("owner_agent_id", "")
            if actor != owner and not actor.startswith("AGENT:orchestrator:"):
                raise RiskError(
                    "UNAUTHORIZED",
                    f"actor {actor!r} is not authorized to mitigate risk {risk_id!r}",
                )
            if risk["status"] != "OPEN":
                raise RiskError(
                    "RISK_NOT_OPEN",
                    f"risk {risk_id!r} status is {risk['status']!r}, expected OPEN",
                )

            def mutate(target: dict[str, Any]) -> None:
                r = (
                    target.setdefault("risk_state", {})
                    .setdefault("risks", {})
                    .get(risk_id)
                )
                if r is not None:
                    r["status"] = "MITIGATING"

            outcome = self._transition_risk(
                actor, risk_id, "OPEN", "MITIGATING", mutate
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "RISK_MITIGATED",
                    risk.get("mission_id"),
                    risk_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                )
            return outcome

    def accept(self, risk_id: str, actor: str) -> PESEOutcome:
        """Transition risk OPEN -> ACCEPTED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, RiskError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            risk = self._find_risk(state, risk_id)
            owner = risk.get("owner_agent_id", "")
            if actor != owner and not actor.startswith("AGENT:orchestrator:"):
                raise RiskError(
                    "UNAUTHORIZED",
                    f"actor {actor!r} is not authorized to accept risk {risk_id!r}",
                )
            if risk["status"] != "OPEN":
                raise RiskError(
                    "RISK_NOT_OPEN",
                    f"risk {risk_id!r} status is {risk['status']!r}, expected OPEN",
                )

            def mutate(target: dict[str, Any]) -> None:
                r = (
                    target.setdefault("risk_state", {})
                    .setdefault("risks", {})
                    .get(risk_id)
                )
                if r is not None:
                    r["status"] = "ACCEPTED"

            outcome = self._transition_risk(actor, risk_id, "OPEN", "ACCEPTED", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "RISK_ACCEPTED",
                    risk.get("mission_id"),
                    risk_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                )
            return outcome

    def resolve(
        self,
        risk_id: str,
        actor: str,
        evidence_refs: Sequence[str] | None = None,
    ) -> PESEOutcome:
        """Transition risk OPEN/MITIGATING -> RESOLVED.  Sets resolved_at."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, RiskError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            risk = self._find_risk(state, risk_id)
            owner = risk.get("owner_agent_id", "")
            if actor != owner and not actor.startswith("AGENT:orchestrator:"):
                raise RiskError(
                    "UNAUTHORIZED",
                    f"actor {actor!r} is not authorized to resolve risk {risk_id!r}",
                )
            from_status = risk["status"]
            if from_status not in {"OPEN", "MITIGATING"}:
                raise RiskError(
                    "INVALID_TRANSITION",
                    f"risk {risk_id!r} status is {from_status!r}; "
                    "resolve requires OPEN or MITIGATING",
                )
            now = utc_now()
            new_evidence = (
                list(evidence_refs) if evidence_refs else risk.get("evidence_refs", [])
            )

            def mutate(target: dict[str, Any]) -> None:
                r = (
                    target.setdefault("risk_state", {})
                    .setdefault("risks", {})
                    .get(risk_id)
                )
                if r is not None:
                    r["status"] = "RESOLVED"
                    r["resolved_at"] = now
                    r["evidence_refs"] = new_evidence

            outcome = self._transition_risk(
                actor, risk_id, from_status, "RESOLVED", mutate
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "RISK_RESOLVED",
                    risk.get("mission_id"),
                    risk_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"evidence_refs": new_evidence},
                )
            return outcome

    def halt(self, risk_id: str, actor: str, reason: str) -> PESEOutcome:
        """Transition risk OPEN -> HALT.  Blocks autonomous execution."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, RiskError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            risk = self._find_risk(state, risk_id)
            owner = risk.get("owner_agent_id", "")
            if actor != owner and not actor.startswith("AGENT:orchestrator:"):
                raise RiskError(
                    "UNAUTHORIZED",
                    f"actor {actor!r} is not authorized to halt risk {risk_id!r}",
                )
            if risk["status"] != "OPEN":
                raise RiskError(
                    "RISK_NOT_OPEN",
                    f"risk {risk_id!r} status is {risk['status']!r}, expected OPEN",
                )

            def mutate(target: dict[str, Any]) -> None:
                r = (
                    target.setdefault("risk_state", {})
                    .setdefault("risks", {})
                    .get(risk_id)
                )
                if r is not None:
                    r["status"] = "HALT"

            outcome = self._transition_risk(actor, risk_id, "OPEN", "HALT", mutate)
            if outcome.code == "UPDATED":
                self._emit_event(
                    "RISK_HALTED",
                    risk.get("mission_id"),
                    risk_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"reason": reason},
                )
            return outcome

    def check(
        self,
        mission_id: str | None = None,
        *,
        actor: str = "AGENT:orchestrator:local",
    ) -> RiskCheck:
        """Hold-mechanism evaluation: whether autonomous execution is blocked.

        Read-only.  Returns a ``RiskCheck`` with ``blocked=True`` when any
        HALT risk, any unresolved CRITICAL risk, or any HIGH risk with a
        declared block condition exists.  Mission-scoped evaluation includes
        company-wide risks (``mission_id=None``).
        """
        result = self._load_state(actor)
        if isinstance(result, RiskError):
            raise RiskError(result.code, result.detail)
        state, _, _ = result
        blocking = self._blocking_reasons(state, mission_id)
        if not blocking:
            return RiskCheck(
                blocked=False, blocking_risks=(), reason="no blocking risks"
            )
        reasons = sorted(set(br.reason for br in blocking))
        return RiskCheck(
            blocked=True,
            blocking_risks=tuple(blocking),
            reason=f"blocked by {'; '.join(reasons)}",
        )

    def report(
        self,
        mission_id: str | None = None,
        *,
        actor: str = "AGENT:orchestrator:local",
    ) -> RiskReport:
        """Read-only mission-level risk summary."""
        result = self._load_state(actor)
        if isinstance(result, RiskError):
            raise RiskError(result.code, result.detail)
        state, _, _ = result
        risks = state.get("risk_state", {}).get("risks", {})
        counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        critical_unresolved = 0
        for risk_id, risk in risks.items():
            if not isinstance(risk, Mapping):
                continue
            r_mission = risk.get("mission_id")
            if (
                mission_id is not None
                and r_mission is not None
                and r_mission != mission_id
            ):
                continue
            s = risk.get("status", "OPEN")
            counts[s] = counts.get(s, 0) + 1
            sv = risk.get("severity", "LOW")
            severity_counts[sv] = severity_counts.get(sv, 0) + 1
            if sv == "CRITICAL" and s not in {"RESOLVED", "ACCEPTED"}:
                critical_unresolved += 1
        total = sum(counts.values())
        check = self.check(mission_id, actor=actor)
        return RiskReport(
            mission_id=mission_id,
            total=total,
            open_count=counts.get("OPEN", 0),
            mitigating_count=counts.get("MITIGATING", 0),
            accepted_count=counts.get("ACCEPTED", 0),
            resolved_count=counts.get("RESOLVED", 0),
            halt_count=counts.get("HALT", 0),
            low_count=severity_counts.get("LOW", 0),
            medium_count=severity_counts.get("MEDIUM", 0),
            high_count=severity_counts.get("HIGH", 0),
            critical_count=severity_counts.get("CRITICAL", 0),
            critical_unresolved_count=critical_unresolved,
            blocked=check.blocked,
        )
