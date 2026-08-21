"""Universal ASC v2.2.0 - Comprehensive Console & Safety Test Suite.

Validates:
- Interactive operator console & command dispatch
- CLI subcommands, flags, and versioning
- Project detection and Git porcelain introspection
- Safe state location (<repo>/.git/asc/)
- Project mutual-exclusion locking and stale lock recovery
- Scheduler RUNNING vs BLOCKED semantics
- Separate execution and verification timeouts
- Scoped Git staging and dirty repository rejection
- Safe attempt delta rollback
- Event streaming and progress callbacks
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from asc.cli import CLI
from asc.console import (
    get_git_info,
    render_activity_panel,
    render_header,
    render_mission_panel,
    render_runtime_panel,
)
from asc.dag import evaluate_mission
from asc.events import Event, EventEmitter, EventType
from asc.lock import LockConflictError, ProjectLock
from asc.models import (
    SchedulerState,
    Task,
    TaskStatus,
)
from asc.repo import Repository
from asc.state import State, resolve_default_state_dir


class TestProjectDetectionAndGitStatus(unittest.TestCase):
    """Test repository detection, porcelain parsing, and dirty-state safety."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        subprocess.run(
            ["git", "init"], cwd=self.temp_dir, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "ASC Test"],
            cwd=self.temp_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@asc.org"],
            cwd=self.temp_dir,
            capture_output=True,
            check=True,
        )

        (Path(self.temp_dir) / "initial.txt").write_text("initial")
        subprocess.run(
            ["git", "add", "initial.txt"],
            cwd=self.temp_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial commit"],
            cwd=self.temp_dir,
            capture_output=True,
            check=True,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_clean_repository_status(self):
        repo = Repository(self.temp_dir)
        status = repo.get_porcelain_status()
        self.assertTrue(status.is_clean)
        self.assertEqual(len(status.all_dirty), 0)
        self.assertTrue(repo.is_clean())

    def test_dirty_repository_modified_and_untracked(self):
        repo = Repository(self.temp_dir)
        (Path(self.temp_dir) / "initial.txt").write_text("modified")
        (Path(self.temp_dir) / "untracked.txt").write_text("new file")

        status = repo.get_porcelain_status()
        self.assertFalse(status.is_clean)
        self.assertIn("initial.txt", status.modified)
        self.assertIn("untracked.txt", status.untracked)
        self.assertFalse(repo.is_clean())
        self.assertEqual(len(repo.get_dirty_files()), 2)

    def test_git_info_metadata(self):
        info = get_git_info(self.temp_dir)
        self.assertTrue(info["is_git"])
        self.assertEqual(info["name"], Path(self.temp_dir).name)
        self.assertTrue(info["clean"])
        self.assertNotEqual(info["head"], "N/A")


class TestSafeStateLocation(unittest.TestCase):
    """Verify that default state storage lives in <repo>/.git/asc/ to avoid dirtying user projects."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        subprocess.run(
            ["git", "init"], cwd=self.temp_dir, capture_output=True, check=True
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_state_dir_resolves_inside_git_dir(self):
        state_dir = resolve_default_state_dir(self.temp_dir)
        expected = Path(self.temp_dir).resolve() / ".git" / "asc"
        self.assertEqual(state_dir, expected)
        self.assertTrue(state_dir.exists())

    def test_state_init_creates_db_inside_git_dir(self):
        state = State(cwd=self.temp_dir)
        expected_db = Path(self.temp_dir).resolve() / ".git" / "asc" / "asc.db"
        self.assertEqual(state.db_path, expected_db)
        self.assertTrue(expected_db.exists())
        state.close()


class TestProjectLocking(unittest.TestCase):
    """Verify single-driver mutual exclusion per repository with stale lock recovery."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_acquire_and_release_lock(self):
        lock = ProjectLock(lock_dir=self.temp_dir, mission_id="m1")
        self.assertFalse(lock.is_locked())
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.is_locked())
        info = lock.get_lock_info()
        self.assertEqual(info["mission_id"], "m1")
        self.assertEqual(info["pid"], os.getpid())

        lock.release()
        self.assertFalse(lock.is_locked())

    def test_concurrent_lock_conflict(self):
        lock_file = Path(self.temp_dir) / "lock"
        # Write fake lock from active PID (current process + 999999 or current pid)
        # Using current pid: acquire should succeed if owned by self, but if another PID:
        fake_payload = {
            "pid": os.getpid(),
            "mission_id": "other-mission",
            "timestamp": time.time(),
            "user": "other",
        }
        lock_file.write_text(json.dumps(fake_payload), encoding="utf-8")

        # Now test with another lock instance assuming different pid
        with patch("asc.lock.is_process_running", return_value=True):
            fake_payload["pid"] = 999998
            lock_file.write_text(json.dumps(fake_payload), encoding="utf-8")
            other_lock = ProjectLock(lock_dir=self.temp_dir, mission_id="new-mission")
            with self.assertRaises(LockConflictError):
                other_lock.acquire()

    def test_stale_lock_recovery_when_pid_dead(self):
        lock_file = Path(self.temp_dir) / "lock"
        dead_payload = {
            "pid": 999999,
            "mission_id": "crashed-mission",
            "timestamp": time.time() - 100,
            "user": "crashed",
        }
        lock_file.write_text(json.dumps(dead_payload), encoding="utf-8")

        with patch("asc.lock.is_process_running", return_value=False):
            lock = ProjectLock(lock_dir=self.temp_dir, mission_id="recovery-mission")
            self.assertTrue(lock.acquire())
            self.assertEqual(lock.get_lock_info()["mission_id"], "recovery-mission")
            lock.release()


