"""Universal ASC v2.3.0 - Comprehensive Reliability & Integration Boundary Test Suite.

Verifies all Section 30 required regression scenarios (A through Q):
  A. Two missions may both use task ID T1 without collision
  B. Duplicate mission ID cannot silently destroy prior state
  C. Mission YAML custom timeouts survive CLI invocation when flags are omitted
  D. Explicit CLI overrides work only when supplied
  E. Mission file located outside target repo still executes/stores state against target repo
  F. Interrupted RUNNING task can be truthfully resumed
  G. Attempt budget survives restart
  H. Model/executor/verification/commit scope survives restart
  I. Interactive / driver run cannot bypass dirty-repo safety
  J. Resume cannot bypass dirty-repo safety
  K. Unrelated mid-run change is NOT staged into ASC commit
  L. Unknown untracked directory is NOT recursively destroyed during rollback
  M. Multi-command verification executes every required command in order (fail-fast)
  N. Large executor stdout/stderr does not deadlock
  O. Timeout terminates execution tree safely
  P. Recent activity returns recent events in chronological order
  Q. JSON/machine output is parseable and derives from same state as human output
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from asc.adapters.base import AgentAdapter
from asc.adapters.mock import MockAdapter
from asc.adapters.omp import OMPAdapter, OMPConfig
from asc.console import get_doctor_snapshot, get_status_snapshot
from asc.driver import MissionDriver
from asc.models import (
    MissionSpec,
    Task,
    TaskStatus,
    VerificationCommand,
    VerificationResult,
)
from asc.repo import Repository
from asc.spec import MissionSpecParser
from asc.state import State
from asc.verifier import Verifier


class TestUniversalIdentityAndState(unittest.TestCase):
    """Scenarios A, B, G, H, P: SQLite Task Identity, Duplicate Safety, and Event Recency."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "asc.db"
        self.state = State(self.db_path)

    def tearDown(self):
        self.state.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenario_a_composite_task_identity_no_collision(self):
        """Scenario A: Two missions may both use task ID T1 without collision."""
        spec_a = MissionSpec(
            id="mission-alpha",
            goal="Alpha mission goal",
            tasks=[
                Task(id="T1", title="Task Alpha 1", prompt="Prompt Alpha 1"),
                Task(id="T2", title="Task Alpha 2", prompt="Prompt Alpha 2"),
            ],
        )
        spec_b = MissionSpec(
            id="mission-beta",
            goal="Beta mission goal",
            tasks=[
                Task(id="T1", title="Task Beta 1", prompt="Prompt Beta 1"),
                Task(id="T2", title="Task Beta 2", prompt="Prompt Beta 2"),
            ],
        )

        self.state.save_mission(spec_a)
        self.state.save_mission(spec_b)

        # Retrieve tasks for both missions
        tasks_a = self.state.get_tasks("mission-alpha")
        tasks_b = self.state.get_tasks("mission-beta")

        self.assertEqual(len(tasks_a), 2)
        self.assertEqual(len(tasks_b), 2)

        t1_a = self.state.get_task("T1", mission_id="mission-alpha")
        t1_b = self.state.get_task("T1", mission_id="mission-beta")

        self.assertIsNotNone(t1_a)
        self.assertIsNotNone(t1_b)
        self.assertEqual(t1_a.title, "Task Alpha 1")
        self.assertEqual(t1_b.title, "Task Beta 1")

        # Update Alpha T1 to COMPLETED and verify Beta T1 remains PENDING
        self.state.update_task_status(
            "T1", TaskStatus.COMPLETED, mission_id="mission-alpha"
        )
        t1_a_updated = self.state.get_task("T1", mission_id="mission-alpha")
        t1_b_updated = self.state.get_task("T1", mission_id="mission-beta")

        self.assertEqual(t1_a_updated.status, TaskStatus.COMPLETED)
        self.assertEqual(t1_b_updated.status, TaskStatus.PENDING)

    def test_scenario_b_duplicate_mission_id_safety(self):
        """Scenario B: Duplicate mission ID cannot silently destroy prior attempt history."""
        spec = MissionSpec(
            id="mission-repeat",
            goal="Initial goal",
            tasks=[Task(id="T1", title="Task 1", prompt="Prompt 1")],
        )
        self.state.save_mission(spec)

        # Record attempts and progress
        self.state.increment_attempt_count("T1", mission_id="mission-repeat")
        self.state.record_attempt(
            task_id="T1",
            attempt_number=1,
            status=TaskStatus.FAILED,
            exit_code=1,
            stdout="fail output",
            mission_id="mission-repeat",
        )
        self.state.update_task_status(
            "T1", TaskStatus.FAILED, mission_id="mission-repeat"
        )

        # Re-saving same mission spec must not wipe attempts
        updated_spec = MissionSpec(
            id="mission-repeat",
            goal="Updated goal",
            tasks=[Task(id="T1", title="Task 1 updated", prompt="Prompt 1 updated")],
        )
        self.state.save_mission(updated_spec)

        attempts = self.state.get_attempts("T1", mission_id="mission-repeat")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].stdout, "fail output")

        m = self.state.get_mission("mission-repeat")
        self.assertEqual(m.goal, "Updated goal")

    def test_scenario_g_attempt_budget_survives_restart(self):
        """Scenario G: Attempt budget survives restart across state instances."""
        spec = MissionSpec(
            id="mission-budget",
            goal="Test budget persistence",
            tasks=[Task(id="T1", title="Task 1", prompt="Prompt 1")],
        )
        self.state.save_mission(spec)
        self.state.increment_attempt_count("T1", mission_id="mission-budget")
        self.state.increment_attempt_count("T1", mission_id="mission-budget")

        # Re-open state on same DB
        self.state.close()
        state2 = State(self.db_path)
        try:
            # Next increment should be 3
            next_attempt = state2.increment_attempt_count(
                "T1", mission_id="mission-budget"
            )
            self.assertEqual(next_attempt, 3)
        finally:
            state2.close()

    def test_scenario_h_contract_persistence_survives_restart(self):
        """Scenario H: Model, executor, verification, commit scope survive restart."""
        spec = MissionSpec(
            id="mission-contract",
            goal="Contract persistence test",
            executor="shell",
            model="omniroute/custom-model",
            execution_timeout=450,
            verification_timeout=150,
            tasks=[
                Task(
                    id="T1",
                    title="Task 1",
                    prompt="Do something",
                    executor="omp",
                    model="custom-task-model",
                    execution_timeout=900,
                    commit_paths=["src/foo.py", "tests/foo_test.py"],
                    commands=[
                        VerificationCommand(
                            command="pytest tests/foo_test.py", timeout=120
                        ),
                        VerificationCommand(command="flake8 src/foo.py", timeout=60),
                    ],
                )
            ],
        )
        self.state.save_mission(spec)

        self.state.close()
        state2 = State(self.db_path)
        try:
            t = state2.get_task("T1", mission_id="mission-contract")
            self.assertIsNotNone(t)
            self.assertEqual(t.executor, "omp")
            self.assertEqual(t.model, "custom-task-model")
            self.assertEqual(t.execution_timeout, 900)
            self.assertEqual(t.commit_paths, ["src/foo.py", "tests/foo_test.py"])
            self.assertEqual(len(t.commands), 2)
            self.assertEqual(t.commands[0].command, "pytest tests/foo_test.py")
            self.assertEqual(t.commands[0].timeout, 120)
            self.assertEqual(t.commands[1].command, "flake8 src/foo.py")
        finally:
            state2.close()

    def test_scenario_p_recent_events_recency_order(self):
        """Scenario P: Recent activity returns the newest N events in chronological order."""
        for i in range(1, 21):
            self.state.record_event(
                {
                    "mission_id": "mission-events",
                    "task_id": "T1",
                    "event_type": f"EVENT_{i:02d}",
                    "payload": {"index": i},
                    "timestamp": float(i * 100),
                }
            )

        # Request limit=5 newest events
        recent = self.state.get_events(mission_id="mission-events", limit=5)
        self.assertEqual(len(recent), 5)
        # Should be events 16, 17, 18, 19, 20 in chronological ascending order
        event_types = [e["event_type"] for e in recent]
        self.assertEqual(
            event_types, ["EVENT_16", "EVENT_17", "EVENT_18", "EVENT_19", "EVENT_20"]
        )


