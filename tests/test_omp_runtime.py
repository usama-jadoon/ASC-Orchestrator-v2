"""Focused tests for Universal ASC v2.1 OMP Runtime.

Tests the execute -> verify -> retry -> commit pipeline, OMP adapter CLI,
executor selection, working directory propagation, and retry enforcement.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asc.adapters.mock import MockAdapter
from asc.adapters.omp import OMPAdapter, OMPConfig
from asc.driver import MissionDriver, build_adapter
from asc.models import (
    MissionDefaults,
    MissionSpec,
    Task,
    TaskStatus,
    VerificationCommand,
)
from asc.repo import Repository
from asc.state import State


class TestOMPAdapterCommandConstruction(unittest.TestCase):
    """Test that OMP adapter builds correct CLI command."""

    def test_omp_invocation_with_positional_prompt(self):
        """OMP command uses top-level -p --auto-approve with positional prompt (no launch subcommand)."""
        with patch("shutil.which", return_value="/fake/omp"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                adapter = OMPAdapter(config=OMPConfig(omp_path="/fake/omp"))
                task = Task(id="t1", title="Test", prompt="Write hello world")
                adapter.execute(task, {"working_directory": "/tmp"})

                # Verify the command structure
                called_cmd = mock_run.call_args[0][0]
                self.assertEqual(called_cmd[0], "/fake/omp")
                self.assertEqual(called_cmd[1], "-p")
                self.assertIn("--auto-approve", called_cmd)
                self.assertEqual(called_cmd[-1], "Write hello world")
                # Must NOT contain launch or invented flags
                self.assertNotIn("launch", called_cmd)
                self.assertNotIn("--prompt", called_cmd)
                self.assertNotIn("--working-dir", called_cmd)
                self.assertNotIn("--timeout", called_cmd)

    def test_omp_cwd_flag_not_working_dir(self):
        """OMP adapter uses --cwd (not --working-dir) for working directory."""
        with patch("shutil.which", return_value="/fake/omp"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                adapter = OMPAdapter(config=OMPConfig(omp_path="/fake/omp"))
                task = Task(id="t1", title="Test", prompt="Do stuff")
                adapter.execute(
                    task, {"working_directory": "/home/user/project with spaces"}
                )

                called_cmd = mock_run.call_args[0][0]
                self.assertIn("--cwd", called_cmd)
                cwd_idx = called_cmd.index("--cwd")
                self.assertEqual(
                    called_cmd[cwd_idx + 1], "/home/user/project with spaces"
                )
                self.assertNotIn("--working-dir", called_cmd)

    def test_omp_no_timeout_flag(self):
        """OMP adapter does not pass --timeout to CLI; harness enforces timeout."""
        with patch("shutil.which", return_value="/fake/omp"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                adapter = OMPAdapter(config=OMPConfig(omp_path="/fake/omp", timeout=60))
                task = Task(id="t1", title="Test", prompt="Do stuff")
                adapter.execute(task, {})

                called_cmd = mock_run.call_args[0][0]
                self.assertNotIn("--timeout", called_cmd)

    def test_omp_discovery_via_path(self):
        """OMP adapter discovers executable via shutil.which."""
        with patch("shutil.which", return_value="/usr/local/bin/omp"):
            adapter = OMPAdapter(config=OMPConfig())
            exe = adapter._get_omp_executable()

    def test_omp_config_override_path(self):
        """Explicit OMP config path overrides PATH discovery."""
        with patch("shutil.which", return_value="/ignored/omp"):
            with patch("os.path.exists", return_value=True):
                with patch("os.access", return_value=True):
                    adapter = OMPAdapter(config=OMPConfig(omp_path="/custom/omp"))
                    exe = adapter._get_omp_executable()
                    self.assertEqual(exe, "/custom/omp")

    """Test execute -> verify order (not verify -> execute)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.state = State(str(self.db_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_execute_then_verify_not_verify_then_execute(self):
        """Execution runs BEFORE verification; verification only on execution success."""
        executed = {"count": 0}
        verified = {"count": 0}

        class TrackingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                executed["count"] += 1
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "", "stderr": "", "duration": 0.0},
                )()

        class TrackingVerifier:
            def __init__(self, timeout=300):
                self.timeout = timeout

            def run_verification(self, commands, cwd="."):
                verified["count"] += 1
                cmd = commands[0]
                if isinstance(cmd, str):
                    return type(
                        "VR",
                        (),
                        {
                            "exit_code": 0,
                            "stdout": "",
                            "stderr": "",
                            "duration": 0.0,
                            "success": True,
                        },
                    )()
                return type(
                    "VR",
                    (),
                    {
                        "exit_code": 0,
                        "stdout": "",
                        "stderr": "",
                        "duration": 0.0,
                        "success": True,
                    },
                )()

        driver = MissionDriver(
            spec=MissionSpec(
                id="m1",
                goal="G",
                tasks=[
                    Task(
                        id="t1",
                        title="T1",
                        prompt="echo hi",
                        command=VerificationCommand(command="echo verify"),
                    )
                ],
            ),
            db_path=str(self.db_path),
            adapter=TrackingAdapter(),
        )
        driver.verifier = TrackingVerifier()

        # Run one task
        driver.mission_id = "m1"
        driver.state.save_mission(
            MissionSpec(
                id="m1",
                goal="G",
                tasks=[
                    Task(
                        id="t1",
                        title="T1",
                        prompt="echo hi",
                        command=VerificationCommand(command="echo verify"),
                    )
                ],
            )
        )
        driver.state.save_task(driver.state.get_tasks("m1")[0], "m1")

        # Manually invoke execute with retry for one task
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)

        # Both should have been called exactly once
        self.assertEqual(executed["count"], 1)
        self.assertEqual(verified["count"], 1)


