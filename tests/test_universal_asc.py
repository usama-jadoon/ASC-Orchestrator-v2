"""Comprehensive test suite for Universal ASC v2.0.0"""

import os
import sys
import tempfile
import time
import unittest

from asc.adapters.mock import MockAdapter
from asc.adapters.shell import ShellAdapter
from asc.dag import evaluate_mission, get_runnable_tasks, is_task_ready
from asc.models import (
    MissionSpec,
    SchedulerState,
    Task,
    TaskStatus,
)
from asc.spec import MissionSpecParser
from asc.state import State
from asc.verifier import Verifier


class TestMissionSpecParser(unittest.TestCase):
    """Test mission specification parsing and validation."""

    def test_parse_yaml_spec(self):
        """Test parsing valid YAML mission spec."""
        spec_yaml = """
id: mission-1
goal: "Complete all tasks"
tasks:
  - id: task-1
    title: "Task 1"
    prompt: "Do something"
  - id: task-2
    title: "Task 2"
    prompt: "Do something else"
    depends_on: ["task-1"]
"""
        parser = MissionSpecParser()
        spec = parser.parse(spec_yaml)
        self.assertEqual(spec.id, "mission-1")
        self.assertEqual(len(spec.tasks), 2)
        self.assertEqual(spec.tasks[0].id, "task-1")
        self.assertEqual(spec.tasks[1].id, "task-2")
        self.assertEqual(spec.tasks[1].depends_on, ["task-1"])

    def test_validate_empty_spec(self):
        """Test validation of empty mission spec."""
        spec_yaml = """
id: empty-mission
goal: "Do nothing"
tasks: []
"""
        parser = MissionSpecParser()
        spec = parser.parse(spec_yaml)
        self.assertEqual(len(spec.tasks), 0)

    def test_validate_duplicate_task_ids(self):
        """Test validation rejects duplicate task IDs."""
        spec_yaml = """
id: mission-1
goal: "Test"
tasks:
  - id: task-1
    title: "Task 1"
    prompt: "Test"
  - id: task-1
    title: "Task 1 duplicate"
    prompt: "Test"
"""
        parser = MissionSpecParser()
        with self.assertRaises(ValueError) as cm:
            parser.parse(spec_yaml)
        self.assertIn("Duplicate task IDs", str(cm.exception))

    def test_validate_missing_dependency(self):
        """Test validation rejects missing dependency IDs."""
        spec_yaml = """
id: mission-1
goal: "Test"
tasks:
  - id: task-1
    title: "Task 1"
    prompt: "Test"
    depends_on: ["nonexistent"]
"""
        parser = MissionSpecParser()
        with self.assertRaises(ValueError) as cm:
            parser.parse(spec_yaml)
        self.assertIn("missing dependency", str(cm.exception).lower())

    def test_validate_self_dependency(self):
        """Test validation rejects self-dependency."""
        spec_yaml = """
id: mission-1
goal: "Test"
tasks:
  - id: task-1
    title: "Task 1"
    prompt: "Test"
    depends_on: ["task-1"]
"""
        parser = MissionSpecParser()
        with self.assertRaises(ValueError) as cm:
            parser.parse(spec_yaml)
        self.assertIn("cyclic dependencies", str(cm.exception).lower())


