"""Encrypted Transport (ETR) v1.0.

A deterministic, stdlib-only symmetric authenticated-encryption layer that
seals ACP payloads and artifact files into ChaCha20-Poly1305 envelopes and
opens them back.  ETR consumes CKS keys read-only, persists channels and
envelopes under PESE ``transport_state`` with transition type
``TRANSPORT_STATUS``, and emits ETR_* events to the EEF execution journal.

Confidentiality is provided by the RFC 8439 ChaCha20-Poly1305 AEAD
construction, deterministically keyed by 32-byte CKS symmetric keys.  The
envelope's metadata (the AEAD associated data) is bound to the ciphertext,
so tampering with any envelope header field fails the authentication tag at
open time.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import struct
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .audit import AuditError
from .execution import EEFEventJournal
from .keys import CKSError, KeyStore
from .pese import PESEOutcome, PESEStore, canonical_json, utc_compact, utc_now

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ETR_FORMAT = "ETR/v1.0"
ETR_CIPHER = "CHACHA20-POLY1305"

DEFAULT_ACTOR = "AGENT:orchestrator:local"

ETR_CHANNEL_STATUSES = frozenset({"ACTIVE", "REVOKED"})

_ETR_CHANNEL_TRANSITIONS: dict[str, set[str]] = {
    "ACTIVE": {"REVOKED"},
}

_ETR_CHANNEL_STATUS_EVENTS: dict[str, str] = {
    "ACTIVE": "ETR_CHANNEL_BOUND",
    "REVOKED": "ETR_CHANNEL_REVOKED",
}

ETR_ENVELOPE_STATUSES = frozenset({"SEALED", "OPENED", "AUTH_FAILED"})

_ETR_ENVELOPE_TRANSITIONS: dict[str, set[str]] = {
    "SEALED": {"OPENED", "AUTH_FAILED"},
}

_ETR_ENVELOPE_STATUS_EVENTS: dict[str, str] = {
    "SEALED": "ETR_SEALED",
    "OPENED": "ETR_UNSEALED",
    "AUTH_FAILED": "ETR_AUTH_FAILED",
}

# RFC 8439 ChaCha20 constants ("expand 32-byte k" little-endian words).
_CHACHA20_CONSTANTS: tuple[int, ...] = (
    0x61707865,
    0x3320646E,
    0x79622D32,
    0x6B206574,
)

# Poly1305 r-clamping mask (RFC 8439 §2.5).
_POLY1305_MASK = 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF

# Poly1305 prime 2^130 - 5.
_POLY1305_PRIME = (1 << 130) - 5

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


def _get_lock(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.RLock())


class EtrError(RuntimeError):
    """A structured ETR precondition or contract failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


# ---------------------------------------------------------------------------
# RFC 8439 primitives (pure Python, stdlib only)
# ---------------------------------------------------------------------------


def _rotl32(value: int, bits: int) -> int:
    """Rotate a 32-bit word left by ``bits`` positions."""
    return ((value << bits) | (value >> (32 - bits))) & 0xFFFFFFFF


