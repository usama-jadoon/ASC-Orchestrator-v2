"""
Universal ASC v2.0.0 Mission Driver

Core execution loop for mission orchestration.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .adapters.mock import MockAdapter
from .adapters.omp import OMPAdapter
from .adapters.shell import ShellAdapter
from .dag import evaluate_mission, get_runnable_tasks
from .models import (
    AttemptRecord,
    SchedulerState,
    Task,
    TaskStatus,
)
from .repo import Repository
from .state import State
from .verifier import Verifier


def build_adapter(executor: str, timeout: int = 300) -> Any:
    """Construct an adapter for the named executor.

    Supported executors: ``omp`` (default), ``shell``, ``mock``.
    Returns Any to accommodate the duck-typed test MockAdapter which does
    not subclass AgentAdapter but satisfies the execute/can_execute contract.
    """
    executor = (executor or "omp").lower()
    if executor == "omp":
        return OMPAdapter(config=None)
    if executor == "shell":
        return ShellAdapter()
    if executor == "mock":
        return MockAdapter()
    raise ValueError(f"Unknown executor: {executor!r}")


class MissionDriver:
    """
    Universal ASC Mission Driver.

    Execution lifecycle:
    1. Load mission + tasks
    2. Evaluate scheduler state (RUNNABLE / COMPLETE / BLOCKED)
    3. While RUNNABLE: execute task -> verify -> (retry on failure) ->
       commit only after verification PASS -> mark COMPLETED
    4. Exit when COMPLETE or BLOCKED
    """

    def __init__(self, *args, **kwargs):
        """Initialize driver with flexible arguments."""
        if args and isinstance(args[0], State):
            self.state = args[0]
            self.db_path = kwargs.get("db_path") or (
                args[2] if len(args) > 2 else str(self.state.db_path)
            )
            self.timeout = kwargs.get("timeout") or (args[3] if len(args) > 3 else 300)
            self.mission_id = (
                kwargs.get("mission_id") or self.state.get_last_mission_id()
            )
            mission_record = (
                self.state.get_mission(self.mission_id) if self.mission_id else None
            )
            mission_executor = getattr(mission_record, "executor", None) if mission_record else None
            mission_wd = getattr(mission_record, "working_directory", None) if mission_record else None

            self.executor = kwargs.get("executor") or mission_executor or "omp"
            self.working_directory = kwargs.get("working_directory") or mission_wd
            self.spec_working_directory = self.working_directory

            if "adapter" in kwargs and kwargs["adapter"] is not None:
                self.adapter = kwargs["adapter"]
            elif len(args) > 1 and args[1] is not None:
                self.adapter = args[1]
            else:
                self.adapter = build_adapter(self.executor, self.timeout)

            self.repository = kwargs.get("repository", Repository())
            self._max_attempts = kwargs.get("max_attempts", 3)
        else:
            spec = kwargs.get("spec") or (args[0] if args else None)
            db_path = kwargs.get("db_path") or (
                args[1] if len(args) > 1 else ".asc/asc.db"
            )
            adapter = kwargs.get("adapter") or None
            timeout = kwargs.get("timeout") or (args[3] if len(args) > 3 else 300)

            self.state = State(db_path)
            self.db_path = db_path
            self.timeout = timeout
            self.repository = Repository()
            self.working_directory = kwargs.get("working_directory")

            # Resolve executor from explicit arg, spec, or defaults.
            spec_executor = getattr(spec, "executor", None) if spec else None
            spec_defaults = getattr(spec, "defaults", None) if spec else None
            default_executor = (
                getattr(spec_defaults, "executor", None) if spec_defaults else None
            )
            self.executor = (
                kwargs.get("executor") or spec_executor or default_executor or "omp"
            )
            self.adapter = adapter or (
                args[2] if len(args) > 2 else build_adapter(self.executor, timeout)
            )

            # Capture spec-level defaults for retry/working_directory
            if spec_defaults:
                self._max_attempts = getattr(spec_defaults, "max_attempts", 3)
                spec_wd = getattr(spec_defaults, "working_directory", None)
                if spec_wd:
                    self.spec_working_directory = spec_wd

            # Also capture spec-level working_directory
            spec_wd = getattr(spec, "working_directory", None) if spec else None
            if spec_wd:
                self.spec_working_directory = spec_wd

            if spec:
                self.state.save_mission(spec)
                self.mission_id = spec.id if hasattr(spec, "id") else spec.get("id")
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

        result: Dict[str, Any] = {
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
        while (
            outcome["state"] == SchedulerState.RUNNABLE
            or outcome["state"] == "RUNNABLE"
        ):
            task = self._get_next_task()
            if task is None:
                break

            # Execute task with retry logic (execute -> verify -> retry)
            is_success, exit_code = self._execute_task_with_retry(task)

            if is_success:
                self._complete_task(task)
                result["tasks_completed"] = int(result["tasks_completed"]) + 1
                if task.commit_sha:
                    result["git_commits"].append(task.commit_sha)
            else:
                # Exhausted retries -> mark failed and blocked
                task.status = TaskStatus.FAILED
                self.state.update_task_status(task, exit_code=exit_code)
                result["tasks_failed"] = int(result["tasks_failed"]) + 1
                self._block_task(task)
                result["tasks_blocked"] = int(result["tasks_blocked"]) + 1

            # Re-evaluate state
            outcome = self._evaluate()

        final_state = outcome["state"]
        result["final_status"] = (
            final_state.value if hasattr(final_state, "value") else str(final_state)
        )
        return result

    def _get_max_attempts(self, task: Task) -> int:
        """Get max_attempts from task defaults or spec defaults."""
        # Try task metadata first
        if task.metadata and "max_attempts" in task.metadata:
            return int(task.metadata["max_attempts"])
        # Fall back to driver/spec defaults
        return getattr(self, "_max_attempts", 3)

    def _execute_task_with_retry(self, task: Task) -> tuple[bool, int]:
        """Execute task through adapter then verify; retry on failure.

        Returns:
            (success: bool, exit_code: int)
        """
        max_attempts = self._get_max_attempts(task)
        attempt = 0
        last_exit_code = 1

        # Build execution context with working directory
        context = {
            "working_directory": (
                task.working_directory
                or self.working_directory
                or getattr(self, "spec_working_directory", None)
                or "."
            )
        }

        while attempt < max_attempts:
            attempt += 1

            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            self.state.update_task_status(task)

            # Log event
            self.state.record_event(
                {
                    "mission_id": self.mission_id,
                    "task_id": task.id,
                    "event_type": "TASK_STARTED",
                    "payload": {"title": task.title, "attempt": attempt},
                }
            )

            # Stage 1: EXECUTE via adapter
            if task.executor and task.executor.lower() != self.executor.lower():
                task_adapter = build_adapter(task.executor, self.timeout)
            else:
                task_adapter = self.adapter
            adapter_res = task_adapter.execute(task, context)
            exec_exit = getattr(adapter_res, "exit_code", 1)
            exec_stdout = getattr(adapter_res, "stdout", "")
            exec_stderr = getattr(adapter_res, "stderr", "")
            exec_success = exec_exit == 0
            # Record attempt
            attempt_record = AttemptRecord(
                id=f"att_{task.id}_{attempt}",
                task_id=task.id,
                attempt_number=attempt,
                status=TaskStatus.COMPLETED if exec_success else TaskStatus.FAILED,
                exit_code=exec_exit,
                stdout=exec_stdout,
                stderr=exec_stderr,
                timestamp=time.time(),
            )
            self.state.record_attempt(attempt_record)

            if not exec_success:
                last_exit_code = exec_exit
                # Execution failed -> retry if attempts remain
                continue

            # Stage 2: VERIFY if task has verification command
            if task.command and task.command.command:
                vr = self.verifier.run_verification(
                    [task.command],
                    cwd=context.get("working_directory", "."),
                )
                verify_exit = vr.exit_code
                verify_stdout = vr.stdout
                verify_stderr = vr.stderr

                # Record verification attempt
                verify_record = AttemptRecord(
                    id=f"att_{task.id}_{attempt}_verify",
                    task_id=task.id,
                    attempt_number=attempt,
                    status=TaskStatus.COMPLETED if vr.success else TaskStatus.FAILED,
                    exit_code=verify_exit,
                    stdout=verify_stdout,
                    stderr=verify_stderr,
                    timestamp=time.time(),
                )
                self.state.record_attempt(verify_record)

                if not vr.success:
                    last_exit_code = verify_exit
                    # Verification failed -> retry if attempts remain
                    continue

            # Both execution and verification succeeded
            return True, 0

        # Exhausted all attempts - mark task as failed
        task.status = TaskStatus.FAILED
        self.state.update_task_status(task, exit_code=last_exit_code)
        return False, last_exit_code

    def _complete_task(self, task: Task) -> None:
        """Mark task as completed and commit changes.

        Commits ONLY after verification PASS (this method is only called
        after successful verification).
        """
        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        self.state.update_task_status(task, exit_code=0)

        # Commit if git repository exists and has changes
        if self.repository.has_changes():
            commit_msg = f"feat({task.id}): {task.title}"
            sha = self.repository.commit(commit_msg)
            task.commit_sha = sha

        # Log event
        self.state.record_event(
            {
                "mission_id": self.mission_id,
                "task_id": task.id,
                "event_type": "TASK_COMPLETED",
                "payload": {"title": task.title, "commit_sha": task.commit_sha},
            }
        )

    def _block_task(self, task: Task) -> None:
        """Mark task as blocked."""
        task.status = TaskStatus.BLOCKED
        self.state.update_task_status(task)

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

    def _get_all_tasks(self) -> Dict[str, Task]:
        """Get all tasks for the current mission."""
        tasks = self.state.get_tasks(self.mission_id or "")
        return {t.id: t for t in tasks}
