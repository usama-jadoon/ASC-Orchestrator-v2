"""Black-box coverage for the CKS v1.0 key-* CLI commands."""

from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main

CONFIG = """[runtime]
project_os_dir = ".project-os"
registry_dir = "registry"
audit_dir = ".project-os/AUDIT"
protocol_version = "ACP/v1.0"
"""

ACTOR = "AGENT:orchestrator:test"


class KeyCliTests(unittest.TestCase):
    @staticmethod
    def _run(root: Path, *arguments: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(root), *arguments])
        return code, output.getvalue()

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
        (self.root / "artifact.txt").write_text("hello world\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_key(self) -> str:
        code, output = self._run(
            self.root, "key-create", "--actor", ACTOR, "--purpose", "audit-signing"
        )
        self.assertEqual(code, 0, output)
        return output.strip().split("key_id=")[1].splitlines()[0]

    def test_create_prints_key_id(self) -> None:
        code, output = self._run(self.root, "key-create", "--actor", ACTOR)
        self.assertEqual(code, 0, output)
        self.assertIn("key_id=KEY-", output)
        self.assertTrue((self.root / ".project-os" / "KEYS" / "keys").is_dir())

    def test_list_prints_key_count_and_ids(self) -> None:
        key_id = self._create_key()
        code, output = self._run(self.root, "key-list")
        self.assertEqual(code, 0, output)
        self.assertIn("key_count=1", output)
        self.assertIn(key_id, output)

    def test_sign_and_verify_round_trip(self) -> None:
        key_id = self._create_key()
        code, output = self._run(
            self.root, "key-sign", "--key-id", key_id, "--file", "artifact.txt"
        )
        self.assertEqual(code, 0, output)
        signature = output.strip().split("signature=")[1].splitlines()[0]
        self.assertEqual(len(signature), 64)
        code, output = self._run(
            self.root,
            "key-verify",
            "--key-id",
            key_id,
            "--file",
            "artifact.txt",
            "--signature",
            signature,
        )
        self.assertEqual(code, 0, output)
        self.assertIn("valid=true", output)

    def test_verify_reports_false_for_bad_signature(self) -> None:
        key_id = self._create_key()
        code, output = self._run(
            self.root,
            "key-verify",
            "--key-id",
            key_id,
            "--file",
            "artifact.txt",
            "--signature",
            "0" * 64,
        )
        self.assertEqual(code, 0, output)
        self.assertIn("valid=false", output)

    def test_verify_missing_key_exits_two(self) -> None:
        code, output = self._run(
            self.root,
            "key-verify",
            "--key-id",
            "KEY-missing",
            "--file",
            "artifact.txt",
            "--signature",
            "0" * 64,
        )
        self.assertEqual(code, 2, output)
        self.assertIn("KEY_NOT_FOUND", output)

    def test_rotate_prints_new_key_and_retires_old(self) -> None:
        key_id = self._create_key()
        code, output = self._run(
            self.root, "key-rotate", "--key-id", key_id, "--actor", ACTOR
        )
        self.assertEqual(code, 0, output)
        new_key_id = output.strip().split("new_key_id=")[1].splitlines()[0]
        self.assertNotEqual(new_key_id, key_id)
        # The old key can no longer sign.
        code, output = self._run(
            self.root, "key-sign", "--key-id", key_id, "--file", "artifact.txt"
        )
        self.assertEqual(code, 2, output)
        self.assertIn("KEY_NOT_ACTIVE", output)

    def test_revoke_reports_revoked_status(self) -> None:
        key_id = self._create_key()
        code, output = self._run(
            self.root, "key-revoke", "--key-id", key_id, "--actor", ACTOR
        )
        self.assertEqual(code, 0, output)
        self.assertIn("status=REVOKED", output)

    def test_validate_reports_valid(self) -> None:
        self._create_key()
        code, output = self._run(self.root, "key-validate")
        self.assertEqual(code, 0, output)
        self.assertIn("outcome=VALID", output)

    def test_validate_detects_tampered_ledger(self) -> None:
        key_id = self._create_key()
        self._run(self.root, "key-sign", "--key-id", key_id, "--file", "artifact.txt")
        ledger = self.root / ".project-os" / "KEYS" / "signatures" / f"{key_id}.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[0] = lines[0].replace('"actor":"', '"actor":"AA')
        ledger.write_text("".join(lines), encoding="utf-8")
        code, output = self._run(self.root, "key-validate")
        self.assertEqual(code, 2, output)
        self.assertIn("outcome=INVALID", output)

    def test_sign_missing_file_exits_two(self) -> None:
        key_id = self._create_key()
        code, output = self._run(
            self.root, "key-sign", "--key-id", key_id, "--file", "nope.txt"
        )
        self.assertEqual(code, 2, output)
        self.assertIn("error:", output)


if __name__ == "__main__":
    unittest.main()