class TestRetryEnforcement(unittest.TestCase):
    """Test deterministic retry limit, no infinite loops."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_max_attempts_respected(self):
        """After max_attempts failures, task is blocked (no infinite retry)."""
        attempt_count = {"exec": 0}

        class FailingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                attempt_count["exec"] += 1
                return type(
                    "R",
                    (),
                    {"exit_code": 1, "stdout": "", "stderr": "fail", "duration": 0.0},
                )()

        spec = MissionSpec(
            id="m1",
            goal="Test retries",
            tasks=[
                Task(id="t1", title="T1", prompt="fail", metadata={"max_attempts": 3})
            ],
            defaults=MissionDefaults(max_attempts=3),
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=FailingAdapter()
        )
        driver._max_attempts = 3

        task = driver.state.get_tasks("m1")[0]
        success, exit_code = driver._execute_task_with_retry(task)

        self.assertFalse(success)
        self.assertEqual(attempt_count["exec"], 3)  # Exactly 3 attempts
        self.assertEqual(task.status, TaskStatus.FAILED)

    def test_task_level_max_attempts_override(self):
        """Task metadata max_attempts overrides spec defaults."""
        attempt_count = {"exec": 0}

        class FailingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                attempt_count["exec"] += 1
                return type(
                    "R",
                    (),
                    {"exit_code": 1, "stdout": "", "stderr": "fail", "duration": 0.0},
                )()

        # Spec says 5, task says 2
        spec = MissionSpec(
            id="m1",
            goal="Test retries",
            tasks=[
                Task(id="t1", title="T1", prompt="fail", metadata={"max_attempts": 2})
            ],
            defaults=MissionDefaults(max_attempts=5),
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=FailingAdapter()
        )
        driver._max_attempts = 5  # driver-level fallback

        task = driver.state.get_tasks("m1")[0]
        success, exit_code = driver._execute_task_with_retry(task)

        self.assertFalse(success)
        self.assertEqual(attempt_count["exec"], 2)  # Task-level 2 overrides spec 5

    def test_retry_on_verification_failure(self):
        """Retries occur when execution succeeds but verification fails."""
        counts = {"exec": 0, "verify": 0}

        class SucceedingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                counts["exec"] += 1
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "ok", "stderr": "", "duration": 0.0},
                )()

        class FailingVerifier:
            def __init__(self, timeout=300):
                self.timeout = timeout

            def run_verification(self, commands, cwd="."):
                counts["verify"] += 1
                return type(
                    "VR",
                    (),
                    {
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "verify fail",
                        "duration": 0.0,
                        "success": False,
                    },
                )()

        spec = MissionSpec(
            id="m1",
            goal="Test retry on verify",
            tasks=[
                Task(
                    id="t1",
                    title="T1",
                    prompt="echo hi",
                    command=VerificationCommand(command="exit 1"),
                    metadata={"max_attempts": 3},
                )
            ],
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=SucceedingAdapter()
        )
        driver.verifier = FailingVerifier()
        driver._max_attempts = 3

        task = driver.state.get_tasks("m1")[0]
        success, exit_code = driver._execute_task_with_retry(task)

        self.assertFalse(success)
        self.assertEqual(counts["exec"], 3)
        self.assertEqual(counts["verify"], 3)  # Both retried


class TestCommitOnlyAfterVerifyPass(unittest.TestCase):
    """Test git commit occurs ONLY after verification PASS."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        # Init a git repo
        subprocess.run(["git", "init"], cwd=self.temp_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            cwd=self.temp_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.temp_dir,
            capture_output=True,
        )
        (Path(self.temp_dir) / "README.md").write_text("# Test\n")
        subprocess.run(
            ["git", "add", "README.md"], cwd=self.temp_dir, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=self.temp_dir, capture_output=True
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_commit_on_execution_failure(self):
        """No commit if execution fails."""

        class FailingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                return type(
                    "R",
                    (),
                    {"exit_code": 1, "stdout": "", "stderr": "", "duration": 0.0},
                )()

        spec = MissionSpec(
            id="m1",
            goal="G",
            tasks=[
                Task(id="t1", title="T1", prompt="fail", metadata={"max_attempts": 1})
            ],
            defaults=MissionDefaults(max_attempts=1),
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=FailingAdapter()
        )
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)

        # Should have 0 commits
        commits = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(int(commits), 1)  # Only initial commit

    def test_no_commit_on_verification_failure(self):
        """No commit if execution succeeds but verification fails."""
        temp_dir = self.temp_dir

        class SucceedingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                # Write a file that would be committed
                (Path(temp_dir) / "generated.txt").write_text("generated")
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "ok", "stderr": "", "duration": 0.0},
                )()

        class FailingVerifier:
            def __init__(self, timeout=300):
                self.timeout = timeout

            def run_verification(self, commands, cwd="."):
                return type(
                    "VR",
                    (),
                    {
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "verify fail",
                        "duration": 0.0,
                        "success": False,
                    },
                )()

        spec = MissionSpec(
            id="m1",
            goal="G",
            tasks=[
                Task(
                    id="t1",
                    title="T1",
                    prompt="echo hi",
                    command=VerificationCommand(command="exit 1"),
                    metadata={"max_attempts": 1},
                )
            ],
            defaults=MissionDefaults(max_attempts=1),
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=SucceedingAdapter()
        )
        driver.verifier = FailingVerifier()
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)

        commits = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(int(commits), 1)  # Only initial commit

    def test_commit_on_both_success(self):
        """Commit occurs when both execution and verification succeed."""
        temp_dir = self.temp_dir

        class SucceedingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                (Path(temp_dir) / "generated.txt").write_text("generated")
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "ok", "stderr": "", "duration": 0.0},
                )()

        class SucceedingVerifier:
            def __init__(self, timeout=300):
                self.timeout = timeout

            def run_verification(self, commands, cwd="."):
                return type(
                    "VR",
                    (),
                    {
                        "exit_code": 0,
                        "stdout": "ok",
                        "stderr": "",
                        "duration": 0.0,
                        "success": True,
                    },
                )()

        spec = MissionSpec(
            id="m1",
            goal="G",
            tasks=[
                Task(
                    id="t1",
                    title="T1",
                    prompt="echo hi",
                    command=VerificationCommand(command="echo verify"),
                    metadata={"max_attempts": 1},
                )
            ],
            defaults=MissionDefaults(max_attempts=1),
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=SucceedingAdapter()
        )
        driver.repository = Repository(self.temp_dir)
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)

        # Now complete the task (would be called after success)
        driver._complete_task(task)

        commits = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(int(commits), 2)  # Initial + one new commit