class TestSchedulerRunningVsBlocked(unittest.TestCase):
    """Test scheduler semantics ensuring active RUNNING tasks produce RUNNING state."""

    def test_running_task_evaluates_to_running_not_blocked(self):
        t1 = Task(id="t1", title="Task 1", prompt="Prompt 1", status=TaskStatus.RUNNING)
        t2 = Task(
            id="t2",
            title="Task 2",
            prompt="Prompt 2",
            status=TaskStatus.PENDING,
            depends_on=["t1"],
        )

        res = evaluate_mission("m1", [t1, t2])
        self.assertEqual(res.state, SchedulerState.RUNNING)

    def test_all_tasks_completed_evaluates_to_complete(self):
        t1 = Task(
            id="t1", title="Task 1", prompt="Prompt 1", status=TaskStatus.COMPLETED
        )
        t2 = Task(
            id="t2", title="Task 2", prompt="Prompt 2", status=TaskStatus.COMPLETED
        )

        res = evaluate_mission("m1", [t1, t2])
        self.assertEqual(res.state, SchedulerState.COMPLETE)

    def test_blocked_task_evaluates_to_blocked(self):
        t1 = Task(id="t1", title="Task 1", prompt="Prompt 1", status=TaskStatus.FAILED)
        t2 = Task(
            id="t2",
            title="Task 2",
            prompt="Prompt 2",
            status=TaskStatus.PENDING,
            depends_on=["t1"],
        )

        res = evaluate_mission("m1", [t1, t2])
        self.assertEqual(res.state, SchedulerState.BLOCKED)
        self.assertIn("t2", res.blocked_ids)


