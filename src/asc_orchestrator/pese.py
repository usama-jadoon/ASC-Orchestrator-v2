"""Persistent Execution State Engine (PESE) v1.0.

The store deliberately has no dependency on the CLI.  It exposes a small
transactional API around the canonical ``.project-os/PESE`` layout and returns
structured outcomes instead of making persistence failures implicit.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

FORMAT = "PESE/v1.0"
ZERO_HASH = "0" * 64
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MISSION_RE = re.compile(r"^MISSION:[A-Za-z0-9._-]+$")
ASSIGNMENT_RE = re.compile(r"^ASSIGNMENT:[A-Za-z0-9._-]+$")
ID_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
CHECKPOINT_RE = re.compile(r"^CP-[A-Za-z0-9._-]+-(\d{8}T\d{9}Z)-(\d{4,})$")
# The canonical v1.0 examples use names such as ``org.asc.tbe`` and
# ``org.asc.lease_seconds``: a reverse-DNS namespace followed by a
# producer-controlled suffix.  The suffix intentionally permits ``_``.
EXTENSION_KEY_RE = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9_-]+)+$", re.IGNORECASE)

REQUIRED_DIRS = (
    "state/history",
    "checkpoints",
    "locks",
    "migrations",
    "audit/access",
    "audit/transitions",
    "recovery",
)
MANDATORY_CHECKPOINTS = {
    "MISSION_STATUS": {
        "ACTIVE": "MISSION_START",
        "COMPLETED": "MISSION_FINISH",
        "CANCELLED": "MISSION_FINISH",
        "FAILED": "MISSION_FINISH",
    },
    "VALIDATION_GATE": {
        "GREEN": "VALIDATION",
        "RED": "VALIDATION",
        "BLOCKED": "VALIDATION",
        "PENDING": "VALIDATION",
    },
    "REPO_HEAD": {"*": "COMMIT"},
    "AGENT_STATUS": {"FAILED": "FAILURE", "QUARANTINED": "FAILURE"},
    "RECOVERY_STATUS": {"FAILED": "FAILURE"},
}
PRIORITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


class PESEError(RuntimeError):
    """A printable structured PESE failure."""

    def __init__(
        self, code: str, detail: str, findings: Iterable[Mapping[str, Any]] = ()
    ):
        self.code, self.detail, self.findings = (
            code,
            detail,
            tuple(dict(x) for x in findings),
        )
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class PESEOutcome:
    code: str
    operation_id: str
    occurred_at: str
    state_revision: int | None = None
    state_sha256: str | None = None
    findings: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code in {
            "STATE_LOADED",
            "VALID",
            "UPDATED",
            "SAVED",
            "CHECKPOINTED",
            "RESUME_PLAN",
            "NO_WORK",
            "RECOVERED",
            "MIGRATED",
            "INITIALIZED",
            "LOCKED",
        }


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_compact(value: str | None = None) -> str:
    stamp = datetime.fromisoformat((value or utc_now()).replace("Z", "+00:00"))
    # YYYYMMDDTHHmmssSSSZ: nine time digits after T (seconds plus millis).
    return stamp.astimezone(UTC).strftime("%Y%m%dT%H%M%S%f")[:18] + "Z"


def canonical_json(value: Any) -> bytes:
    """Serialize JSON using sorted keys and ECMAScript-compatible numbers.

    The encoder covers the finite-number edge cases PESE may persist while
    rejecting non-finite JSON values.  It deliberately avoids CPython's
    non-JCS spellings such as ``1.0`` and ``1e-06``.
    """

    def number(item: int | float) -> str:
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, int):
            return str(item)
        if not math.isfinite(item):
            raise PESEError("MALFORMED_JSON", "non-finite number")
        if item == 0:
            return "0"
        text = repr(item)
        absolute = abs(item)
        if "e" in text.lower() and 1e-6 <= absolute < 1e21:
            text = format(item, ".17f").rstrip("0").rstrip(".")
        elif "e" in text.lower():
            mantissa, exponent = re.split("e", text, flags=re.IGNORECASE)
            mantissa = mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa
            sign = (
                "+"
                if exponent.startswith("+")
                else "-"
                if exponent.startswith("-")
                else ""
            )
            digits = exponent.lstrip("+-").lstrip("0") or "0"
            text = f"{mantissa}e{sign}{digits}"
        elif text.endswith(".0"):
            text = text[:-2]
        return text

    def encode(item: Any) -> str:
        if item is None:
            return "null"
        if isinstance(item, (bool, int, float)):
            return number(item)
        if isinstance(item, str):
            return json.encoder.encode_basestring(item)
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise PESEError("MALFORMED_JSON", "JSON object keys must be strings")
            return (
                "{"
                + ",".join(f"{encode(key)}:{encode(item[key])}" for key in sorted(item))
                + "}"
            )
        if isinstance(item, (list, tuple)):
            return "[" + ",".join(encode(child) for child in item) + "]"
        raise PESEError("MALFORMED_JSON", "object cannot be canonicalized")

    return encode(value).encode("utf-8")


def canonical_sha256(value: Any, omit: str | None = None) -> str:
    if omit is not None:
        if not isinstance(value, Mapping):
            raise PESEError("MALFORMED_JSON", "hash omission requires object")
        value = {key: val for key, val in value.items() if key != omit}
    return sha256(canonical_json(value)).hexdigest()


def _json_load(path: Path) -> Any:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise PESEError("MALFORMED_JSON", f"non-canonical encoding: {path}")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, PESEError) as exc:
        if isinstance(exc, PESEError):
            raise
        raise PESEError("MALFORMED_JSON", f"unreadable JSON: {path}") from exc


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PESEError("MALFORMED_JSON", f"duplicate key {key!r}")
        result[key] = value
    return result


def _safe_rel(root: Path, reference: str) -> Path:
    candidate = Path(reference.replace("/", os.sep))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise PESEError("CONTRACT_INVALID", f"unsafe artifact reference: {reference}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PESEError(
            "CONTRACT_INVALID", f"artifact escapes repository: {reference}"
        ) from exc
    return resolved


class PESEStore:
    """The PESE state/checkpoint/lock/recovery manager.

    Public operations are :meth:`initialize`, :meth:`load`, :meth:`validate`,
    :meth:`update`, :meth:`checkpoint`, :meth:`resume`, :meth:`recover`, and
    :meth:`migrate`.  All paths are rooted below the supplied repository root.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        lease_seconds: int = 120,
        liveness_check: Callable[[str], bool | None] | None = None,
    ):
        if lease_seconds < 30:
            raise ValueError("lease_seconds must be at least 30")
        self.root = Path(root).resolve()
        self.base = self.root / ".project-os" / "PESE"
        self.lease_seconds = lease_seconds
        self.liveness_check = liveness_check
        self._lock_id: str | None = None

    @property
    def live_path(self) -> Path:
        return self.base / "state/live.json"

    @property
    def lock_path(self) -> Path:
        return self.base / "locks/state.lock.json"

    def _path(self, *parts: str) -> Path:
        return self.base.joinpath(*parts)

    def _outcome(
        self,
        code: str,
        *,
        state: Mapping[str, Any] | None = None,
        findings: Iterable[Mapping[str, Any]] = (),
        **data: Any,
    ) -> PESEOutcome:
        return PESEOutcome(
            code,
            f"OP-{utc_compact()}-{os.getpid()}",
            utc_now(),
            state.get("revision") if state else None,
            state.get("state_sha256") if state else None,
            tuple(dict(x) for x in findings),
            data,
        )

    def _mkdirs(self) -> None:
        for directory in REQUIRED_DIRS:
            self._path(directory).mkdir(parents=True, exist_ok=True)

    def initialize(
        self, writer: str, state: Mapping[str, Any] | None = None
    ) -> PESEOutcome:
        """Create the exact PESE layout and initial revision (revision 1)."""
        self._mkdirs()
        acquired = self.acquire_lock(writer, 0)
        if acquired.code != "LOCK_ACQUIRED":
            return acquired
        try:
            if self.live_path.exists() or any(
                self._path("state/history").glob("*.json")
            ):
                return self.load()
            payload = dict(state) if state is not None else self.default_state()
            self._validate_state_shape(payload)
            envelope = self._envelope(payload, 1, writer, 0, ZERO_HASH)
            self._atomic_write(
                self._path("state/history/1.json"), envelope, overwrite=False
            )
            self._atomic_write(self.live_path, envelope)
            self._audit_access(writer, "SAVE", "PESE/state/live.json", "SUCCEEDED", 1)
            return self._outcome("INITIALIZED", state=envelope)
        finally:
            self.release_lock(writer)

    def default_state(self) -> dict[str, Any]:
        now = utc_now()
        repo = self.repository_observation(allow_missing=True)
        return {
            "schema_version": "1.0.0",
            "company_state": {
                "company_id": "COMPANY:asc-orchestrator-v2",
                "status": "INITIALIZING",
                "protocols": {"ACP": "1.0", "ACR": "1.0", "TBE": "1.0", "PESE": "1.0"},
                "registry_ref": "docs/ACR_v1.0.md",
                "team_builder_ref": "docs/TBE_v1.0.md",
                "message_protocol_ref": "docs/ACP_v1.0.md",
                "created_at": now,
                "updated_at": now,
            },
            "repo_state": repo,
            "mission_state": {"active_mission_id": None, "missions": {}},
            "execution_state": {
                "current_milestone_id": None,
                "milestones": [],
                "assignments": {},
                "next_task_candidates": [],
            },
            "validation_state": {"gates": {}, "artifacts": {}},
            "risk_state": {"risks": {}},
            "agent_state": {"agents": {}},
            "recovery_state": {"recoveries": {}},
            "extensions": {},
        }

    def repository_observation(self, *, allow_missing: bool = False) -> dict[str, Any]:
        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

        try:
            head = git("rev-parse", "HEAD")
            branch = git("symbolic-ref", "--short", "HEAD")
            try:
                origin = git("remote", "get-url", "origin")
                origin = (
                    re.sub(r"^[^@/]+@", "", origin)
                    .split("?", 1)[0]
                    .split("#", 1)[0]
                    .removesuffix(".git")
                )
            except subprocess.CalledProcessError:
                # A local Git repository is valid without an origin remote.
                origin = "local:" + self.root.as_posix()
            dirty = sorted(
                path
                for line in git("status", "--porcelain").splitlines()
                if line
                for path in [line[3:].replace("\\", "/")]
                # PESE's append-only store is operational metadata; including
                # it would make every successful save self-diverge the bound
                # repository fingerprint.
                if path not in {".project-os", ".project-os/"}
                and not path.startswith(".project-os/PESE/")
            )
            identity = origin
        except (OSError, subprocess.CalledProcessError):
            if not allow_missing:
                raise PESEError(
                    "REPOSITORY_DIVERGENCE", "Git repository identity is unavailable"
                )
            head, branch, dirty = "", "", []
            identity = "local:" + self.root.as_posix()
        repository_id = "REPO:" + sha256(f"git\n{identity}".encode()).hexdigest()
        fingerprint = canonical_sha256(
            {"HEAD": head, "BRANCH": branch, "dirty_paths": dirty}
        )
        return {
            "repository_id": repository_id,
            "root": ".",
            "vcs": "git",
            "origin_identity": identity,
            "HEAD": head,
            "BRANCH": branch,
            "head_kind": "COMMIT",
            "worktree_fingerprint_sha256": fingerprint,
            "dirty_paths": dirty,
            "last_verified_at": utc_now(),
        }

    def load(
        self, *, actor: str = "AGENT:system:reader", check_migrations: bool = True
    ) -> PESEOutcome:
        report = self.validate(
            check_repository=False, check_migrations=check_migrations
        )
        if report.code != "VALID":
            return self._outcome("STATE_CORRUPT", findings=report.findings)
        envelope = _json_load(self.live_path)
        self._audit_access(
            actor, "LOAD", "PESE/state/live.json", "ALLOWED", envelope["revision"]
        )
        return self._outcome("STATE_LOADED", state=envelope, envelope=envelope)

    def validate(
        self,
        *,
        check_repository: bool = True,
        check_lock: bool = True,
        check_migrations: bool = True,
    ) -> PESEOutcome:
        """Return all independently detectable integrity findings without mutation."""
        findings: list[dict[str, Any]] = []
        for directory in REQUIRED_DIRS:
            if not self._path(directory).is_dir():
                findings.append(
                    {
                        "gate": "layout",
                        "code": "LAYOUT_INVALID",
                        "detail": f"missing {directory}",
                    }
                )
        if check_lock:
            findings.extend(self._validate_lock())
        history_dir = self._path("state/history")
        records: list[tuple[int, Path, dict[str, Any]]] = []
        if history_dir.exists():
            for file in history_dir.glob("*.json"):
                if not re.fullmatch(r"[1-9][0-9]*\.json", file.name):
                    findings.append(
                        {
                            "gate": "layout",
                            "code": "LAYOUT_INVALID",
                            "detail": f"invalid history filename {file.name}",
                        }
                    )
                    continue
                try:
                    records.append((int(file.stem), file, _json_load(file)))
                except PESEError as exc:
                    findings.append(
                        {"gate": "encoding", "code": exc.code, "detail": exc.detail}
                    )
        if not records:
            findings.append(
                {"gate": "layout", "code": "LAYOUT_INVALID", "detail": "no history"}
            )
        records.sort()
        previous = ZERO_HASH
        last: dict[str, Any] | None = None
        for expected, (revision, file, envelope) in enumerate(records, 1):
            try:
                self._validate_envelope(envelope)
                if (
                    revision != expected
                    or envelope["revision"] != revision
                    or envelope["previous_revision"] != revision - 1
                    or envelope["previous_state_sha256"] != previous
                ):
                    raise PESEError(
                        "STATE_CHAIN_INVALID", f"history sequence break at {file.name}"
                    )
                previous, last = envelope["state_sha256"], envelope
            except PESEError as exc:
                findings.append(
                    {"gate": "state chain", "code": exc.code, "detail": exc.detail}
                )
        if last is not None:
            try:
                if not self.live_path.exists() or canonical_json(
                    _json_load(self.live_path)
                ) != canonical_json(last):
                    raise PESEError(
                        "STATE_CHAIN_INVALID",
                        "live.json does not equal highest history",
                    )
            except PESEError as exc:
                findings.append(
                    {"gate": "state chain", "code": exc.code, "detail": exc.detail}
                )
            findings.extend(self._validate_checkpoints(last))
            findings.extend(self._validate_audits())
            if check_migrations:
                findings.extend(self._validate_migrations())
            findings.extend(self._validate_recovery_records())
            if check_repository:
                try:
                    observed = self.repository_observation()
                    stored = last["state"]["repo_state"]
                    if any(
                        stored.get(key) != observed.get(key)
                        for key in (
                            "repository_id",
                            "HEAD",
                            "BRANCH",
                            "worktree_fingerprint_sha256",
                        )
                    ):
                        findings.append(
                            {
                                "gate": "repository",
                                "code": "REPOSITORY_DIVERGENCE",
                                "detail": "repository observation differs from state",
                            }
                        )
                except PESEError as exc:
                    findings.append(
                        {"gate": "repository", "code": exc.code, "detail": exc.detail}
                    )
            findings.extend(self._validate_contracts(last["state"]))
        return self._outcome(
            "VALID" if not findings else "INVALID", state=last, findings=findings
        )

    def update(
        self,
        *,
        expected_revision: int,
        actor: str,
        transition_type: str,
        subject: str,
        from_value: Any,
        to_value: Any,
        mutate: Callable[[dict[str, Any]], None] | Mapping[str, Any],
        evidence_refs: Iterable[str] = (),
        acp_correlation_id: str | None = None,
        _lock_held: bool = False,
    ) -> PESEOutcome:
        """Commit one typed state update and its mandatory checkpoint, if any."""
        acquired_here = False
        if _lock_held:
            if not self._owns_lock(actor):
                return self._outcome(
                    "SAFETY_HALT",
                    findings=(
                        {
                            "code": "LOCK_OWNERSHIP",
                            "detail": "caller does not hold writer lock",
                        },
                    ),
                )
        else:
            acquired = self.acquire_lock(actor, expected_revision)
            if acquired.code != "LOCK_ACQUIRED":
                return acquired
            acquired_here = True
        try:
            loaded = self.load(actor=actor, check_migrations=not _lock_held)
            if loaded.code != "STATE_LOADED":
                return self._outcome("HALTED", findings=loaded.findings)
            old = loaded.data["envelope"]
            if old["revision"] != expected_revision:
                return self._outcome(
                    "CONFLICT",
                    state=old,
                    findings=(
                        {"code": "CONFLICT", "detail": "expected revision differs"},
                    ),
                )
            new_state = json.loads(canonical_json(old["state"]).decode())
            if callable(mutate):
                mutate(new_state)
            else:
                self._deep_merge(new_state, mutate)
            self._validate_transition(
                transition_type,
                from_value,
                to_value,
                old["state"],
                new_state,
                subject,
                actor,
            )
            for reference in evidence_refs:
                self._validate_evidence_reference(reference)
            self._validate_state_shape(new_state)
            new = self._envelope(
                new_state,
                expected_revision + 1,
                actor,
                expected_revision,
                old["state_sha256"],
            )
            self._atomic_write(
                self._path(f"state/history/{new['revision']}.json"),
                new,
                overwrite=False,
            )
            self._atomic_write(self.live_path, new)
            self._audit_transition(
                actor,
                transition_type,
                subject,
                from_value,
                to_value,
                old["state_sha256"],
                new["state_sha256"],
                list(evidence_refs),
                acp_correlation_id,
            )
            self._audit_access(
                actor, "SAVE", "PESE/state/live.json", "SUCCEEDED", new["revision"]
            )
            reason = MANDATORY_CHECKPOINTS.get(transition_type, {}).get(
                str(to_value), MANDATORY_CHECKPOINTS.get(transition_type, {}).get("*")
            )
            checkpoint = None
            if reason:
                mission_id = self._mission_for_subject(new_state, subject)
                if mission_id:
                    checkpoint = self.checkpoint(
                        mission_id, reason, actor=actor, state_envelope=new
                    )
                    if checkpoint.code != "CHECKPOINTED":
                        # The state history remains durable evidence, but the
                        # state transition is deliberately not reported as a
                        # completed operation until its required checkpoint is.
                        return self._outcome(
                            "HALTED",
                            state=new,
                            findings=checkpoint.findings
                            or (
                                {
                                    "code": "CHECKPOINT_REQUIRED",
                                    "detail": f"automatic {reason} checkpoint failed",
                                },
                            ),
                            checkpoint=checkpoint.data,
                        )
            return self._outcome(
                "UPDATED", state=new, checkpoint=checkpoint.data if checkpoint else None
            )
        except PESEError as exc:
            return self._outcome(
                exc.code, findings=({"code": exc.code, "detail": exc.detail},)
            )
        finally:
            if acquired_here:
                self.release_lock(actor)

    def checkpoint(
        self,
        mission_id: str,
        reason: str,
        *,
        actor: str,
        state_envelope: Mapping[str, Any] | None = None,
    ) -> PESEOutcome:
        if reason not in {
            "MISSION_START",
            "MISSION_FINISH",
            "VALIDATION",
            "COMMIT",
            "FAILURE",
            "INTERRUPTION",
            "MANUAL",
        }:
            raise PESEError("INVALID", f"unknown checkpoint reason {reason}")
        state_envelope = dict(
            state_envelope or self.load(actor=actor).data.get("envelope", {})
        )
        if not state_envelope:
            return self._outcome(
                "HALTED",
                findings=({"code": "STATE_MISSING", "detail": "cannot checkpoint"},),
            )
        state = state_envelope["state"]
        mission = state.get("mission_state", {}).get("missions", {}).get(mission_id)
        if mission is None or not MISSION_RE.fullmatch(mission_id):
            return self._outcome(
                "INVALID",
                state=state_envelope,
                findings=({"code": "CONTRACT_INVALID", "detail": "unknown mission"},),
            )
        snapshot = self._snapshot(state, mission_id)
        observed = state["repo_state"]
        prior = self._latest_checkpoint(mission_id)
        snapshot_hash = canonical_sha256(snapshot)
        duplicate_key = (
            mission_id,
            reason,
            state_envelope["state_sha256"],
            observed.get("HEAD"),
            snapshot_hash,
        )
        for _, existing in self._checkpoints(mission_id):
            if (
                existing["mission_id"],
                existing["reason"],
                existing["state_sha256"],
                existing["repository"].get("head"),
                existing["snapshot_sha256"],
            ) == duplicate_key:
                return self._outcome(
                    "CHECKPOINTED",
                    state=state_envelope,
                    checkpoint_id=existing["checkpoint_id"],
                    duplicate=True,
                )
        if mission.get("status") in {
            "COMPLETED",
            "CANCELLED",
            "FAILED",
            "ARCHIVED",
        } and reason not in {"MISSION_FINISH", "FAILURE", "INTERRUPTION"}:
            return self._outcome(
                "HALTED",
                state=state_envelope,
                findings=(
                    {"code": "INVALID", "detail": "terminal mission checkpoint"},
                ),
            )
        sequence = len(self._checkpoints(mission_id)) + 1
        # ``:`` is legal in logical IDs but illegal in Windows filenames.  The
        # checkpoint ID is also its filename, so canonicalize that separator.
        checkpoint_id = (
            f"CP-{mission_id.replace(':', '-')}-{utc_compact()}-{sequence:04d}"
        )
        item: dict[str, Any] = {
            "format": FORMAT,
            "kind": "checkpoint",
            "checkpoint_id": checkpoint_id,
            "reason": reason,
            "created_at": utc_now(),
            "created_by": actor,
            "mission_id": mission_id,
            "state_revision": state_envelope["revision"],
            "state_sha256": state_envelope["state_sha256"],
            "repository": {
                "repository_id": observed.get("repository_id"),
                "head": observed.get("HEAD"),
                "branch": observed.get("BRANCH"),
                "worktree_fingerprint_sha256": observed.get(
                    "worktree_fingerprint_sha256"
                ),
            },
            "snapshot": snapshot,
            "snapshot_sha256": snapshot_hash,
            "previous_checkpoint_id": prior[1]["checkpoint_id"] if prior else None,
            "previous_checkpoint_sha256": prior[1]["file_sha256"] if prior else None,
        }
        item["file_sha256"] = canonical_sha256(item)
        path = self._path("checkpoints", checkpoint_id + ".json")
        self._atomic_write(path, item, overwrite=False)
        self._audit_access(
            actor,
            "CHECKPOINT_WRITE",
            f"PESE/checkpoints/{path.name}",
            "SUCCEEDED",
            state_envelope["revision"],
        )
        return self._outcome(
            "CHECKPOINTED",
            state=state_envelope,
            checkpoint_id=checkpoint_id,
            duplicate=False,
        )

    def resume(self) -> PESEOutcome:
        report = self.validate(check_repository=True)
        if report.code != "VALID":
            return self._outcome(
                "SAFETY_HALT", findings=report.findings, reason="PESE_INTEGRITY_FAILURE"
            )
        envelope = _json_load(self.live_path)
        state = envelope["state"]
        active = state["mission_state"].get("active_mission_id")
        if not active:
            return self._outcome("NO_WORK", state=envelope)
        mission = state["mission_state"]["missions"].get(active)
        if not mission or mission.get("status") not in {
            "PLANNED",
            "ACTIVE",
            "BLOCKED",
            "INTERRUPTED",
            "VALIDATING",
        }:
            return self._outcome(
                "SAFETY_HALT",
                state=envelope,
                findings=(
                    {
                        "code": "MANIFEST_OR_ASSIGNMENT_MISMATCH",
                        "detail": "active mission invalid",
                    },
                ),
            )
        current = self._computed_milestone(state, active)
        if current != state["execution_state"].get("current_milestone_id"):
            return self._outcome(
                "RECOVERY_REQUIRED",
                state=envelope,
                reason="MILESTONE_MISMATCH",
                computed_milestone=current,
            )
        agents = state["agent_state"].get("agents", state["agent_state"])
        assignments = state["execution_state"].get("assignments", {})
        interrupted = [
            aid
            for aid, assignment in assignments.items()
            if assignment.get("status") == "IN_PROGRESS"
            and agents.get(assignment.get("assigned_agent_id"), {}).get("status")
            in {"FAILED", "QUARANTINED"}
        ]
        if interrupted:
            return self._outcome(
                "RECOVERY_REQUIRED", state=envelope, interrupted_assignments=interrupted
            )
        candidates = []
        for aid, assignment in assignments.items():
            agent = agents.get(assignment.get("assigned_agent_id"), {})
            if (
                assignment.get("mission_id") != active
                or assignment.get("status") != "READY"
                or assignment.get("milestone_id") != current
            ):
                continue
            if (
                agent.get("status") != "READY"
                or agent.get("dependency_environment_state", {}).get("status")
                != "VERIFIED"
            ):
                continue
            if any(
                assignments.get(dep, {}).get("status") != "COMPLETED"
                for dep in assignment.get("depends_on", [])
            ):
                continue
            if any(
                r.get("status") == "HALT"
                or r.get("severity") == "CRITICAL"
                and r.get("status") != "RESOLVED"
                for r in state.get("risk_state", {}).get("risks", {}).values()
            ):
                continue
            candidates.append(
                (
                    PRIORITY.get(mission.get("priority"), 99),
                    self._milestone_order(state, current),
                    aid,
                    assignment,
                )
            )
        if not candidates:
            return self._outcome("NO_WORK", state=envelope)
        _, _, aid, assignment = min(candidates)
        latest = self._latest_checkpoint(active)
        if not latest:
            return self._outcome(
                "RECOVERY_REQUIRED", state=envelope, reason="MISSING_CHECKPOINT"
            )
        return self._outcome(
            "RESUME_PLAN",
            state=envelope,
            milestone_id=current,
            active_mission_ids=[active],
            completed_mission_ids=[
                mid
                for mid, item in state["mission_state"]["missions"].items()
                if item.get("status")
                in {"COMPLETED", "CANCELLED", "FAILED", "ARCHIVED"}
            ],
            interrupted_assignments=[],
            next_assignment_id=aid,
            required_checkpoint_id=latest[1]["checkpoint_id"],
            preconditions_validated=True,
        )

    def acquire_lock(
        self, actor: str, expected_revision: int | None = None
    ) -> PESEOutcome:
        self._mkdirs()
        lock_id = f"LOCK-{utc_compact()}-{os.getpid()}"
        now = datetime.now(UTC)
        value = {
            "format": FORMAT,
            "kind": "lock",
            "lock_name": "state",
            "lock_id": lock_id,
            "owner_agent_id": actor,
            "owner_process_id": str(os.getpid()),
            "acquired_at": utc_now(),
            "lease_expires_at": (now + timedelta(seconds=self.lease_seconds))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "last_renewed_at": utc_now(),
            "purpose": "state-update",
            "expected_revision": expected_revision
            if expected_revision is not None
            else 0,
            "extensions": {"org.asc.lease_seconds": self.lease_seconds},
        }
        value["file_sha256"] = canonical_sha256(value)
        try:
            self._exclusive_write(self.lock_path, value)
            self._lock_id = lock_id
            return self._outcome("LOCK_ACQUIRED", lock_id=lock_id)
        except FileExistsError:
            return self._outcome(
                "LOCKED", findings=({"code": "LOCKED", "detail": "writer lock exists"},)
            )

    def renew_lock(self, actor: str) -> PESEOutcome:
        if not self.lock_path.exists() or self._lock_id is None:
            return self._outcome(
                "SAFETY_HALT",
                findings=({"code": "LOCK_OWNERSHIP", "detail": "no owned lock"},),
            )
        lock = _json_load(self.lock_path)
        if lock.get("lock_id") != self._lock_id or lock.get("owner_agent_id") != actor:
            return self._outcome(
                "SAFETY_HALT",
                findings=(
                    {"code": "LOCK_OWNERSHIP", "detail": "lock ownership changed"},
                ),
            )
        now = datetime.now(UTC)
        lock["last_renewed_at"] = utc_now()
        lock["lease_expires_at"] = (
            (now + timedelta(seconds=self.lease_seconds))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        lock["file_sha256"] = canonical_sha256(lock, "file_sha256")
        self._atomic_write(self.lock_path, lock)
        return self._outcome("LOCK_RENEWED", lock_id=self._lock_id)

    def release_lock(self, actor: str) -> PESEOutcome:
        if not self.lock_path.exists():
            return self._outcome("LOCK_RELEASED")
        lock = _json_load(self.lock_path)
        if lock.get("lock_id") != self._lock_id or lock.get("owner_agent_id") != actor:
            return self._outcome(
                "SAFETY_HALT",
                findings=(
                    {
                        "code": "LOCK_OWNERSHIP",
                        "detail": "cannot release another writer lock",
                    },
                ),
            )
        self.lock_path.unlink()
        self._lock_id = None
        return self._outcome("LOCK_RELEASED")

    def recover(
        self, *, actor: str, trigger: str = "INTERRUPTION", stale_lock: bool = False
    ) -> PESEOutcome:
        """Reconcile a completed history publication with a stale/missing live alias.

        A stale takeover preserves the lock as recovery evidence before acquiring
        a successor lock.  Ambiguous liveness is intentionally a safety halt.
        """
        self._mkdirs()
        # Before promoting any history revision, prove the complete continuous
        # history/checkpoint/audit chain.  ``live.json`` and a migration journal
        # are derived/recoverable, so they are evaluated separately below.
        integrity = self.validate(
            check_repository=False, check_lock=False, check_migrations=False
        )
        non_live = [
            finding
            for finding in integrity.findings
            if not (
                finding["code"] == "STATE_CHAIN_INVALID"
                and "live.json" in finding["detail"]
            )
        ]
        if non_live:
            return self._outcome("SAFETY_HALT", findings=non_live)
        if self.lock_path.exists():
            lock = _json_load(self.lock_path)
            expires = datetime.fromisoformat(
                lock["lease_expires_at"].replace("Z", "+00:00")
            )
            live = (
                self.liveness_check(lock.get("owner_process_id", ""))
                if self.liveness_check
                else None
            )
            if not stale_lock or datetime.now(UTC) <= expires or live is not False:
                return self._outcome(
                    "SAFETY_HALT",
                    findings=(
                        {
                            "code": "SAFETY_HALT",
                            "detail": "lock is non-stale or liveness ambiguous",
                        },
                    ),
                )
            preserved = self._path("recovery", f"STALE-LOCK-{utc_compact()}-0001.json")
            os.replace(self.lock_path, preserved)
        successor = self.acquire_lock(actor)
        if successor.code != "LOCK_ACQUIRED":
            return successor
        history = sorted(
            self._path("state/history").glob("*.json"), key=lambda p: int(p.stem)
        )
        if not history:
            self.release_lock(actor)
            return self._outcome(
                "SAFETY_HALT",
                findings=(
                    {"code": "STATE_MISSING", "detail": "no recoverable history"},
                ),
            )
        try:
            highest = _json_load(history[-1])
            self._validate_envelope(highest)
            self._atomic_write(self.live_path, highest)
            self._recover_started_migrations(highest)
            record = {
                "format": FORMAT,
                "kind": "recovery",
                "recovery_id": f"REC-{utc_compact()}-0001",
                "started_at": utc_now(),
                "completed_at": utc_now(),
                "trigger": "STALE_LOCK_RECOVERY" if stale_lock else trigger,
                "affected_mission_id": highest["state"]["mission_state"].get(
                    "active_mission_id"
                ),
                "affected_agent_id": None,
                "affected_assignment_id": None,
                "position_id": None,
                "replacement_count_before": 0,
                "replacement_count_after": 0,
                "replacement_lineage_ref": None,
                "last_good_checkpoint_id": None,
                "observed_evidence_refs": [f"PESE/state/history/{history[-1].name}"],
                "actions": ["RECONCILE_LIVE"],
                "outcome": "RESUMED",
            }
            record["file_sha256"] = canonical_sha256(record)
            self._atomic_write(
                self._path("recovery", record["recovery_id"] + ".json"),
                record,
                overwrite=False,
            )
            return self._outcome(
                "RECOVERED", state=highest, recovery_id=record["recovery_id"]
            )
        finally:
            self.release_lock(actor)

    def migrate(
        self,
        *,
        actor: str,
        to_schema_version: str,
        transform: Callable[[dict[str, Any]], dict[str, Any]],
        mission_id: str | None = None,
    ) -> PESEOutcome:
        """Migrate under one lock, including the required pre-migration checkpoint."""
        acquired = self.acquire_lock(actor)
        if acquired.code != "LOCK_ACQUIRED":
            return acquired
        try:
            loaded = self.load(actor=actor, check_migrations=False)
            if loaded.code != "STATE_LOADED":
                return self._outcome("HALTED", findings=loaded.findings)
            old = loaded.data["envelope"]
            if int(to_schema_version.split(".")[0]) != 1:
                return self._outcome("STATE_INCOMPATIBLE", state=old)
            target_mission = mission_id or old["state"]["mission_state"].get(
                "active_mission_id"
            )
            cp = (
                self.checkpoint(
                    target_mission, "MANUAL", actor=actor, state_envelope=old
                )
                if target_mission
                else None
            )
            if target_mission and (cp is None or cp.code != "CHECKPOINTED"):
                return self._outcome(
                    "HALTED",
                    state=old,
                    findings=cp.findings
                    if cp
                    else (
                        {
                            "code": "CHECKPOINT_REQUIRED",
                            "detail": "pre-migration checkpoint missing",
                        },
                    ),
                )
            migration_id = f"MIG-{utc_compact()}-0001"
            started = {
                "format": FORMAT,
                "kind": "migration",
                "migration_id": migration_id,
                "from_schema_version": old["state"]["schema_version"],
                "to_schema_version": to_schema_version,
                "started_at": utc_now(),
                "completed_at": None,
                "initiated_by": actor,
                "pre_migration_checkpoint_id": cp.data["checkpoint_id"]
                if cp and cp.code == "CHECKPOINTED"
                else None,
                "input_revision": old["revision"],
                "output_revision": None,
                "result": "STARTED",
                "transform_sha256": canonical_sha256(
                    {"from": old["state"]["schema_version"], "to": to_schema_version}
                ),
                "error": None,
            }
            started["file_sha256"] = canonical_sha256(started)
            # Migration status is a transaction journal: STARTED is published
            # before executing untrusted transform code, then terminalized.
            self._atomic_write(
                self._path("migrations", migration_id + ".json"),
                started,
                overwrite=False,
            )
            try:
                proposed = transform(json.loads(canonical_json(old["state"]).decode()))
                proposed["schema_version"] = to_schema_version
                self._validate_state_shape(proposed)

                def apply_migration(current: dict[str, Any]) -> None:
                    current.clear()
                    current.update(proposed)

                result = self.update(
                    expected_revision=old["revision"],
                    actor=actor,
                    transition_type="SCHEMA_VERSION",
                    subject="state",
                    from_value=old["state"]["schema_version"],
                    to_value=to_schema_version,
                    mutate=apply_migration,
                    _lock_held=True,
                )
                status, output, error = (
                    ("SUCCEEDED", result.state_revision, None)
                    if result.code == "UPDATED"
                    else (
                        "FAILED",
                        None,
                        {
                            "code": result.code,
                            "detail": "migration state update failed",
                        },
                    )
                )
            except Exception as exc:
                status, output, error = (
                    "FAILED",
                    None,
                    {
                        "code": getattr(exc, "code", "MIGRATION_FAILED"),
                        "detail": str(exc)[:256],
                    },
                )
            record = {
                **started,
                "completed_at": utc_now(),
                "output_revision": output,
                "result": status,
                "error": error,
            }
            record["file_sha256"] = canonical_sha256(record, "file_sha256")
            self._atomic_write(self._path("migrations", migration_id + ".json"), record)
            return self._outcome(
                "MIGRATED" if status == "SUCCEEDED" else "HALTED",
                state=_json_load(self.live_path),
                migration_id=migration_id,
            )
        finally:
            self.release_lock(actor)

    def _envelope(
        self,
        state: Mapping[str, Any],
        revision: int,
        writer: str,
        previous_revision: int,
        previous_hash: str,
    ) -> dict[str, Any]:
        result = {
            "format": FORMAT,
            "kind": "state",
            "revision": revision,
            "created_at": utc_now(),
            "writer": writer,
            "previous_revision": previous_revision,
            "previous_state_sha256": previous_hash,
            "state_sha256": canonical_sha256(state),
            "state": dict(state),
        }
        result["file_sha256"] = canonical_sha256(result)
        return result

    def _atomic_write(
        self, destination: Path, value: Mapping[str, Any], *, overwrite: bool = True
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not overwrite and destination.exists():
            raise FileExistsError(destination)
        encoded = canonical_json(value) + b"\n"
        fd, temporary = tempfile.mkstemp(
            prefix=destination.name + ".", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if not overwrite and destination.exists():
                raise FileExistsError(destination)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _exclusive_write(self, destination: Path, value: Mapping[str, Any]) -> None:
        """Atomically publish a new lock without a check-then-replace race."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_json(value) + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            # We created this name atomically, so only this failing writer can
            # remove it; no other writer can have acquired the same name.
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            raise

    def _owns_lock(self, actor: str) -> bool:
        if self._lock_id is None or not self.lock_path.exists():
            return False
        try:
            lock = _json_load(self.lock_path)
            return (
                lock.get("lock_id") == self._lock_id
                and lock.get("owner_agent_id") == actor
            )
        except PESEError:
            return False

    def _validate_envelope(self, item: Mapping[str, Any]) -> None:
        required = {
            "format",
            "kind",
            "revision",
            "created_at",
            "writer",
            "previous_revision",
            "previous_state_sha256",
            "state_sha256",
            "file_sha256",
            "state",
        }
        if (
            set(item) != required
            or item.get("format") != FORMAT
            or item.get("kind") != "state"
        ):
            raise PESEError("SCHEMA_INVALID", "invalid state envelope shape")
        if (
            not isinstance(item["revision"], int)
            or item["revision"] < 1
            or not HASH_RE.fullmatch(item["state_sha256"])
            or not HASH_RE.fullmatch(item["file_sha256"])
        ):
            raise PESEError("SCHEMA_INVALID", "invalid state envelope fields")
        if item["state_sha256"] != canonical_sha256(item["state"]) or item[
            "file_sha256"
        ] != canonical_sha256(item, "file_sha256"):
            raise PESEError("STATE_CHAIN_INVALID", "state/file hash mismatch")
        self._validate_state_shape(item["state"])

    @staticmethod
    def _validate_extensions(extensions: Any) -> None:
        """Require the v1.0 extension namespace without interpreting its data."""
        if not isinstance(extensions, Mapping) or any(
            not isinstance(key, str) or not EXTENSION_KEY_RE.fullmatch(key)
            for key in extensions
        ):
            raise PESEError(
                "SCHEMA_INVALID",
                "extensions keys must use reverse-DNS names",
            )

    def _validate_state_shape(self, state: Mapping[str, Any]) -> None:
        allowed = {
            "schema_version",
            "company_state",
            "repo_state",
            "mission_state",
            "execution_state",
            "validation_state",
            "risk_state",
            "agent_state",
            "recovery_state",
            "extensions",
        }
        # recovery_state is optional so states initialized before REC v1.0
        # (without the recovery ledger) continue to validate.
        required = allowed - {"extensions", "recovery_state"}
        if (
            not isinstance(state, Mapping)
            or not required <= set(state)
            or not set(state) <= allowed
        ):
            raise PESEError(
                "SCHEMA_INVALID", "state must contain exactly PESE top-level components"
            )
        if "extensions" in state:
            self._validate_extensions(state["extensions"])
        version = state.get("schema_version")
        if not isinstance(version, str) or not re.fullmatch(r"1\.\d+\.\d+", version):
            raise PESEError(
                "STATE_INCOMPATIBLE", f"unsupported schema version {version!r}"
            )
        for name in required - {"schema_version"}:
            if not isinstance(state[name], Mapping):
                raise PESEError("SCHEMA_INVALID", f"{name} must be object")
        company_fields = {
            "company_id",
            "status",
            "protocols",
            "registry_ref",
            "team_builder_ref",
            "message_protocol_ref",
            "created_at",
            "updated_at",
        }
        repo_fields = {
            "repository_id",
            "root",
            "vcs",
            "origin_identity",
            "HEAD",
            "BRANCH",
            "head_kind",
            "worktree_fingerprint_sha256",
            "dirty_paths",
            "last_verified_at",
        }
        if set(state["company_state"]) != company_fields or state["company_state"].get(
            "status"
        ) not in {"INITIALIZING", "ACTIVE", "RECOVERING", "HALTED", "ARCHIVED"}:
            raise PESEError("SCHEMA_INVALID", "invalid company_state")
        if (
            set(state["repo_state"]) != repo_fields
            or state["repo_state"].get("vcs") != "git"
            or state["repo_state"].get("head_kind") != "COMMIT"
        ):
            raise PESEError("SCHEMA_INVALID", "invalid repo_state")
        if (
            set(state["mission_state"]) != {"active_mission_id", "missions"}
            or set(state["execution_state"])
            != {
                "current_milestone_id",
                "milestones",
                "assignments",
                "next_task_candidates",
            }
            or set(state["validation_state"]) != {"gates", "artifacts"}
            or set(state["risk_state"]) != {"risks"}
            or set(state["agent_state"]) != {"agents"}
        ):
            raise PESEError("SCHEMA_INVALID", "invalid PESE component shape")
        missions = state["mission_state"].get("missions")
        if not isinstance(missions, Mapping):
            raise PESEError("SCHEMA_INVALID", "mission_state.missions must be object")
        active = state["mission_state"].get("active_mission_id")
        if active is not None and active not in missions:
            raise PESEError("CONTRACT_INVALID", "active mission does not exist")
        active_statuses = {"ACTIVE", "INTERRUPTED", "VALIDATING"}
        mission_fields = {
            "status",
            "priority",
            "manifest_ref",
            "manifest_version",
            "assigned_agent_ids",
            "started_at",
            "completed_at",
            "last_checkpoint_id",
            "acceptance_evidence_refs",
            "dissolution_record",
        }
        for mission_id, mission in missions.items():
            if (
                not MISSION_RE.fullmatch(mission_id)
                or not isinstance(mission, Mapping)
                or not {
                    field for field in mission_fields if field != "dissolution_record"
                }
                <= set(mission)
                or not set(mission) <= mission_fields
                or mission.get("status")
                not in {
                    "PLANNED",
                    "ACTIVE",
                    "BLOCKED",
                    "INTERRUPTED",
                    "VALIDATING",
                    "COMPLETED",
                    "CANCELLED",
                    "FAILED",
                    "ARCHIVED",
                }
            ):
                raise PESEError("SCHEMA_INVALID", f"invalid mission {mission_id!r}")
            if mission.get("status") == "ARCHIVED":
                self._validate_dissolution(mission_id, mission)
        if (
            sum(
                1 for item in missions.values() if item.get("status") in active_statuses
            )
            > 1
        ):
            raise PESEError(
                "CONTRACT_INVALID",
                "multiple active missions require manifest partition evidence",
            )
        assignments = state["execution_state"].get("assignments")
        if not isinstance(assignments, Mapping):
            raise PESEError(
                "SCHEMA_INVALID", "execution_state.assignments must be object"
            )
        agents = state["agent_state"].get("agents", state["agent_state"])
        if not isinstance(agents, Mapping):
            raise PESEError("SCHEMA_INVALID", "agent_state must be object")
        assignment_fields = {
            "mission_id",
            "milestone_id",
            "status",
            "assigned_agent_id",
            "manifest_version",
            "depends_on",
            "input_refs",
            "output_refs",
            "started_at",
            "completed_at",
            "last_checkpoint_id",
            "position_id",
            "replacement_count",
            "replacement_lineage",
            "interruption",
        }
        for assignment_id, assignment in assignments.items():
            if (
                not ASSIGNMENT_RE.fullmatch(assignment_id)
                or not isinstance(assignment, Mapping)
                or set(assignment) != assignment_fields
                or assignment.get("status")
                not in {
                    "PENDING",
                    "READY",
                    "IN_PROGRESS",
                    "BLOCKED",
                    "INTERRUPTED",
                    "COMPLETED",
                    "CANCELLED",
                    "FAILED",
                }
            ):
                raise PESEError(
                    "SCHEMA_INVALID", f"invalid assignment {assignment_id!r}"
                )
            if assignment.get("mission_id") not in missions:
                raise PESEError(
                    "CONTRACT_INVALID",
                    f"assignment {assignment_id} has unknown mission",
                )
            if assignment.get("status") in {"READY", "IN_PROGRESS"}:
                agent = agents.get(assignment.get("assigned_agent_id"), {})
                if (
                    agent.get("dependency_environment_state", {}).get("status")
                    != "VERIFIED"
                ):
                    raise PESEError(
                        "CONTRACT_INVALID",
                        f"assignment {assignment_id} has unverified dependencies",
                    )
        agent_fields = {
            "agent_id",
            "status",
            "mission_id",
            "assignment_id",
            "manifest_version",
            "last_heartbeat_at",
            "last_checkpoint_id",
            "acr_ref",
            "dependency_environment_state",
            "interruption",
        }
        for agent_id, agent in agents.items():
            if (
                not isinstance(agent, Mapping)
                or set(agent) != agent_fields
                or agent.get("agent_id") != agent_id
            ):
                raise PESEError("SCHEMA_INVALID", f"invalid agent {agent_id!r}")
            dependency = agent["dependency_environment_state"]
            if (
                not isinstance(dependency, Mapping)
                or set(dependency)
                != {
                    "status",
                    "verified_at",
                    "tool_dependencies",
                    "environment_dependencies",
                }
                or dependency.get("status")
                not in {"VERIFIED", "MISSING", "MISMATCH", "UNKNOWN"}
            ):
                raise PESEError(
                    "SCHEMA_INVALID", f"invalid dependencies for {agent_id}"
                )
        gates = state["validation_state"].get("gates", {})
        if not isinstance(gates, Mapping):
            raise PESEError("SCHEMA_INVALID", "validation_state.gates must be object")
        artifacts = state["validation_state"].get("artifacts", {})
        if not isinstance(artifacts, Mapping):
            raise PESEError(
                "SCHEMA_INVALID", "validation_state.artifacts must be object"
            )
        for gate_id, gate in gates.items():
            gate_fields = {
                "mission_id",
                "status",
                "validator_agent_id",
                "manifest_version",
                "criteria_refs",
                "artifact_ids",
                "last_checkpoint_id",
                "verdict_at",
            }
            if (
                not isinstance(gate, Mapping)
                or set(gate) != gate_fields
                or gate.get("status")
                not in {
                    "PENDING",
                    "RUNNING",
                    "GREEN",
                    "RED",
                    "BLOCKED",
                    "INVALIDATED",
                    "WAIVED",
                }
            ):
                raise PESEError(
                    "SCHEMA_INVALID", f"invalid validation gate {gate_id!r}"
                )
            if gate.get("mission_id") not in missions:
                raise PESEError(
                    "CONTRACT_INVALID", f"gate {gate_id} has unknown mission"
                )
            if gate.get("status") == "GREEN":
                validator = agents.get(gate.get("validator_agent_id"), {})
                artifact_ids = gate.get("artifact_ids", [])
                artifacts = state["validation_state"].get("artifacts", {})
                if (
                    not validator
                    or not isinstance(artifact_ids, list)
                    or not artifact_ids
                ):
                    raise PESEError(
                        "VALIDATION_EVIDENCE_INVALID",
                        f"green gate {gate_id} lacks validator/artifacts",
                    )
                for artifact_id in artifact_ids:
                    artifact = artifacts.get(artifact_id)
                    required_artifact = {
                        "path",
                        "sha256",
                        "type",
                        "produced_at",
                        "producer_agent_id",
                        "retention_class",
                    }
                    if (
                        not isinstance(artifact, Mapping)
                        or set(artifact) != required_artifact
                    ):
                        raise PESEError(
                            "VALIDATION_EVIDENCE_INVALID",
                            f"green gate {gate_id} has invalid artifact",
                        )
                    path = _safe_rel(self.root, artifact["path"])
                    if (
                        not path.is_file()
                        or sha256(path.read_bytes()).hexdigest() != artifact["sha256"]
                    ):
                        raise PESEError(
                            "VALIDATION_EVIDENCE_INVALID",
                            f"green gate {gate_id} artifact binding fails",
                        )
        artifact_fields = {
            "path",
            "sha256",
            "type",
            "produced_at",
            "producer_agent_id",
            "retention_class",
        }
        for artifact_id, artifact in artifacts.items():
            if (
                not isinstance(artifact, Mapping)
                or set(artifact) != artifact_fields
                or not HASH_RE.fullmatch(artifact.get("sha256", ""))
            ):
                raise PESEError("SCHEMA_INVALID", f"invalid artifact {artifact_id!r}")
        risks = state["risk_state"]["risks"]
        risk_fields = {
            "risk_id",
            "status",
            "severity",
            "description",
            "mission_id",
            "evidence_refs",
            "owner_agent_id",
            "opened_at",
            "resolved_at",
        }
        if not isinstance(risks, Mapping):
            raise PESEError("SCHEMA_INVALID", "risk_state.risks must be object")
        for risk_id, risk in risks.items():
            if (
                not isinstance(risk, Mapping)
                or set(risk) != risk_fields
                or risk.get("risk_id") != risk_id
                or risk.get("status")
                not in {"OPEN", "MITIGATING", "ACCEPTED", "RESOLVED", "HALT"}
                or risk.get("severity") not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
            ):
                raise PESEError("SCHEMA_INVALID", f"invalid risk {risk_id!r}")

    def _validate_dissolution(
        self, mission_id: str, mission: Mapping[str, Any]
    ) -> None:
        record = mission.get("dissolution_record")
        required = {
            "status",
            "trigger",
            "freeze_checkpoint_id",
            "final_validation",
            "mission_record_ref",
            "consolidated_evidence_refs",
            "consolidated_gate_refs",
            "consolidated_review_refs",
            "consolidated_kpi_refs",
            "consolidated_conflict_refs",
            "knowledge_extraction_refs",
            "retention_applied_at",
            "membership_release_verified_at",
            "final_manifest_ref",
            "dissolution_report_ref",
            "completed_at",
        }
        if (
            not isinstance(record, Mapping)
            or not required <= set(record)
            or record.get("status") != "COMPLETE"
        ):
            raise PESEError(
                "DISSOLUTION_RECORD_INCOMPLETE",
                f"archived {mission_id} lacks dissolution record",
            )
        reference = record.get("mission_record_ref")
        if (
            not isinstance(reference, Mapping)
            or set(reference) != {"path", "sha256"}
            or not HASH_RE.fullmatch(reference.get("sha256", ""))
        ):
            raise PESEError(
                "DISSOLUTION_RECORD_INCOMPLETE", "invalid mission_record_ref"
            )
        # TEAM identifiers are namespace values (with colons), while the path
        # itself remains repository-relative and containment-checked.
        path = _safe_rel(self.root, reference["path"])
        prefix = ".project-os/COMPANY/TEAMS/"
        if (
            not reference["path"].replace("\\", "/").startswith(prefix)
            or not path.is_file()
            or sha256(path.read_bytes()).hexdigest() != reference["sha256"]
        ):
            raise PESEError(
                "DISSOLUTION_RECORD_INCOMPLETE",
                "mission record is missing, misplaced, or hash-mismatched",
            )
        try:
            contents = _json_load(path)
        except PESEError as exc:
            raise PESEError(
                "DISSOLUTION_RECORD_INCOMPLETE", "mission record is not valid evidence"
            ) from exc
        required_evidence = ("evidence", "gates", "reviews", "kpis", "conflicts")
        if not all(key in contents for key in required_evidence):
            raise PESEError(
                "DISSOLUTION_RECORD_INCOMPLETE",
                "mission record lacks consolidated evidence",
            )
        final = record.get("final_validation", {})
        if record.get("trigger") == "VERIFIED_COMPLETION" and (
            final.get("required") is not True or not final.get("green_gate_ids")
        ):
            raise PESEError(
                "DISSOLUTION_RECORD_INCOMPLETE",
                "verified completion needs final green validation",
            )
        if not self._checkpoint_exists(record["freeze_checkpoint_id"]):
            raise PESEError(
                "DISSOLUTION_RECORD_INCOMPLETE", "freeze checkpoint is missing"
            )
        gates = self._load_current_gates()
        for gate_id in final.get("green_gate_ids", []):
            if gates.get(gate_id, {}).get("status") != "GREEN":
                raise PESEError(
                    "DISSOLUTION_RECORD_INCOMPLETE", "final green gate is not bound"
                )
        for key in ("final_manifest_ref", "dissolution_report_ref"):
            candidate = _safe_rel(self.root, record[key])
            if not candidate.is_file():
                raise PESEError("DISSOLUTION_RECORD_INCOMPLETE", f"missing {key}")
        for key in (
            "consolidated_evidence_refs",
            "consolidated_review_refs",
            "consolidated_kpi_refs",
            "consolidated_conflict_refs",
        ):
            if not isinstance(record[key], list) or not record[key]:
                raise PESEError("DISSOLUTION_RECORD_INCOMPLETE", f"missing {key}")
        bindings = {
            "consolidated_evidence_refs": "evidence",
            "consolidated_gate_refs": "gates",
            "consolidated_review_refs": "reviews",
            "consolidated_kpi_refs": "kpis",
            "consolidated_conflict_refs": "conflicts",
        }
        for record_key, content_key in bindings.items():
            references = record.get(record_key)
            if (
                not isinstance(references, list)
                or not isinstance(contents[content_key], list)
                or not {canonical_json(value) for value in references}
                <= {canonical_json(value) for value in contents[content_key]}
            ):
                raise PESEError(
                    "DISSOLUTION_RECORD_INCOMPLETE",
                    f"mission record does not bind {record_key}",
                )
            for evidence in references:
                if isinstance(evidence, Mapping):
                    self._validate_evidence_reference(evidence)
                elif isinstance(evidence, str) and not evidence.startswith(
                    ("GATE:", "ACP:")
                ):
                    candidate = _safe_rel(self.root, evidence)
                    if not candidate.is_file():
                        raise PESEError(
                            "DISSOLUTION_RECORD_INCOMPLETE",
                            f"missing bound evidence {evidence}",
                        )
                else:
                    if not isinstance(evidence, str):
                        raise PESEError(
                            "DISSOLUTION_RECORD_INCOMPLETE",
                            "invalid bound evidence reference",
                        )
        if (
            not isinstance(record["knowledge_extraction_refs"], list)
            or not record["knowledge_extraction_refs"]
            or not record.get("retention_applied_at")
            or not record.get("membership_release_verified_at")
            or not record.get("completed_at")
        ):
            raise PESEError(
                "DISSOLUTION_RECORD_INCOMPLETE",
                "knowledge, retention, release, or completion evidence missing",
            )

    def _checkpoint_exists(self, checkpoint_id: str) -> bool:
        return (
            isinstance(checkpoint_id, str)
            and (self._path("checkpoints", checkpoint_id + ".json")).is_file()
        )

    def _load_current_gates(self) -> Mapping[str, Any]:
        """Use in-memory state validation where possible without trusting live aliases."""
        if not self.live_path.exists():
            return {}
        try:
            return (
                _json_load(self.live_path)
                .get("state", {})
                .get("validation_state", {})
                .get("gates", {})
            )
        except PESEError:
            return {}

    def _validate_evidence_reference(self, reference: Any) -> None:
        if isinstance(reference, str):
            # ACP identifiers are cross-audit references, not repository paths.
            if reference.startswith("ACP:"):
                return
            _safe_rel(self.root, reference)
            return
        if (
            not isinstance(reference, Mapping)
            or set(reference) != {"path", "sha256"}
            or not HASH_RE.fullmatch(reference.get("sha256", ""))
        ):
            raise PESEError(
                "CONTRACT_INVALID", "evidence reference must be a path or {path,sha256}"
            )
        path = _safe_rel(self.root, reference["path"])
        if (
            not path.is_file()
            or sha256(path.read_bytes()).hexdigest() != reference["sha256"]
        ):
            raise PESEError(
                "CONTRACT_INVALID", f"evidence hash mismatch: {reference['path']}"
            )

    def _validate_checkpoints(self, last: Mapping[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        preceding: dict[str, tuple[str | None, str | None]] = {}
        for path in sorted(self._path("checkpoints").glob("*.json")):
            try:
                item = _json_load(path)
                checkpoint_fields = {
                    "format",
                    "kind",
                    "checkpoint_id",
                    "reason",
                    "created_at",
                    "created_by",
                    "mission_id",
                    "state_revision",
                    "state_sha256",
                    "repository",
                    "snapshot",
                    "snapshot_sha256",
                    "previous_checkpoint_id",
                    "previous_checkpoint_sha256",
                    "file_sha256",
                }
                if (
                    set(item) != checkpoint_fields
                    or item.get("reason")
                    not in {
                        "MISSION_START",
                        "MISSION_FINISH",
                        "VALIDATION",
                        "COMMIT",
                        "FAILURE",
                        "INTERRUPTION",
                        "MANUAL",
                    }
                    or item.get("format") != FORMAT
                    or item.get("kind") != "checkpoint"
                    or path.stem != item.get("checkpoint_id")
                    or not CHECKPOINT_RE.fullmatch(item.get("checkpoint_id", ""))
                ):
                    raise PESEError(
                        "CHECKPOINT_CHAIN_INVALID",
                        f"invalid checkpoint identity {path.name}",
                    )
                if item.get("file_sha256") != canonical_sha256(
                    item, "file_sha256"
                ) or item.get("snapshot_sha256") != canonical_sha256(
                    item.get("snapshot")
                ):
                    raise PESEError(
                        "CHECKPOINT_CHAIN_INVALID",
                        f"checkpoint hash mismatch {path.name}",
                    )
                history = self._path("state/history", f"{item['state_revision']}.json")
                if not history.exists() or _json_load(history).get(
                    "state_sha256"
                ) != item.get("state_sha256"):
                    raise PESEError(
                        "CHECKPOINT_CHAIN_INVALID",
                        f"checkpoint state binding {path.name}",
                    )
                prior = preceding.get(item["mission_id"], (None, None))
                if (
                    item.get("previous_checkpoint_id"),
                    item.get("previous_checkpoint_sha256"),
                ) != prior:
                    raise PESEError(
                        "CHECKPOINT_CHAIN_INVALID",
                        f"checkpoint predecessor {path.name}",
                    )
                preceding[item["mission_id"]] = (
                    item["checkpoint_id"],
                    item["file_sha256"],
                )
            except (PESEError, KeyError) as exc:
                findings.append(
                    {
                        "gate": "checkpoint chain",
                        "code": getattr(exc, "code", "CHECKPOINT_CHAIN_INVALID"),
                        "detail": str(exc),
                    }
                )
        return findings

    def _validate_lock(self) -> list[dict[str, Any]]:
        """Validate a present lease; absence is the normal unlocked state."""
        if not self.lock_path.exists():
            return []
        try:
            item = _json_load(self.lock_path)
            required = {
                "format",
                "kind",
                "lock_name",
                "lock_id",
                "owner_agent_id",
                "owner_process_id",
                "acquired_at",
                "lease_expires_at",
                "last_renewed_at",
                "purpose",
                "expected_revision",
                "file_sha256",
                "extensions",
            }
            if (
                set(item) != required
                or item.get("format") != FORMAT
                or item.get("kind") != "lock"
                or item.get("lock_name") != "state"
                or not isinstance(item.get("expected_revision"), int)
            ):
                raise PESEError("LOCK_INVALID", "invalid lock object shape")
            self._validate_extensions(item["extensions"])
            if item.get("file_sha256") != canonical_sha256(item, "file_sha256"):
                raise PESEError("LOCK_INVALID", "lock hash mismatch")
            expires = datetime.fromisoformat(
                item["lease_expires_at"].replace("Z", "+00:00")
            )
            if expires.tzinfo is None:
                raise PESEError("LOCK_INVALID", "lock expiry has no timezone")
            if datetime.now(UTC) > expires:
                return [
                    {
                        "gate": "locking",
                        "code": "UNVERIFIED_STALE_LOCK",
                        "detail": "expired lock requires verified recovery",
                    }
                ]
        except (KeyError, ValueError, PESEError) as exc:
            return [{"gate": "locking", "code": "LOCK_INVALID", "detail": str(exc)}]
        return []

    def _validate_audits(self) -> list[dict[str, Any]]:
        findings = []
        for stream in ("access", "transitions"):
            previous = ZERO_HASH
            for path in sorted(self._path("audit", stream).glob("*.json")):
                try:
                    item = _json_load(path)
                    access_fields = {
                        "format",
                        "kind",
                        "audit_id",
                        "occurred_at",
                        "actor_agent_id",
                        "operation",
                        "target",
                        "result",
                        "state_revision",
                        "correlation_id",
                        "detail_sha256",
                        "previous_audit_sha256",
                        "file_sha256",
                    }
                    transition_fields = {
                        "format",
                        "kind",
                        "audit_id",
                        "occurred_at",
                        "actor_agent_id",
                        "transition_type",
                        "subject",
                        "from",
                        "to",
                        "reason",
                        "before_state_sha256",
                        "after_state_sha256",
                        "evidence_refs",
                        "acp_correlation_id",
                        "previous_audit_sha256",
                        "file_sha256",
                    }
                    expected = (
                        access_fields if stream == "access" else transition_fields
                    )
                    if (
                        set(item) != expected
                        or item.get("format") != FORMAT
                        or item.get("kind")
                        != (
                            "access-audit" if stream == "access" else "transition-audit"
                        )
                        or item.get("file_sha256")
                        != canonical_sha256(item, "file_sha256")
                        or item.get("previous_audit_sha256") != previous
                    ):
                        raise PESEError(
                            "AUDIT_CHAIN_INVALID", f"audit chain break {path.name}"
                        )
                    previous = item["file_sha256"]
                except PESEError as exc:
                    findings.append(
                        {"gate": "audit chain", "code": exc.code, "detail": exc.detail}
                    )
        return findings

    def _validate_migrations(self) -> list[dict[str, Any]]:
        findings = []
        for path in self._path("migrations").glob("*.json"):
            try:
                item = _json_load(path)
                fields = {
                    "format",
                    "kind",
                    "migration_id",
                    "from_schema_version",
                    "to_schema_version",
                    "started_at",
                    "completed_at",
                    "initiated_by",
                    "pre_migration_checkpoint_id",
                    "input_revision",
                    "output_revision",
                    "result",
                    "transform_sha256",
                    "error",
                    "file_sha256",
                }
                if (
                    set(item) != fields
                    or item.get("format") != FORMAT
                    or item.get("kind") != "migration"
                    or item.get("file_sha256") != canonical_sha256(item, "file_sha256")
                    or item.get("result") not in {"SUCCEEDED", "FAILED", "ROLLED_BACK"}
                ):
                    raise PESEError(
                        "MIGRATION_INVALID",
                        f"invalid or unfinished migration {path.name}",
                    )
            except PESEError as exc:
                findings.append(
                    {"gate": "migration", "code": exc.code, "detail": exc.detail}
                )
        return findings

    def _validate_recovery_records(self) -> list[dict[str, Any]]:
        findings = []
        fields = {
            "format",
            "kind",
            "recovery_id",
            "started_at",
            "completed_at",
            "trigger",
            "affected_mission_id",
            "affected_agent_id",
            "affected_assignment_id",
            "position_id",
            "replacement_count_before",
            "replacement_count_after",
            "replacement_lineage_ref",
            "last_good_checkpoint_id",
            "observed_evidence_refs",
            "actions",
            "outcome",
            "file_sha256",
        }
        for path in self._path("recovery").glob("REC-*.json"):
            try:
                item = _json_load(path)
                if (
                    set(item) != fields
                    or item.get("format") != FORMAT
                    or item.get("kind") != "recovery"
                    or item.get("outcome")
                    not in {"RESUMED", "REASSIGNED", "REPLACED", "HALTED", "FAILED"}
                    or item.get("file_sha256") != canonical_sha256(item, "file_sha256")
                ):
                    raise PESEError(
                        "SCHEMA_INVALID", f"invalid recovery record {path.name}"
                    )
            except PESEError as exc:
                findings.append(
                    {"gate": "recovery", "code": exc.code, "detail": exc.detail}
                )
        return findings

    def _recover_started_migrations(self, highest: Mapping[str, Any]) -> None:
        """Terminalize crash-left migration journals without altering history."""
        for path in self._path("migrations").glob("*.json"):
            try:
                item = _json_load(path)
            except PESEError:
                continue
            if item.get("kind") != "migration" or item.get("result") != "STARTED":
                continue
            output = (
                highest["revision"]
                if highest["revision"] > item.get("input_revision", highest["revision"])
                and highest.get("state", {}).get("schema_version")
                == item.get("to_schema_version")
                else None
            )
            mismatch = highest["revision"] > item.get(
                "input_revision", highest["revision"]
            )
            item["result"] = (
                "SUCCEEDED"
                if output is not None
                else "FAILED"
                if mismatch
                else "ROLLED_BACK"
            )
            item["output_revision"] = output
            item["completed_at"] = utc_now()
            item["error"] = (
                None
                if output is not None
                else {
                    "code": "MIGRATION_OUTPUT_MISMATCH" if mismatch else "ROLLED_BACK",
                    "detail": "published revision lacks the requested schema"
                    if mismatch
                    else "no migrated revision was published",
                }
            )
            item["file_sha256"] = canonical_sha256(item, "file_sha256")
            self._atomic_write(path, item)

    def _validate_contracts(self, state: Mapping[str, Any]) -> list[dict[str, Any]]:
        findings = []
        assignments = state["execution_state"].get("assignments", {})
        agents = state["agent_state"].get("agents", state["agent_state"])
        for aid, assignment in assignments.items():
            if not ASSIGNMENT_RE.fullmatch(aid):
                findings.append(
                    {
                        "gate": "contract",
                        "code": "CONTRACT_INVALID",
                        "detail": f"invalid assignment id {aid}",
                    }
                )
            if assignment.get("status") in {"READY", "IN_PROGRESS"}:
                agent = agents.get(assignment.get("assigned_agent_id"), {})
                if (
                    agent.get("dependency_environment_state", {}).get("status")
                    != "VERIFIED"
                ):
                    findings.append(
                        {
                            "gate": "contract",
                            "code": "CONTRACT_INVALID",
                            "detail": f"unverified dependencies for {aid}",
                        }
                    )
        for artifact in state["validation_state"].get("artifacts", {}).values():
            try:
                path = _safe_rel(self.root, artifact["path"])
                if (
                    not path.is_file()
                    or sha256(path.read_bytes()).hexdigest() != artifact["sha256"]
                ):
                    raise PESEError(
                        "VALIDATION_EVIDENCE_INVALID",
                        "validation artifact missing or altered",
                    )
            except (KeyError, PESEError) as exc:
                findings.append(
                    {
                        "gate": "validation",
                        "code": getattr(exc, "code", "VALIDATION_EVIDENCE_INVALID"),
                        "detail": str(exc),
                    }
                )
        return findings

    def _audit_access(
        self, actor: str, operation: str, target: str, result: str, revision: int | None
    ) -> None:
        self._audit(
            "access",
            {
                "format": FORMAT,
                "kind": "access-audit",
                "audit_id": f"ACCESS-{utc_compact()}-{self._next_sequence('audit/access'):04d}",
                "occurred_at": utc_now(),
                "actor_agent_id": actor,
                "operation": operation,
                "target": target,
                "result": result,
                "state_revision": revision,
                "correlation_id": None,
                "detail_sha256": canonical_sha256({}),
            },
        )

    def _audit_transition(
        self,
        actor: str,
        transition: str,
        subject: str,
        old: Any,
        new: Any,
        before: str,
        after: str,
        evidence: list[str],
        correlation: str | None,
    ) -> None:
        self._audit(
            "transitions",
            {
                "format": FORMAT,
                "kind": "transition-audit",
                "audit_id": f"TRANSITION-{utc_compact()}-{self._next_sequence('audit/transitions'):04d}",
                "occurred_at": utc_now(),
                "actor_agent_id": actor,
                "transition_type": transition,
                "subject": subject,
                "from": old,
                "to": new,
                "reason": "state-update",
                "before_state_sha256": before,
                "after_state_sha256": after,
                "evidence_refs": evidence,
                "acp_correlation_id": correlation,
            },
        )

    def _audit(self, stream: str, item: dict[str, Any]) -> None:
        # Readers never take the state writer lock.  A separate short-lived,
        # exclusive audit lock makes the append-chain safe across processes.
        with self._audit_guard:
            lock = self._path("locks", f"audit-{stream}.lock")
            acquired = False
            for _ in range(1_000):
                try:
                    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                    os.close(fd)
                    acquired = True
                    break
                except (FileExistsError, PermissionError):
                    time.sleep(0.001)
            if not acquired:
                raise PESEError(
                    "IO_FAILURE", f"audit append lock unavailable: {stream}"
                )
            try:
                prior = sorted(self._path("audit", stream).glob("*.json"))
                prefix = "ACCESS" if stream == "access" else "TRANSITION"
                item["audit_id"] = f"{prefix}-{utc_compact()}-{len(prior) + 1:04d}"
                item["previous_audit_sha256"] = (
                    _json_load(prior[-1])["file_sha256"] if prior else ZERO_HASH
                )
                item["file_sha256"] = canonical_sha256(item)
                self._exclusive_write(
                    self._path("audit", stream, item["audit_id"] + ".json"), item
                )
            finally:
                for _ in range(100):
                    try:
                        lock.unlink(missing_ok=True)
                        break
                    except PermissionError:
                        time.sleep(0.001)

    def _next_sequence(self, directory: str) -> int:
        return len(list(self._path(directory).glob("*.json"))) + 1

    def _checkpoints(self, mission_id: str) -> list[tuple[Path, dict[str, Any]]]:
        items = []
        for path in self._path("checkpoints").glob("*.json"):
            try:
                item = _json_load(path)
                if item.get("mission_id") == mission_id:
                    items.append((path, item))
            except PESEError:
                continue
        return sorted(
            items,
            key=lambda pair: (
                pair[1].get("created_at", ""),
                pair[1].get("checkpoint_id", ""),
            ),
        )

    def _latest_checkpoint(self, mission_id: str) -> tuple[Path, dict[str, Any]] | None:
        values = self._checkpoints(mission_id)
        return values[-1] if values else None

    def _snapshot(self, state: Mapping[str, Any], mission_id: str) -> dict[str, Any]:
        execution = state["execution_state"]
        assignments = execution.get("assignments", {})
        return {
            "mission_id": mission_id,
            "milestone_id": execution.get("current_milestone_id"),
            "active_assignments": sorted(
                key
                for key, item in assignments.items()
                if item.get("mission_id") == mission_id
                and item.get("status")
                in {"READY", "IN_PROGRESS", "BLOCKED", "INTERRUPTED"}
            ),
            "completed_assignments": sorted(
                key
                for key, item in assignments.items()
                if item.get("mission_id") == mission_id
                and item.get("status") == "COMPLETED"
            ),
            "validation_gate_refs": sorted(
                key
                for key, item in state["validation_state"].get("gates", {}).items()
                if item.get("mission_id") == mission_id
            ),
            "evidence_refs": [],
        }

    def _mission_for_subject(
        self, state: Mapping[str, Any], subject: str
    ) -> str | None:
        if subject in state["mission_state"].get("missions", {}):
            return subject
        return state["execution_state"].get("assignments", {}).get(subject, {}).get(
            "mission_id"
        ) or state["mission_state"].get("active_mission_id")

    def _validate_transition(
        self,
        kind: str,
        old: Any,
        new: Any,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        subject: str,
        actor: str,
    ) -> None:
        legal = {
            "MISSION_STATUS": {
                "PLANNED": {"ACTIVE"},
                "ACTIVE": {
                    "VALIDATING",
                    "BLOCKED",
                    "INTERRUPTED",
                    "FAILED",
                    "CANCELLED",
                },
                "VALIDATING": {
                    "COMPLETED",
                    "BLOCKED",
                    "INTERRUPTED",
                    "FAILED",
                    "CANCELLED",
                },
                "COMPLETED": {"ARCHIVED"},
            },
            "ASSIGNMENT_STATUS": {
                "PENDING": {"READY"},
                "READY": {
                    "IN_PROGRESS",
                    "BLOCKED",
                    "INTERRUPTED",
                    "FAILED",
                    "CANCELLED",
                },
                "IN_PROGRESS": {
                    "COMPLETED",
                    "BLOCKED",
                    "INTERRUPTED",
                    "FAILED",
                    "CANCELLED",
                },
                "BLOCKED": {"READY"},
                "INTERRUPTED": {"READY"},
            },
            "VALIDATION_GATE": {
                "PENDING": {"RUNNING"},
                "RUNNING": {"GREEN", "RED", "BLOCKED", "PENDING"},
                "GREEN": {"INVALIDATED"},
            },
        }
        if kind in legal and new not in legal[kind].get(old, set()):
            raise PESEError("INVALID_TRANSITION", f"{kind}: {old!r} -> {new!r}")
        if kind == "ASSIGNMENT_STATUS":
            assignment = (
                before["execution_state"].get("assignments", {}).get(subject, {})
            )
            if assignment.get("assigned_agent_id") != actor:
                raise PESEError(
                    "UNAUTHORIZED",
                    "only the assigned agent may transition its assignment",
                )
            mission = (
                before["mission_state"]
                .get("missions", {})
                .get(assignment.get("mission_id"), {})
            )
            self._validate_manifest_ownership(mission, actor, subject)
        elif kind == "MISSION_STATUS":
            mission = before["mission_state"].get("missions", {}).get(subject, {})
            if actor not in mission.get("assigned_agent_ids", ()):
                raise PESEError("UNAUTHORIZED", "actor is not assigned to the mission")
            self._validate_manifest_ownership(mission, actor)
        elif kind == "VALIDATION_GATE":
            gate = before["validation_state"].get("gates", {}).get(subject, {})
            if gate.get("validator_agent_id") != actor:
                raise PESEError("UNAUTHORIZED", "actor is not the designated validator")
        # The durable ACR reference is the minimum local proof of a known
        # contract.  PESE does not interpret registry capabilities, but it
        # refuses an actor with no declared ACR output-contract reference.
        agents = before["agent_state"].get("agents", before["agent_state"])
        actor_record = agents.get(actor, {})
        if kind in {
            "ASSIGNMENT_STATUS",
            "MISSION_STATUS",
            "VALIDATION_GATE",
        } and not actor_record.get("acr_ref"):
            raise PESEError(
                "UNAUTHORIZED", "actor has no declared ACR contract reference"
            )
        if kind in {"ASSIGNMENT_STATUS", "MISSION_STATUS", "VALIDATION_GATE"}:
            registry_dir = self.root / ".project-os" / "COMPANY" / "DEPARTMENTS"
            if registry_dir.is_dir():
                try:
                    from .registry import load_project_registry

                    registry = load_project_registry(self.root)
                    agent_type = (
                        actor.split(":", 2)[1] if actor.startswith("AGENT:") else ""
                    )
                    contract = registry.get(agent_type)
                    outputs = contract and contract.get("output-contracts", {}).get(
                        "output-state-changes"
                    )
                    required_scope = {
                        "ASSIGNMENT_STATUS": "EXECUTION",
                        "MISSION_STATUS": "EXECUTION",
                        "VALIDATION_GATE": "VALIDATION",
                    }[kind]
                    # The orchestrator is the designated state authority; its
                    # authority derives from the TBE manifest when no separate
                    # department registry entry exists.
                    if agent_type != "orchestrator" and (
                        not outputs
                        or not any(
                            str(entry).startswith(required_scope + "/")
                            for entry in outputs
                        )
                    ):
                        raise PESEError(
                            "UNAUTHORIZED",
                            "actor ACR has no output state-change authority",
                        )
                except PESEError:
                    raise
                except Exception as exc:
                    raise PESEError(
                        "UNAUTHORIZED", "ACR registry is unavailable or invalid"
                    ) from exc
        if kind == "MISSION_STATUS" and new == "ARCHIVED":
            record = (
                after["mission_state"]["missions"]
                .get(subject, {})
                .get("dissolution_record")
            )
            if not record or record.get("status") != "COMPLETE":
                raise PESEError(
                    "DISSOLUTION_RECORD_INCOMPLETE",
                    "archive requires complete dissolution record",
                )

    def _validate_manifest_ownership(
        self,
        mission: Mapping[str, Any],
        actor: str,
        assignment_id: str | None = None,
    ) -> None:
        reference = mission.get("manifest_ref")
        if not isinstance(reference, str):
            raise PESEError("UNAUTHORIZED", "mission has no manifest reference")
        path = _safe_rel(self.root, reference)
        if not path.is_file():
            raise PESEError("UNAUTHORIZED", "referenced TBE manifest is missing")
        try:
            manifest = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except OSError as exc:
            raise PESEError("UNAUTHORIZED", "manifest cannot be read") from exc
        headings = [
            "TEAM IDENTITY",
            "PROJECT CLASSIFICATION",
            "MEMBERSHIP TABLE",
            "OWNERSHIP MATRIX",
            "EXECUTION GRAPH",
            "REVIEW MATRIX",
            "VALIDATOR ASSIGNMENT",
            "ESCALATION ROUTES",
            "CAPACITY RECORD",
            "ACTIVE POLICIES",
        ]

        def normalized(text: str) -> str:
            return re.sub(r"[^A-Z0-9]", "", text.upper())

        expected = [normalized(heading) for heading in headings]
        lines = manifest.splitlines(keepends=True)
        offsets: list[int] = []
        cursor = 0
        for line in lines:
            offsets.append(cursor)
            cursor += len(line)
        positions = []
        for heading in expected:
            matches = [
                offsets[index]
                for index, line in enumerate(lines)
                if normalized(line) == heading
            ]
            positions.append(matches[0] if len(matches) == 1 else -1)
        if any(position < 0 for position in positions) or positions != sorted(
            positions
        ):
            raise PESEError("UNAUTHORIZED", "TEAM.md lacks fixed-order TBE sections")
        identity = manifest[positions[0] : positions[1]]
        version = re.search(
            r"(?im)\b(?:manifest[ _-]*version|version)\b\s*(?::|=|-)?\s*(\d+)\b",
            identity,
        )
        if version is None or int(version.group(1)) != mission.get("manifest_version"):
            raise PESEError(
                "UNAUTHORIZED", "manifest version differs from mission state"
            )
        membership = manifest[positions[2] : positions[3]]
        if not re.search(
            rf"(?<![A-Za-z0-9:_-]){re.escape(actor)}(?![A-Za-z0-9:_-])",
            membership,
        ):
            raise PESEError("UNAUTHORIZED", "actor is absent from TBE manifest")
        ownership = manifest[positions[3] : positions[5]]
        if assignment_id is not None:
            owns_assignment = bool(
                re.search(
                    rf"(?m)^\|[^\n]*{re.escape(assignment_id)}[^\n]*\|\s*{re.escape(actor)}\s*\|",
                    ownership,
                )
            )
            review = manifest[positions[5] : positions[6]]
            validator = manifest[positions[6] : positions[7]]
            scheduled_owner = self._manifest_scheduled_assignment_owner(
                assignment_id, review, validator
            )
            if not owns_assignment and scheduled_owner != actor:
                raise PESEError(
                    "UNAUTHORIZED",
                    "manifest does not assign ownership of this assignment",
                )

    @staticmethod
    def _manifest_scheduled_assignment_owner(
        assignment_id: str, review_section: str, validator_section: str
    ) -> str | None:
        """Resolve TBE's canonical review/validation control assignments.

        TBE deliberately records repository ownership only for builders.  Its
        Review Matrix and Validator Assignment sections authorize the derived
        PESE control assignments instead, so they must not be treated as file
        ownership.  This parser mirrors TBE's deterministic ID derivation and
        accepts only exact rows from those canonical sections.
        """

        def rows(section: str) -> Iterable[list[str]]:
            for line in section.splitlines():
                if not line.lstrip().startswith("|"):
                    continue
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                if not cells or all(
                    re.fullmatch(r":?-{3,}:?", cell) is not None for cell in cells
                ):
                    continue
                yield cells

        def derived(kind: str, label: str) -> str | None:
            token = label.removeprefix("ASSIGNMENT:")
            safe = "".join(
                character
                if character.isascii() and (character.isalnum() or character in "._-")
                else "-"
                for character in token
            ).strip("-")
            return f"ASSIGNMENT:{kind}-{safe}" if safe else None

        for row in rows(review_section):
            # Deliverable type, owning builder, assigned reviewer, rotation.
            if len(row) >= 3 and derived("review", row[0]) == assignment_id:
                return row[2]
        for row in rows(validator_section):
            # Gate, validator, fallback validator.
            if len(row) >= 2 and derived("validate", row[0]) == assignment_id:
                return row[1]
        return None

    @staticmethod
    def _deep_merge(destination: dict[str, Any], update: Mapping[str, Any]) -> None:
        for key, value in update.items():
            if isinstance(value, Mapping) and isinstance(destination.get(key), dict):
                PESEStore._deep_merge(destination[key], value)
            else:
                destination[key] = value

    def _computed_milestone(
        self, state: Mapping[str, Any], active_mission_id: str | None = None
    ) -> str | None:
        assignments = state["execution_state"].get("assignments", {})
        gates = state["validation_state"].get("gates", {})
        for milestone in sorted(
            state["execution_state"].get("milestones", []),
            key=lambda item: item.get("order", 0),
        ):
            if milestone.get("status") == "SKIPPED":
                continue
            relevant = [
                item
                for item in assignments.values()
                if item.get("milestone_id") == milestone.get("id")
                and (
                    active_mission_id is None
                    or item.get("mission_id") == active_mission_id
                )
            ]
            if active_mission_id is not None and not relevant:
                continue
            mission_ids = {item.get("mission_id") for item in relevant}
            required_gates = [
                gate for gate in gates.values() if gate.get("mission_id") in mission_ids
            ]
            if (
                not relevant
                or not all(item.get("status") == "COMPLETED" for item in relevant)
                or not all(gate.get("status") == "GREEN" for gate in required_gates)
            ):
                return milestone.get("id")
        return None

    def _milestone_order(
        self, state: Mapping[str, Any], milestone_id: str | None
    ) -> int:
        return next(
            (
                item.get("order", 999999)
                for item in state["execution_state"].get("milestones", [])
                if item.get("id") == milestone_id
            ),
            999999,
        )

    _audit_guard = threading.RLock()
