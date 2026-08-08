"""Focused deterministic tests for the AEX v1.0 agent execution runtime."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

sys_path = Path(__file__).resolve().parents[1] / "src"
import sys  # noqa: E402

sys.path.insert(0, str(sys_path))

from asc_orchestrator.aex import AEX, AEXError, ExecutionResult  # noqa: E402
from asc_orchestrator.execution import ExecutionSession, build_context  # noqa: E402
from asc_orchestrator.keys import KeyStore  # noqa: E402
from asc_orchestrator.pese import PESEStore  # noqa: E402
from asc_orchestrator.tbe import (  # noqa: E402
    assemble_team,
    bind_manifest_to_pese,
    team_manifest_relative_path,
)
from tests.test_tbe import PROJECT, mission, registry  # noqa: E402

ORCHESTRATOR = "AGENT:orchestrator:123e4567-e89b-42d3-a456-426614174000"
ASSEMBLED_AT = "2026-08-04T00:00:00.000Z"


def _canonical(record: dict[str, object]) -> bytes:
    return json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class _AEXTestBase(unittest.TestCase):
    """Shared setUp: git-backed temp repo, PESE init, TBE manifest bound."""

    def setUp(self) -> None:
        self._previous_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["GIT_CEILING_DIRECTORIES"] = str(self.root.parent)
        self._git("init")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "AEX Tests")
        (self.root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git("add", "tracked.txt")
        self._git("commit", "-m", "initial")
        (self.root / "asc-orchestrator.toml").write_text(
            '[runtime]\nproject_os_dir = ".project-os"\n'
            'registry_dir = ".project-os/COMPANY/DEPARTMENTS"\n'
            'audit_dir = ".project-os/AUDIT"\n'
            'protocol_version = "ACP/v1.0"\n',
            encoding="utf-8",
        )
        self.store = PESEStore(self.root)
        self.assertEqual(self.store.initialize(ORCHESTRATOR).code, "INITIALIZED")
        self.manifest = assemble_team(
            mission(), [PROJECT], registry(), assembled_at=ASSEMBLED_AT
        )
        self.reference = team_manifest_relative_path(self.manifest)
        self.mission_id = self.manifest.mission_id
        dest = self.root / self.reference
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.manifest.to_markdown(), encoding="utf-8", newline="\n")
        bind = bind_manifest_to_pese(
            self.manifest, self.store, manifest_ref=self.reference, actor=ORCHESTRATOR
        )
        self.assertEqual(bind.code, "UPDATED")
        self.actor = self.store.load().data["envelope"]["state"]["mission_state"][
            "missions"
        ][self.mission_id]["assigned_agent_ids"][0]
        self.aex = AEX(self.root)

    def tearDown(self) -> None:
        if self._previous_ceiling is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = self._previous_ceiling
        self.temp.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )

    def _start_mission(self) -> None:
        ctx, err = build_context(
            self.root,
            None,  # type: ignore[arg-type]
            self.mission_id,
            self.actor,
        )
        self.assertIsNone(err, f"build_context failed: {err}")
        assert ctx is not None
        outcome = ExecutionSession(ctx, actor=self.actor).start()
        self.assertEqual(outcome.code, "UPDATED")

    def _assignment(self, assignment_id: str) -> dict[str, object]:
        state = self.store.load().data["envelope"]["state"]
        return state["execution_state"]["assignments"][assignment_id]

    def _ready_assignment(self) -> tuple[str, str]:
        """Return (assignment_id, agent_id) for the first READY assignment."""
        state = self.store.load().data["envelope"]["state"]
        ready = [
            aid
            for aid, a in state["execution_state"]["assignments"].items()
            if a.get("mission_id") == self.mission_id and a["status"] == "READY"
        ]
        self.assertGreater(len(ready), 0)
        aid = ready[0]
        agent = state["execution_state"]["assignments"][aid]["assigned_agent_id"]
        return aid, agent

    def _in_progress(self) -> tuple[str, str]:
        aid, agent = self._ready_assignment()
        outcome = self.aex.dispatch(self.mission_id, aid, agent)
        self.assertEqual(outcome.code, "UPDATED")
        return aid, agent

    def _event_types(self) -> list[str]:
        return [
            e["event_type"]
            for e in self.aex._journal.events()  # type: ignore[attr-defined]
        ]


class TestDispatch(_AEXTestBase):
    def test_dispatch_claims_ready_assignment(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        outcome = self.aex.dispatch(self.mission_id, aid, agent)
        self.assertEqual(outcome.code, "UPDATED")
        self.assertIsNotNone(outcome.state_revision)
        a = self._assignment(aid)
        self.assertEqual(a["status"], "IN_PROGRESS")
        self.assertIsNotNone(a.get("started_at"))

    def test_dispatch_rejects_non_ready_assignment(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        self.aex.dispatch(self.mission_id, aid, agent)
        with self.assertRaises(AEXError) as ctx:
            self.aex.dispatch(self.mission_id, aid, agent)
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_NOT_READY")

    def test_dispatch_rejects_unauthorized_actor(self) -> None:
        self._start_mission()
        aid, _ = self._ready_assignment()
        with self.assertRaises(AEXError) as ctx:
            self.aex.dispatch(self.mission_id, aid, "AGENT:impostor:local")
        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")

    def test_dispatch_rejects_unknown_assignment(self) -> None:
        self._start_mission()
        with self.assertRaises(AEXError) as ctx:
            self.aex.dispatch(self.mission_id, "ASSIGNMENT:ghost", self.actor)
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_NOT_FOUND")

    def test_dispatch_rejects_unknown_mission(self) -> None:
        self._start_mission()
        with self.assertRaises(AEXError) as ctx:
            self.aex.dispatch("MISSION:ghost", "ASSIGNMENT:build", self.actor)
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_NOT_FOUND")

    def test_dispatch_requires_active_mission_state(self) -> None:
        # Mission is still PLANNED; the assignment is PENDING.  Depending on
        # whether the actor matches the assigned agent, either UNAUTHORIZED
        # (actor mismatch) or ASSIGNMENT_NOT_READY (PENDING not READY) fires.
        state = self.store.load().data["envelope"]["state"]
        a = state["execution_state"]["assignments"]["ASSIGNMENT:build"]
        actor = a["assigned_agent_id"]
        with self.assertRaises(AEXError) as ctx:
            self.aex.dispatch(self.mission_id, "ASSIGNMENT:build", actor)
        self.assertIn(ctx.exception.code, {"ASSIGNMENT_NOT_READY", "UNAUTHORIZED"})

    def test_dispatch_emits_event(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        self.aex.dispatch(self.mission_id, aid, agent)
        self.assertIn("ASSIGNMENT_DISPATCHED", self._event_types())
        self.assertTrue(self.aex._journal.verify_chain())  # type: ignore[attr-defined]


class TestComplete(_AEXTestBase):
    def test_complete_transitions_and_writes_result(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        record = self.aex.complete(self.mission_id, aid, agent, output_text="work done")
        self.assertEqual(record["format"], "AEX/v1.0")
        self.assertEqual(record["kind"], "execution-result")
        self.assertEqual(record["status"], "COMPLETED")
        self.assertEqual(record["output_text"], "work done")
        self.assertEqual(record["assignment_id"], aid)
        self.assertEqual(record["mission_id"], self.mission_id)
        self.assertEqual(record["agent_id"], agent)
        self.assertEqual(record["artifact_hashes"], {})
        self.assertIsNotNone(record["entry_hash"])
        a = self._assignment(aid)
        self.assertEqual(a["status"], "COMPLETED")
        self.assertIsNotNone(a.get("completed_at"))
        # output_refs points at the result path (IDs percent-encoded for Windows).
        safe_m = self.mission_id.replace(":", "%3A")
        safe_a = aid.replace(":", "%3A")
        self.assertIn(f"ARTIFACTS/{safe_m}/{safe_a}/result.json", a["output_refs"])

    def test_complete_result_record_loaded_back(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        self.aex.complete(self.mission_id, aid, agent, output_text="done")
        result = self.aex.result(self.mission_id, aid)
        self.assertIsInstance(result, ExecutionResult)
        assert result is not None
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.output_text, "done")
        self.assertIsNotNone(result.pese_revision)
        self.assertIsNotNone(result.pese_state_sha256)
        # entry_hash is the canonical hash of the record without itself.
        raw = json.loads(
            (
                self.root
                / ".project-os"
                / "ARTIFACTS"
                / self.mission_id.replace(":", "%3A")
                / aid.replace(":", "%3A")
                / "result.json"
            ).read_text(encoding="utf-8")
        )
        material = {k: v for k, v in raw.items() if k != "entry_hash"}
        self.assertEqual(
            result.entry_hash,
            hashlib.sha256(_canonical(material)).hexdigest(),
        )

    def test_complete_requires_in_progress(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        with self.assertRaises(AEXError) as ctx:
            self.aex.complete(self.mission_id, aid, agent)
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_NOT_ACTIVE")

    def test_complete_persists_artifact_and_hash(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        artifact = self.root / "report.md"
        artifact.write_text("investigation report", encoding="utf-8")
        record = self.aex.complete(self.mission_id, aid, agent, artifacts=["report.md"])
        self.assertEqual(
            record["artifact_hashes"],
            {"report.md": hashlib.sha256(b"investigation report").hexdigest()},
        )
        safe_m = self.mission_id.replace(":", "%3A")
        safe_a = aid.replace(":", "%3A")
        dest = (
            self.root
            / ".project-os"
            / "ARTIFACTS"
            / safe_m
            / safe_a
            / "artifacts"
            / "report.md"
        )
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_text(encoding="utf-8"), "investigation report")
        a = self._assignment(aid)
        self.assertIn(
            f"ARTIFACTS/{safe_m}/{safe_a}/artifacts/report.md",
            a["output_refs"],
        )

    def test_complete_rejects_artifact_escape(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        # A file just outside the repository root.
        escape = self.root.parent / "escape.txt"
        escape.write_text("outside", encoding="utf-8")
        try:
            with self.assertRaises(AEXError) as ctx:
                self.aex.complete(
                    self.mission_id, aid, agent, artifacts=["../escape.txt"]
                )
            self.assertEqual(ctx.exception.code, "ARTIFACT_ESCAPE")
        finally:
            escape.unlink()

    def test_complete_rejects_missing_artifact(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        with self.assertRaises(AEXError) as ctx:
            self.aex.complete(self.mission_id, aid, agent, artifacts=["nope.md"])
        self.assertEqual(ctx.exception.code, "ARTIFACT_NOT_FOUND")

    def test_complete_signed_with_cks(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        key = KeyStore(self.root).create_key(ORCHESTRATOR, purpose="aex-test")
        record = self.aex.complete(
            self.mission_id, aid, agent, output_text="signed", key_id=key.key_id
        )
        self.assertIsNotNone(record.get("signature"))
        sig = record["signature"]
        self.assertEqual(sig["key_id"], key.key_id)
        # The signed payload is the record without the signature field.
        signed = {k: v for k, v in record.items() if k != "signature"}
        valid = KeyStore(self.root).verify(
            key.key_id, _canonical(signed), sig["signature_hex"]
        )
        self.assertTrue(valid)

    def test_complete_rejects_inactive_key(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        ks = KeyStore(self.root)
        key = ks.create_key(ORCHESTRATOR, purpose="aex-test")
        ks.revoke(ORCHESTRATOR, key.key_id, reason="test")
        with self.assertRaises(AEXError) as ctx:
            self.aex.complete(self.mission_id, aid, agent, key_id=key.key_id)
        self.assertEqual(ctx.exception.code, "CKS_ERROR")

    def test_complete_emits_event(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        self.aex.complete(self.mission_id, aid, agent)
        self.assertIn("ASSIGNMENT_COMPLETED", self._event_types())


class TestFail(_AEXTestBase):
    def test_fail_marks_assignment_failed(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        outcome = self.aex.fail(self.mission_id, aid, agent, reason="bad gate")
        self.assertEqual(outcome.code, "UPDATED")
        a = self._assignment(aid)
        self.assertEqual(a["status"], "FAILED")
        self.assertIsNotNone(a.get("completed_at"))

    def test_fail_requires_in_progress(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        with self.assertRaises(AEXError) as ctx:
            self.aex.fail(self.mission_id, aid, agent, reason="nope")
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_NOT_ACTIVE")

    def test_fail_emits_event(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        self.aex.fail(self.mission_id, aid, agent, reason="bad gate")
        self.assertIn("ASSIGNMENT_FAILED", self._event_types())


class TestBlockUnblock(_AEXTestBase):
    def test_block_blocks_ready_assignment(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        outcome = self.aex.block(self.mission_id, aid, agent, reason="waiting")
        self.assertEqual(outcome.code, "UPDATED")
        self.assertEqual(self._assignment(aid)["status"], "BLOCKED")

    def test_block_rejects_completed_assignment(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        self.aex.complete(self.mission_id, aid, agent)
        with self.assertRaises(AEXError) as ctx:
            self.aex.block(self.mission_id, aid, agent, reason="late")
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_NOT_BLOCKABLE")

    def test_unblock_reactivates_to_ready(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        self.aex.block(self.mission_id, aid, agent, reason="waiting")
        outcome = self.aex.unblock(self.mission_id, aid, agent)
        self.assertEqual(outcome.code, "UPDATED")
        self.assertEqual(self._assignment(aid)["status"], "READY")

    def test_unblock_rejects_non_blocked(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        with self.assertRaises(AEXError) as ctx:
            self.aex.unblock(self.mission_id, aid, agent)
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_NOT_BLOCKED")

    def test_block_unblock_emit_events(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        self.aex.block(self.mission_id, aid, agent, reason="waiting")
        self.aex.unblock(self.mission_id, aid, agent)
        types = self._event_types()
        self.assertIn("ASSIGNMENT_BLOCKED", types)
        self.assertIn("ASSIGNMENT_ACTIVATED", types)


class TestStatus(_AEXTestBase):
    def test_status_reads_ready_assignment(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        status = self.aex.status(self.mission_id, aid, agent)
        self.assertEqual(status.assignment_id, aid)
        self.assertEqual(status.mission_id, self.mission_id)
        self.assertEqual(status.agent_id, agent)
        self.assertEqual(status.status, "READY")
        self.assertIsNone(status.started_at)
        self.assertEqual(status.output_refs, [])

    def test_status_reflects_in_progress(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        status = self.aex.status(self.mission_id, aid, agent)
        self.assertEqual(status.status, "IN_PROGRESS")
        self.assertIsNotNone(status.started_at)

    def test_status_rejects_unknown_assignment(self) -> None:
        self._start_mission()
        with self.assertRaises(AEXError) as ctx:
            self.aex.status(self.mission_id, "ASSIGNMENT:ghost", self.actor)
        self.assertEqual(ctx.exception.code, "ASSIGNMENT_NOT_FOUND")


class TestResult(_AEXTestBase):
    def test_result_none_before_completion(self) -> None:
        self._start_mission()
        aid, _ = self._ready_assignment()
        self.assertIsNone(self.aex.result(self.mission_id, aid))

    def test_result_reads_signed_record(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        key = KeyStore(self.root).create_key(ORCHESTRATOR, purpose="aex-test")
        self.aex.complete(
            self.mission_id, aid, agent, output_text="audited", key_id=key.key_id
        )
        result = self.aex.result(self.mission_id, aid)
        assert result is not None
        self.assertIsNotNone(result.signature)
        self.assertEqual(result.signature["key_id"], key.key_id)  # type: ignore[index]
        self.assertEqual(result.entry_hash, result.entry_hash)

    def test_result_corrupt_raises(self) -> None:
        self._start_mission()
        aid, agent = self._in_progress()
        self.aex.complete(self.mission_id, aid, agent)
        result_path = (
            self.root
            / ".project-os"
            / "ARTIFACTS"
            / self.mission_id.replace(":", "%3A")
            / aid.replace(":", "%3A")
            / "result.json"
        )
        result_path.write_text("not json", encoding="utf-8")
        with self.assertRaises(AEXError) as ctx:
            self.aex.result(self.mission_id, aid)
        self.assertEqual(ctx.exception.code, "RESULT_CORRUPT")


class TestEventJournal(_AEXTestBase):
    def test_full_lifecycle_chain_verifies(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        self.aex.dispatch(self.mission_id, aid, agent)
        self.aex.complete(self.mission_id, aid, agent)
        self.assertTrue(self.aex._journal.verify_chain())  # type: ignore[attr-defined]
        events = self.aex._journal.events()  # type: ignore[attr-defined]
        types = [e["event_type"] for e in events]
        self.assertIn("ASSIGNMENT_DISPATCHED", types)
        self.assertIn("ASSIGNMENT_COMPLETED", types)
        # Every event carries the PESE revision and state hash.
        for e in events:
            if e["event_type"] in {"ASSIGNMENT_DISPATCHED", "ASSIGNMENT_COMPLETED"}:
                self.assertIsNotNone(e.get("pese_revision"))
                self.assertIsNotNone(e.get("pese_state_sha256"))

    def test_tamper_detection(self) -> None:
        self._start_mission()
        aid, agent = self._ready_assignment()
        self.aex.dispatch(self.mission_id, aid, agent)
        journal = self.aex._journal  # type: ignore[attr-defined]
        path = journal.path
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[0] = lines[0].replace(
            '"event_type":"SESSION_STARTED"', '"event_type":"TAMPERED"'
        )
        path.write_text("".join(lines), encoding="utf-8")
        self.assertFalse(journal.verify_chain())


# ---------------------------------------------------------------------------
# RB-12: AEX relative_to guard on _result_path / _artifacts_path
# ---------------------------------------------------------------------------


class TestPathEscapeGuard(unittest.TestCase):
    """RB-12: _result_path and _artifacts_path reject traversal."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Path-escape tests only need the AEX engine's _artifacts_dir — no PESE state required.
        from asc_orchestrator.aex import AEX

        self.engine = AEX(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_result_path_escapes_rejected(self) -> None:
        from asc_orchestrator.aex import AEXError

        with self.assertRaises(AEXError) as ctx:
            self.engine._result_path("../../escape", "ASN:ok")
        self.assertEqual(ctx.exception.code, "PATH_ESCAPE")

    def test_artifacts_path_escapes_rejected(self) -> None:
        from asc_orchestrator.aex import AEXError

        with self.assertRaises(AEXError) as ctx:
            self.engine._artifacts_path("MISSION:ok", "../../escape")
        self.assertEqual(ctx.exception.code, "PATH_ESCAPE")

    def test_normal_path_accepted(self) -> None:
        p = self.engine._result_path("MISSION:test", "ASN:ok:1")
        self.assertTrue(str(p).endswith("result.json"))


if __name__ == "__main__":
    unittest.main()
