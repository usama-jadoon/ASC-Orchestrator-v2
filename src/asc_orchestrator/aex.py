"""Agent Execution Engine (AEX) v1.0.

A deterministic, stdlib-only agent execution runtime that consumes
EEF-dispatched assignments, transitions them through their lifecycle,
persists work product artifacts, and signs execution attestations via CKS.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .audit import AuditError
from .execution import EEFEventJournal
from .keys import CKSError, KeyStore
from .pese import PESEOutcome, PESEStore, utc_compact, utc_now

AEX_FORMAT = "AEX/v1.0"
ARTIFACTS_DIR = "ARTIFACTS"
_AEX_EXTENSION_KEY = "org.asc.aex"


class AEXError(RuntimeError):
    """A structured AEX precondition or contract failure."""

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
class AssignmentStatus:
    """Read-only snapshot of an assignment's current AEX state."""

    assignment_id: str
    mission_id: str
    agent_id: str
    status: str
    started_at: str | None
    completed_at: str | None
    milestone_id: str
    output_refs: list[str]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Read-only snapshot of an execution result record."""

    assignment_id: str
    mission_id: str
    agent_id: str
    status: str
    output_text: str | None
    artifact_hashes: dict[str, str]
    started_at: str | None
    completed_at: str | None
    pese_revision: int | None
    pese_state_sha256: str | None
    entry_hash: str
    signature: dict[str, str] | None


# ---------------------------------------------------------------------------
# AEX runtime
# ---------------------------------------------------------------------------


class AEX:
    """Deterministic agent execution runtime operating over PESE/EEF/CKS."""

    def __init__(
        self,
        root: str | Path,
        *,
        audit_directory: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._store = PESEStore(self.root)
        self._journal = EEFEventJournal(self.root, audit_directory=audit_directory)
        self._artifacts_dir = self.root / ".project-os" / ARTIFACTS_DIR
        self._lock = _get_lock(self._artifacts_dir)

    # --- internal helpers ---------------------------------------------------

    def _load_state(
        self, actor: str
    ) -> tuple[dict[str, Any], int, str, str] | AEXError:
        """Load PESE state and return (state_dict, revision, state_sha256, actor).

        Raises ``AEXError`` if the state is not loaded or revision/sha are None.
        """
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return AEXError("STATE_LOAD_FAILED", f"PESE load failed: {loaded.code}")
        if loaded.state_revision is None or loaded.state_sha256 is None:
            return AEXError(
                "STATE_LOAD_FAILED", "PESE state missing revision or sha256"
            )
        state = loaded.data["envelope"]["state"]
        return state, loaded.state_revision, loaded.state_sha256, actor

    def _find_assignment(
        self,
        state: dict[str, Any],
        mission_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        """Find the assignment or raise ASSIGNMENT_NOT_FOUND."""
        assignments = state.get("execution_state", {}).get("assignments", {})
        assignment = assignments.get(assignment_id)
        if (
            assignment is None
            or not isinstance(assignment, Mapping)
            or assignment.get("mission_id") != mission_id
        ):
            raise AEXError(
                "ASSIGNMENT_NOT_FOUND",
                f"assignment {assignment_id} not found in mission {mission_id}",
            )
        return dict(assignment)

    def _require_actor(self, assignment: dict[str, Any], actor: str) -> None:
        if assignment.get("assigned_agent_id") != actor:
            raise AEXError(
                "UNAUTHORIZED",
                f"actor {actor} is not the assigned agent",
            )

    def _transition(
        self,
        actor: str,
        assignment_id: str,
        from_status: str,
        to_status: str,
        mutate_fn: Any,
        *,
        evidence_refs: list[str] | None = None,
    ) -> tuple[PESEOutcome, int | None, str | None]:
        """Transition an assignment through PESE. Returns (outcome, rev, sha)."""
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return (
                PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": "STATE_LOAD_FAILED", "detail": "reload for transition"},),
                ),
                None,
                None,
            )
        if loaded.state_revision is None or loaded.state_sha256 is None:
            return (
                PESEOutcome(
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
                ),
                None,
                None,
            )
        outcome = self._store.update(
            expected_revision=loaded.state_revision,
            actor=actor,
            transition_type="ASSIGNMENT_STATUS",
            subject=assignment_id,
            from_value=from_status,
            to_value=to_status,
            mutate=mutate_fn,
            evidence_refs=evidence_refs or (),
        )
        new_rev = loaded.state_revision if outcome.code == "UPDATED" else None
        new_sha = loaded.state_sha256 if outcome.code == "UPDATED" else None
        return outcome, new_rev, new_sha

    def _emit_event(
        self,
        event_type: str,
        mission_id: str,
        assignment_id: str,
        actor: str,
        pese_revision: int | None,
        pese_state_sha256: str | None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, object] | None:
        try:
            return self._journal.append(
                event_type=event_type,
                mission_id=mission_id,
                assignment_id=assignment_id,
                actor_agent_id=actor,
                pese_revision=pese_revision,
                pese_state_sha256=pese_state_sha256,
                detail=detail,
            )
        except (AuditError, Exception):
            return None

    def _result_path(self, mission_id: str, assignment_id: str) -> Path:
        base = self._artifacts_dir.resolve()
        path = base / _safe_id(mission_id) / _safe_id(assignment_id) / "result.json"
        self._assert_contained(base, path)
        return path

    def _artifacts_path(self, mission_id: str, assignment_id: str) -> Path:
        base = self._artifacts_dir.resolve()
        path = base / _safe_id(mission_id) / _safe_id(assignment_id) / "artifacts"
        self._assert_contained(base, path)
        return path

    @staticmethod
    def _assert_contained(base: Path, path: Path) -> None:
        """Fail-closed containment check against directory traversal."""
        try:
            path.resolve().relative_to(base)
        except ValueError:
            raise AEXError(
                "PATH_ESCAPE",
                f"resolved path escapes artifacts directory: {path}",
            )

    def _write_result(
        self,
        record: dict[str, Any],
    ) -> None:
        result_path = self._result_path(record["mission_id"], record["assignment_id"])
        result_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = result_path.with_suffix(".tmp")
        tmp.write_text(_canonical_json(record) + "\n", encoding="utf-8", newline="\n")
        tmp.replace(result_path)

    def _copy_artifacts(
        self,
        mission_id: str,
        assignment_id: str,
        artifact_paths: list[str],
    ) -> dict[str, str]:
        dest_dir = self._artifacts_path(mission_id, assignment_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        hashes: dict[str, str] = {}
        for raw_path in artifact_paths:
            src = Path(raw_path)
            if not src.is_absolute():
                src = self.root / src
            resolved = src.resolve()
            try:
                resolved.relative_to(self.root)
            except ValueError:
                raise AEXError(
                    "ARTIFACT_ESCAPE",
                    f"artifact path escapes repository root: {raw_path}",
                )
            if not resolved.is_file():
                raise AEXError(
                    "ARTIFACT_NOT_FOUND",
                    f"artifact file not found: {raw_path}",
                )
            filename = resolved.name
            content = resolved.read_bytes()
            hashes[filename] = _sha256_hex(content)
            dest_file = dest_dir / filename
            if dest_file.exists():
                dest_file.unlink()
            shutil.copy2(str(resolved), str(dest_file))
            os.chmod(str(dest_file), 0o444)
        return hashes

    def _sign_result(
        self,
        key_id: str,
        record: dict[str, Any],
        actor: str,
    ) -> dict[str, str]:
        ks = KeyStore(self.root)
        canonical = _canonical_json(record).encode("utf-8")
        sig = ks.sign(key_id, canonical, actor)
        return {"key_id": key_id, "signature_hex": sig.signature_hex}

    def _populate_output_refs(
        self,
        state: dict[str, Any],
        assignment_id: str,
        output_refs: list[str],
    ) -> None:
        assignments = state.get("execution_state", {}).get("assignments", {})
        if assignment_id in assignments:
            assignments[assignment_id]["output_refs"] = output_refs

    # --- public API ---------------------------------------------------------

    def dispatch(self, mission_id: str, assignment_id: str, actor: str) -> PESEOutcome:
        """Claim a READY assignment: READY → IN_PROGRESS."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AEXError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _, _ = result
            assignment = self._find_assignment(state, mission_id, assignment_id)
            self._require_actor(assignment, actor)
            if assignment["status"] != "READY":
                raise AEXError(
                    "ASSIGNMENT_NOT_READY",
                    f"assignment {assignment_id} status is {assignment['status']}, expected READY",
                )

            def mutate(state: dict[str, Any]) -> None:
                a = state["execution_state"].get("assignments", {}).get(assignment_id)
                if a is not None:
                    a["status"] = "IN_PROGRESS"
                    a["started_at"] = utc_now()

            outcome, rev, sha = self._transition(
                actor,
                assignment_id,
                "READY",
                "IN_PROGRESS",
                mutate,
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "ASSIGNMENT_DISPATCHED",
                    mission_id,
                    assignment_id,
                    actor,
                    rev,
                    sha,
                    {"agent_id": assignment["assigned_agent_id"]},
                )
            return outcome

    def complete(
        self,
        mission_id: str,
        assignment_id: str,
        actor: str,
        *,
        output_text: str | None = None,
        artifacts: list[str] | None = None,
        key_id: str | None = None,
    ) -> dict[str, Any]:
        """Complete an IN_PROGRESS assignment and persist the result record."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AEXError):
                raise AEXError(result.code, result.detail)
            state, rev, sha, _ = result
            assignment = self._find_assignment(state, mission_id, assignment_id)
            self._require_actor(assignment, actor)
            if assignment["status"] != "IN_PROGRESS":
                raise AEXError(
                    "ASSIGNMENT_NOT_ACTIVE",
                    f"assignment {assignment_id} status is {assignment['status']}, expected IN_PROGRESS",
                )

            # Copy artifacts before PESE transition.
            artifact_hashes: dict[str, str] = {}
            output_refs: list[str] = []
            safe_m = _safe_id(mission_id)
            safe_a = _safe_id(assignment_id)
            if artifacts:
                artifact_hashes = self._copy_artifacts(
                    mission_id, assignment_id, artifacts
                )
                for name in artifact_hashes:
                    output_refs.append(f"ARTIFACTS/{safe_m}/{safe_a}/artifacts/{name}")

            result_path = f"ARTIFACTS/{safe_m}/{safe_a}/result.json"
            output_refs.append(result_path)

            def mutate(state: dict[str, Any]) -> None:
                a = state["execution_state"].get("assignments", {}).get(assignment_id)
                if a is not None:
                    a["status"] = "COMPLETED"
                    a["completed_at"] = utc_now()
                    a["output_refs"] = list(output_refs)

            outcome, new_rev, new_sha = self._transition(
                actor,
                assignment_id,
                "IN_PROGRESS",
                "COMPLETED",
                mutate,
                evidence_refs=[result_path],
            )
            if outcome.code != "UPDATED":
                raise AEXError(
                    "PESE_UPDATE_FAILED",
                    f"transition failed: {outcome.code}",
                )

            # Build the result record.
            record: dict[str, Any] = {
                "format": AEX_FORMAT,
                "kind": "execution-result",
                "assignment_id": assignment_id,
                "mission_id": mission_id,
                "agent_id": assignment["assigned_agent_id"],
                "status": "COMPLETED",
                "output_text": output_text,
                "artifact_hashes": artifact_hashes,
                "started_at": assignment.get("started_at"),
                "completed_at": utc_now(),
                "pese_revision": outcome.state_revision,
                "pese_state_sha256": outcome.state_sha256,
            }

            # CKS signature (optional).
            signature_data: dict[str, str] | None = None
            if key_id:
                record["entry_hash"] = _entry_hash(record)
                try:
                    signature_data = self._sign_result(key_id, record, actor)
                except (CKSError, AEXError) as exc:
                    raise AEXError(
                        "CKS_ERROR",
                        f"signing failed: {exc}",
                    ) from exc
            record["entry_hash"] = _entry_hash(record)
            if signature_data:
                record["signature"] = signature_data

            # Write the immutable result record.
            self._write_result(record)

            # Emit EEF event.
            self._emit_event(
                "ASSIGNMENT_COMPLETED",
                mission_id,
                assignment_id,
                actor,
                outcome.state_revision,
                outcome.state_sha256,
                {
                    "artifact_count": len(artifact_hashes),
                    "output_refs": output_refs,
                    "signed": signature_data is not None,
                },
            )
            return record

    def fail(
        self,
        mission_id: str,
        assignment_id: str,
        actor: str,
        *,
        reason: str,
    ) -> PESEOutcome:
        """Mark an IN_PROGRESS assignment as FAILED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AEXError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _, _ = result
            assignment = self._find_assignment(state, mission_id, assignment_id)
            self._require_actor(assignment, actor)
            if assignment["status"] != "IN_PROGRESS":
                raise AEXError(
                    "ASSIGNMENT_NOT_ACTIVE",
                    f"assignment {assignment_id} status is {assignment['status']}, expected IN_PROGRESS",
                )

            def mutate(state: dict[str, Any]) -> None:
                a = state["execution_state"].get("assignments", {}).get(assignment_id)
                if a is not None:
                    a["status"] = "FAILED"
                    a["completed_at"] = utc_now()

            outcome, rev, sha = self._transition(
                actor,
                assignment_id,
                "IN_PROGRESS",
                "FAILED",
                mutate,
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "ASSIGNMENT_FAILED",
                    mission_id,
                    assignment_id,
                    actor,
                    rev,
                    sha,
                    {"reason": reason},
                )
            return outcome

    def block(
        self,
        mission_id: str,
        assignment_id: str,
        actor: str,
        *,
        reason: str,
    ) -> PESEOutcome:
        """Block a READY or IN_PROGRESS assignment: → BLOCKED."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AEXError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _, _ = result
            assignment = self._find_assignment(state, mission_id, assignment_id)
            self._require_actor(assignment, actor)
            current = assignment["status"]
            if current not in {"READY", "IN_PROGRESS"}:
                raise AEXError(
                    "ASSIGNMENT_NOT_BLOCKABLE",
                    f"assignment {assignment_id} status is {current}, expected READY or IN_PROGRESS",
                )

            def mutate(state: dict[str, Any]) -> None:
                a = state["execution_state"].get("assignments", {}).get(assignment_id)
                if a is not None:
                    a["status"] = "BLOCKED"

            outcome, rev, sha = self._transition(
                actor,
                assignment_id,
                current,
                "BLOCKED",
                mutate,
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "ASSIGNMENT_BLOCKED",
                    mission_id,
                    assignment_id,
                    actor,
                    rev,
                    sha,
                    {"reason": reason, "blocked_from_status": current},
                )
            return outcome

    def unblock(
        self,
        mission_id: str,
        assignment_id: str,
        actor: str,
    ) -> PESEOutcome:
        """Release a BLOCKED assignment back to READY."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, AEXError):
                return PESEOutcome(
                    "HALTED",
                    f"OP-{utc_compact()}-{os.getpid()}",
                    utc_now(),
                    None,
                    None,
                    ({"code": result.code, "detail": result.detail},),
                )
            state, _, _, _ = result
            assignment = self._find_assignment(state, mission_id, assignment_id)
            self._require_actor(assignment, actor)
            if assignment["status"] != "BLOCKED":
                raise AEXError(
                    "ASSIGNMENT_NOT_BLOCKED",
                    f"assignment {assignment_id} status is {assignment['status']}, expected BLOCKED",
                )

            def mutate(state: dict[str, Any]) -> None:
                a = state["execution_state"].get("assignments", {}).get(assignment_id)
                if a is not None:
                    a["status"] = "READY"

            outcome, rev, sha = self._transition(
                actor,
                assignment_id,
                "BLOCKED",
                "READY",
                mutate,
            )
            if outcome.code == "UPDATED":
                self._emit_event(
                    "ASSIGNMENT_ACTIVATED",
                    mission_id,
                    assignment_id,
                    actor,
                    rev,
                    sha,
                    {"reactivated_from": "BLOCKED"},
                )
            return outcome

    def status(
        self, mission_id: str, assignment_id: str, actor: str
    ) -> AssignmentStatus:
        """Read the current state of an assignment."""
        result = self._load_state(actor)
        if isinstance(result, AEXError):
            raise AEXError(result.code, result.detail)
        state, _, _, _ = result
        assignment = self._find_assignment(state, mission_id, assignment_id)
        return AssignmentStatus(
            assignment_id=assignment_id,
            mission_id=mission_id,
            agent_id=assignment.get("assigned_agent_id", ""),
            status=assignment.get("status", "UNKNOWN"),
            started_at=assignment.get("started_at"),
            completed_at=assignment.get("completed_at"),
            milestone_id=assignment.get("milestone_id", ""),
            output_refs=list(assignment.get("output_refs", [])),
        )

    def result(self, mission_id: str, assignment_id: str) -> ExecutionResult | None:
        """Load the execution result record, if any."""
        result_path = self._result_path(mission_id, assignment_id)
        if not result_path.exists():
            return None
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise AEXError(
                "RESULT_CORRUPT",
                f"failed to read result record: {exc}",
            ) from exc
        return ExecutionResult(
            assignment_id=data.get("assignment_id", assignment_id),
            mission_id=data.get("mission_id", mission_id),
            agent_id=data.get("agent_id", ""),
            status=data.get("status", "UNKNOWN"),
            output_text=data.get("output_text"),
            artifact_hashes=data.get("artifact_hashes", {}),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            pese_revision=data.get("pese_revision"),
            pese_state_sha256=data.get("pese_state_sha256"),
            entry_hash=data.get("entry_hash", ""),
            signature=data.get("signature"),
        )
