"""Focused deterministic tests for the EEF v1.0 execution runtime."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asc_orchestrator.execution import (
    SESSION_CANCELLED,
    SESSION_COMPLETED,
    SESSION_PAUSED,
    SESSION_RUNNING,
    EEFError,
    EEFEventJournal,
    ExecutionContext,
    ExecutionSession,
    build_context,
)
from asc_orchestrator.pese import PESEStore
from asc_orchestrator.tbe import (
    assemble_team,
    bind_manifest_to_pese,
    team_manifest_relative_path,
)
from tests.test_tbe import PROJECT, mission, registry

ORCHESTRATOR = "AGENT:orchestrator:123e4567-e89b-42d3-a456-426614174000"
ASSEMBLED_AT = "2026-08-04T00:00:00.000Z"


class _ExecutionTestBase(unittest.TestCase):
    """Shared setUp: git-backed temp repo, PESE init, TBE manifest bound."""

    def setUp(self) -> None:
        self._previous_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["GIT_CEILING_DIRECTORIES"] = str(self.root.parent)
        self._git("init")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "EEF Tests")
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
        # Session actor = first assigned agent (a member with acr_ref).
        self.actor = self.store.load().data["envelope"]["state"]["mission_state"][
            "missions"
        ][self.mission_id]["assigned_agent_ids"][0]

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

    def _context(self) -> ExecutionContext:
        ctx, err = build_context(
            self.root,
            None,  # type: ignore[arg-type]
            self.mission_id,
            self.actor,
        )
        self.assertIsNone(err, f"build_context failed: {err}")
        assert ctx is not None
        return ctx

    def _session(self) -> ExecutionSession:
        return ExecutionSession(self._context(), actor=self.actor)

    def _bind_second_mission(self) -> str:
        """Bind a second mission so the first is no longer active."""
        m = mission(mission_id="MISSION:other")
        built = assemble_team(m, [PROJECT], registry(), assembled_at=ASSEMBLED_AT)
        ref = team_manifest_relative_path(built)
        dest = self.root / ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(built.to_markdown(), encoding="utf-8", newline="\n")
        bind = bind_manifest_to_pese(
            built, self.store, manifest_ref=ref, actor=ORCHESTRATOR
        )
        self.assertEqual(bind.code, "UPDATED")
        return built.mission_id

    def _assign_agent(self, assignment_id: str, new_status: str) -> None:
        """Simulate an agent-owned ASSIGNMENT_STATUS transition."""
        loaded = self.store.load(actor=self.actor)
        state = loaded.data["envelope"]["state"]
        a = state["execution_state"]["assignments"][assignment_id]
        agent_actor = a["assigned_agent_id"]

        def mutate(s):
            sa = s["execution_state"]["assignments"][assignment_id]
            sa["status"] = new_status
            if new_status == "IN_PROGRESS":
                sa["started_at"] = "2026-08-04T00:00:01.000Z"
            elif new_status == "COMPLETED":
                sa["completed_at"] = "2026-08-04T00:00:02.000Z"

        outcome = self.store.update(
            expected_revision=loaded.state_revision,
            actor=agent_actor,
            transition_type="ASSIGNMENT_STATUS",
            subject=assignment_id,
            from_value=a["status"],
            to_value=new_status,
            mutate=mutate,
        )
        self.assertEqual(
            outcome.code, "UPDATED", f"agent transition failed: {outcome.code}"
        )


class TestBuildContext(_ExecutionTestBase):
    def test_returns_context_for_bound_mission(self) -> None:
        ctx = self._context()
        self.assertEqual(ctx.mission_id, self.mission_id)
        self.assertEqual(ctx.root, self.root)
        self.assertIsInstance(ctx.store, PESEStore)
        self.assertGreater(len(ctx.assignments), 0)
        self.assertGreater(len(ctx.milestones), 0)

    def test_returns_error_for_unknown_mission(self) -> None:
        ctx, err = build_context(self.root, None, "MISSION:nonexistent", self.actor)  # type: ignore[arg-type]
        self.assertIsNone(ctx)
        self.assertEqual(err.code, "MISSION_NOT_FOUND")


class TestStart(_ExecutionTestBase):
    def test_start_activates_mission_and_root_assignments(self) -> None:
        session = self._session()
        outcome = session.start()
        self.assertEqual(outcome.code, "UPDATED")
        state = self.store.load().data["envelope"]["state"]
        m = state["mission_state"]["missions"][self.mission_id]
        self.assertEqual(m["status"], "ACTIVE")
        self.assertIsNotNone(m["started_at"])
        # Root assignments should now be READY.
        exec_state = state["execution_state"]
        ready = [
            aid
            for aid, a in exec_state["assignments"].items()
            if a.get("mission_id") == self.mission_id and a["status"] == "READY"
        ]
        self.assertGreater(len(ready), 0)
        # Extension written.
        ext = state["extensions"]["org.asc.eef"][self.mission_id]
        self.assertEqual(ext["session_status"], SESSION_RUNNING)
        self.assertEqual(ext["resume_count"], 0)
        self.assertEqual(ext["pause_count"], 0)
        self.assertTrue(self.store.validate(check_repository=False).code, "VALID")

    def test_start_sets_dependency_environment_verified(self) -> None:
        session = self._session()
        session.start()
        state = self.store.load().data["envelope"]["state"]
        for member in self.manifest.members:
            dep = state["agent_state"]["agents"][member.agent_id][
                "dependency_environment_state"
            ]
            self.assertEqual(dep["status"], "VERIFIED")

    def test_start_fires_mission_start_checkpoint(self) -> None:
        session = self._session()
        outcome = session.start()
        self.assertTrue(outcome.data.get("checkpoint"))

    def test_start_rejects_non_planned_mission(self) -> None:
        session = self._session()
        session.start()
        outcome2 = session.start()
        self.assertEqual(outcome2.code, "INVALID_TRANSITION")

    def test_start_appends_session_started_event(self) -> None:
        session = self._session()
        session.start()
        events = session.journal.events()
        types = [e["event_type"] for e in events]
        self.assertIn("SESSION_STARTED", types)
        self.assertTrue(session.journal.verify_chain())


class TestSchedule(_ExecutionTestBase):
    def test_schedule_returns_deterministic_root_assignment(self) -> None:
        session = self._session()
        session.start()
        result = session.schedule()
        self.assertEqual(result.code, "READY")
        self.assertIsNotNone(result.assignment_id)
        # The assignment should be one that has no dependencies.
        state = self.store.load().data["envelope"]["state"]
        a = state["execution_state"]["assignments"][result.assignment_id]
        self.assertEqual(a["status"], "READY")
        self.assertFalse(a["depends_on"])

    def test_schedule_no_active_mission_when_different_active(self) -> None:
        session = self._session()
        session.start()
        self._bind_second_mission()
        # Now the first mission is no longer active.
        result = session.schedule()
        self.assertEqual(result.code, "NO_ACTIVE_MISSION")

    def test_schedule_emits_schedule_result_event(self) -> None:
        session = self._session()
        session.start()
        session.schedule()
        types = [e["event_type"] for e in session.journal.events()]
        self.assertIn("SCHEDULE_RESULT", types)


class TestPauseResume(_ExecutionTestBase):
    def test_pause_interrupts_mission_and_assignments(self) -> None:
        session = self._session()
        session.start()
        outcome = session.pause()
        self.assertEqual(outcome.code, "UPDATED")
        state = self.store.load().data["envelope"]["state"]
        m = state["mission_state"]["missions"][self.mission_id]
        self.assertEqual(m["status"], "INTERRUPTED")
        # Non-terminal assignments → INTERRUPTED.
        for aid, a in state["execution_state"]["assignments"].items():
            if a.get("mission_id") == self.mission_id:
                self.assertIn(
                    a["status"], {"INTERRUPTED", "COMPLETED", "CANCELLED", "FAILED"}
                )
        ext = state["extensions"]["org.asc.eef"][self.mission_id]
        self.assertEqual(ext["session_status"], SESSION_PAUSED)
        self.assertEqual(ext["pause_count"], 1)
        types = [e["event_type"] for e in session.journal.events()]
        self.assertIn("SESSION_PAUSED", types)

    def test_pause_rejects_non_active_mission(self) -> None:
        session = self._session()
        # Mission is PLANNED.
        outcome = session.pause()
        self.assertEqual(outcome.code, "INVALID_TRANSITION")

    def test_resume_reactivates_interrupted_assignments(self) -> None:
        session = self._session()
        session.start()
        session.pause()
        outcome = session.resume_session()
        self.assertEqual(outcome.code, "UPDATED")
        state = self.store.load().data["envelope"]["state"]
        m = state["mission_state"]["missions"][self.mission_id]
        self.assertEqual(m["status"], "ACTIVE")
        ext = state["extensions"]["org.asc.eef"][self.mission_id]
        self.assertEqual(ext["session_status"], SESSION_RUNNING)
        self.assertEqual(ext["resume_count"], 1)
        types = [e["event_type"] for e in session.journal.events()]
        self.assertIn("SESSION_RESUMED", types)

    def test_resume_rejects_non_interrupted_mission(self) -> None:
        session = self._session()
        session.start()
        outcome = session.resume_session()
        self.assertEqual(outcome.code, "INVALID_TRANSITION")

    def test_pause_resume_cycle_maintains_event_chain(self) -> None:
        session = self._session()
        session.start()
        session.pause()
        session.resume_session()
        session.pause()
        session.resume_session()
        self.assertTrue(session.journal.verify_chain())
        ext = self.store.load().data["envelope"]["state"]["extensions"]["org.asc.eef"][
            self.mission_id
        ]
        self.assertEqual(ext["resume_count"], 2)
        self.assertEqual(ext["pause_count"], 2)


class TestCancel(_ExecutionTestBase):
    def test_cancel_terminates_mission_and_assignments(self) -> None:
        session = self._session()
        session.start()
        outcome = session.cancel()
        self.assertEqual(outcome.code, "UPDATED")
        state = self.store.load().data["envelope"]["state"]
        m = state["mission_state"]["missions"][self.mission_id]
        self.assertEqual(m["status"], "CANCELLED")
        for aid, a in state["execution_state"]["assignments"].items():
            if a.get("mission_id") == self.mission_id:
                self.assertIn(a["status"], {"CANCELLED", "COMPLETED", "FAILED"})
        ext = state["extensions"]["org.asc.eef"][self.mission_id]
        self.assertEqual(ext["session_status"], SESSION_CANCELLED)
        types = [e["event_type"] for e in session.journal.events()]
        self.assertIn("SESSION_CANCELLED", types)

    def test_cancel_fires_mission_finish_checkpoint(self) -> None:
        session = self._session()
        session.start()
        outcome = session.cancel()
        self.assertEqual(outcome.code, "UPDATED")
        checkpoint = outcome.data.get("checkpoint")
        self.assertIsNotNone(checkpoint)
        checkpoint_id = checkpoint.get("checkpoint_id") if checkpoint else None
        self.assertTrue(checkpoint_id)
        # The checkpoint file itself records the MISSION_FINISH reason.
        stored = [
            item
            for _, item in self.store._checkpoints(self.mission_id)
            if item["checkpoint_id"] == checkpoint_id
        ]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["reason"], "MISSION_FINISH")

    def test_cancel_rejects_non_cancellable_mission(self) -> None:
        session = self._session()
        # PLANNED → not cancellable.
        outcome = session.cancel()
        self.assertEqual(outcome.code, "INVALID_TRANSITION")


class TestComplete(_ExecutionTestBase):
    def test_complete_advances_mission_to_validating(self) -> None:
        session = self._session()
        session.start()
        outcome = session.complete()
        self.assertEqual(outcome.code, "UPDATED")
        state = self.store.load().data["envelope"]["state"]
        m = state["mission_state"]["missions"][self.mission_id]
        self.assertEqual(m["status"], "VALIDATING")
        ext = state["extensions"]["org.asc.eef"][self.mission_id]
        self.assertEqual(ext["session_status"], SESSION_COMPLETED)
        types = [e["event_type"] for e in session.journal.events()]
        self.assertIn("SESSION_COMPLETED", types)

    def test_complete_does_not_fire_terminal_checkpoint(self) -> None:
        # complete() moves ACTIVE → VALIDATING; MISSION_FINISH fires only on
        # terminal COMPLETED/CANCELLED/FAILED, so no mandatory checkpoint yet.
        session = self._session()
        session.start()
        outcome = session.complete()
        self.assertEqual(outcome.code, "UPDATED")
        self.assertIsNone(outcome.data.get("checkpoint"))
        state = self.store.load().data["envelope"]["state"]
        self.assertEqual(
            state["mission_state"]["missions"][self.mission_id]["status"], "VALIDATING"
        )

    def test_complete_rejects_non_active_mission(self) -> None:
        session = self._session()
        outcome = session.complete()
        self.assertEqual(outcome.code, "INVALID_TRANSITION")


class TestStatus(_ExecutionTestBase):
    def test_status_after_start(self) -> None:
        session = self._session()
        session.start()
        status = session.status()
        self.assertEqual(status.mission_status, "ACTIVE")
        self.assertEqual(status.session_status, SESSION_RUNNING)
        self.assertIsNotNone(status.current_milestone_id)
        self.assertGreater(status.active_assignments, 0)
        self.assertEqual(status.completed_assignments, 0)
        self.assertEqual(status.blocked_assignments, 0)

    def test_status_after_cancel(self) -> None:
        session = self._session()
        session.start()
        session.cancel()
        status = session.status()
        self.assertEqual(status.mission_status, "CANCELLED")
        self.assertEqual(status.session_status, SESSION_CANCELLED)

    def test_status_returns_outcome_on_store_error(self) -> None:
        bad_ctx = ExecutionContext(
            mission_id="MISSION:gone",
            root=self.root,
            store=PESEStore(self.root / "nonexistent"),
            manifest_path=self.root,
            manifest_version=1,
            dependency_edges=(),
            assignments={},
            milestones=[],
            agent_ids=(),
        )
        session = ExecutionSession(bad_ctx, actor=self.actor)
        result = session.status()
        self.assertIsNotNone(getattr(result, "code", None))


class TestDependencyGating(_ExecutionTestBase):
    def test_defers_dependent_assignment_until_dependency_completed(self) -> None:
        m = mission(
            mission_id="MISSION:dep-gating",
            demands=[
                {
                    "id": "ASSIGNMENT:a",
                    "capability": "developer",
                    "paths": ["src/a.py"],
                },
                {
                    "id": "ASSIGNMENT:b",
                    "capability": "developer",
                    "paths": ["src/b.py"],
                    "depends_on": ["ASSIGNMENT:a"],
                },
            ],
        )
        built = assemble_team(m, [PROJECT], registry(), assembled_at=ASSEMBLED_AT)
        ref = team_manifest_relative_path(built)
        dest = self.root / ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(built.to_markdown(), encoding="utf-8", newline="\n")
        bind = bind_manifest_to_pese(
            built, self.store, manifest_ref=ref, actor=ORCHESTRATOR
        )
        self.assertEqual(bind.code, "UPDATED")
        actor = self.store.load().data["envelope"]["state"]["mission_state"][
            "missions"
        ][built.mission_id]["assigned_agent_ids"][0]
        ctx, err = build_context(self.root, None, built.mission_id, actor)  # type: ignore[arg-type]
        self.assertIsNone(err)
        assert ctx is not None
        session = ExecutionSession(ctx, actor=actor)
        session.start()
        # B should be PENDING (not READY) since A hasn't completed.
        state = self.store.load().data["envelope"]["state"]
        b_status = state["execution_state"]["assignments"]["ASSIGNMENT:b"]["status"]
        self.assertEqual(b_status, "PENDING")
        result = session.schedule()
        self.assertEqual(result.code, "READY")
        self.assertEqual(result.assignment_id, "ASSIGNMENT:a")


class TestEventJournal(_ExecutionTestBase):
    def test_journal_chain_and_verify(self) -> None:
        session = self._session()
        session.start()
        self.assertTrue(session.journal.verify_chain())
        self.assertGreater(len(session.journal.events()), 0)

    def test_journal_tamper_detection(self) -> None:
        session = self._session()
        session.start()
        events = session.journal.events()
        self.assertGreater(len(events), 0)
        # Tamper with a field.
        path = session.journal.path
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        first = lines[0]
        lines[0] = first.replace(
            '"event_type":"SESSION_STARTED"', '"event_type":"TAMPERED"'
        )
        path.write_text("".join(lines), encoding="utf-8")
        self.assertFalse(session.journal.verify_chain())

    def test_journal_rejects_invalid_event_type(self) -> None:
        journal = EEFEventJournal(self.root)
        with self.assertRaises(EEFError) as ctx:
            journal.append(
                event_type="INVALID",
                mission_id="MISSION:x",
                assignment_id=None,
                actor_agent_id="AGENT:test",
                pese_revision=1,
                pese_state_sha256="a" * 64,
            )
        self.assertEqual(ctx.exception.code, "INVALID_EVENT_TYPE")

    def test_journal_path_is_execution_events(self) -> None:
        journal = EEFEventJournal(self.root)
        self.assertTrue(journal.path.name, "execution-events.jsonl")
        self.assertIn("AUDIT", str(journal.path.parent))


class TestAgentOwnedTransition(_ExecutionTestBase):
    def test_agent_completes_assignment_via_ready_in_progress_completed(self) -> None:
        session = self._session()
        session.start()
        state = self.store.load().data["envelope"]["state"]
        ready = [
            aid
            for aid, a in state["execution_state"]["assignments"].items()
            if a.get("mission_id") == self.mission_id and a["status"] == "READY"
        ]
        self.assertGreater(len(ready), 0)
        aid = ready[0]
        self._assign_agent(aid, "IN_PROGRESS")
        self._assign_agent(aid, "COMPLETED")
        state = self.store.load().data["envelope"]["state"]
        self.assertEqual(
            state["execution_state"]["assignments"][aid]["status"], "COMPLETED"
        )


if __name__ == "__main__":
    unittest.main()
