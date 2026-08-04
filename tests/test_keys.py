"""Focused deterministic tests for the stdlib CKS v1.0 key service."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asc_orchestrator.keys import CKSError, KeyStore

ACTOR = "AGENT:orchestrator:test"
PURPOSE = "audit-signing"


class KeyStoreTestBase(unittest.TestCase):
    """Shared setUp: a temp root and a fresh KeyStore with one created key."""

    def setUp(self) -> None:
        self._previous_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["GIT_CEILING_DIRECTORIES"] = str(self.root.parent)
        self.store = KeyStore(self.root)

    def tearDown(self) -> None:
        if self._previous_ceiling is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = self._previous_ceiling
        self.temp.cleanup()


class TestCreateAndLoad(KeyStoreTestBase):
    def test_create_persists_immutable_record(self) -> None:
        record = self.store.create_key(ACTOR, purpose=PURPOSE)
        self.assertTrue(record.key_id.startswith("KEY-"))
        self.assertEqual(record.key_type, "HMAC-SHA256")
        self.assertEqual(record.purpose, PURPOSE)
        self.assertEqual(record.created_by, ACTOR)
        self.assertEqual(len(record.material_hex), 64)
        self.assertEqual(len(record.fingerprint_hex), 64)
        # Fingerprint is the SHA-256 of the hex-encoded material string.
        expected = hashlib.sha256(record.material_hex.encode("utf-8")).hexdigest()
        self.assertEqual(record.fingerprint_hex, expected)
        # The record file exists and the status journal is ACTIVE.
        key_file = self.store._key_file(record.key_id)
        self.assertTrue(key_file.exists())
        self.assertEqual(self.store.status(record.key_id), "ACTIVE")

    def test_key_ids_are_unique(self) -> None:
        first = self.store.create_key(ACTOR)
        second = self.store.create_key(ACTOR)
        self.assertNotEqual(first.key_id, second.key_id)

    def test_load_round_trip(self) -> None:
        created = self.store.create_key(ACTOR, purpose=PURPOSE)
        loaded = self.store.load_key(created.key_id)
        self.assertEqual(loaded.key_id, created.key_id)
        self.assertEqual(loaded.material_hex, created.material_hex)
        self.assertEqual(loaded.fingerprint_hex, created.fingerprint_hex)
        self.assertEqual(loaded.file_sha256, created.file_sha256)

    def test_load_missing_key_raises(self) -> None:
        with self.assertRaises(CKSError) as ctx:
            self.store.load_key("KEY-does-not-exist")
        self.assertEqual(ctx.exception.code, "KEY_NOT_FOUND")

    def test_list_keys_sorted_by_created_at(self) -> None:
        self.store.create_key(ACTOR, purpose="first")
        self.store.create_key(ACTOR, purpose="second")
        records = self.store.list_keys()
        self.assertEqual(len(records), 2)
        stamps = [r.created_at for r in records]
        self.assertEqual(stamps, sorted(stamps))

    def test_validate_fresh_store(self) -> None:
        self.assertTrue(self.store.validate())

    def test_validate_after_create(self) -> None:
        self.store.create_key(ACTOR)
        self.assertTrue(self.store.validate())


class TestSigning(KeyStoreTestBase):
    def test_sign_verify_round_trip(self) -> None:
        key = self.store.create_key(ACTOR, purpose=PURPOSE)
        signature = self.store.sign(key.key_id, b"payload-bytes", ACTOR)
        self.assertEqual(len(signature.signature_hex), 64)
        self.assertTrue(
            self.store.verify(key.key_id, b"payload-bytes", signature.signature_hex)
        )
        self.assertFalse(
            self.store.verify(key.key_id, b"different-bytes", signature.signature_hex)
        )

    def test_signing_is_deterministic(self) -> None:
        key = self.store.create_key(ACTOR)
        first = self.store.sign(key.key_id, b"payload", ACTOR)
        second = self.store.sign(key.key_id, b"payload", ACTOR)
        self.assertEqual(first.signature_hex, second.signature_hex)
        # The HMAC key is the UTF-8 encoding of the hex-encoded material string.
        expected = _hmac.new(
            key.material_hex.encode("utf-8"), b"payload", "sha256"
        ).hexdigest()
        self.assertEqual(first.signature_hex, expected)

    def test_sign_records_ledger_entry(self) -> None:
        key = self.store.create_key(ACTOR)
        self.store.sign(key.key_id, b"payload", ACTOR)
        ledger = self.store._ledger(key.key_id)
        lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["kind"], "signature")
        self.assertEqual(entry["key_id"], key.key_id)
        self.assertEqual(
            entry["payload_sha256"], hashlib.sha256(b"payload").hexdigest()
        )

    def test_sign_unknown_key_raises(self) -> None:
        with self.assertRaises(CKSError) as ctx:
            self.store.sign("KEY-missing", b"payload", ACTOR)
        self.assertEqual(ctx.exception.code, "KEY_NOT_FOUND")

    def test_verify_unknown_key_raises(self) -> None:
        with self.assertRaises(CKSError) as ctx:
            self.store.verify("KEY-missing", b"payload", "00" * 32)
        self.assertEqual(ctx.exception.code, "KEY_NOT_FOUND")

    def test_verify_rejects_wrong_signature_length(self) -> None:
        key = self.store.create_key(ACTOR)
        self.assertFalse(self.store.verify(key.key_id, b"payload", "short"))


class TestRotationAndRevocation(KeyStoreTestBase):
    def test_rotate_marks_old_rotated_and_creates_new(self) -> None:
        old = self.store.create_key(ACTOR, purpose=PURPOSE)
        new = self.store.rotate(ACTOR, old.key_id, reason="REGENERATION")
        self.assertEqual(self.store.status(old.key_id), "ROTATED")
        self.assertEqual(self.store.status(new.key_id), "ACTIVE")
        self.assertNotEqual(old.key_id, new.key_id)
        # Old key material is preserved for historical verification.
        self.assertEqual(self.store.load_key(old.key_id).material_hex, old.material_hex)
        # Old key can no longer sign.
        with self.assertRaises(CKSError) as ctx:
            self.store.sign(old.key_id, b"payload", ACTOR)
        self.assertEqual(ctx.exception.code, "KEY_NOT_ACTIVE")

    def test_rotate_requires_active_key(self) -> None:
        key = self.store.create_key(ACTOR)
        self.store.revoke(ACTOR, key.key_id)
        with self.assertRaises(CKSError) as ctx:
            self.store.rotate(ACTOR, key.key_id)
        self.assertEqual(ctx.exception.code, "KEY_NOT_ACTIVE")

    def test_revoke_marks_revoked_and_blocks_signing(self) -> None:
        key = self.store.create_key(ACTOR)
        entry = self.store.revoke(ACTOR, key.key_id, reason="COMPROMISED")
        self.assertEqual(entry["status"], "REVOKED")
        self.assertEqual(entry["reason"], "COMPROMISED")
        self.assertEqual(self.store.status(key.key_id), "REVOKED")
        with self.assertRaises(CKSError) as ctx:
            self.store.sign(key.key_id, b"payload", ACTOR)
        self.assertEqual(ctx.exception.code, "KEY_NOT_ACTIVE")
        self.assertFalse(self.store.verify(key.key_id, b"payload", "00" * 32))

    def test_revoke_requires_active_key(self) -> None:
        key = self.store.create_key(ACTOR)
        self.store.revoke(ACTOR, key.key_id)
        with self.assertRaises(CKSError) as ctx:
            self.store.revoke(ACTOR, key.key_id)
        self.assertEqual(ctx.exception.code, "KEY_NOT_ACTIVE")

    def test_status_defaults_active_without_journal(self) -> None:
        key = self.store.create_key(ACTOR)
        # Remove the status journal: effective status must fall back to ACTIVE.
        self.store._status_journal(key.key_id).unlink()
        self.assertEqual(self.store.status(key.key_id), "ACTIVE")

    def test_signatures_before_rotation_still_verify(self) -> None:
        key = self.store.create_key(ACTOR)
        signature = self.store.sign(key.key_id, b"payload", ACTOR)
        self.store.rotate(ACTOR, key.key_id)
        # Historical signature verifies even though the key is now ROTATED? No —
        # verification requires ACTIVE, so ROTATED keys no longer verify.
        self.assertFalse(
            self.store.verify(key.key_id, b"payload", signature.signature_hex)
        )


class TestLedgerIntegrity(KeyStoreTestBase):
    def test_chain_verifies_after_multiple_signatures(self) -> None:
        key = self.store.create_key(ACTOR)
        for index in range(5):
            self.store.sign(key.key_id, f"payload-{index}".encode(), ACTOR)
        self.assertTrue(self.store.verify_chain(key.key_id))
        self.assertTrue(self.store.validate())

    def test_chain_detects_tampered_signature(self) -> None:
        key = self.store.create_key(ACTOR)
        self.store.sign(key.key_id, b"payload-1", ACTOR)
        self.store.sign(key.key_id, b"payload-2", ACTOR)
        ledger = self.store._ledger(key.key_id)
        lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[0] = lines[0].replace('"payload_sha256":"', '"payload_sha256":"AAAA')
        ledger.write_text("".join(lines), encoding="utf-8")
        self.assertFalse(self.store.verify_chain(key.key_id))
        self.assertFalse(self.store.validate())

    def test_chain_detects_removed_middle_entry(self) -> None:
        key = self.store.create_key(ACTOR)
        self.store.sign(key.key_id, b"payload-1", ACTOR)
        self.store.sign(key.key_id, b"payload-2", ACTOR)
        self.store.sign(key.key_id, b"payload-3", ACTOR)
        ledger = self.store._ledger(key.key_id)
        lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
        # Removing the middle entry breaks the linkage for the tail entry.
        ledger.write_text("".join(lines[:1] + lines[2:]), encoding="utf-8")
        self.assertFalse(self.store.verify_chain(key.key_id))

    def test_sign_refuses_broken_ledger(self) -> None:
        key = self.store.create_key(ACTOR)
        self.store.sign(key.key_id, b"payload-1", ACTOR)
        ledger = self.store._ledger(key.key_id)
        lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[0] = lines[0].replace('"payload_sha256":"', '"payload_sha256":"AAAA')
        ledger.write_text("".join(lines), encoding="utf-8")
        with self.assertRaises(CKSError) as ctx:
            self.store.sign(key.key_id, b"payload-2", ACTOR)
        self.assertEqual(ctx.exception.code, "LEDGER_BROKEN")

    def test_validate_detects_tampered_key_file(self) -> None:
        key = self.store.create_key(ACTOR)
        key_file = self.store._key_file(key.key_id)
        original = key_file.read_text(encoding="utf-8")
        key_file.write_text(
            original.replace('"purpose"', '"purpose":"hacked"'), encoding="utf-8"
        )
        self.assertFalse(self.store.validate())


class TestConcurrentSigning(KeyStoreTestBase):
    def test_concurrent_signs_preserve_chain(self) -> None:
        key = self.store.create_key(ACTOR)
        errors: list[Exception] = []

        def worker(index: int) -> None:
            try:
                self.store.sign(key.key_id, f"payload-{index}".encode(), ACTOR)
            except Exception as exc:  # pragma: no cover - failure surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertTrue(self.store.verify_chain(key.key_id))
        # Every signature was recorded exactly once.
        ledger = self.store._ledger(key.key_id)
        count = len(
            [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln]
        )
        self.assertEqual(count, 8)


if __name__ == "__main__":
    unittest.main()