def _quarter_round(state: list[int], a: int, b: int, c: int, d: int) -> None:
    """Apply one ChaCha20 quarter round to a 16-word state."""
    state[a] = (state[a] + state[b]) & 0xFFFFFFFF
    state[d] = _rotl32(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _rotl32(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b]) & 0xFFFFFFFF
    state[d] = _rotl32(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & 0xFFFFFFFF
    state[b] = _rotl32(state[b] ^ state[c], 7)


def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    """Generate one 64-byte ChaCha20 keystream block (RFC 8439 §2.3)."""
    if len(key) != 32:
        raise EtrError("BAD_KEY", f"ChaCha20 key must be 32 bytes, got {len(key)}")
    if len(nonce) != 12:
        raise EtrError(
            "BAD_NONCE", f"ChaCha20 nonce must be 12 bytes, got {len(nonce)}"
        )
    if not 0 <= counter <= 0xFFFFFFFF:
        raise EtrError("BAD_COUNTER", f"ChaCha20 counter out of range: {counter}")
    state: list[int] = list(_CHACHA20_CONSTANTS)
    state += [int.from_bytes(key[i : i + 4], "little") for i in range(0, 32, 4)]
    state += [counter]
    state += [int.from_bytes(nonce[i : i + 4], "little") for i in range(0, 12, 4)]
    working = list(state)
    for _ in range(10):  # 10 double rounds == 20 rounds.
        _quarter_round(working, 0, 4, 8, 12)
        _quarter_round(working, 1, 5, 9, 13)
        _quarter_round(working, 2, 6, 10, 14)
        _quarter_round(working, 3, 7, 11, 15)
        _quarter_round(working, 0, 5, 10, 15)
        _quarter_round(working, 1, 6, 11, 12)
        _quarter_round(working, 2, 7, 8, 13)
        _quarter_round(working, 3, 4, 9, 14)
    for i in range(16):
        working[i] = (working[i] + state[i]) & 0xFFFFFFFF
    return b"".join(struct.pack("<I", word) for word in working)


def _chacha20_xor(key: bytes, counter: int, nonce: bytes, data: bytes) -> bytes:
    """XOR ``data`` with ChaCha20 keystream starting at ``counter`` (§2.4)."""
    out = bytearray()
    block_counter = counter
    for offset in range(0, len(data), 64):
        block = _chacha20_block(key, block_counter, nonce)
        chunk = data[offset : offset + 64]
        out.extend(a ^ b for a, b in zip(chunk, block))
        block_counter += 1
    return bytes(out)


def _poly1305(key: bytes, message: bytes) -> bytes:
    """Compute a 16-byte Poly1305 tag (RFC 8439 §2.5)."""
    if len(key) != 32:
        raise EtrError("BAD_KEY", f"Poly1305 key must be 32 bytes, got {len(key)}")
    r = int.from_bytes(key[0:16], "little") & _POLY1305_MASK
    s = int.from_bytes(key[16:32], "little")
    acc = 0
    for i in range(0, len(message), 16):
        chunk = message[i : i + 16]
        acc = ((acc + int.from_bytes(chunk + b"\x01", "little")) * r) % _POLY1305_PRIME
    acc = (acc + s) & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    return acc.to_bytes(16, "little")


def _pad16(data: bytes) -> bytes:
    """Pad ``data`` to a multiple of 16 bytes (RFC 8439 §2.8)."""
    remainder = len(data) % 16
    if remainder == 0:
        return data
    return data + (b"\x00" * (16 - remainder))


def _aead_compute_tag(key: bytes, nonce: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    """Compute the RFC 8439 §2.8 Poly1305 authentication tag."""
    # poly1305_key_gen (RFC 8439 §2.6.1): the one-time key is the first
    # 32 bytes of the counter-0 block (equivalent to encrypting 32 zero
    # bytes and keeping the result).
    subkey = _chacha20_block(key, 0, nonce)[0:32]
    mac_data = (
        _pad16(aad)
        + _pad16(ciphertext)
        + struct.pack("<Q", len(aad))
        + struct.pack("<Q", len(ciphertext))
    )
    return _poly1305(subkey, mac_data)


def _aead_seal(
    key: bytes, nonce: bytes, aad: bytes, plaintext: bytes
) -> tuple[bytes, bytes]:
    """Seal ``plaintext`` with ChaCha20-Poly1305; return ``(ciphertext, tag)``."""
    ciphertext = _chacha20_xor(key, 1, nonce, plaintext)
    tag = _aead_compute_tag(key, nonce, aad, ciphertext)
    return ciphertext, tag


def _aead_open(
    key: bytes, nonce: bytes, aad: bytes, ciphertext: bytes, tag: bytes
) -> bytes | None:
    """Authenticate and decrypt.  Returns ``None`` on authentication failure."""
    expected = _aead_compute_tag(key, nonce, aad, ciphertext)
    if not hmac.compare_digest(expected, tag):
        return None
    return _chacha20_xor(key, 1, nonce, ciphertext)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransportChannel:
    """Read-only snapshot of a persisted transport channel."""

    channel_id: str
    format: str
    from_id: str | None
    to_id: str | None
    key_id: str
    status: str
    created_at: str
    updated_at: str | None
    revoked_at: str | None


@dataclass(frozen=True, slots=True)
class SealedEnvelope:
    """Read-only snapshot of a persisted sealed envelope."""

    envelope_id: str
    format: str
    cipher: str
    key_id: str
    nonce: str
    aad: str
    ciphertext: str
    tag: str
    plaintext_sha256: str
    message_type: str | None
    from_id: str | None
    to_id: str | None
    mission_id: str | None
    correlation_id: str | None
    status: str
    created_at: str
    opened_at: str | None


@dataclass(frozen=True, slots=True)
class UnsealedPayload:
    """Result of successfully authenticating and opening an envelope."""

    payload: bytes
    envelope_id: str
    key_id: str
    plaintext_sha256: str


@dataclass(frozen=True, slots=True)
class TransportReport:
    """Aggregated ETR summary."""

    channels_total: int
    channels_active: int
    channels_revoked: int
    envelopes_total: int
    envelopes_sealed: int
    envelopes_opened: int
    envelopes_auth_failed: int


# ---------------------------------------------------------------------------
# ETR runtime
# ---------------------------------------------------------------------------


class EncryptedTransport:
    """Deterministic symmetric encrypted-transport runtime over PESE/EEF/CKS."""

    def __init__(
        self,
        root: str | Path,
        *,
        audit_directory: str | Path | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._store = PESEStore(self.root)
        self._journal = EEFEventJournal(self.root, audit_directory=audit_directory)
        self._keys = KeyStore(self.root)
        self._lock = _get_lock(self.root / ".project-os" / "PESE")

    # --- internal helpers ---------------------------------------------------

    def _load_state(self, actor: str) -> tuple[dict[str, Any], int, str] | EtrError:
        """Load PESE state and return ``(state_dict, revision, sha256)``."""
        loaded = self._store.load(actor=actor)
        if loaded.code != "STATE_LOADED":
            return EtrError("STATE_LOAD_FAILED", f"PESE load failed: {loaded.code}")
        if loaded.state_revision is None or loaded.state_sha256 is None:
            return EtrError(
                "STATE_LOAD_FAILED", "PESE state missing revision or sha256"
            )
        state = loaded.data["envelope"]["state"]
        return state, loaded.state_revision, loaded.state_sha256

    def _transport(self, state: dict[str, Any]) -> dict[str, Any]:
        return state.setdefault("transport_state", {})

    def _channels(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._transport(state).setdefault("channels", {})

    def _envelopes(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._transport(state).setdefault("envelopes", {})

    def _find_channel(self, state: dict[str, Any], channel_id: str) -> dict[str, Any]:
        """Find the channel record or raise ``EtrError``."""
        channels = self._channels(state)
        rec = channels.get(channel_id)
        if rec is None or not isinstance(rec, Mapping):
            raise EtrError("CHANNEL_NOT_FOUND", f"channel {channel_id!r} not found")
        return dict(rec)

    def _find_envelope(self, state: dict[str, Any], envelope_id: str) -> dict[str, Any]:
        """Find the envelope record or raise ``EtrError``."""
        envelopes = self._envelopes(state)
        rec = envelopes.get(envelope_id)
        if rec is None or not isinstance(rec, Mapping):
            raise EtrError("ENVELOPE_NOT_FOUND", f"envelope {envelope_id!r} not found")
        return dict(rec)

    def _to_channel(self, rec: Mapping[str, Any]) -> TransportChannel:
        return TransportChannel(
            channel_id=rec.get("channel_id", ""),
            format=rec.get("format", ETR_FORMAT),
            from_id=rec.get("from"),
            to_id=rec.get("to"),
            key_id=rec.get("key_id", ""),
            status=rec.get("status", ""),
            created_at=rec.get("created_at", ""),
            updated_at=rec.get("updated_at"),
            revoked_at=rec.get("revoked_at"),
        )

    def _to_envelope(self, rec: Mapping[str, Any]) -> SealedEnvelope:
        return SealedEnvelope(
            envelope_id=rec.get("envelope_id", ""),
            format=rec.get("format", ETR_FORMAT),
            cipher=rec.get("cipher", ETR_CIPHER),
            key_id=rec.get("key_id", ""),
            nonce=rec.get("nonce", ""),
            aad=rec.get("aad", ""),
            ciphertext=rec.get("ciphertext", ""),
            tag=rec.get("tag", ""),
            plaintext_sha256=rec.get("plaintext_sha256", ""),
            message_type=rec.get("message_type"),
            from_id=rec.get("from"),
            to_id=rec.get("to"),
            mission_id=rec.get("mission_id"),
            correlation_id=rec.get("correlation_id"),
            status=rec.get("status", ""),
            created_at=rec.get("created_at", ""),
            opened_at=rec.get("opened_at"),
        )

    def _header_for_aad(self, rec: Mapping[str, Any]) -> dict[str, Any]:
        """Canonical envelope header bound as the AEAD associated data."""
        return {
            "format": rec.get("format", ETR_FORMAT),
            "key_id": rec.get("key_id", ""),
            "nonce": rec.get("nonce", ""),
            "message_type": rec.get("message_type"),
            "from": rec.get("from"),
            "to": rec.get("to"),
            "mission_id": rec.get("mission_id"),
            "correlation_id": rec.get("correlation_id"),
            "plaintext_sha256": rec.get("plaintext_sha256", ""),
        }

    def _resolve_key(self, key_id: str) -> bytes:
        """Resolve a CKS key id to its raw 32 key bytes (read-only)."""
        try:
            record = self._keys.load_key(key_id)
            status = self._keys.status(key_id)
        except CKSError as exc:
            raise EtrError(exc.code, exc.detail) from exc
        if status != "ACTIVE":
            raise EtrError("KEY_NOT_ACTIVE", f"key {key_id} status is {status}")
        try:
            material = bytes.fromhex(record.material_hex)
        except (ValueError, TypeError):
            raise EtrError(
                "KEY_MATERIAL_INVALID", f"key {key_id} material is not valid hex"
            ) from None
        if len(material) != 32:
            raise EtrError(
                "KEY_MATERIAL_INVALID",
                f"key {key_id} material is {len(material)} bytes, expected 32",
            )
        return material

    def _transition(
        self,
        actor: str,
        record_id: str,
        from_status: str | None,
        to_status: str,
        mutate_fn: Any,
    ) -> PESEOutcome:
        """Transition a transport record through PESE (TRANSPORT_STATUS)."""
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
            transition_type="TRANSPORT_STATUS",
            subject=record_id,
            from_value=from_status,
            to_value=to_status,
            mutate=mutate_fn,
        )

    def _emit_event(
        self,
        event_type: str,
        mission_id: str | None,
        record_id: str,
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
                assignment_id=record_id,
                actor_agent_id=actor,
                pese_revision=pese_revision,
                pese_state_sha256=pese_state_sha256,
                detail=detail,
            )
        except (AuditError, Exception):
            return None

    # --- channels -----------------------------------------------------------

    def bind_channel(
        self, from_id: str, to_id: str, key_id: str, actor: str
    ) -> TransportChannel:
        """Bind an ACTIVE channel to a CKS key (the ACP §19 session key)."""
        if not from_id or not to_id:
            raise EtrError("BAD_CHANNEL", "from_id and to_id are required")
        if actor != from_id and not actor.startswith("AGENT:orchestrator:"):
            raise EtrError(
                "UNAUTHORIZED",
                f"actor {actor!r} is not authorized to bind channel for sender {from_id!r}",
            )
        with self._lock:
            self._resolve_key(key_id)  # validate the key exists and is ACTIVE
            channel_id = f"CHANNEL:{uuid.uuid4().hex}"
            now = utc_now()
            record: dict[str, Any] = {
                "channel_id": channel_id,
                "format": ETR_FORMAT,
                "from": from_id,
                "to": to_id,
                "key_id": key_id,
                "status": "ACTIVE",
                "created_at": now,
                "updated_at": now,
                "revoked_at": None,
            }

            def mutate_channel(state: dict[str, Any]) -> None:
                self._channels(state)[channel_id] = dict(record)

            outcome = self._transition(
                actor, channel_id, None, "ACTIVE", mutate_channel
            )
            if outcome.code != "UPDATED":
                raise EtrError("PERSIST_FAILED", f"PESE update failed: {outcome.code}")
            self._emit_event(
                "ETR_CHANNEL_BOUND",
                None,
                channel_id,
                actor,
                outcome.state_revision,
                outcome.state_sha256,
                {"key_id": key_id, "from": from_id, "to": to_id},
            )
            return self._to_channel(record)

    def revoke_channel(self, channel_id: str, actor: str) -> TransportChannel:
        """Revoke an ACTIVE channel (ACTIVE → REVOKED, no reverse)."""
        with self._lock:
            result = self._load_state(actor)
            if isinstance(result, EtrError):
                raise result
            state, _, _ = result
            record = self._find_channel(state, channel_id)
            endpoints = {record.get("from"), record.get("to")}
            if not actor.startswith("AGENT:orchestrator:") and actor not in endpoints:
                raise EtrError(
                    "UNAUTHORIZED",
                    f"actor {actor!r} is not authorized to revoke channel {channel_id!r}",
                )
            if record["status"] != "ACTIVE":
                raise EtrError(
                    "CHANNEL_NOT_ACTIVE",
                    f"channel {channel_id} status is {record['status']}",
                )
            now = utc_now()
            record["status"] = "REVOKED"
            record["updated_at"] = now
            record["revoked_at"] = now

            def mutate_revoke(state: dict[str, Any]) -> None:
                self._channels(state)[channel_id] = dict(record)

            outcome = self._transition(
                actor, channel_id, "ACTIVE", "REVOKED", mutate_revoke
            )
            if outcome.code != "UPDATED":
                raise EtrError("PERSIST_FAILED", f"PESE update failed: {outcome.code}")
            self._emit_event(
                "ETR_CHANNEL_REVOKED",
                None,
                channel_id,
                actor,
                outcome.state_revision,
                outcome.state_sha256,
                {"key_id": record.get("key_id")},
            )
            return self._to_channel(record)

    def channel(self, channel_id: str, actor: str) -> TransportChannel:
        """Read a single channel record."""
        result = self._load_state(actor)
        if isinstance(result, EtrError):
            raise result
        state, _, _ = result
        return self._to_channel(self._find_channel(state, channel_id))

    def list_channels(
        self,
        *,
        from_id: str | None = None,
        to_id: str | None = None,
        status: str | None = None,
        actor: str = DEFAULT_ACTOR,
    ) -> tuple[TransportChannel, ...]:
        """List channels, optionally filtered, sorted by channel_id."""
        result = self._load_state(actor)
        if isinstance(result, EtrError):
            raise result
        state, _, _ = result
        channels = self._channels(state)
        matched = []
        for channel_id in sorted(channels):
            rec = channels[channel_id]
            if from_id is not None and rec.get("from") != from_id:
                continue
            if to_id is not None and rec.get("to") != to_id:
                continue
            if status is not None and rec.get("status") != status:
                continue
            matched.append(self._to_channel(rec))
        return tuple(matched)

    # --- envelopes ----------------------------------------------------------

    def seal(
        self,
        payload: bytes,
        *,
        key_id: str | None = None,
        channel_id: str | None = None,
        message_type: str | None = None,
        from_id: str | None = None,
        to_id: str | None = None,
        mission_id: str | None = None,
        correlation_id: str | None = None,
        actor: str = DEFAULT_ACTOR,
    ) -> SealedEnvelope:
        """Seal a payload into a ChaCha20-Poly1305 envelope.

        Exactly one of ``key_id`` or ``channel_id`` must be supplied.  The
        payload must be non-empty.  The nonce is the single non-deterministic
        input, matching the accepted CKS key-generation pattern.
        """
        if not payload:
            raise EtrError("EMPTY_PAYLOAD", "payload must be non-empty")
        if (key_id is None) == (channel_id is None):
            raise EtrError(
                "KEY_REQUIRED", "exactly one of key_id or channel_id is required"
            )
        with self._lock:
            if channel_id is not None:
                result = self._load_state(actor)
                if isinstance(result, EtrError):
                    raise result
                state, _, _ = result
                channel = self._find_channel(state, channel_id)
                if channel["status"] != "ACTIVE":
                    raise EtrError(
                        "CHANNEL_NOT_ACTIVE",
                        f"channel {channel_id} status is {channel['status']}",
                    )
                key_id = channel["key_id"]
                if from_id is None:
                    from_id = channel.get("from")
                if to_id is None:
                    to_id = channel.get("to")
            assert (
                key_id is not None
            )  # guaranteed by the key/channel mutual-exclusion above
            key = self._resolve_key(key_id)
            nonce = secrets.token_bytes(12)
            envelope_id = f"ENVELOPE:{uuid.uuid4().hex}"
            plaintext_sha256 = hashlib.sha256(payload).hexdigest()
            now = utc_now()
            record: dict[str, Any] = {
                "envelope_id": envelope_id,
                "format": ETR_FORMAT,
                "cipher": ETR_CIPHER,
                "key_id": key_id,
                "nonce": nonce.hex(),
                "aad": "",
                "ciphertext": "",
                "tag": "",
                "plaintext_sha256": plaintext_sha256,
                "message_type": message_type,
                "from": from_id,
                "to": to_id,
                "mission_id": mission_id,
                "correlation_id": correlation_id,
                "status": "SEALED",
                "created_at": now,
                "opened_at": None,
            }
            aad = canonical_json(self._header_for_aad(record))
            ciphertext, tag = _aead_seal(key, nonce, aad, payload)
            record["aad"] = aad.hex()
            record["ciphertext"] = ciphertext.hex()
            record["tag"] = tag.hex()

            def mutate_seal(state: dict[str, Any]) -> None:
                self._envelopes(state)[envelope_id] = dict(record)

            outcome = self._transition(actor, envelope_id, None, "SEALED", mutate_seal)
            if outcome.code != "UPDATED":
                raise EtrError("PERSIST_FAILED", f"PESE update failed: {outcome.code}")
            self._emit_event(
                "ETR_SEALED",
                mission_id,
                envelope_id,
                actor,
                outcome.state_revision,
                outcome.state_sha256,
                {
                    "key_id": key_id,
                    "message_type": message_type,
                    "plaintext_sha256": plaintext_sha256,
                },
            )
            return self._to_envelope(record)

    def open(
        self,
        envelope: str | Mapping[str, Any],
        *,
        actor: str = DEFAULT_ACTOR,
    ) -> UnsealedPayload:
        """Authenticate and open an envelope.

        ``envelope`` may be an envelope id (looked up in PESE state) or a
        mapping record (e.g. loaded from an envelope JSON file).  On success
        the record transitions SEALED → OPENED; on authentication failure it
        transitions SEALED → AUTH_FAILED and ``EtrError`` is raised.
        """
        with self._lock:
            if isinstance(envelope, str):
                result = self._load_state(actor)
                if isinstance(result, EtrError):
                    raise result
                state, _, _ = result
                record = self._find_envelope(state, envelope)
            elif isinstance(envelope, Mapping):
                record = dict(envelope)
            else:
                raise EtrError(
                    "BAD_ENVELOPE", "envelope must be an envelope id or record mapping"
                )
            if record.get("format") != ETR_FORMAT:
                raise EtrError(
                    "BAD_ENVELOPE",
                    f"unsupported envelope format: {record.get('format')!r}",
                )
            if record.get("status") != "SEALED":
                raise EtrError(
                    "ENVELOPE_NOT_OPENABLE",
                    f"envelope status is {record.get('status')!r}",
                )
            recipient = record.get("to")
            if (
                recipient
                and actor != recipient
                and not actor.startswith("AGENT:orchestrator:")
            ):
                raise EtrError(
                    "UNAUTHORIZED",
                    f"actor {actor!r} is not authorized to open envelope addressed to {recipient!r}",
                )
            key_id = record.get("key_id")
            if not key_id:
                raise EtrError("BAD_ENVELOPE", "envelope is missing key_id")
            key = self._resolve_key(key_id)
            try:
                nonce = bytes.fromhex(record["nonce"])
                ciphertext = bytes.fromhex(record["ciphertext"])
                tag = bytes.fromhex(record["tag"])
            except (KeyError, ValueError) as exc:
                raise EtrError(
                    "BAD_ENVELOPE", f"envelope has invalid cipher fields: {exc}"
                ) from exc
            # Recompute the AAD from the current header so tampering with any
            # metadata field invalidates the tag.
            computed_aad = canonical_json(self._header_for_aad(record))
            plaintext = _aead_open(key, nonce, computed_aad, ciphertext, tag)
            envelope_id = record.get("envelope_id", "")
            if plaintext is None:
                self._persist_envelope_status(
                    actor, envelope_id, "SEALED", "AUTH_FAILED"
                )
                self._emit_event(
                    "ETR_AUTH_FAILED",
                    record.get("mission_id"),
                    envelope_id or "ENVELOPE:unknown",
                    actor,
                    None,
                    None,
                    {"key_id": key_id},
                )
                raise EtrError(
                    "AUTH_FAILED", "envelope authentication tag verification failed"
                )
            self._persist_envelope_status(actor, envelope_id, "SEALED", "OPENED")
            self._emit_event(
                "ETR_UNSEALED",
                record.get("mission_id"),
                envelope_id or "ENVELOPE:unknown",
                actor,
                None,
                None,
                {"key_id": key_id},
            )
            return UnsealedPayload(
                payload=plaintext,
                envelope_id=envelope_id,
                key_id=key_id,
                plaintext_sha256=record.get("plaintext_sha256", ""),
            )

    def _persist_envelope_status(
        self, actor: str, envelope_id: str, from_status: str, to_status: str
    ) -> PESEOutcome | None:
        """Transition an envelope's status in state when the record exists."""
        if not envelope_id:
            return None
        result = self._load_state(actor)
        if isinstance(result, EtrError):
            return None
        state, _, _ = result
        existing = self._envelopes(state).get(envelope_id)
        if (
            existing is None
            or not isinstance(existing, Mapping)
            or existing.get("status") != from_status
        ):
            return None
        now = utc_now()

        def mutate(state_new: dict[str, Any]) -> None:
            rec = self._envelopes(state_new)[envelope_id]
            rec["status"] = to_status
            if to_status == "OPENED":
                rec["opened_at"] = now

        return self._transition(actor, envelope_id, from_status, to_status, mutate)

    def list_envelopes(
        self,
        *,
        key_id: str | None = None,
        message_type: str | None = None,
        status: str | None = None,
        actor: str = DEFAULT_ACTOR,
    ) -> tuple[SealedEnvelope, ...]:
        """List envelopes, optionally filtered, sorted by envelope_id."""
        result = self._load_state(actor)
        if isinstance(result, EtrError):
            raise result
        state, _, _ = result
        envelopes = self._envelopes(state)
        matched = []
        for envelope_id in sorted(envelopes):
            rec = envelopes[envelope_id]
            if key_id is not None and rec.get("key_id") != key_id:
                continue
            if message_type is not None and rec.get("message_type") != message_type:
                continue
            if status is not None and rec.get("status") != status:
                continue
            matched.append(self._to_envelope(rec))
        return tuple(matched)

    # --- file transport -----------------------------------------------------

    def seal_file(
        self,
        source: str | Path,
        *,
        key_id: str | None = None,
        channel_id: str | None = None,
        message_type: str | None = None,
        from_id: str | None = None,
        to_id: str | None = None,
        mission_id: str | None = None,
        correlation_id: str | None = None,
        output: str | Path | None = None,
        actor: str = DEFAULT_ACTOR,
    ) -> SealedEnvelope:
        """Seal a file's bytes; persist the envelope JSON to ``output``."""
        source_path = Path(source)
        payload = source_path.read_bytes()
        envelope = self.seal(
            payload,
            key_id=key_id,
            channel_id=channel_id,
            message_type=message_type,
            from_id=from_id,
            to_id=to_id,
            mission_id=mission_id,
            correlation_id=correlation_id,
            actor=actor,
        )
        output_path = Path(output) if output else Path(str(source) + ".etr")
        self._write_envelope(output_path, envelope)
        return envelope

    def open_file(
        self,
        envelope_path: str | Path,
        *,
        output: str | Path | None = None,
        actor: str = DEFAULT_ACTOR,
    ) -> bytes:
        """Authenticate and open an envelope file; write plaintext to ``output``."""
        envelope_path = Path(envelope_path)
        record = json.loads(envelope_path.read_text(encoding="utf-8"))
        unsealed = self.open(record, actor=actor)
        output_path = Path(output) if output else envelope_path.with_suffix("")
        output_path.write_bytes(unsealed.payload)
        return unsealed.payload

    def _write_envelope(self, output: Path, envelope: SealedEnvelope) -> None:
        """Write an envelope as JSON to ``output``."""
        record: dict[str, Any] = {
            "envelope_id": envelope.envelope_id,
            "format": envelope.format,
            "cipher": envelope.cipher,
            "key_id": envelope.key_id,
            "nonce": envelope.nonce,
            "aad": envelope.aad,
            "ciphertext": envelope.ciphertext,
            "tag": envelope.tag,
            "plaintext_sha256": envelope.plaintext_sha256,
            "message_type": envelope.message_type,
            "from": envelope.from_id,
            "to": envelope.to_id,
            "mission_id": envelope.mission_id,
            "correlation_id": envelope.correlation_id,
            "status": envelope.status,
            "created_at": envelope.created_at,
            "opened_at": envelope.opened_at,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # --- reporting ----------------------------------------------------------

    def report(self, *, actor: str = DEFAULT_ACTOR) -> TransportReport:
        """Aggregate channel and envelope statistics."""
        result = self._load_state(actor)
        if isinstance(result, EtrError):
            raise result
        state, _, _ = result
        channels = self._channels(state)
        envelopes = self._envelopes(state)
        return TransportReport(
            channels_total=len(channels),
            channels_active=sum(
                1 for c in channels.values() if c.get("status") == "ACTIVE"
            ),
            channels_revoked=sum(
                1 for c in channels.values() if c.get("status") == "REVOKED"
            ),
            envelopes_total=len(envelopes),
            envelopes_sealed=sum(
                1 for e in envelopes.values() if e.get("status") == "SEALED"
            ),
            envelopes_opened=sum(
                1 for e in envelopes.values() if e.get("status") == "OPENED"
            ),
            envelopes_auth_failed=sum(
                1 for e in envelopes.values() if e.get("status") == "AUTH_FAILED"
            ),
        )
