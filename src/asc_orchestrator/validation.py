"""Validation Engine (VAL) v1.0.

A deterministic, stdlib-only validation runtime that drives PESE validation_state
gates through their lifecycle (PENDING -> RUNNING -> GREEN/RED/BLOCKED), registers
and verifies validation artifacts via SHA-256, and emits validation events to the
hash-chained EEF execution journal.  All state mutations flow through
PESEStore.update() with transition_type VALIDATION_GATE; the VAL engine never
bypasses PESE invariants.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .audit import AuditError
from .execution import EEFEventJournal
from .pese import PESEOutcome, PESEStore, utc_compact, utc_now

VAL_FORMAT = "VAL/v1.0"
VAL_EXTENSION_KEY = "org.asc.val"

GATE_STATUSES = frozenset(
    {
        "PENDING",
        "RUNNING",
        "GREEN",
        "RED",
        "BLOCKED",
        "INVALIDATED",
        "WAIVED",
    }
)

_ARTIFACT_FIELDS = frozenset(
    {
        "path",
        "sha256",
        "type",
        "produced_at",
        "producer_agent_id",
        "retention_class",
    }
)

_VERDICT_EVENTS = {
    "GREEN": "GATE_PASSED",
    "RED": "GATE_FAILED",
    "BLOCKED": "GATE_BLOCKED",
}


class VALError(RuntimeError):
    """A structured VAL precondition or contract failure."""

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


def _canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _entry_hash(record: dict[str, Any], *, exclude: str = "entry_hash") -> str:
    material = {k: v for k, v in record.items() if k != exclude}
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_id(identifier: str) -> str:
    """Replace reserved characters for Windows-compatible directory names."""
    return identifier.replace(":", "%3A")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GateStatus:
    """Read-only snapshot of a validation gate."""

    gate_id: str
    mission_id: str
    status: str
    validator_agent_id: str
    manifest_version: int
    criteria_refs: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    last_checkpoint_id: str | None
    verdict_at: str | None


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Read-only snapshot of a registered validation artifact."""

    artifact_id: str
    path: str
    sha256: str
    type: str
    produced_at: str
    producer_agent_id: str
    retention_class: str