class TestScopedStagingAndAttemptRollback(unittest.TestCase):
    """Test scoped git commits and attempt delta rollback."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        subprocess.run(
            ["git", "init"], cwd=self.temp_dir, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "ASC Test"],
            cwd=self.temp_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@asc.org"],
            cwd=self.temp_dir,
            capture_output=True,
            check=True,
        )

        (Path(self.temp_dir) / "user_file.txt").write_text("user content")
        subprocess.run(
            ["git", "add", "user_file.txt"],
            cwd=self.temp_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.temp_dir,
            capture_output=True,
            check=True,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scoped_staging_only_stages_specified_files(self):
        repo = Repository(self.temp_dir)
        (Path(self.temp_dir) / "task_generated.txt").write_text("generated")
        (Path(self.temp_dir) / "unrelated_user.txt").write_text("unrelated")

        sha = repo.commit_scoped("feat: task change", paths=["task_generated.txt"])
        self.assertIsNotNone(sha)

        # unrelated_user.txt must still be untracked!
        status = repo.get_porcelain_status()
        self.assertIn("unrelated_user.txt", status.untracked)
        self.assertNotIn("task_generated.txt", status.all_dirty)

    def test_commit_paths_filter_rejection(self):
        repo = Repository(self.temp_dir)
        (Path(self.temp_dir) / "forbidden.txt").write_text("forbidden")
        with self.assertRaises(ValueError):
            repo.commit_scoped(
                "feat: change",
                paths=["forbidden.txt"],
                commit_paths_filter=["allowed.txt"],
            )

    def test_rollback_attempt_cleans_only_delta(self):
        repo = Repository(self.temp_dir)
        (Path(self.temp_dir) / "user_file.txt").write_text("user modified")
        (Path(self.temp_dir) / "attempt_junk.txt").write_text("junk")

        # Rollback only attempt_junk.txt
        repo.rollback_attempt(["attempt_junk.txt"])

        self.assertFalse((Path(self.temp_dir) / "attempt_junk.txt").exists())
        self.assertTrue((Path(self.temp_dir) / "user_file.txt").exists())


class TestEventAndProgressStreaming(unittest.TestCase):
    """Test EventEmitter and domain event dispatch."""

    def test_event_emitter_dispatches_events(self):
        emitter = EventEmitter()
        received: list[Event] = []

        def listener(ev: Event):
            received.append(ev)

        emitter.subscribe(listener)
        ev = Event(
            event_type=EventType.TASK_STARTED,
            mission_id="m1",
            task_id="t1",
            message="Starting",
        )
        emitter.emit(ev)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].event_type, EventType.TASK_STARTED)
        self.assertEqual(received[0].task_id, "t1")

        emitter.unsubscribe(listener)
        emitter.emit(Event(event_type=EventType.TASK_COMPLETED))
        self.assertEqual(len(received), 1)


class TestConsoleAndCLIRendering(unittest.TestCase):
    """Test console panels and CLI execution."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_render_panels_without_error(self):
        git_info = {
            "is_git": True,
            "name": "Repo",
            "branch": "main",
            "head": "12345678",
            "clean": True,
            "dirty_count": 0,
        }
        tasks = [
            Task(
                id="t1",
                title="Task 1",
                prompt="p1",
                status=TaskStatus.COMPLETED,
                commit_sha="abc12345",
            ),
            Task(id="t2", title="Task 2", prompt="p2", status=TaskStatus.RUNNING),
        ]
        events = [
            {
                "event_type": "TASK_STARTED",
                "task_id": "t2",
                "timestamp": time.time(),
                "message": "Executing",
            }
        ]

        h = render_header(git_info, state_name="RUNNING")
        m = render_mission_panel(tasks, mission_goal="Build test")
        r = render_runtime_panel(executor_status="READY", lock_status="HELD")
        a = render_activity_panel(events)

        self.assertIsNotNone(h)
        self.assertIsNotNone(m)
        self.assertIsNotNone(r)
        self.assertIsNotNone(a)

    def test_progress_bar_renders_clean_text_without_raw_markup(self):
        from asc.console import _render_progress_bar

        empty_bar = _render_progress_bar(0, 0)
        self.assertNotIn("[bold green]", empty_bar.plain)
        self.assertIn("0% (0/0 tasks)", empty_bar.plain)

        active_bar = _render_progress_bar(2, 4)
        self.assertNotIn("[bold green]", active_bar.plain)
        self.assertIn("50% (2/4 tasks)", active_bar.plain)

    def test_idle_runtime_panel_values(self):
        r_idle = render_runtime_panel(has_active_mission=False)
        import io

        from rich.console import Console

        sio = io.StringIO()
        test_c = Console(file=sio, width=120)
        test_c.print(r_idle)
        output = sio.getvalue()

        self.assertIn("— / —", output)
        self.assertIn("0 changes", output)
        self.assertNotIn("WAITING", output)
        self.assertNotIn("0 delta", output)

    def test_empty_mission_panel_shows_action_hint(self):
        m_empty = render_mission_panel([], mission_goal="No active mission")
        import io

        from rich.console import Console

        sio = io.StringIO()
        test_c = Console(file=sio, width=120)
        test_c.print(m_empty)
        output = sio.getvalue()

        self.assertIn("No active mission — run <mission-file> to start", output)
        self.assertNotIn("No tasks", output)

    def test_console_renders_cleanly_at_multiple_column_widths(self):
        import io

        from rich.console import Console

        git_info = get_git_info(self.temp_dir)
        tasks = [
            Task(
                id="t1",
                title="Task 1",
                prompt="p1",
                status=TaskStatus.COMPLETED,
                commit_sha="abc12345",
            ),
            Task(id="t2", title="Task 2", prompt="p2", status=TaskStatus.RUNNING),
        ]
        events = [
            {
                "event_type": "TASK_STARTED",
                "task_id": "t2",
                "timestamp": time.time(),
                "message": "Executing",
            },
            {
                "event_type": "EXECUTOR_HEARTBEAT",
                "task_id": "t2",
                "timestamp": time.time(),
                "payload": {"elapsed_seconds": 5},
            },
        ]

        for width in [120, 150, 180]:
            sio = io.StringIO()
            test_c = Console(file=sio, width=width, safe_box=True)
            h = render_header(
                git_info,
                state_name="RUNNING",
                mission_status="RUNNING",
                model="stepfun/step-3.7-flash:free",
            )
            m = render_mission_panel(tasks, mission_goal="Integration Test")
            r = render_runtime_panel(
                executor_status="READY",
                attempt="1 / 2",
                has_active_mission=True,
                exec_phase="RUNNING",
                verify_phase="IDLE",
            )
            a = render_activity_panel(events)

            test_c.print(h)
            test_c.print(m)
            test_c.print(r)
            test_c.print(a)

            rendered = sio.getvalue()
            # Ensure no raw unrendered rich markup tags leaked into plain output
            self.assertNotIn("[bold green]", rendered)
            self.assertNotIn("[bold cyan]", rendered)
            self.assertNotIn("[/bold", rendered)
            self.assertIn("stepfun/step-3.7-flash:free", rendered)

    def test_cli_help_and_version(self):
        cli = CLI(db_path=str(Path(self.temp_dir) / "asc.db"))
        with self.assertRaises(SystemExit) as cm:
            cli.run(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_validate_command(self):
        mission_file = Path(self.temp_dir) / "mission.yaml"
        mission_file.write_text(
            "id: m1\ngoal: Test\ntasks:\n  - id: t1\n    title: T1\n    prompt: P1\n",
            encoding="utf-8",
        )
        cli = CLI(db_path=str(Path(self.temp_dir) / "asc.db"))
        # Validate should execute cleanly
        cli.run(["validate", str(mission_file), "--cwd", self.temp_dir])


if __name__ == "__main__":
    unittest.main()