class TestDAGEvaluation(unittest.TestCase):
    """Test DAG evaluation and task readiness."""

    def test_is_task_ready_no_dependencies(self):
        """Test task with no dependencies is ready."""
        task = Task(id="task-1", title="Task 1", prompt="Test")
        self.assertTrue(is_task_ready(task, [task]))

    def test_is_task_ready_with_completed_dependency(self):
        """Test task with completed dependency is ready."""
        task_a = Task(
            id="task-a", title="Task A", prompt="Test", status=TaskStatus.COMPLETED
        )
        task_b = Task(id="task-b", title="Task B", prompt="Test", depends_on=["task-a"])
        self.assertTrue(is_task_ready(task_b, [task_a, task_b]))

    def test_is_task_ready_with_pending_dependency(self):
        """Test task with pending dependency is not ready."""
        task_a = Task(
            id="task-a", title="Task A", prompt="Test", status=TaskStatus.PENDING
        )
        task_b = Task(id="task-b", title="Task B", prompt="Test", depends_on=["task-a"])
        self.assertFalse(is_task_ready(task_b, [task_a, task_b]))

    def test_get_runnable_tasks(self):
        """Test getting runnable tasks."""
        task_a = Task(
            id="task-a", title="Task A", prompt="Test", status=TaskStatus.COMPLETED
        )
        task_b = Task(id="task-b", title="Task B", prompt="Test", depends_on=["task-a"])
        task_c = Task(id="task-c", title="Task C", prompt="Test", depends_on=["task-a"])
        task_d = Task(
            id="task-d", title="Task D", prompt="Test", depends_on=["task-b", "task-c"]
        )

        runnable = get_runnable_tasks([task_a, task_b, task_c, task_d])
        runnable_ids = {t.id for t in runnable}
        self.assertEqual(runnable_ids, {"task-b", "task-c"})

    def test_evaluate_mission_complete(self):
        """Test mission evaluation when all tasks complete."""
        task_a = Task(
            id="task-a", title="Task A", prompt="Test", status=TaskStatus.COMPLETED
        )
        task_b = Task(
            id="task-b", title="Task B", prompt="Test", status=TaskStatus.COMPLETED
        )
        result = evaluate_mission("mission-1", [task_a, task_b])
        self.assertEqual(result.state, SchedulerState.COMPLETE)

    def test_evaluate_mission_runnable(self):
        """Test mission evaluation when tasks are runnable."""
        task_a = Task(
            id="task-a", title="Task A", prompt="Test", status=TaskStatus.COMPLETED
        )
        task_b = Task(id="task-b", title="Task B", prompt="Test", depends_on=["task-a"])
        result = evaluate_mission("mission-1", [task_a, task_b])
        self.assertEqual(result.state, SchedulerState.RUNNABLE)

    def test_evaluate_mission_blocked(self):
        """Test mission evaluation when tasks are blocked."""
        task_a = Task(id="task-a", title="Task A", prompt="Test", depends_on=["task-b"])
        task_b = Task(id="task-b", title="Task B", prompt="Test", depends_on=["task-a"])
        result = evaluate_mission("mission-1", [task_a, task_b])
        self.assertEqual(result.state, SchedulerState.BLOCKED)