@dataclass(frozen=True, slots=True)
class ArtifactVerification:
    """Verification result for a single artifact."""

    artifact_id: str
    path: str
    status: str  # MATCH, MISSING, MISMATCH
    expected_sha256: str
    actual_sha256: str | None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Read-only verification result for all artifacts bound to a gate."""

    gate_id: str
    mission_id: str
    all_match: bool
    artifact_verifications: tuple[ArtifactVerification, ...]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Mission-level validation summary."""

    mission_id: str
    gate_count: int
    green_count: int
    red_count: int
    blocked_count: int
    pending_count: int
    running_count: int
    invalidated_count: int
    waived_count: int
    overall: str  # PASS, FAIL, HOLD
    findings: tuple[dict[str, Any], ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Validation engine
# ---------------------------------------------------------------------------


class ValidationEngine:
    """Deterministic validation runtime operating over PESE/EEF."""

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

    def _load_state(self, actor: str) -> tuple[dict[str, Any], int, str] | VALError:
        """Load PESE state and return ``(state_dict, revision, sha256)``.

        Raises ``VALError`` if the state is not loaded or revision/sha are None.
        """
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return VALError("STATE_LOAD_FAILED", f"PESE load failed: {loaded.code}")
        if loaded.state_revision is None or loaded.state_sha256 is None:
            return VALError(
                "STATE_LOAD_FAILED", "PESE state missing revision or sha256"
            )
        state = loaded.data["envelope"]["state"]
        return state, loaded.state_revision, loaded.state_sha256

    def _find_gate(
        self,
        state: dict[str, Any],
        mission_id: str,
        gate_id: str,
    ) -> dict[str, Any]:
        """Find the gate or raise VALError."""
        gates = state.get("validation_state", {}).get("gates", {})
        gate = gates.get(gate_id)
        if gate is None or not isinstance(gate, Mapping):
            raise VALError(
                "GATE_NOT_FOUND",
                f"gate {gate_id} not found in validation state",
            )
        if gate.get("mission_id") != mission_id:
            raise VALError(
                "GATE_NOT_FOUND",
                f"gate {gate_id} does not belong to mission {mission_id}",
            )
        return dict(gate)

    def _find_mission(self, state: dict[str, Any], mission_id: str) -> dict[str, Any]:
        """Find the mission or raise VALError."""
        missions = state.get("mission_state", {}).get("missions", {})
        mission = missions.get(mission_id)
        if mission is None or not isinstance(mission, Mapping):
            raise VALError(
                "MISSION_NOT_FOUND",
                f"mission {mission_id} not found in PESE state",
            )
        return dict(mission)

    def _require_validator(self, gate: dict[str, Any], actor: str) -> None:
        """Verify that *actor* is the designated validator for *gate*."""
        if gate.get("validator_agent_id") != actor:
            raise VALError(
                "UNAUTHORIZED",
                f"actor {actor} is not the designated validator "
                f"(expected {gate.get('validator_agent_id')})",
            )

    def _transition_gate(
        self,
        actor: str,
        gate_id: str,
        from_status: str,
        to_status: str,
        mutate_fn: Any,
    ) -> PESEOutcome:
        """Transition a gate through PESE.  Returns the store outcome."""
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
            transition_type="VALIDATION_GATE",
            subject=gate_id,
            from_value=from_status,
            to_value=to_status,
            mutate=mutate_fn,
        )

    def _emit_event(
        self,
        event_type: str,
        mission_id: str,
        gate_id: str,
        actor: str,
        pese_revision: int | None,
        pese_state_sha256: str | None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, object] | None:
        """Append an event to the EEF execution journal."""
        try:
            return self._journal.append(
                event_type=event_type,
                mission_id=mission_id,
                assignment_id=gate_id,
                actor_agent_id=actor,
                pese_revision=pese_revision,
                pese_state_sha256=pese_state_sha256,
                detail=detail,
            )
        except (AuditError, Exception):
            return None

    def _artifact_id(self, mission_id: str, gate_id: str, counter: int) -> str:
        """Deterministic artifact ID for a validation artifact."""
        return f"ARTIFACT:VAL:{mission_id}:{gate_id}:{counter:04d}"

    # --- public API ---------------------------------------------------------

    def start(self, mission_id: str, gate_id: str, actor: str) -> PESEOutcome:
        """Begin gate execution: PENDING -> RUNNING."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, VALError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            gate = self._find_gate(state, mission_id, gate_id)
            self._require_validator(gate, actor)
            if gate["status"] != "PENDING":
                raise VALError(
                    "GATE_NOT_PENDING",
                    f"gate {gate_id} status is {gate['status']}, expected PENDING",
                )

            def mutate(target: dict[str, Any]) -> None:
                g = (
                    target.setdefault("validation_state", {})
                    .setdefault("gates", {})
                    .get(gate_id)
                )
                if g is not None:
                    g["status"] = "RUNNING"

            outcome = self._transition_gate(
                actor, gate_id, "PENDING", "RUNNING", mutate
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "GATE_STARTED",
                    mission_id,
                    gate_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {"validator_agent_id": gate["validator_agent_id"]},
                )
            return outcome

    def finish(
        self,
        mission_id: str,
        gate_id: str,
        actor: str,
        *,
        status: str,
        artifacts: list[dict[str, Any]] | None = None,
        reason: str | None = None,
    ) -> PESEOutcome:
        """Conclude gate execution: RUNNING -> GREEN/RED/BLOCKED.

        For GREEN verdicts, *artifacts* must be a non-empty list of artifact
        descriptors with at least ``path``, ``type``, and ``retention_class``.
        SHA-256 hashes are computed from the file bytes on disk and produced_at
        is set to the current UTC timestamp.

        For RED/BLOCKED verdicts, *artifacts* may be omitted.  *reason*
        provides context for the verdict.
        """
        if status not in {"GREEN", "RED", "BLOCKED"}:
            raise VALError(
                "INVALID_VERDICT",
                f"verdict must be GREEN, RED, or BLOCKED, got {status!r}",
            )
        if status == "GREEN" and not artifacts:
            raise VALError(
                "ARTIFACTS_REQUIRED",
                "GREEN verdict requires at least one validation artifact",
            )
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, VALError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _ = result
            gate = self._find_gate(state, mission_id, gate_id)
            self._require_validator(gate, actor)
            if gate["status"] != "RUNNING":
                raise VALError(
                    "GATE_NOT_RUNNING",
                    f"gate {gate_id} status is {gate['status']}, expected RUNNING",
                )

            # Pre-validate artifact files for GREEN verdicts.
            prepared: list[tuple[str, Path, dict[str, Any]]] = []
            if artifacts:
                for i, art in enumerate(artifacts):
                    raw_path = art.get("path", "")
                    if not raw_path:
                        raise VALError(
                            "ARTIFACT_PATH_MISSING",
                            f"artifact {i} has no path",
                        )
                    art_path = Path(raw_path)
                    if not art_path.is_absolute():
                        art_path = self.root / art_path
                    resolved = art_path.resolve()
                    try:
                        resolved.relative_to(self.root)
                    except ValueError:
                        raise VALError(
                            "ARTIFACT_ESCAPE",
                            f"artifact path escapes repository root: {raw_path}",
                        )
                    if not resolved.is_file():
                        raise VALError(
                            "ARTIFACT_NOT_FOUND",
                            f"artifact file not found: {raw_path}",
                        )
                    content = resolved.read_bytes()
                    sha = _sha256_hex(content)
                    aid = self._artifact_id(
                        mission_id,
                        gate_id,
                        len(prepared) + len(gate.get("artifact_ids", ())),
                    )
                    prepared.append(
                        (
                            aid,
                            resolved,
                            {
                                "path": str(resolved.relative_to(self.root)).replace(
                                    "\\", "/"
                                ),
                                "sha256": sha,
                                "type": art.get("type", "validation-result"),
                                "produced_at": utc_now(),
                                "producer_agent_id": actor,
                                "retention_class": art.get(
                                    "retention_class", "mission"
                                ),
                            },
                        )
                    )

            all_artifact_ids = list(gate.get("artifact_ids", ()))
            all_artifacts_to_register = {aid: rec for aid, _, rec in prepared}

            def mutate(target: dict[str, Any]) -> None:
                g = (
                    target.setdefault("validation_state", {})
                    .setdefault("gates", {})
                    .get(gate_id)
                )
                if g is not None:
                    g["status"] = status
                    g["verdict_at"] = utc_now()
                    g["artifact_ids"] = all_artifact_ids + list(
                        all_artifacts_to_register.keys()
                    )
                vs = target.setdefault("validation_state", {})
                arts = vs.setdefault("artifacts", {})
                for aid, rec in all_artifacts_to_register.items():
                    arts[aid] = rec

            outcome = self._transition_gate(actor, gate_id, "RUNNING", status, mutate)
            if outcome.code == "UPDATED":
                event_type = _VERDICT_EVENTS[status]
                detail: dict[str, Any] = {
                    "verdict": status,
                    "artifact_count": len(prepared),
                }
                if reason:
                    detail["reason"] = reason
                self._emit_event(
                    event_type,
                    mission_id,
                    gate_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    detail,
                )
            return outcome

    def _check_artifact_files(
        self,
        gate: Mapping[str, Any],
        artifacts: Mapping[str, Any],
    ) -> tuple[tuple[ArtifactVerification, ...], bool]:
        """Compare bound artifact files against recorded hashes."""
        verifications: list[ArtifactVerification] = []
        all_match = True
        for aid in gate.get("artifact_ids", ()):
            art = artifacts.get(aid)
            if art is None or not isinstance(art, Mapping):
                verifications.append(ArtifactVerification(aid, "", "MISSING", "", None))
                all_match = False
                continue
            art_path = art.get("path", "")
            expected = art.get("sha256", "")
            # Guard against path escape in untrusted state data.
            try:
                full_path = self.root.joinpath(art_path).resolve()
                full_path.relative_to(self.root)
            except (ValueError, OSError):
                verifications.append(
                    ArtifactVerification(aid, art_path, "MISSING", expected, None)
                )
                all_match = False
                continue
            if not full_path.is_file():
                verifications.append(
                    ArtifactVerification(aid, art_path, "MISSING", expected, None)
                )
                all_match = False
                continue
            actual = _sha256_hex(full_path.read_bytes())
            if actual == expected:
                verifications.append(
                    ArtifactVerification(aid, art_path, "MATCH", expected, actual)
                )
            else:
                verifications.append(
                    ArtifactVerification(aid, art_path, "MISMATCH", expected, actual)
                )
                all_match = False
        return tuple(verifications), all_match

    def verify(self, mission_id: str, gate_id: str, actor: str) -> VerificationResult:
        """Verify all artifacts bound to a gate exist and match their hashes.

        This is a read-only operation that does not transition state.

        When PESE state is loadable (all artifacts intact), verification is
        performed against the validated state.  When tampered artifacts make
        the state unloadable (``STATE_CORRUPT``), a raw read of ``live.json``
        provides per-artifact diagnostic information so the operator can
        identify the specific file that broke the integrity chain.
        """
        result = self._load_state(actor)
        if not isinstance(result, VALError):
            state, _, _ = result
            gate = self._find_gate(state, mission_id, gate_id)
            artifacts = state.get("validation_state", {}).get("artifacts", {})
            avs, all_match = self._check_artifact_files(gate, artifacts)
            return VerificationResult(
                gate_id=gate_id,
                mission_id=mission_id,
                all_match=all_match,
                artifact_verifications=avs,
            )

        # PESE state is corrupt (likely tampered artifacts).  Read the raw
        # live.json to provide per-artifact diagnostic information so the
        # operator can identify the file that broke the integrity chain.
        # This is strictly read-only and does NOT assert state validity.
        # Fail closed: a verdict computed from unverified state is never
        # authoritative, so all_match is forced False regardless of what the
        # raw read happens to show.
        from .pese import _json_load  # local to avoid circular at module level

        try:
            envelope = _json_load(self.live_path)
            state = envelope.get("state", {})
        except Exception as exc:
            raise VALError(
                "STATE_LOAD_FAILED",
                f"PESE load failed: {result.detail}; raw read: {exc}",
            ) from exc
        gate = self._find_gate(state, mission_id, gate_id)
        artifacts = state.get("validation_state", {}).get("artifacts", {})
        avs, _ = self._check_artifact_files(gate, artifacts)
        return VerificationResult(
            gate_id=gate_id,
            mission_id=mission_id,
            all_match=False,
            artifact_verifications=avs,
        )

    def _binding_failed(self, state: dict[str, Any]) -> list[str]:
        """Check artifact and repository binding against current disk state.

        Returns a list of failure reasons (empty = binding is sound).
        """
        reasons: list[str] = []
        # Artifact binding: check every artifact record in validation_state.
        artifacts = state.get("validation_state", {}).get("artifacts", {})
        for aid, art in artifacts.items():
            if not isinstance(art, Mapping):
                reasons.append(f"artifact {aid} has invalid record")
                continue
            art_path = art.get("path", "")
            expected = art.get("sha256", "")
            try:
                full = self.root.joinpath(art_path).resolve()
                full.relative_to(self.root)
            except (ValueError, OSError):
                reasons.append(f"artifact {aid} path escapes root")
                continue
            if not full.is_file():
                reasons.append(f"artifact {aid} missing")
                continue
            if _sha256_hex(full.read_bytes()) != expected:
                reasons.append(f"artifact {aid} hash mismatch")
        # Repository binding: compare stored repo observation with current.
        stored = state.get("repo_state", {})
        try:
            observed = self._store.repository_observation()
            for key in (
                "repository_id",
                "HEAD",
                "BRANCH",
                "worktree_fingerprint_sha256",
            ):
                if stored.get(key) != observed.get(key):
                    reasons.append("repository binding diverged")
                    break
        except Exception:
            reasons.append("repository observation unavailable")
        return reasons

    def invalidate(self, mission_id: str, gate_id: str, actor: str) -> PESEOutcome:
        """Invalidate a GREEN gate when artifact/repository binding fails: GREEN -> INVALIDATED.

        Per the PESE specification section 5.3, this transition is only
        permitted when the gate's artifact or repository binding has failed.
        If the binding is sound (artifact files match their hashes and the
        repository observation matches the stored baseline), the engine raises
        ``BINDING_INTACT``.

        Tampered artifacts that make the PESE state unloadable trigger a
        secure halt (``STATE_LOAD_FAILED``) — recovery of tampered evidence
        is an operator recovery action, not a programmatic invalidation.
        """
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, VALError):
                raise VALError(result.code, result.detail)
            state, _, _ = result
            gate = self._find_gate(state, mission_id, gate_id)
            self._require_validator(gate, actor)
            if gate["status"] != "GREEN":
                raise VALError(
                    "GATE_NOT_GREEN",
                    f"gate {gate_id} status is {gate['status']}, expected GREEN",
                )

            # Binding must be failed (PESE spec section 5.3).
            binding_reasons = self._binding_failed(state)
            if not binding_reasons:
                raise VALError(
                    "BINDING_INTACT",
                    f"gate {gate_id} artifact/repository binding is sound; "
                    "invalidation requires a binding failure",
                )

            def mutate(target: dict[str, Any]) -> None:
                g = (
                    target.setdefault("validation_state", {})
                    .setdefault("gates", {})
                    .get(gate_id)
                )
                if g is not None:
                    g["status"] = "INVALIDATED"
                    g["verdict_at"] = utc_now()

            outcome = self._transition_gate(
                actor, gate_id, "GREEN", "INVALIDATED", mutate
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "GATE_INVALIDATED",
                    mission_id,
                    gate_id,
                    actor,
                    outcome.state_revision,
                    outcome.state_sha256,
                    {
                        "reason": "binding_failure",
                        "binding_reasons": binding_reasons,
                    },
                )
            return outcome

    def report(self, mission_id: str, actor: str) -> ValidationReport:
        """Read-only mission-level validation summary."""
        result = self._load_state(actor)
        if isinstance(result, VALError):
            raise VALError(result.code, result.detail)
        state, _, _ = result
        self._find_mission(state, mission_id)
        gates = state.get("validation_state", {}).get("gates", {})
        mission_gates = {
            gid: g
            for gid, g in gates.items()
            if isinstance(g, Mapping) and g.get("mission_id") == mission_id
        }
        counts: dict[str, int] = {}
        for g in mission_gates.values():
            s = g.get("status", "PENDING")
            counts[s] = counts.get(s, 0) + 1
        total = len(mission_gates)
        green = counts.get("GREEN", 0)
        red = counts.get("RED", 0)
        blocked = counts.get("BLOCKED", 0)
        pending = counts.get("PENDING", 0)
        running = counts.get("RUNNING", 0)
        invalidated = counts.get("INVALIDATED", 0)
        waived = counts.get("WAIVED", 0)
        if red > 0 or invalidated > 0:
            overall = "FAIL"
        elif pending > 0 or running > 0:
            overall = "HOLD"
        else:
            overall = "PASS"
        findings: list[dict[str, Any]] = []
        for gid, g in mission_gates.items():
            findings.append({"gate": gid, "status": g.get("status", "UNKNOWN")})
        return ValidationReport(
            mission_id=mission_id,
            gate_count=total,
            green_count=green,
            red_count=red,
            blocked_count=blocked,
            pending_count=pending,
            running_count=running,
            invalidated_count=invalidated,
            waived_count=waived,
            overall=overall,
            findings=tuple(findings),
        )

    def gates(self, mission_id: str, actor: str) -> tuple[GateStatus, ...]:
        """Read-only list of all gate statuses for a mission."""
        result = self._load_state(actor)
        if isinstance(result, VALError):
            raise VALError(result.code, result.detail)
        state, _, _ = result
        gates = state.get("validation_state", {}).get("gates", {})
        out: list[GateStatus] = []
        for gid, g in gates.items():
            if not isinstance(g, Mapping):
                continue
            if g.get("mission_id") != mission_id:
                continue
            out.append(
                GateStatus(
                    gate_id=gid,
                    mission_id=g.get("mission_id", mission_id),
                    status=g.get("status", "UNKNOWN"),
                    validator_agent_id=g.get("validator_agent_id", ""),
                    manifest_version=g.get("manifest_version", 1),
                    criteria_refs=tuple(g.get("criteria_refs", ())),
                    artifact_ids=tuple(g.get("artifact_ids", ())),
                    last_checkpoint_id=g.get("last_checkpoint_id"),
                    verdict_at=g.get("verdict_at"),
                )
            )
        out.sort(key=lambda gs: gs.gate_id)
        return tuple(out)

    def artifacts(
        self, mission_id: str, gate_id: str, actor: str
    ) -> tuple[ArtifactRecord, ...]:
        """Read-only list of artifacts bound to a gate."""
        result = self._load_state(actor)
        if isinstance(result, VALError):
            raise VALError(result.code, result.detail)
        state, _, _ = result
        gate = self._find_gate(state, mission_id, gate_id)
        all_artifacts = state.get("validation_state", {}).get("artifacts", {})
        out: list[ArtifactRecord] = []
        for aid in gate.get("artifact_ids", ()):
            art = all_artifacts.get(aid)
            if art is None or not isinstance(art, Mapping):
                continue
            out.append(
                ArtifactRecord(
                    artifact_id=aid,
                    path=art.get("path", ""),
                    sha256=art.get("sha256", ""),
                    type=art.get("type", ""),
                    produced_at=art.get("produced_at", ""),
                    producer_agent_id=art.get("producer_agent_id", ""),
                    retention_class=art.get("retention_class", ""),
                )
            )
        return tuple(out)