class TestExecutorSelection(unittest.TestCase):
    """Test executor selection default and overrides."""

    def test_build_adapter_default_omp(self):
        with patch("shutil.which", return_value="/fake/omp"):
            adapter = build_adapter("omp", 300)
            self.assertIsInstance(adapter, OMPAdapter)

    def test_build_adapter_shell(self):
        adapter = build_adapter("shell", 300)
        from asc.adapters.shell import ShellAdapter

        self.assertIsInstance(adapter, ShellAdapter)

    def test_build_adapter_mock(self):
        adapter = build_adapter("mock", 300)
        self.assertIsInstance(adapter, MockAdapter)

    def test_build_adapter_case_insensitive(self):
        with patch("shutil.which", return_value="/fake/omp"):
            self.assertIsInstance(build_adapter("OMP", 300), OMPAdapter)
            self.assertIsInstance(build_adapter("Omp", 300), OMPAdapter)

    def test_build_adapter_unknown_raises(self):
        with self.assertRaises(ValueError):
            build_adapter("nonexistent", 300)

    def test_driver_uses_spec_executor_default(self):
        """Driver uses executor from spec.defaults.executor."""
        with patch("shutil.which", return_value="/fake/omp"):
            temp_dir = tempfile.mkdtemp()
            try:
                db_path = str(Path(temp_dir) / "test.db")
                spec = MissionSpec(
                    id="m1",
                    goal="G",
                    tasks=[Task(id="t1", title="T1", prompt="hi")],
                    defaults=MissionDefaults(executor="shell"),
                )
                driver = MissionDriver(spec=spec, db_path=db_path)
                self.assertEqual(driver.executor, "shell")
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
            self.assertEqual(driver.executor, "shell")


