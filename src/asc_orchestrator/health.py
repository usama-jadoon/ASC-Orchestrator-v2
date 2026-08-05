"""Agent Health Protocol (AHP) v1.0.

A deterministic, stdlib-only liveness store that records per-agent heartbeat
histories under ``.project-os/HEALTH/`` and derives ALIVE / STALLED / UNKNOWN
status from heartbeat freshness relative to a configurable timeout.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audit import _process_lock
from .pese import PESEStore, utc_now

AHP_FORMAT = "AHP/v1.0"
HEALTH_DIR = "HEALTH"
_AHP_EXTENSION_KEY = "org.asc.ahp"

_STATUS_ALIVE = "ALIVE"
_STATUS_STALLED = "STALLED"
_STATUS_UNKNOWN = "UNKNOWN"

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.Lock] = {}


def _get_lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.Lock())


def _canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_hash(record: dict[str, Any]) -> str:
    material = {k: v for k, v in record.items() if k != "heartbeat_sha256"}
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _safe_id(identifier: str) -> str:
    """Replace reserved characters for Windows-compatible directory names."""
    return identifier.replace(":", "%3A")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class AHPError(RuntimeError):
    """A structured AHP precondition or contract failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class HeartbeatRecord:
    """Immutable snapshot of a persisted heartbeat record."""

    agent_id: str
    sequence: int
    occurred_at: str
    mission_id: str | None
    assignment_id: str | None
    note: str | None
    previous_heartbeat_sha256: str | None
    heartbeat_sha256: str


@dataclass(frozen=True, slots=True)
class AgentHealth:
    """Derived liveness snapshot for one agent."""

    agent_id: str
    status: str
    heartbeat_count: int
    age_seconds: float | None
    last_heartbeat_at: str | None
    last_mission_id: str | None
    last_assignment_id: str | None


def _parse_timeout(value: object, *, label: str = "timeout") -> float:
    if isinstance(value, bool):
        raise AHPError("INVALID_TIMEOUT", f"{label} must be a non-negative number")
    if not isinstance(value, (int, float, str)):
        raise AHPError("INVALID_TIMEOUT", f"{label} must be a non-negative number")
    try:
        timeout = float(value)
    except ValueError:
        raise AHPError("INVALID_TIMEOUT", f"{label} must be a non-negative number")
    if timeout < 0:
        raise AHPError("INVALID_TIMEOUT", f"{label} must be a non-negative number")
    return timeout


