"""Deterministic, stdlib-only cryptographic key service (CKS v1.0)."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CKS_FORMAT = "CKS/v1.0"
KEYS_DIR = "KEYS"
KEYS_EXTENSION_KEY = "org.asc.cks"

_STATUS_ACTIVE = "ACTIVE"
_STATUS_ROTATED = "ROTATED"
_STATUS_REVOKED = "REVOKED"
_TERMINAL = frozenset({_STATUS_ROTATED, _STATUS_REVOKED})

_KEY_ID_RE_PREFIX = "KEY-"


def _utc_now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _utc_compact() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"


def _canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry_hash(record: dict[str, Any], *, exclude: str = "entry_hash") -> str:
    material = {k: v for k, v in record.items() if k != exclude}
    return _sha256_hex(_canonical_json(material).encode("utf-8"))


def _file_hash(record: dict[str, Any]) -> str:
    return _entry_hash(record, exclude="file_sha256")


def _make_key_id() -> str:
    return f"KEY-{uuid.uuid4().hex}-{_utc_compact()}"


class CKSError(RuntimeError):
    """A structured CKS failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class KeyRecord:
    """Immutable key metadata."""

    key_id: str
    key_type: str
    purpose: str | None
    created_at: str
    created_by: str
    material_hex: str
    fingerprint_hex: str
    file_sha256: str


@dataclass(frozen=True)
class SignatureRecord:
    """Signing result."""

    key_id: str
    payload_sha256: str
    signature_hex: str
    signed_at: str
    actor: str
    purpose: str | None
    entry_hash: str


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.Lock] = {}


def _get_lock(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.Lock())