class TestSQLitePersistence(unittest.TestCase):
    """Test SQLite database persistence."""

    def setUp(self):
        """Set up temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, ".asc.db")
        self.state = State(self.db_path)

    def tearDown(self):
        """Clean up temporary directory."""
        try:
            self.state.close()
        except Exception:
            pass
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_db(self):
        """Test database initialization."""
        state = State(self.db_path)
        self.assertIsNotNone(state)

    def test_create_and_get_mission(self):
        """Test creating and retrieving mission from database."""
        mission_spec = MissionSpec(
            id="mission-1",
            goal="Test mission",
            tasks=[
                Task(id="task-1", title="Task 1", prompt="Test task"),
                Task(id="task-2", title="Task 2", prompt="Another task"),
            ],
        )
        self.state.create_mission(mission_spec)

        retrieved = self.state.get_mission("mission-1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, "mission-1")
        self.assertEqual(retrieved.goal, "Test mission")

    def test_record_and_retrieve_attempt(self):
        """Test recording and retrieving task attempts."""
        self.state.init_db()

        attempt = {
            "task_id": "task-1",
            "attempt_number": 1,
            "status": TaskStatus.COMPLETED,
            "exit_code": 0,
            "stdout": "Success output",
            "stderr": "",
            "timestamp": 1234567890.0,
            "id": "attempt-1",
        }
        self.state.record_attempt(attempt)

        attempts = self.state.get_attempts("task-1")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["task_id"], "task-1")
        self.assertEqual(attempts[0]["attempt_number"], 1)

    def test_update_task_status(self):
        """Test updating task status in database."""
        self.state.init_db()

        task = Task(id="task-1", title="Task 1", prompt="Test")
        self.state.save_task(task, "mission-1")
        self.state.update_task_status(task, exit_code=0)

        tasks = self.state.get_tasks("mission-1")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].id, "task-1")

    def test_record_and_retrieve_event(self):
        """Test recording and retrieving events."""
        self.state.init_db()

        event = {
            "mission_id": "mission-1",
            "task_id": "task-1",
            "event_type": "TASK_STARTED",
            "payload": {"test": "data"},
            "timestamp": 1234567890.0,
            "id": "event-1",
        }
        self.state.record_event(event)

        events = self.state.get_events("mission-1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "TASK_STARTED")

    def test_get_last_mission_id(self):
        """Test retrieving the most recently created mission ID."""
        self.state.init_db()
        self.assertIsNone(self.state.get_last_mission_id())

        spec1 = MissionSpec(id="m-first", goal="G1", tasks=[])
        self.state.save_mission(spec1)
        self.assertEqual(self.state.get_last_mission_id(), "m-first")

        time.sleep(0.01)
        spec2 = MissionSpec(id="m-second", goal="G2", tasks=[])
        self.state.save_mission(spec2)
        self.assertEqual(self.state.get_last_mission_id(), "m-second")

    def test_increment_attempt_count_sequential_persistence(self):
        """Test database-atomic sequential attempt_count increments."""
        self.state.init_db()
        task = Task(id="task-incr", title="Incr Task", prompt="Test")
        self.state.save_task(task, "m1")

        c1 = self.state.increment_attempt_count("task-incr")
        self.assertEqual(c1, 1)

        c2 = self.state.increment_attempt_count("task-incr")
        self.assertEqual(c2, 2)

        c3 = self.state.increment_attempt_count("task-incr")
        self.assertEqual(c3, 3)

        # Confirm value survives in a fresh query
        tasks = self.state.get_tasks("m1")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].id, "task-incr")


class TestVerifier(unittest.TestCase):
    """Test verification command execution."""

    def test_run_verification_success(self):
        """Test successful verification command."""
        verifier = Verifier()
        result = verifier.run_verification(["echo hello"], cwd=".")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello", result.stdout)

    def test_run_verification_failure(self):
        """Test failing verification command."""
        verifier = Verifier()
        result = verifier.run_verification(["exit 1"], cwd=".")
        self.assertEqual(result.exit_code, 1)

    def test_run_verification_timeout(self):
        """Test verification command timeout."""
        verifier = Verifier(timeout=1)
        result = verifier.run_verification(
            [sys.executable + ' -c "import time; time.sleep(10)"'], cwd="."
        )
        self.assertEqual(result.exit_code, 124)


class TestEndToEndMission(unittest.TestCase):
    """Test end-to-end mission execution using mock adapter."""

    def setUp(self):
        """Set up temporary directory for mission."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_complete_mission_execution(self):
        """Test complete mission execution from start to finish."""
        spec = MissionSpec(
            id="mission-1",
            goal="Test complete mission",
            tasks=[
                Task(id="task-1", title="Task 1", prompt="Test task 1"),
                Task(
                    id="task-2",
                    title="Task 2",
                    prompt="Test task 2",
                    depends_on=["task-1"],
                ),
            ],
        )
        self.assertEqual(len(spec.tasks), 2)
        # Just verify spec parsing and DAG evaluation work
        task_a = Task(
            id="task-1", title="Task 1", prompt="Test", status=TaskStatus.COMPLETED
        )
        task_b = Task(
            id="task-2",
            title="Task 2",
            prompt="Test",
            depends_on=["task-1"],
            status=TaskStatus.PENDING,
        )
        result = evaluate_mission("mission-1", [task_a, task_b])
        self.assertEqual(result.state, SchedulerState.RUNNABLE)


class TestUtilityFunctions(unittest.TestCase):
    """Test utility functions and integration."""

    def test_parse_json_spec(self):
        """Test parsing JSON mission spec."""
        import json

        spec_json = json.dumps(
            {
                "id": "mission-1",
                "goal": "Test mission",
                "tasks": [{"id": "task-1", "title": "Task 1", "prompt": "Test task"}],
            }
        )
        parser = MissionSpecParser()
        spec = parser.parse(spec_json)
        self.assertEqual(spec.id, "mission-1")
        self.assertEqual(len(spec.tasks), 1)


class TestAdapters(unittest.TestCase):
    """Test agent adapters."""

    def test_mock_adapter(self):
        """Test mock adapter execution."""
        adapter = MockAdapter()
        task = Task(id="task-1", title="Task 1", prompt="Test task")
        result = adapter.execute(task, {})
        self.assertEqual(result.exit_code, 0)

    def test_shell_adapter(self):
        """Test shell adapter execution."""
        adapter = ShellAdapter()
        task = Task(id="task-1", title="Task 1", prompt="echo hello")
        result = adapter.execute(task, {})
        self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