class TestWorkingDirectoryPropagation(unittest.TestCase):
    """Test working directory flows to adapter and verifier."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_task_working_directory_to_adapter(self):
        """Task-level working_directory propagates to adapter context."""
        captured_context = {}

        class CaptureAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                captured_context["working_directory"] = context.get("working_directory")
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "", "stderr": "", "duration": 0.0},
                )()

        spec = MissionSpec(
            id="m1",
            goal="G",
            tasks=[
                Task(id="t1", title="T1", prompt="hi", working_directory="/custom/path")
            ],
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=CaptureAdapter()
        )
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)

        self.assertEqual(captured_context["working_directory"], "/custom/path")

    def test_spec_defaults_working_directory_fallback(self):
        """Spec defaults working_directory used when task has none."""
        captured_context = {}

        class CaptureAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                captured_context["working_directory"] = context.get("working_directory")
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "", "stderr": "", "duration": 0.0},
                )()

        spec = MissionSpec(
            id="m1",
            goal="G",
            tasks=[Task(id="t1", title="T1", prompt="hi")],
            defaults=MissionDefaults(working_directory="/spec/default"),
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=CaptureAdapter()
        )
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)

        self.assertEqual(captured_context["working_directory"], "/spec/default")

    def test_verification_runs_in_same_directory(self):
        """Verification runs in the same working directory as execution."""
        verify_cwds = []

        class SucceedingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "", "stderr": "", "duration": 0.0},
                )()

        class CaptureVerifier:
            def __init__(self, timeout=300):
                self.timeout = timeout

            def run_verification(self, commands, cwd="."):
                verify_cwds.append(cwd)
                return type(
                    "VR",
                    (),
                    {
                        "exit_code": 0,
                        "stdout": "",
                        "stderr": "",
                        "duration": 0.0,
                        "success": True,
                    },
                )()

        spec = MissionSpec(
            id="m1",
            goal="G",
            tasks=[
                Task(
                    id="t1",
                    title="T1",
                    prompt="hi",
                    command=VerificationCommand(command="echo verify"),
                    working_directory="/task/workdir",
                )
            ],
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=SucceedingAdapter()
        )
        driver.verifier = CaptureVerifier()
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)

        self.assertEqual(verify_cwds, ["/task/workdir"])

    def test_windows_path_with_spaces_handling(self):
        """Windows paths with spaces are handled correctly (argv not shell)."""
        captured_cmd = {}

        class CaptureAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                # OMPAdapter builds cmd as list, passes to subprocess without shell=True
                # This test verifies the driver passes working_directory correctly
                captured_cmd["cwd"] = context.get("working_directory")
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "", "stderr": "", "duration": 0.0},
                )()

        spec = MissionSpec(
            id="m1",
            goal="G",
            tasks=[
                Task(
                    id="t1",
                    title="T1",
                    prompt="hi",
                    working_directory=r"C:\Users\Name\My Project",
                )
            ],
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=CaptureAdapter()
        )
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)

        self.assertEqual(captured_cmd["cwd"], r"C:\Users\Name\My Project")


class TestGitSafety(unittest.TestCase):
    """Test no auto-push, no auto-merge, no auto-tag, no auto-release."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        subprocess.run(["git", "init"], cwd=self.temp_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            cwd=self.temp_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.temp_dir,
            capture_output=True,
        )
        (Path(self.temp_dir) / "README.md").write_text("# Test\n")
        subprocess.run(
            ["git", "add", "README.md"], cwd=self.temp_dir, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=self.temp_dir, capture_output=True
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_push_no_merge_no_tag_no_release(self):
        """Driver commits but never pushes, merges, tags, or releases."""
        temp_dir = self.temp_dir

        class SucceedingAdapter:
            def can_execute(self, task):
                return True

            def prepare(self, context):
                pass

            def cleanup(self):
                pass

            def execute(self, task, context):
                (Path(temp_dir) / "gen.txt").write_text("x")
                return type(
                    "R",
                    (),
                    {"exit_code": 0, "stdout": "", "stderr": "", "duration": 0.0},
                )()

        class SucceedingVerifier:
            def __init__(self, timeout=300):
                self.timeout = timeout

            def run_verification(self, commands, cwd="."):
                return type(
                    "VR",
                    (),
                    {
                        "exit_code": 0,
                        "stdout": "",
                        "stderr": "",
                        "duration": 0.0,
                        "success": True,
                    },
                )()

        spec = MissionSpec(
            id="m1",
            goal="G",
            tasks=[
                Task(
                    id="t1",
                    title="T1",
                    prompt="hi",
                    command=VerificationCommand(command="echo v"),
                )
            ],
            defaults=MissionDefaults(max_attempts=1),
        )
        driver = MissionDriver(
            spec=spec, db_path=str(self.db_path), adapter=SucceedingAdapter()
        )
        driver.verifier = SucceedingVerifier()
        driver.repository = Repository(self.temp_dir)
        task = driver.state.get_tasks("m1")[0]
        driver._execute_task_with_retry(task)
        driver._complete_task(task)

        # Only one new commit
        commits = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(int(commits), 2)

        # No tags
        tags = subprocess.run(
            ["git", "tag", "-l"], cwd=self.temp_dir, capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(tags, "")

        # No remote pushed
        remotes = subprocess.run(
            ["git", "remote", "-v"], cwd=self.temp_dir, capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(remotes, "")


class TestMissionSpecParserRuntimeFieldPropagation(unittest.TestCase):
    """Test full parsing and propagation of defaults and task-level fields."""

    def test_parser_propagates_all_runtime_fields(self):
        """YAML defaults and task fields survive to MissionSpec and MissionDriver."""
        from asc.spec import MissionSpecParser

        yaml_content = """
id: mission-runtime-fields
goal: "Verify complete runtime field propagation"
defaults:
  max_attempts: 5
  verification_timeout: 120
  executor: "omp"
  working_directory: "/default/proj/dir"
tasks:
  - id: t1
    title: "Task 1 Default"
    prompt: "Default prompt"
    command: "pytest tests/test_1.py"
  - id: t2
    title: "Task 2 Overridden"
    prompt: "Task prompt"
    executor: "shell"
    working_directory: "/task2/custom/dir"
    verify:
      - "pytest tests/test_2.py"
"""
        spec = MissionSpecParser.parse(yaml_content)

        # Assert spec defaults
        self.assertEqual(spec.id, "mission-runtime-fields")
        self.assertEqual(spec.defaults.max_attempts, 5)
        self.assertEqual(spec.defaults.verification_timeout, 120)
        self.assertEqual(spec.defaults.executor, "omp")
        self.assertEqual(spec.defaults.working_directory, "/default/proj/dir")
        self.assertEqual(spec.executor, "omp")
        self.assertEqual(spec.working_directory, "/default/proj/dir")

        # Assert task 1 (inherits defaults)
        self.assertEqual(spec.tasks[0].id, "t1")
        self.assertIsNone(spec.tasks[0].executor)
        self.assertIsNone(spec.tasks[0].working_directory)
        self.assertEqual(spec.tasks[0].command.command, "pytest tests/test_1.py")

        # Assert task 2 (overridden executor, working_directory, verify alias)
        self.assertEqual(spec.tasks[1].id, "t2")
        self.assertEqual(spec.tasks[1].executor, "shell")
        self.assertEqual(spec.tasks[1].working_directory, "/task2/custom/dir")
        self.assertEqual(spec.tasks[1].command.command, "pytest tests/test_2.py")

        # Verify MissionDriver receives these values
        with patch("shutil.which", return_value="/fake/omp"):
            temp_dir = tempfile.mkdtemp()
            try:
                db_path = str(Path(temp_dir) / "test.db")
                driver = MissionDriver(spec=spec, db_path=db_path)
                self.assertEqual(driver.executor, "omp")
                self.assertIsInstance(driver.adapter, OMPAdapter)
                self.assertEqual(driver._max_attempts, 5)
                self.assertEqual(driver.spec_working_directory, "/default/proj/dir")
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)


class TestResumeExecutorConsistency(unittest.TestCase):
    """Test resume preserves executor and working directory configuration deterministically."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test.db")
        self.state = State(self.db_path)

    def tearDown(self):
        self.state.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resume_omp_mission_uses_omp_adapter(self):
        """Persisted OMP mission does not silently resume using ShellAdapter."""
        with patch("shutil.which", return_value="/fake/omp"):
            spec = MissionSpec(
                id="mission-omp-resume",
                goal="Goal",
                tasks=[Task(id="t1", title="T1", prompt="Prompt")],
                defaults=MissionDefaults(executor="omp", working_directory="/my/project"),
            )
            # Save mission to state (like asc init / run)
            self.state.save_mission(spec)

            # Re-instantiate driver using ONLY state (simulating asc resume)
            driver = MissionDriver(self.state, mission_id="mission-omp-resume")

            self.assertEqual(driver.executor, "omp")
            self.assertIsInstance(driver.adapter, OMPAdapter)
            self.assertEqual(driver.working_directory, "/my/project")

    def test_resume_shell_mission_uses_shell_adapter(self):
        """Persisted Shell mission resumes using ShellAdapter."""
        spec = MissionSpec(
            id="mission-shell-resume",
            goal="Goal",
            tasks=[Task(id="t1", title="T1", prompt="Prompt")],
            defaults=MissionDefaults(executor="shell", working_directory="/my/shell/project"),
        )
        self.state.save_mission(spec)

        driver = MissionDriver(self.state, mission_id="mission-shell-resume")

        self.assertEqual(driver.executor, "shell")
        from asc.adapters.shell import ShellAdapter
        self.assertIsInstance(driver.adapter, ShellAdapter)
        self.assertEqual(driver.working_directory, "/my/shell/project")


class TestTaskLevelExecutorOverride(unittest.TestCase):
    """Test task-level executor override during execution."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_task_executor_override_uses_correct_adapter(self):
        """Task with executor='shell' runs via ShellAdapter even if mission defaults to omp."""
        with patch("shutil.which", return_value="/fake/omp"):
            executed_by = []

            spec = MissionSpec(
                id="mission-override",
                goal="Goal",
                tasks=[
                    Task(
                        id="t1",
                        title="T1",
                        prompt="echo task_override_output",
                        executor="shell",
                    )
                ],
                defaults=MissionDefaults(executor="omp"),
            )
            driver = MissionDriver(spec=spec, db_path=self.db_path)
            # Driver default is OMPAdapter
            self.assertIsInstance(driver.adapter, OMPAdapter)

            task = driver.state.get_tasks("mission-override")[0]
            success, exit_code = driver._execute_task_with_retry(task)

            self.assertTrue(success)
            self.assertEqual(exit_code, 0)
            attempts = driver.state.get_attempts("t1")
            self.assertEqual(len(attempts), 1)
            self.assertIn("task_override_output", attempts[0]["stdout"])


class TestOMPTimeoutHandling(unittest.TestCase):
    """Test OMP adapter subprocess timeout returns exit_code=124."""

    def test_timeout_returns_124(self):
        """Subprocess.TimeoutExpired results in VerificationResult(exit_code=124)."""
        with patch("shutil.which", return_value="/fake/omp"):
            adapter = OMPAdapter(config=OMPConfig(omp_path="/fake/omp", timeout=1))
            task = Task(id="t1", title="T1", prompt="sleep 10")

            with patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["omp"], timeout=1),
            ):
                result = adapter.execute(task, {})

            self.assertEqual(result.exit_code, 124)
            self.assertIn("Timeout", result.stderr)


if __name__ == "__main__":
    unittest.main()