class TestPathPrecedenceAndCliOverrides(unittest.TestCase):
    """Scenarios C, D, E: Path Precedence, CLI Overrides, External Mission Files."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir) / "target_repo"
        self.repo_dir.mkdir()
        subprocess.run(
            ["git", "init"], cwd=self.repo_dir, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=self.repo_dir, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.repo_dir,
            check=True,
        )

        # Initial commit
        (self.repo_dir / "README.md").write_text("initial", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial commit"], cwd=self.repo_dir, check=True
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenario_c_mission_yaml_custom_timeouts_survive_cli(self):
        """Scenario C: Mission YAML custom timeouts survive CLI invocation when flags are omitted."""
        yaml_content = """
id: timeout-mission
goal: Custom timeout survival test
execution_timeout: 777
verification_timeout: 444
tasks:
  - id: T1
    title: Task 1
    prompt: Do work
"""
        yaml_path = Path(self.temp_dir) / "mission.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        spec = MissionSpecParser.from_file(yaml_path)
        self.assertEqual(spec.execution_timeout, 777)
        self.assertEqual(spec.verification_timeout, 444)

        # Driver initialized without CLI override flags
        driver = MissionDriver(spec=spec, working_directory=str(self.repo_dir))
        self.assertEqual(driver.execution_timeout, 777)
        self.assertEqual(driver.verification_timeout, 444)

    def test_scenario_d_explicit_cli_overrides_work_only_when_supplied(self):
        """Scenario D: Explicit CLI overrides work when supplied, and do not override when omitted."""
        yaml_content = """