class KeyStore:
    """Deterministic CKS v1.0 key store operating under .project-os/KEYS/."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.keys_dir = self.root / ".project-os" / KEYS_DIR
        self._keys_path = self.keys_dir / "keys"
        self._status_path = self.keys_dir / "status"
        self._signatures_path = self.keys_dir / "signatures"
        self._lock = _get_lock(self.keys_dir)

    # --- internal helpers ---------------------------------------------------

    def _ensure_dirs(self) -> None:
        self._keys_path.mkdir(parents=True, exist_ok=True)
        self._status_path.mkdir(parents=True, exist_ok=True)
        self._signatures_path.mkdir(parents=True, exist_ok=True)

    def _key_file(self, key_id: str) -> Path:
        return self._keys_path / f"{key_id}.json"

    def _status_journal(self, key_id: str) -> Path:
        return self._status_path / f"{key_id}.jsonl"

    def _ledger(self, key_id: str) -> Path:
        return self._signatures_path / f"{key_id}.jsonl"

    def _ledger_lock(self, key_id: str) -> Path:
        return self._signatures_path / f".{key_id}.lock"

    def _last_hash(self, journal_path: Path) -> str | None:
        if not journal_path.exists():
            return None
        last_line: str | None = None
        with journal_path.open("r", encoding="utf-8", newline="") as f:
            for line in f:
                if line.strip():
                    last_line = line
        if last_line is None:
            return None
        try:
            record = json.loads(last_line)
            h = record.get("entry_hash")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CKSError("LEDGER_BROKEN", f"invalid journal entry: {exc}") from exc
        if not isinstance(h, str) or len(h) != 64:
            raise CKSError("LEDGER_BROKEN", "invalid entry_hash in journal")
        return h

    def _append_jsonl(
        self, journal_path: Path, record: dict[str, Any], *, exclude: str = "entry_hash"
    ) -> dict[str, Any]:
        record["previous_hash"] = self._last_hash(journal_path)
        record["entry_hash"] = _entry_hash(record, exclude=exclude)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = _canonical_json(record) + "\n"
        with journal_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        return dict(record)

    # --- public API ---------------------------------------------------------

    def create_key(self, writer: str, *, purpose: str | None = None) -> KeyRecord:
        """Generate a new HMAC-SHA256 key and persist it as an immutable record."""
        self._ensure_dirs()
        material_hex = secrets.token_hex(32)
        fingerprint_hex = _sha256_hex(material_hex.encode("utf-8"))
        key_id = _make_key_id()
        now = _utc_now()
        record: dict[str, Any] = {
            "format": CKS_FORMAT,
            "kind": "key",
            "key_id": key_id,
            "key_type": "HMAC-SHA256",
            "purpose": purpose,
            "created_at": now,
            "created_by": writer,
            "material_hex": material_hex,
            "fingerprint_hex": fingerprint_hex,
        }
        record["file_sha256"] = _file_hash(record)
        key_file = self._key_file(key_id)
        if key_file.exists():
            raise CKSError("KEY_EXISTS", f"key file already exists: {key_id}")
        self._atomic_write(key_file, record)
        # Write initial ACTIVE status entry.
        status_journal = self._status_journal(key_id)
        status_record: dict[str, Any] = {
            "format": CKS_FORMAT,
            "kind": "key-status",
            "key_id": key_id,
            "status": _STATUS_ACTIVE,
            "reason": "CREATION",
            "actor": writer,
            "at": now,
        }
        self._append_jsonl(status_journal, status_record)
        return KeyRecord(
            key_id=key_id,
            key_type="HMAC-SHA256",
            purpose=purpose,
            created_at=now,
            created_by=writer,
            material_hex=material_hex,
            fingerprint_hex=fingerprint_hex,
            file_sha256=record["file_sha256"],
        )

    def _atomic_write(self, path: Path, record: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(_canonical_json(record) + "\n", encoding="utf-8", newline="\n")
        tmp.replace(path)

    def load_key(self, key_id: str) -> KeyRecord:
        """Load a key record by ID."""
        path = self._key_file(key_id)
        if not path.exists():
            raise CKSError("KEY_NOT_FOUND", f"key not found: {key_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise CKSError("KEY_NOT_FOUND", f"corrupt key file: {exc}") from exc
        return KeyRecord(
            key_id=data["key_id"],
            key_type=data["key_type"],
            purpose=data.get("purpose"),
            created_at=data["created_at"],
            created_by=data["created_by"],
            material_hex=data["material_hex"],
            fingerprint_hex=data["fingerprint_hex"],
            file_sha256=data.get("file_sha256", ""),
        )

    def list_keys(self) -> list[KeyRecord]:
        """Return all key records sorted by created_at."""
        if not self._keys_path.exists():
            return []
        records: list[KeyRecord] = []
        for path in sorted(self._keys_path.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                records.append(
                    KeyRecord(
                        key_id=data["key_id"],
                        key_type=data["key_type"],
                        purpose=data.get("purpose"),
                        created_at=data["created_at"],
                        created_by=data["created_by"],
                        material_hex=data["material_hex"],
                        fingerprint_hex=data["fingerprint_hex"],
                        file_sha256=data.get("file_sha256", ""),
                    )
                )
            except (json.JSONDecodeError, OSError, KeyError):
                continue
        return sorted(records, key=lambda r: r.created_at)

    def status(self, key_id: str) -> str:
        """Resolve a key's current status from its status journal.

        Fails closed: raises ``LEDGER_BROKEN`` if the status journal is
        missing, empty, corrupt, or has a broken hash chain.  A key
        record whose status journal cannot be verified is not trusted.
        """
        self.load_key(key_id)  # raises KEY_NOT_FOUND if missing
        journal = self._status_journal(key_id)
        if not journal.exists():
            raise CKSError(
                "LEDGER_BROKEN",
                f"status journal missing for key {key_id}",
            )
        # Verify the entire hash chain before reading the last entry.
        # This catches corruption in any entry, not just the last line.
        if not self._verify_journal_chain(journal):
            raise CKSError(
                "LEDGER_BROKEN",
                f"status journal hash chain broken for key {key_id}",
            )
        last_line: str | None = None
        with journal.open("r", encoding="utf-8", newline="") as f:
            for line in f:
                if line.strip():
                    last_line = line
        if last_line is None:
            raise CKSError(
                "LEDGER_BROKEN",
                f"status journal empty for key {key_id}",
            )
        try:
            record = json.loads(last_line)
        except (json.JSONDecodeError, KeyError) as exc:
            raise CKSError(
                "LEDGER_BROKEN",
                f"status journal corrupt for key {key_id}: {exc}",
            ) from exc
        if "status" not in record:
            raise CKSError(
                "LEDGER_BROKEN",
                f"status entry missing status field for key {key_id}",
            )
        return str(record["status"])

    def _require_active(self, key_id: str) -> KeyRecord:
        key = self.load_key(key_id)
        st = self.status(key_id)
        if st != _STATUS_ACTIVE:
            raise CKSError("KEY_NOT_ACTIVE", f"key {key_id} status is {st}")
        if key.key_type != "HMAC-SHA256":
            raise CKSError(
                "KEY_TYPE_UNSUPPORTED", f"unsupported key type: {key.key_type}"
            )
        return key

    def sign(
        self,
        key_id: str,
        payload: bytes,
        actor: str,
        *,
        purpose: str | None = None,
    ) -> SignatureRecord:
        """Sign a payload with the specified key and record in the signing ledger."""
        with self._lock:
            self._ensure_dirs()
            key = self._require_active(key_id)
            payload_sha256 = _sha256_hex(payload)
            sig = _hmac.new(
                key.material_hex.encode("utf-8"), payload, "sha256"
            ).hexdigest()
            now = _utc_now()
            ledger = self._ledger(key_id)
            if not self.verify_chain(key_id):
                raise CKSError(
                    "LEDGER_BROKEN",
                    f"signing ledger chain broken for {key_id}",
                )
            record: dict[str, Any] = {
                "format": CKS_FORMAT,
                "kind": "signature",
                "key_id": key_id,
                "payload_sha256": payload_sha256,
                "signature_hex": sig,
                "signed_at": now,
                "actor": actor,
                "purpose": purpose,
            }
            saved = self._append_jsonl(ledger, record)
            return SignatureRecord(
                key_id=key_id,
                payload_sha256=payload_sha256,
                signature_hex=sig,
                signed_at=now,
                actor=actor,
                purpose=purpose,
                entry_hash=saved["entry_hash"],
            )

    def verify(
        self,
        key_id: str,
        payload: bytes,
        signature_hex: str,
    ) -> bool:
        """Verify a signature against the specified key. Read-only, no side effects.

        Fails closed: if the key's status cannot be established (broken status
        journal), verification returns False rather than trusting the key.
        """
        key = self.load_key(key_id)
        try:
            if self.status(key_id) != _STATUS_ACTIVE:
                return False
        except CKSError:
            return False
        if key.key_type != "HMAC-SHA256":
            return False
        computed = _hmac.new(
            key.material_hex.encode("utf-8"), payload, "sha256"
        ).hexdigest()
        return _hmac.compare_digest(computed, signature_hex)

    def rotate(
        self,
        writer: str,
        old_key_id: str,
        *,
        reason: str = "ROTATION",
        purpose: str | None = None,
    ) -> KeyRecord:
        """Rotate an active key: mark old as ROTATED, create new ACTIVE key."""
        with self._lock:
            self._require_active(old_key_id)
            now = _utc_now()
            # Append ROTATED status to the old key.
            old_journal = self._status_journal(old_key_id)
            status_record: dict[str, Any] = {
                "format": CKS_FORMAT,
                "kind": "key-status",
                "key_id": old_key_id,
                "status": _STATUS_ROTATED,
                "reason": reason,
                "actor": writer,
                "at": now,
            }
            self._append_jsonl(old_journal, status_record)
            # Create new key.
            return self.create_key(writer, purpose=purpose)

    def revoke(
        self,
        writer: str,
        key_id: str,
        *,
        reason: str = "REVOCATION",
    ) -> dict[str, Any]:
        """Revoke an active key."""
        with self._lock:
            self._require_active(key_id)
            now = _utc_now()
            journal = self._status_journal(key_id)
            status_record: dict[str, Any] = {
                "format": CKS_FORMAT,
                "kind": "key-status",
                "key_id": key_id,
                "status": _STATUS_REVOKED,
                "reason": reason,
                "actor": writer,
                "at": now,
            }
            return self._append_jsonl(journal, status_record)

    def _verify_journal_chain(self, path: Path) -> bool:
        """Verify the hash chain of a JSONL journal file.

        Returns ``True`` only if every entry is hash-linked and entries are
        not malformed.  Empty or blank-only files return ``True`` (no
        entries to violate the chain).
        """
        if not path.exists():
            return False
        previous_hash: str | None = None
        with path.open("r", encoding="utf-8", newline="") as f:
            for line in f:
                if not line.strip():
                    return False
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    return False
                if record.get("previous_hash") != previous_hash:
                    return False
                computed = _entry_hash(record)
                if record.get("entry_hash") != computed:
                    return False
                previous_hash = record.get("entry_hash")
        return True

    def verify_chain(self, key_id: str) -> bool:
        """Return True only if both signing ledger and status journal chains
        are hash-linked and well-formed."""
        # Signing ledger may not exist yet (key never signed) → OK.
        ledger = self._ledger(key_id)
        if ledger.exists():
            if not self._verify_journal_chain(ledger):
                return False
        # Status journal must exist for every known key (written at creation).
        status_journal = self._status_journal(key_id)
        if not self._verify_journal_chain(status_journal):
            return False
        return True

    def validate(self) -> bool:
        """Full integrity check: all key records, fingerprints, and ledgers."""
        if not self._keys_path.exists():
            return True
        for path in self._keys_path.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return False
            key_id = data.get("key_id", "")
            # Verify file hash.
            stored_hash = data.pop("file_sha256", None)
            computed_hash = _file_hash(data)
            data["file_sha256"] = stored_hash
            if stored_hash != computed_hash:
                return False
            # Verify fingerprint.
            material = data.get("material_hex", "")
            expected_fp = _sha256_hex(material.encode("utf-8"))
            if data.get("fingerprint_hex") != expected_fp:
                return False
            # Verify signing ledger chain.
            if not self.verify_chain(key_id):
                return False
        return True
