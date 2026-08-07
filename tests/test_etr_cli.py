"""Black-box coverage for the ETR v1.0 etr-* CLI commands."""

from __future__ import annotations

import json
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
FROM_ID = "AGENT:sender:test"
TO_ID = "AGENT:receiver:test"


class EtrCliTests(unittest.TestCase):
    """ETR CLI lifecycle in a temp repo: bind → seal → open → revoke → report."""

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
        code, output = self._run(self.root, "state", "--initialize")
        self.assertEqual(code, 0, output)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_key(self) -> str:
        code, output = self._run(
            self.root, "key-create", "--actor", ACTOR, "--purpose", "transport"
        )
        self.assertEqual(code, 0, output)
        return output.strip().split("key_id=")[1].splitlines()[0]

    def _bind_channel(self, key_id: str) -> str:
        code, output = self._run(
            self.root,
            "etr-bind-channel",
            "--from",
            FROM_ID,
            "--to",
            TO_ID,
            "--key-id",
            key_id,
            "--actor",
            ACTOR,
        )
        self.assertEqual(code, 0, output)
        return output.strip().split("channel_id=")[1].splitlines()[0]

    @staticmethod
    def _field(output: str, name: str) -> str:
        for line in output.splitlines():
            key, sep, value = line.partition("=")
            if sep and key == name:
                return value
        raise AssertionError(f"field {name!r} not found in output:\n{output}")

    # -- channel lifecycle ----------------------------------------------------

    def test_bind_channel_lifecycle(self) -> None:
        key_id = self._create_key()
        channel_id = self._bind_channel(key_id)
        self.assertTrue(channel_id.startswith("CHANNEL:"))

        # channel read
        code, output = self._run(self.root, "etr-channel", "--channel-id", channel_id)
        self.assertEqual(code, 0, output)
        self.assertIn(f"channel_id={channel_id}", output)
        self.assertIn("status=ACTIVE", output)
        self.assertIn(f"from_id={FROM_ID}", output)
        self.assertIn(f"to_id={TO_ID}", output)
        self.assertIn(f"key_id={key_id}", output)

        # list channels
        code, output = self._run(self.root, "etr-list-channels")
        self.assertEqual(code, 0, output)
        self.assertIn("channel_count=1", output)
        self.assertIn(f"channel_id={channel_id}", output)

        # list filtered by from
        code, output = self._run(self.root, "etr-list-channels", "--from", FROM_ID)
        self.assertEqual(code, 0, output)
        self.assertIn("channel_count=1", output)

        # list filtered by status miss
        code, output = self._run(self.root, "etr-list-channels", "--status", "REVOKED")
        self.assertEqual(code, 0, output)
        self.assertIn("channel_count=0", output)

        # revoke
        code, output = self._run(
            self.root, "etr-revoke-channel", "--channel-id", channel_id
        )
        self.assertEqual(code, 0, output)
        self.assertIn("status=REVOKED", output)
        self.assertIn("revoked_at=", output)

    def test_revoke_inactive_channel_exits_two(self) -> None:
        key_id = self._create_key()
        channel_id = self._bind_channel(key_id)
        self._run(self.root, "etr-revoke-channel", "--channel-id", channel_id)
        code, output = self._run(
            self.root, "etr-revoke-channel", "--channel-id", channel_id
        )
        self.assertEqual(code, 2, output)
        self.assertIn("CHANNEL_NOT_ACTIVE", output)

    def test_channel_missing_exits_two(self) -> None:
        code, output = self._run(
            self.root, "etr-channel", "--channel-id", "CHANNEL:nope"
        )
        self.assertEqual(code, 2, output)
        self.assertIn("CHANNEL_NOT_FOUND", output)

    # -- seal / open lifecycle -------------------------------------------------

    def test_seal_open_round_trip(self) -> None:
        key_id = self._create_key()
        payload = self.root / "secret.txt"
        payload.write_text("classified data\n", encoding="utf-8")
        code, output = self._run(
            self.root,
            "etr-seal",
            "--file",
            "secret.txt",
            "--key-id",
            key_id,
            "--message-type",
            "STATUS",
            "--mission-id",
            "MISSION:etr-cli",
            "--from",
            FROM_ID,
            "--to",
            TO_ID,
        )
        self.assertEqual(code, 0, output)
        envelope_id = self._field(output, "envelope_id")
        self.assertTrue(envelope_id.startswith("ENVELOPE:"))
        self.assertIn(f"key_id={key_id}", output)
        self.assertIn("status=SEALED", output)
        envelope_path = self.root / "secret.txt.etr"
        self.assertTrue(envelope_path.exists())
        envelope_json = json.loads(envelope_path.read_text(encoding="utf-8"))
        self.assertEqual(envelope_json["envelope_id"], envelope_id)
        self.assertEqual(envelope_json["message_type"], "STATUS")
        self.assertEqual(envelope_json["mission_id"], "MISSION:etr-cli")
        self.assertEqual(envelope_json["from"], FROM_ID)
        self.assertEqual(envelope_json["to"], TO_ID)
        self.assertEqual(envelope_json["status"], "SEALED")
        self.assertNotIn("classified data", envelope_path.read_text(encoding="utf-8"))

        # open by envelope file path
        out_path = self.root / "revealed.txt"
        code, output = self._run(
            self.root,
            "etr-open",
            "--envelope",
            "secret.txt.etr",
            "--output",
            "revealed.txt",
        )
        self.assertEqual(code, 0, output)
        self.assertIn(f"envelope_id={envelope_id}", output)
        self.assertIn("status=OPENED", output)
        self.assertEqual(out_path.read_text(encoding="utf-8"), "classified data\n")

        # list envelopes shows OPENED status
        code, output = self._run(self.root, "etr-list-envelopes")
        self.assertEqual(code, 0, output)
        self.assertIn("envelope_count=1", output)
        self.assertIn(f"envelope_id={envelope_id}", output)

    def test_seal_via_channel_resolves_sender_recipient(self) -> None:
        key_id = self._create_key()
        channel_id = self._bind_channel(key_id)
        payload = self.root / "chan.txt"
        payload.write_text("channel bound\n", encoding="utf-8")
        code, output = self._run(
            self.root,
            "etr-seal",
            "--file",
            "chan.txt",
            "--channel-id",
            channel_id,
        )
        self.assertEqual(code, 0, output)
        self.assertIn(f"key_id={key_id}", output)
        envelope_path = self.root / "chan.txt.etr"
        envelope_json = json.loads(envelope_path.read_text(encoding="utf-8"))
        self.assertEqual(envelope_json["from"], FROM_ID)
        self.assertEqual(envelope_json["to"], TO_ID)
        self.assertEqual(envelope_json["key_id"], key_id)

    def test_seal_requires_key_or_channel(self) -> None:
        payload = self.root / "none.txt"
        payload.write_text("x", encoding="utf-8")
        code, output = self._run(self.root, "etr-seal", "--file", "none.txt")
        self.assertEqual(code, 2, output)
        self.assertIn("KEY_REQUIRED", output)

    def test_open_tampered_envelope_exits_two(self) -> None:
        key_id = self._create_key()
        payload = self.root / "tamper.txt"
        payload.write_text("tamper me\n", encoding="utf-8")
        code, output = self._run(
            self.root, "etr-seal", "--file", "tamper.txt", "--key-id", key_id
        )
        self.assertEqual(code, 0, output)
        envelope_path = self.root / "tamper.txt.etr"
        record = json.loads(envelope_path.read_text(encoding="utf-8"))
        first = record["ciphertext"][0]
        record["ciphertext"] = ("1" if first != "1" else "0") + record["ciphertext"][1:]
        envelope_path.write_text(json.dumps(record), encoding="utf-8")
        code, output = self._run(self.root, "etr-open", "--envelope", "tamper.txt.etr")
        self.assertEqual(code, 2, output)
        self.assertIn("AUTH_FAILED", output)

    def test_open_missing_envelope_exits_two(self) -> None:
        code, output = self._run(self.root, "etr-open", "--envelope", "ENVELOPE:nope")
        self.assertEqual(code, 2, output)
        self.assertIn("ENVELOPE_NOT_FOUND", output)

    # -- report and event journal ----------------------------------------------

    def test_report_counts(self) -> None:
        key_id = self._create_key()
        self._bind_channel(key_id)
        payload = self.root / "r.txt"
        payload.write_text("report\n", encoding="utf-8")
        self._run(self.root, "etr-seal", "--file", "r.txt", "--key-id", key_id)
        code, output = self._run(self.root, "etr-report")
        self.assertEqual(code, 0, output)
        self.assertIn("channels_total=1", output)
        self.assertIn("channels_active=1", output)
        self.assertIn("channels_revoked=0", output)
        self.assertIn("envelopes_total=1", output)
        self.assertIn("envelopes_sealed=1", output)
        self.assertIn("envelopes_opened=0", output)
        self.assertIn("envelopes_auth_failed=0", output)

    def test_auth_failure_appears_in_report(self) -> None:
        key_id = self._create_key()
        payload = self.root / "af.txt"
        payload.write_text("auth fail\n", encoding="utf-8")
        code, output = self._run(
            self.root, "etr-seal", "--file", "af.txt", "--key-id", key_id
        )
        self.assertEqual(code, 0, output)
        envelope_path = self.root / "af.txt.etr"
        record = json.loads(envelope_path.read_text(encoding="utf-8"))
        first = record["tag"][0]
        record["tag"] = ("1" if first != "1" else "0") + record["tag"][1:]
        envelope_path.write_text(json.dumps(record), encoding="utf-8")
        code, output = self._run(self.root, "etr-open", "--envelope", "af.txt.etr")
        self.assertEqual(code, 2, output)
        code, output = self._run(self.root, "etr-report")
        self.assertEqual(code, 0, output)
        self.assertIn("envelopes_auth_failed=1", output)

    def test_events_appended_to_journal(self) -> None:
        key_id = self._create_key()
        channel_id = self._bind_channel(key_id)
        payload = self.root / "ev.txt"
        payload.write_text("events\n", encoding="utf-8")
        code, output = self._run(
            self.root, "etr-seal", "--file", "ev.txt", "--key-id", key_id
        )
        envelope_id = self._field(output, "envelope_id")
        self.assertEqual(code, 0, output)
        code, output = self._run(self.root, "etr-open", "--envelope", envelope_id)
        self.assertEqual(code, 0, output)
        self._run(self.root, "etr-revoke-channel", "--channel-id", channel_id)
        journal_path = self.root / ".project-os" / "AUDIT" / "execution-events.jsonl"
        events = [
            json.loads(line)
            for line in journal_path.read_text(encoding="utf-8").splitlines()
        ]
        event_types = [event["event_type"] for event in events]
        self.assertIn("ETR_CHANNEL_BOUND", event_types)
        self.assertIn("ETR_SEALED", event_types)
        self.assertIn("ETR_UNSEALED", event_types)
        self.assertIn("ETR_CHANNEL_REVOKED", event_types)


if __name__ == "__main__":
    unittest.main()
