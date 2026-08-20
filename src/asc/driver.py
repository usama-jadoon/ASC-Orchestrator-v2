"""
Universal ASC v2.0.0 Mission Driver

Core execution loop for mission orchestration.
"""

from __future__ import annotations

import time
from typing import Dict, Any, Optional

from .state import State
from .repo import Repository
from .verifier import Verifier
from .models import Task, TaskStatus, SchedulerState, AttemptRecord
from .dag import evaluate_mission, get_runnable_tasks
from .adapters.mock import MockAdapter
from .adapters.shell import ShellAdapter


class MissionDriver:
    """
    MissionDriver orchestrates mission execution from start to completion.

    Lifecycle:
    1. Load mission state
    2. Evaluate DAG for current state (RUNNABLE / COMPLETE / BLOCKED)
    3. While RUNNABLE: dispatch task -> adapter -> verify -> commit -> mark COMPLETED
    4. Exit when COMPLETE or BLOCKED
    """

    def __init__(self, *args, **kwargs):
        """Initialize driver with flexible arguments."""
        if args and isinstance(args[0], State):
            self.state = args[0]
            self.adapter = kwargs.get('adapter') or (args[1] if len(args) > 1 else ShellAdapter())
            self.repository = kwargs.get('repository', Repository())
            self.db_path = kwargs.get('db_path') or (args[2] if len(args) > 2 else '.asc/asc.db')
            self.timeout = kwargs.get('timeout') or (args[3] if len(args) > 3 else 300)
            self.mission_id = kwargs.get('mission_id') or self.state.get_last_mission_id()
        else:
            spec = kwargs.get('spec') or (args[0] if args else None)
            db_path = kwargs.get('db_path') or (args[1] if len(args) > 1 else '.asc/asc.db')
            adapter = kwargs.get('adapter') or (args[2] if len(args) > 2 else ShellAdapter())
            timeout = kwargs.get('timeout') or (args[3] if len(args) > 3 else 300)

            self.state = State(db_path)
            self.adapter = adapter
            self.db_path = db_path
            self.timeout = timeout
            self.repository = Repository()

            if spec:
                self.state.save_mission(spec)
                self.mission_id = spec.id if hasattr(spec, 'id') else spec.get('id')
            else:
                self.mission_id = self.state.get_last_mission_id()

        self.verifier = Verifier(timeout=self.timeout)

    def run(self, mission_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute mission from given mission ID.

        Args:
            mission_id: ID of mission to execute

        Returns:
            Summary dict with execution results
        """
        if mission_id:
            self.mission_id = mission_id
        if not self.mission_id:
            self.mission_id = self.state.get_last_mission_id()

        result = {
            "mission_id": self.mission_id,
            "final_status": None,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_blocked": 0,
            "git_commits": [],
            "error": None,
        }

        # Initial state evaluation
        outcome = self._evaluate()

        # Main execution loop
        while outcome["state"] == SchedulerState.RUNNABLE or outcome["state"] == "RUNNABLE":
            task = self._get_next_task()
            if task is None:
                break

            # Execute task
            is_success, exit_code = self._execute_task(task)

            if is_success:
                self._complete_task(task)
                result["tasks_completed"] += 1
            else:
                task.status = TaskStatus.FAILED
                self.state.update_task_status(task, exit_code=exit_code)
                result["tasks_failed"] += 1

                # Record attempt
                attempt_record = AttemptRecord(
                    id=f"att_{task.id}_{time.time()}",
                    task_id=task.id,
                    attempt_number=1,
                    status=TaskStatus.FAILED,
                    exit_code=exit_code,
                    timestamp=time.time(),
                )
                self.state.record_attempt(attempt_record)

                # Mark as blocked on failure
                self._block_task(task)
                result["tasks_blocked"] += 1

            # Re-evaluate state
            outcome = self._evaluate()

        final_state = outcome["state"]
        result["final_status"] = final_state.value if hasattr(final_state, "value") else str(final_state)
        return result

    def _evaluate(self) -> Dict[str, Any]:
        """Evaluate current mission state."""
        tasks = self._get_all_tasks()
        eval_res = evaluate_mission(self.mission_id or "default", tasks)
        return {
            "state": eval_res.state,
            "runnable": eval_res.runnable_tasks,
            "diagnostics": eval_res.blocked_ids,
        }

    def _get_next_task(self) -> Optional[Task]:
        """Get the next task to execute."""
        tasks = self._get_all_tasks()
        runnable = get_runnable_tasks(tasks)
        return runnable[0] if runnable else None

    def _execute_task(self, task: Task) -> tuple[bool, int]:
        """
        Execute a task through adapter and verifier.

        Returns:
            (success: bool, exit_code: int)
        """
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        self.state.update_task_status(task)

        # Log event
        self.state.record_event({
            "mission_id": self.mission_id,
            "task_id": task.id,
            "event_type": "TASK_STARTED",
            "payload": {"title": task.title},
        })

        # Run verification command if task has one
        if task.command and task.command.command:
            vr = self.verifier.run_verification([task.command])
            is_success = (vr.exit_code == 0)
            exit_code = vr.exit_code
        else:
            # Fallback to adapter execution
            adapter_res = self.adapter.execute(task, {})
            exit_code = getattr(adapter_res, 'exit_code', 0)
            is_success = (exit_code == 0)

        return is_success, exit_code

    def _complete_task(self, task: Task) -> None:
        """Mark task as completed and update state."""
        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        self.state.update_task_status(task, exit_code=0)

        # Commit if git repository exists and has changes
        if self.repository.has_changes():
            commit_msg = f"feat({task.id}): {task.title}"
            sha = self.repository.commit(commit_msg)
            task.commit_sha = sha

        # Log event
        self.state.record_event({
            "mission_id": self.mission_id,
            "task_id": task.id,
            "event_type": "TASK_COMPLETED",
            "payload": {"title": task.title},
        })

    def _block_task(self, task: Task) -> None:
        """Mark task as blocked."""
        task.status = TaskStatus.BLOCKED
        self.state.update_task_status(task)

    def _get_all_tasks(self) -> Dict[str, Task]:
        """Get all tasks for the current mission."""
        tasks = self.state.get_tasks(self.mission_id or "")
        return {t.id: t for t in tasks}