def _resolve_query_time(now: str | datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if isinstance(now, datetime):
        return now.astimezone(UTC)
    return _parse_utc(now)


class HealthStore:
    """Deterministic AHP v1.0 health store operating under .project-os/HEALTH/."""

    def __init__(
        self,
        root: str | Path,
        *,
        health_directory: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        base = (
            Path(health_directory)
            if health_directory is not None
            else self.root / ".project-os" / HEALTH_DIR
        )
        self.directory = base.resolve()
        self.agents_dir = self.directory / "agents"
        self._lock = _get_lock(self.directory)

    # --- internal helpers ---------------------------------------------------

    def _journal_path(self, agent_id: str) -> Path:
        return self.agents_dir / f"{_safe_id(agent_id)}.jsonl"

    def _last_hash(self, path: Path) -> str | None:
        if not path.exists():
            return None
        last: str | None = None
        with path.open("r", encoding="utf-8", newline="") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if last is None:
            return None
        try:
            record = json.loads(last)
            value = record["heartbeat_sha256"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AHPError(
                "JOURNAL_CORRUPT", f"invalid final heartbeat for {path.name}"
            ) from exc
        if not isinstance(value, str) or len(value) != 64:
            raise AHPError(
                "JOURNAL_CORRUPT", f"invalid final heartbeat hash for {path.name}"
            )
        return value

    def _records(self, agent_id: str) -> list[dict[str, Any]]:
        path = self._journal_path(agent_id)
        if not path.exists():
            return []
        result: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8", newline="") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise AHPError(
                        "JOURNAL_CORRUPT",
                        f"malformed heartbeat for {agent_id}: {exc}",
                    ) from exc
        return result

    def _next_sequence(self, agent_id: str) -> int:
        records = self._records(agent_id)
        if not records:
            return 1
        sequence = records[-1].get("sequence")
        if not isinstance(sequence, int):
            raise AHPError("JOURNAL_CORRUPT", f"non-integer sequence for {agent_id}")
        return sequence + 1

    # --- public API ---------------------------------------------------------

    def heartbeat(
        self,
        agent_id: str,
        *,
        mission_id: str | None = None,
        assignment_id: str | None = None,
        note: str | None = None,
        occurred_at: str | None = None,
    ) -> HeartbeatRecord:
        """Append one heartbeat to the agent's hash-chained journal."""
        if not agent_id:
            raise AHPError("INVALID_AGENT", "agent_id must be a non-empty string")
        stamp = occurred_at or utc_now()
        with self._lock:
            self.agents_dir.mkdir(parents=True, exist_ok=True)
            path = self._journal_path(agent_id)
            with _process_lock(self.directory / ".agents.jsonl.lock"):
                sequence = self._next_sequence(agent_id)
                record: dict[str, Any] = {
                    "format": AHP_FORMAT,
                    "kind": "heartbeat",
                    "sequence": sequence,
                    "agent_id": agent_id,
                    "mission_id": mission_id,
                    "assignment_id": assignment_id,
                    "occurred_at": stamp,
                    "note": note,
                    "previous_heartbeat_sha256": self._last_hash(path),
                }
                record["heartbeat_sha256"] = _record_hash(record)
                encoded = _canonical_json(record) + "\n"
                with path.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(encoded)
                    fh.flush()
                    os.fsync(fh.fileno())
        return HeartbeatRecord(
            agent_id=agent_id,
            sequence=sequence,
            occurred_at=stamp,
            mission_id=mission_id,
            assignment_id=assignment_id,
            note=note,
            previous_heartbeat_sha256=record["previous_heartbeat_sha256"],
            heartbeat_sha256=record["heartbeat_sha256"],
        )

    def agent_health(
        self,
        agent_id: str,
        *,
        timeout: object = 300,
        now: str | datetime | None = None,
    ) -> AgentHealth:
        """Derive the liveness status for one agent at the query time."""
        if not agent_id:
            raise AHPError("INVALID_AGENT", "agent_id must be a non-empty string")
        parsed_timeout = _parse_timeout(timeout)
        query_time = _resolve_query_time(now)
        records = self._records(agent_id)
        if not records:
            return AgentHealth(
                agent_id=agent_id,
                status=_STATUS_UNKNOWN,
                heartbeat_count=0,
                age_seconds=None,
                last_heartbeat_at=None,
                last_mission_id=None,
                last_assignment_id=None,
            )
        last = records[-1]
        try:
            occurred_at = _parse_utc(str(last.get("occurred_at", "")))
        except (ValueError, TypeError) as exc:
            raise AHPError(
                "JOURNAL_CORRUPT", f"unparseable occurred_at for {agent_id}"
            ) from exc
        age = max(0.0, (query_time - occurred_at).total_seconds())
        status = _STATUS_ALIVE if age <= parsed_timeout else _STATUS_STALLED
        return AgentHealth(
            agent_id=agent_id,
            status=status,
            heartbeat_count=len(records),
            age_seconds=age,
            last_heartbeat_at=last.get("occurred_at"),
            last_mission_id=last.get("mission_id"),
            last_assignment_id=last.get("assignment_id"),
        )

    def mission_agents(self, mission_id: str) -> tuple[str, ...]:
        """Read the assigned agent ids for a mission from PESE (read-only)."""
        if not mission_id:
            return ()
        loaded = PESEStore(self.root).load(actor="AGENT:orchestrator:local")
        if loaded.code != "STATE_LOADED":
            return ()
        mission = (
            loaded.data["envelope"]["state"]
            .get("mission_state", {})
            .get("missions", {})
            .get(mission_id)
        )
        if not isinstance(mission, dict):
            return ()
        return tuple(mission.get("assigned_agent_ids", ()))

    def mission_health(
        self,
        mission_id: str,
        *,
        timeout: object = 300,
        now: str | datetime | None = None,
    ) -> tuple[AgentHealth, ...]:
        """Report health for every agent assigned to the mission."""
        agents = self.mission_agents(mission_id)
        return tuple(
            sorted(
                (self.agent_health(a, timeout=timeout, now=now) for a in agents),
                key=lambda h: h.agent_id,
            )
        )

    def check_stalled(
        self,
        mission_id: str,
        *,
        timeout: object = 300,
        now: str | datetime | None = None,
    ) -> tuple[str, ...]:
        """Return the sorted agent ids whose status is STALLED for the mission."""
        return tuple(
            h.agent_id
            for h in self.mission_health(mission_id, timeout=timeout, now=now)
            if h.status == _STATUS_STALLED
        )

    def validate(self) -> bool:
        """Verify every journal's chain, hashes, and sequence (read-only)."""
        if not self.agents_dir.is_dir():
            return True
        for path in sorted(self.agents_dir.glob("*.jsonl")):
            previous: str | None = None
            expected_sequence = 1
            with path.open("r", encoding="utf-8", newline="") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        return False
                    if not isinstance(record, dict):
                        return False
                    if record.get("previous_heartbeat_sha256") != previous:
                        return False
                    if record.get("heartbeat_sha256") != _record_hash(record):
                        return False
                    if record.get("sequence") != expected_sequence:
                        return False
                    previous = record.get("heartbeat_sha256")
                    expected_sequence += 1
        return True
