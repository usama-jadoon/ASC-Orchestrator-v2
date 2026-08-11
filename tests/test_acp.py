"""Focused validation for the ACP v1.0 local runtime foundation."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from asc_orchestrator.acp import (  # noqa: E402
    MESSAGE_TYPES,
    REQUIRED_PAYLOAD_FIELDS,
    ACPMessage,
    ACPParseError,
    parse_message,
)
from asc_orchestrator.audit import AuditJournal  # noqa: E402


def _message(message_type: str = "HEARTBEAT") -> ACPMessage:
    sender = f"AGENT:developer:{uuid4()}"
    values = {field: "NONE" for field in REQUIRED_PAYLOAD_FIELDS[message_type]}
    values.update(
        {
            "PRIORITY": "Medium",
            "BOUNDARIES": "included|excluded|repository|ownership",
            "AUTHORITY": "autonomous|escalate",
            "STEP": "N/A",
            "PROGRESS-PERCENT": "0",
            "RESOURCE-USAGE": "0|0|0",
            "TYPE": "test",
            "HASH": "0" * 64,
            "ISSUE-TYPE": "blocker",
            "TIME-OBSERVED": "2026-08-04T12:34:56.789Z",
            "RECOVERABLE": "YES",
            "SUGGECTED-NEXT-STEP": "investigate",
            "READY-TO-RESUME": "YES",
            "GATE": "qa",
            "RESULT": "PASS",
            "RETRY-ALLOWED": "YES",
            "APPROVAL-TYPE": "gate",
            "ALL-GATES-PASSED": "YES",
            "HANDOFF-READY": "YES",
            "REASON": "other",
            "PARTIAL-WORK-STATUS": "preserve",
            "REVIEW-TYPE": "peer",
            "DECISION-ID": str(uuid4()),
            "REVERSIBLE": "YES",
            "KNOWLEDGE-TYPE": "pattern",
            "ENTRY-TIME": "2026-08-04T12:34:56.789Z",
            "FIELD-CHANGED": "scope",
            "EFFECTIVE-IMMEDIATELY": "YES",
            "STATUS": "ready",
            "RESOURCE-LOAD": "0|0",
            "LAST-HEARTBEAT": "2026-08-04T12:34:56.789Z",
            "APPROVING-AGENT": sender,
            "CANCELLING-AGENT": sender,
        }
    )
    payload = [
        (field, values[field]) for field in REQUIRED_PAYLOAD_FIELDS[message_type]
    ]
    return ACPMessage.create(
        message_type,
        sender,
        "BROADCAST",
        "NONE",
        "2026-08-04T12:34:56.789Z",
        str(uuid4()),
        payload,
    )


class ACPMessageTests(unittest.TestCase):
    def _with_replaced_value(
        self, message_type: str, field: str, value: str
    ) -> ACPMessage:
        message = _message(message_type)
        payload = [
            (key, value if key == field else existing)
            for key, existing in message.payload
        ]
        return ACPMessage.create(
            message.message_type,
            message.sender,
            message.recipient,
            message.mission,
            message.timestamp,
            message.correlation,
            payload,
        )

    def test_all_message_types_can_be_constructed(self) -> None:
        for message_type in MESSAGE_TYPES:
            message = _message(message_type)
            self.assertEqual(parse_message(message.serialize()), message)

    def test_serialization_is_deterministic_utf8(self) -> None:
        message = _message()
        first = message.serialize()
        self.assertEqual(first, message.serialize())
        self.assertEqual(parse_message(first.encode("utf-8")).serialize(), first)

    def test_rejects_reordered_headers_and_payload_fields(self) -> None:
        message = _message("STATUS_UPDATE")
        wire = message.serialize()
        lines = wire.split("\n")
        lines[1], lines[2] = lines[2], lines[1]
        with self.assertRaises(ACPParseError):
            parse_message("\n".join(lines))

        payload = list(message.payload)
        payload[0], payload[1] = payload[1], payload[0]
        text = "\n".join(f"{key}:{value}" for key, value in payload)
        invalid = (
            wire.split("\n")[:7]
            + ["PAYLOAD-SHA256:" + hashlib.sha256(text.encode()).hexdigest()]
            + text.split("\n")
        )
        with self.assertRaises(ACPParseError):
            parse_message("\n".join(invalid))

    def test_rejects_invalid_identity_hash_and_missing_required_field(self) -> None:
        message = _message()
        wire = message.serialize()
        with self.assertRaises(ACPParseError):
            parse_message(wire.replace("AGENT:developer:", "AGENT:Developer:", 1))
        with self.assertRaises(ACPParseError):
            parse_message(wire.replace("PAYLOAD-SHA256:", "PAYLOAD-SHA256:xyz", 1))
        with self.assertRaises(ACPParseError):
            parse_message("\n".join(wire.split("\n")[:-1]))

    def test_optional_fields_and_semantic_formats_are_enforced(self) -> None:
        self.assertEqual(_message("EVIDENCE").message_type, "EVIDENCE")
        self.assertEqual(_message("WARNING").message_type, "WARNING")
        self.assertEqual(_message("COMPLETION").message_type, "COMPLETION")
        self.assertEqual(_message("HEARTBEAT").message_type, "HEARTBEAT")
        with self.assertRaises(Exception):
            ACPMessage.create(
                "STATUS_UPDATE",
                f"AGENT:developer:{uuid4()}",
                "NONE",
                "NONE",
                "2026-08-04T12:34:56.789Z",
                str(uuid4()),
                [
                    ("STEP", "2/1"),
                    ("PROGRESS-PERCENT", "101"),
                    ("BLOCKERS", "NONE"),
                    ("RESOURCE-USAGE", "0|0"),
                    ("NEXT-EXPECTED-OUTCOME", "x"),
                ],
            )

    def test_rejects_all_closed_acp_payload_domains(self) -> None:
        for message_type, field, value in (
            ("FAILURE", "SUGGECTED-NEXT-STEP", "invalid"),
            ("CANCELLATION", "PARTIAL-WORK-STATUS", "invalid"),
            ("ASSIGNMENT", "BOUNDARIES", "one-section"),
            ("ASSIGNMENT", "AUTHORITY", "one-section"),
        ):
            with self.subTest(message_type=message_type, field=field):
                with self.assertRaises(Exception):
                    self._with_replaced_value(message_type, field, value)

        message = _message("EVIDENCE")
        with self.assertRaises(Exception):
            ACPMessage.create(
                message.message_type,
                message.sender,
                message.recipient,
                message.mission,
                message.timestamp,
                message.correlation,
                [*message.payload, ("TIME-RANGE", "N/A")],
            )


class AuditJournalTests(unittest.TestCase):
    def test_append_creates_hash_chained_utf8_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AuditJournal(temporary_directory)
            first = journal.append("OUT", _message(), "VALID")
            second = journal.append("IN", "malformed message", "INVALID")
            self.assertTrue(journal.path.is_file())
            self.assertIsNone(first["previous_hash"])
            self.assertEqual(second["previous_hash"], first["entry_hash"])
            self.assertTrue(journal.verify_chain())

    def test_explicit_directory_concurrent_append_and_traversal_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            custom_directory = Path(temporary_directory) / "custom-audit"
            journal = AuditJournal(
                temporary_directory, audit_directory=custom_directory
            )
            self.assertEqual(journal.directory, custom_directory.resolve())
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(
                    executor.map(
                        lambda _: journal.append("OUT", _message(), "VALID"), range(12)
                    )
                )
            self.assertEqual(len(list(journal.entries())), 12)
            self.assertTrue(journal.verify_chain())
            with self.assertRaises(Exception):
                AuditJournal(temporary_directory, filename="../outside.jsonl")

    def test_separate_process_appends_preserve_the_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            script = (
                "from pathlib import Path; "
                "from asc_orchestrator.audit import AuditJournal; "
                "import sys; "
                "AuditJournal(Path(sys.argv[1])).append('OUT', sys.argv[2], 'VALID')"
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = (
                str(SRC) + os.pathsep + environment.get("PYTHONPATH", "")
            )
            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        script,
                        temporary_directory,
                        f"message-{index}",
                    ],
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(6)
            ]
            for process in processes:
                _, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
            journal = AuditJournal(temporary_directory)
            self.assertEqual(len(list(journal.entries())), 6)
            self.assertTrue(journal.verify_chain())


if __name__ == "__main__":
    unittest.main()
