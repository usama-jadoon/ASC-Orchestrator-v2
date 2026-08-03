"""Local append-only, hash-chained ACP audit journaling."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .acp import ACPMessage, serialize_message


class AuditError(RuntimeError):
    """Raised when the local audit journal cannot be read or verified."""


_JOURNAL_LOCKS: dict[Path, threading.Lock] = {}
_JOURNAL_LOCKS_GUARD = threading.Lock()


@contextmanager
def _process_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive lock which is shared by every local process.

    The companion ``.lock`` file keeps the audit JSONL append-only while
    allowing the audit log itself to remain simple, human-readable evidence.
    """

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            import fcntl
        except ImportError:
            import msvcrt

            for attempt in range(100):
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if attempt == 99:
                        raise AuditError("timed out acquiring the audit journal lock")
                    time.sleep(0.01)

            def unlock() -> None:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)

        else:
            flock = getattr(fcntl, "flock")
            lock_ex = getattr(fcntl, "LOCK_EX")
            lock_un = getattr(fcntl, "LOCK_UN")
            flock(lock_file.fileno(), lock_ex)

            def unlock() -> None:
                flock(lock_file.fileno(), lock_un)

        try:
            yield
        finally:
            lock_file.seek(0)
            unlock()


class AuditJournal:
    """An append-only JSON-lines audit journal rooted at ``.project-os/AUDIT``."""

    def __init__(
        self,
        project_root: str | Path = ".",
        *,
        filename: str = "acp-audit.jsonl",
        audit_directory: str | Path | None = None,
    ) -> None:
        root = Path(project_root).resolve()
        if Path(filename).name != filename or filename in {"", ".", ".."}:
            raise AuditError("filename must be a non-empty basename")
        self.directory = (
            Path(audit_directory)
            if audit_directory is not None
            else root / ".project-os" / "AUDIT"
        ).resolve()
        self.path = (self.directory / filename).resolve()
        self.lock_path = self.directory / f".{filename}.lock"
        try:
            self.path.relative_to(self.directory)
        except ValueError as exc:
            raise AuditError("audit filename must stay within audit_directory") from exc
        with _JOURNAL_LOCKS_GUARD:
            self._lock = _JOURNAL_LOCKS.setdefault(self.path, threading.Lock())

    @staticmethod
    def _timestamp() -> str:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    @staticmethod
    def _canonical_json(record: dict[str, object]) -> str:
        return json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @classmethod
    def _entry_hash(cls, record: dict[str, object]) -> str:
        material = {key: value for key, value in record.items() if key != "entry_hash"}
        return hashlib.sha256(cls._canonical_json(material).encode("utf-8")).hexdigest()

    def _last_hash(self) -> str | None:
        if not self.path.exists():
            return None
        last_nonempty: str | None = None
        with self.path.open("r", encoding="utf-8", newline="") as audit_file:
            for line in audit_file:
                if line.strip():
                    last_nonempty = line
        if last_nonempty is None:
            return None
        try:
            record = json.loads(last_nonempty)
            value = record["entry_hash"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AuditError("existing audit log has an invalid final entry") from exc
        if not isinstance(value, str) or len(value) != 64:
            raise AuditError("existing audit log has an invalid final entry hash")
        return value

    def append(
        self,
        direction: str,
        message: ACPMessage | str | bytes,
        verification_status: str,
    ) -> dict[str, object]:
        """Append one full ACP transfer record and return its immutable data copy."""
        if direction not in {"IN", "OUT"}:
            raise AuditError("direction must be IN or OUT")
        if not isinstance(verification_status, str) or not verification_status:
            raise AuditError("verification_status must be non-empty text")
        if isinstance(message, ACPMessage):
            full_message = serialize_message(message)
        elif isinstance(message, bytes):
            try:
                full_message = message.decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise AuditError("audit message bytes must be valid UTF-8") from exc
        elif isinstance(message, str):
            try:
                message.encode("utf-8", "strict")
            except UnicodeEncodeError as exc:
                raise AuditError("audit message must be valid UTF-8") from exc
            full_message = message
        else:
            raise AuditError("message must be ACPMessage, str, or bytes")

        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with _process_lock(self.lock_path):
                if not self.verify_chain():
                    raise AuditError(
                        "refusing to append to an audit journal with a broken hash "
                        "chain"
                    )
                record: dict[str, object] = {
                    "timestamp": self._timestamp(),
                    "direction": direction,
                    "message": full_message,
                    "verification_status": verification_status,
                    "previous_hash": self._last_hash(),
                }
                record["entry_hash"] = self._entry_hash(record)
                encoded = self._canonical_json(record) + "\n"
                # Opening in append mode makes each complete line append-only at
                # the filesystem API level; the lock preserves local chain order.
                with self.path.open("a", encoding="utf-8", newline="\n") as audit_file:
                    audit_file.write(encoded)
                    audit_file.flush()
                    os.fsync(audit_file.fileno())
        return dict(record)

    def entries(self) -> Iterator[dict[str, object]]:
        """Yield parsed journal entries in their on-disk order."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8", newline="") as audit_file:
            for number, line in enumerate(audit_file, start=1):
                if not line.strip():
                    raise AuditError(f"blank audit entry at line {number}")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AuditError(f"invalid JSON at audit line {number}") from exc
                if not isinstance(record, dict):
                    raise AuditError(f"invalid audit entry at line {number}")
                yield record

    def verify_chain(self) -> bool:
        """Return true only if every audit entry is present and hash-linked."""
        previous_hash: str | None = None
        for record in self.entries():
            if record.get("previous_hash") != previous_hash:
                return False
            if record.get("entry_hash") != self._entry_hash(record):
                return False
            entry_hash = record.get("entry_hash")
            if not isinstance(entry_hash, str):
                return False
            previous_hash = entry_hash
        return True


def append_audit_record(
    project_root: str | Path,
    direction: str,
    message: ACPMessage | str | bytes,
    verification_status: str,
    *,
    audit_directory: str | Path | None = None,
) -> dict[str, object]:
    """Convenience wrapper for a single local ACP audit append."""
    return AuditJournal(project_root, audit_directory=audit_directory).append(
        direction, message, verification_status
    )