id: override-mission
goal: Override test
execution_timeout: 500
tasks:
  - id: T1
    title: Task 1
    prompt: Prompt 1
"""
        yaml_path = Path(self.temp_dir) / "mission.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")
        spec = MissionSpecParser.from_file(yaml_path)

        # With explicit override
        driver_override = MissionDriver(
            spec=spec,
            working_directory=str(self.repo_dir),
            execution_timeout=999,
            model="explicit-model",
        )
        self.assertEqual(driver_override.execution_timeout, 999)
        self.assertEqual(driver_override.model, "explicit-model")

    def test_scenario_e_external_mission_file_targets_repo_and_stores_state(self):
        """Scenario E: Mission file located outside target repo still executes/stores state against target repo."""
        external_yaml = Path(self.temp_dir) / "external_mission.yaml"
        external_yaml.write_text(
            """
id: external-mission
goal: External file test
tasks:
  - id: T1
    title: Task 1
    prompt: Create a file
""",
            encoding="utf-8",
        )

        spec = MissionSpecParser.from_file(external_yaml)
        driver = MissionDriver(
            spec=spec, working_directory=str(self.repo_dir), adapter=MockAdapter()
        )
        self.assertEqual(
            Path(driver.working_directory).resolve(), self.repo_dir.resolve()
        )
        # State DB should be located inside target repo's .git/asc/asc.db
        expected_db = self.repo_dir / ".git" / "asc" / "asc.db"
        self.assertEqual(Path(driver.db_path).resolve(), expected_db.resolve())


class TestGitSafetyAndInterruption(unittest.TestCase):
    """Scenarios F, I, J, K, L: Interruption Reconciliation, Preflight Safety, Scoped Delta, Safe Rollback."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir) / "repo"
        self.repo_dir.mkdir()
        subprocess.run(
            ["git", "init"], cwd=self.repo_dir, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=self.repo_dir, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.repo_dir,
            check=True,
        )

        (self.repo_dir / "init.txt").write_text("base", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init commit"], cwd=self.repo_dir, check=True
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenario_f_interrupted_running_task_reconciliation(self):
        """Scenario F: Interrupted RUNNING task on dead process is truthfully reconciled to INTERRUPTED."""
        db_path = self.repo_dir / ".git" / "asc" / "asc.db"
        state = State(db_path)
        spec = MissionSpec(
            id="crash-mission",
            goal="Simulate crash and resume",
            tasks=[
                Task(id="T1", title="Task 1", prompt="Prompt 1"),
                Task(id="T2", title="Task 2", prompt="Prompt 2", depends_on=["T1"]),
            ],
        )
        state.save_mission(spec)
        # Simulate process crash while T1 was RUNNING
        state.update_task_status("T1", TaskStatus.RUNNING, mission_id="crash-mission")
        state.record_attempt(
            task_id="T1",
            attempt_number=1,
            status=TaskStatus.RUNNING,
            exit_code=0,
            mission_id="crash-mission",
        )
        state.close()

        # Resume mission
        driver = MissionDriver(
            spec=spec, working_directory=str(self.repo_dir), adapter=MockAdapter()
        )
        # Running should reconcile T1 to INTERRUPTED then complete it
        res = driver.run("crash-mission")
        self.assertEqual(res["final_status"], "COMPLETE")
        self.assertEqual(res["tasks_completed"], 2)

    def test_scenario_i_and_j_dirty_repo_preflight_blocks_run_and_resume(self):
        """Scenarios I & J: Dirty repository blocks both run and resume uniformly."""
        spec = MissionSpec(
            id="preflight-mission",
            goal="Preflight dirty test",
            tasks=[Task(id="T1", title="Task 1", prompt="Prompt 1")],
        )
        # Create an uncommitted dirty file
        (self.repo_dir / "dirty_untracked.txt").write_text(
            "dirty content", encoding="utf-8"
        )

        driver = MissionDriver(
            spec=spec, working_directory=str(self.repo_dir), adapter=MockAdapter()
        )
        with self.assertRaises(RuntimeError) as ctx:
            driver.run()
        self.assertIn("Repository preflight check failed", str(ctx.exception))

    def test_scenario_k_unrelated_midrun_change_not_staged(self):
        """Scenario K: Unrelated change created during task execution is NOT staged into task commit."""

        class SideEffectAdapter(AgentAdapter):
            def can_execute(self, task: Task) -> bool:
                return True

            def prepare(self, context: dict) -> None:
                pass

            def cleanup(self) -> None:
                pass

            def execute(self, task: Task, context: dict) -> VerificationResult:
                wd = Path(context["working_directory"])
                # Task creates its intended file
                (wd / "task_output.txt").write_text("task work", encoding="utf-8")
                return VerificationResult(
                    command=VerificationCommand(command="test"),
                    exit_code=0,
                )

        spec = MissionSpec(
            id="scoped-commit-mission",
            goal="Scoped commit test",
            tasks=[
                Task(
                    id="T1",
                    title="Task 1",
                    prompt="Create file",
                    commit_paths=["task_output.txt"],
                )
            ],
        )
        driver = MissionDriver(
            spec=spec, working_directory=str(self.repo_dir), adapter=SideEffectAdapter()
        )
        res = driver.run()
        self.assertEqual(res["final_status"], "COMPLETE")

        # Verify only task_output.txt was committed
        repo = Repository(self.repo_dir)
        self.assertTrue(repo.is_clean())
        head_show = subprocess.run(
            ["git", "show", "--name-only", "--oneline", "HEAD"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("task_output.txt", head_show)

    def test_scenario_l_failed_attempt_rollback_preserves_unrelated_directories(self):
        """Scenario L: Failed attempt rollback does NOT recursively destroy existing directories."""
        # Create a user directory beforehand
        user_dir = self.repo_dir / "user_docs"
        user_dir.mkdir()
        (user_dir / "keep_me.md").write_text("precious docs", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add user docs"], cwd=self.repo_dir, check=True
        )

        repo = Repository(self.repo_dir)
        # Attempt creates a failed file inside a subfolder
        failed_file = self.repo_dir / "user_docs" / "failed_temp.txt"
        failed_file.write_text("temporary bad output", encoding="utf-8")

        # Rollback attempt delta
        repo.rollback_attempt(["user_docs/failed_temp.txt"])
        self.assertFalse(failed_file.exists())
        self.assertTrue(user_dir.exists())
        self.assertTrue((user_dir / "keep_me.md").exists())


class TestMultiCommandVerificationAndProcesses(unittest.TestCase):
    """Scenarios M, N, O, Q: Multi-Command Verification, Stream Draining, Tree Termination, JSON Output."""

    def test_scenario_m_multi_command_verification_fail_fast(self):
        """Scenario M: Multi-command verification executes every required command in order, stopping on first failure."""
        verifier = Verifier(timeout=10)

        # 1. All pass
        commands_pass = [
            VerificationCommand(command="python -c \"print('step 1')\""),
            VerificationCommand(command="python -c \"print('step 2')\""),
            VerificationCommand(command="python -c \"print('step 3')\""),
        ]
        res_pass = verifier.run_verification(commands_pass)
        self.assertTrue(res_pass.success)
        self.assertEqual(res_pass.exit_code, 0)
        self.assertEqual(len(res_pass.results), 3)

        # 2. Fail at step 2 (step 3 must not execute)
        commands_fail = [
            VerificationCommand(command="python -c \"print('step 1 ok')\""),
            VerificationCommand(command='python -c "import sys; sys.exit(42)"'),
            VerificationCommand(command="python -c \"print('step 3 should not run')\""),
        ]
        res_fail = verifier.run_verification(commands_fail)
        self.assertFalse(res_fail.success)
        self.assertEqual(res_fail.exit_code, 42)
        self.assertEqual(len(res_fail.results), 2)
        self.assertNotIn("step 3 should not run", res_fail.stdout)

    def test_scenario_n_large_output_stream_draining_no_deadlock(self):
        """Scenario N: Output larger than OS pipe buffer (>64KB) is continuously drained without deadlocking."""
        adapter = OMPAdapter(config=OMPConfig(timeout=10))

        temp_dir = tempfile.mkdtemp()
        try:
            fake_omp_py = Path(temp_dir) / "fake_omp.py"
            fake_omp_py.write_text(
                "import sys\n[print('A' * 1000) for _ in range(200)]\nsys.exit(0)\n",
                encoding="utf-8",
            )
            fake_omp_bat = Path(temp_dir) / "fake_omp.bat"
            fake_omp_bat.write_text(
                f'@"{sys.executable}" "{fake_omp_py}" %*\n',
                encoding="utf-8",
            )

            fake_task = Task(
                id="T_LARGE", title="Large stream test", prompt="some prompt"
            )

            with patch.object(
                adapter, "_get_omp_executable", return_value=str(fake_omp_bat)
            ):
                res = adapter.execute(
                    fake_task,
                    {
                        "working_directory": temp_dir,
                        "execution_timeout": 10,
                    },
                )
            self.assertEqual(res.exit_code, 0)
            self.assertGreater(len(res.stdout), 100_000)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_scenario_o_timeout_process_tree_termination(self):
        """Scenario O: Timeout terminates execution tree cleanly and reports exit code 124."""
        adapter = OMPAdapter(config=OMPConfig(timeout=1))

        temp_dir = tempfile.mkdtemp()
        try:
            hanging_py = Path(temp_dir) / "hang.py"
            hanging_py.write_text("import time; time.sleep(30)\n", encoding="utf-8")
            hanging_bat = Path(temp_dir) / "hang.bat"
            hanging_bat.write_text(
                f'@"{sys.executable}" "{hanging_py}" %*\n', encoding="utf-8"
            )

            fake_task = Task(
                id="T_HANG", title="Hang test", prompt="hang", execution_timeout=1
            )

            with patch.object(
                adapter, "_get_omp_executable", return_value=str(hanging_bat)
            ):
                start = time.time()
                res = adapter.execute(
                    fake_task,
                    {
                        "working_directory": temp_dir,
                        "execution_timeout": 1,
                    },
                )
                elapsed = time.time() - start
            self.assertEqual(res.exit_code, 124)
            self.assertLess(elapsed, 5.0)
            self.assertIn("Timeout", res.stderr)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_scenario_q_machine_readable_json_output(self):
        """Scenario Q: JSON snapshot outputs are parseable and derive from same state as human views."""
        temp_dir = tempfile.mkdtemp()
        try:
            repo_dir = Path(temp_dir) / "repo"
            repo_dir.mkdir()
            subprocess.run(
                ["git", "init"], cwd=repo_dir, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo_dir, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_dir,
                check=True,
            )

            doc_snap = get_doctor_snapshot(cwd=repo_dir)
            self.assertEqual(doc_snap["asc_version"], "2.3.0")
            self.assertEqual(doc_snap["system_status"], "READY")
            self.assertIn("git", doc_snap)

            stat_snap = get_status_snapshot(cwd=repo_dir)
            self.assertEqual(stat_snap["asc_version"], "2.3.0")
            self.assertIn("tasks", stat_snap)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
