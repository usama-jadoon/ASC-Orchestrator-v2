"""Unit tests for AHP v1.0 — Agent Health Protocol."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.health import (
    AHPError,
    HealthStore,
    HeartbeatRecord,
    _record_hash,
)


def _ts(seconds: float = 0.0) -> str:
    """UTC timestamp offset from a fixed baseline."""
    base = datetime(2026, 8, 5, 4, 0, 0, tzinfo=UTC) + timedelta(seconds=seconds)
    return base.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TestHeartbeatRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_heartbeat_appends_record(self) -> None:
        store = HealthStore(self.root)
        rec = store.heartbeat("AGENT:dev:local", occurred_at=_ts())
        self.assertIsInstance(rec, HeartbeatRecord)
        self.assertEqual(rec.agent_id, "AGENT:dev:local")
        self.assertEqual(rec.sequence, 1)
        self.assertEqual(len(rec.heartbeat_sha256), 64)

    def test_heartbeat_increments_sequence(self) -> None:
        store = HealthStore(self.root)
        r1 = store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        r2 = store.heartbeat("AGENT:dev:local", occurred_at=_ts(10))
        self.assertEqual(r1.sequence, 1)
        self.assertEqual(r2.sequence, 2)
        self.assertEqual(r2.previous_heartbeat_sha256, r1.heartbeat_sha256)

    def test_heartbeat_hash_chain(self) -> None:
        store = HealthStore(self.root)
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(10))
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(20))
        self.assertTrue(store.validate())

    def test_heartbeat_with_metadata(self) -> None:
        store = HealthStore(self.root)
        rec = store.heartbeat(
            "AGENT:dev:local",
            mission_id="MISSION:m1",
            assignment_id="ASSIGNMENT:a1",
            note="working",
            occurred_at=_ts(),
        )
        self.assertEqual(rec.mission_id, "MISSION:m1")
        self.assertEqual(rec.assignment_id, "ASSIGNMENT:a1")
        self.assertEqual(rec.note, "working")

    def test_empty_agent_id_raises(self) -> None:
        store = HealthStore(self.root)
        with self.assertRaises(AHPError) as ctx:
            store.heartbeat("")
        self.assertEqual(ctx.exception.code, "INVALID_AGENT")


class TestAgentHealth(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = HealthStore(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unknown_when_no_heartbeat(self) -> None:
        h = self.store.agent_health("AGENT:dev:local", timeout=300, now=_ts(0))
        self.assertEqual(h.status, "UNKNOWN")
        self.assertEqual(h.heartbeat_count, 0)
        self.assertIsNone(h.age_seconds)

    def test_alive_within_timeout(self) -> None:
        self.store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        h = self.store.agent_health("AGENT:dev:local", timeout=300, now=_ts(100))
        self.assertEqual(h.status, "ALIVE")
        self.assertAlmostEqual(h.age_seconds, 100.0, places=1)
        self.assertEqual(h.heartbeat_count, 1)

    def test_stalled_outside_timeout(self) -> None:
        self.store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        h = self.store.agent_health("AGENT:dev:local", timeout=300, now=_ts(400))
        self.assertEqual(h.status, "STALLED")
        self.assertAlmostEqual(h.age_seconds, 400.0, places=1)

    def test_exactly_at_timeout_is_alive(self) -> None:
        self.store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        h = self.store.agent_health("AGENT:dev:local", timeout=300, now=_ts(300))
        self.assertEqual(h.status, "ALIVE")
        self.assertAlmostEqual(h.age_seconds, 300.0, places=1)

    def test_custom_timeout(self) -> None:
        self.store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        h = self.store.agent_health("AGENT:dev:local", timeout=10, now=_ts(50))
        self.assertEqual(h.status, "STALLED")
        h2 = self.store.agent_health("AGENT:dev:local", timeout=10, now=_ts(9))
        self.assertEqual(h2.status, "ALIVE")

    def test_last_mission_and_assignment(self) -> None:
        self.store.heartbeat(
            "AGENT:dev:local",
            mission_id="MISSION:m1",
            assignment_id="ASSIGNMENT:a1",
            occurred_at=_ts(0),
        )
        h = self.store.agent_health("AGENT:dev:local", timeout=300, now=_ts(10))
        self.assertEqual(h.last_mission_id, "MISSION:m1")
        self.assertEqual(h.last_assignment_id, "ASSIGNMENT:a1")

    def test_empty_agent_id_raises(self) -> None:
        with self.assertRaises(AHPError) as ctx:
            self.store.agent_health("")
        self.assertEqual(ctx.exception.code, "INVALID_AGENT")

    def test_negative_timeout_raises(self) -> None:
        self.store.heartbeat("AGENT:dev:local", occurred_at=_ts())
        with self.assertRaises(AHPError) as ctx:
            self.store.agent_health("AGENT:dev:local", timeout=-1)
        self.assertEqual(ctx.exception.code, "INVALID_TIMEOUT")

    def test_age_clamped_to_zero_when_future_heartbeat(self) -> None:
        self.store.heartbeat("AGENT:dev:local", occurred_at=_ts(100))
        h = self.store.agent_health("AGENT:dev:local", timeout=0, now=_ts(100))
        self.assertEqual(h.status, "ALIVE")
        self.assertAlmostEqual(h.age_seconds, 0.0, places=1)


class TestMissionHealth(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = HealthStore(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mission_agents_empty_when_no_pese(self) -> None:
        agents = self.store.mission_agents("MISSION:nope")
        self.assertEqual(agents, ())

    def test_check_stalled_empty_when_all_alive(self) -> None:
        agents = self.store.check_stalled("MISSION:nope", timeout=300, now=_ts())
        self.assertEqual(agents, ())


class TestValidation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_validate_passes_empty_dir(self) -> None:
        store = HealthStore(self.root)
        self.assertTrue(store.validate())

    def test_validate_passes_valid_chain(self) -> None:
        store = HealthStore(self.root)
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(10))
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(20))
        self.assertTrue(store.validate())

    def test_validate_fails_broken_chain(self) -> None:
        store = HealthStore(self.root)
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(10))
        # Tamper: overwrite last hash
        path = store._journal_path("AGENT:dev:local")
        lines = path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["note"] = "tampered"
        lines[1] = json.dumps(record, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        self.assertFalse(store.validate())

    def test_validate_fails_malformed_json(self) -> None:
        store = HealthStore(self.root)
        store.heartbeat("AGENT:dev:local", occurred_at=_ts())
        path = store._journal_path("AGENT:dev:local")
        path.write_text("NOT JSON\n", encoding="utf-8")
        self.assertFalse(store.validate())

    def test_validate_fails_sequence_gap(self) -> None:
        store = HealthStore(self.root)
        path = store.agents_dir
        path.mkdir(parents=True, exist_ok=True)
        journal = path / "AGENT%3Adev%3Alocal.jsonl"
        r1 = {
            "format": "AHP/v1.0",
            "kind": "heartbeat",
            "sequence": 1,
            "agent_id": "AGENT:dev:local",
            "mission_id": None,
            "assignment_id": None,
            "occurred_at": _ts(0),
            "note": None,
            "previous_heartbeat_sha256": None,
        }
        r1["heartbeat_sha256"] = _record_hash(r1)
        # Skip sequence 2
        r3 = {
            "format": "AHP/v1.0",
            "kind": "heartbeat",
            "sequence": 3,
            "agent_id": "AGENT:dev:local",
            "mission_id": None,
            "assignment_id": None,
            "occurred_at": _ts(10),
            "note": None,
            "previous_heartbeat_sha256": r1["heartbeat_sha256"],
        }
        r3["heartbeat_sha256"] = _record_hash(r3)
        journal.write_text(
            json.dumps(r1, sort_keys=True, separators=(",", ":"))
            + "\n"
            + json.dumps(r3, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        self.assertFalse(store.validate())

    def test_validate_detects_hash_mismatch(self) -> None:
        store = HealthStore(self.root)
        store.heartbeat("AGENT:dev:local", occurred_at=_ts(0))
        # Tamper the record content but not the hash
        path = store._journal_path("AGENT:dev:local")
        lines = path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["note"] = "tampered"
        lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        self.assertFalse(store.validate())

    def test_validate_multiple_agents(self) -> None:
        store = HealthStore(self.root)
        store.heartbeat("AGENT:a:local", occurred_at=_ts(0))
        store.heartbeat("AGENT:b:local", occurred_at=_ts(10))
        store.heartbeat("AGENT:a:local", occurred_at=_ts(20))
        self.assertTrue(store.validate())


if __name__ == "__main__":
    unittest.main()
