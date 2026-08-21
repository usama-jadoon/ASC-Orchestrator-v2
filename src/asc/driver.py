"""Universal ASC v2.2.0 - Mission Driver.

Core execution loop for mission orchestration with event streaming,
project locking, scoped git staging, and safe retry rollback.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .adapters.mock import MockAdapter
from .adapters.omp import OMPAdapter
from .adapters.shell import ShellAdapter
from .dag import evaluate_mission, get_runnable_tasks
from .events import Event, EventEmitter, EventListener, EventType
from .lock import LockConflictError, ProjectLock
from .models import (
    AttemptRecord,
    SchedulerState,
    Task,
    TaskStatus,
)
from .repo import Repository
from .state import State
from .verifier import Verifier


def build_adapter(executor: str, timeout: int = 600) -> Any:
    """Construct an adapter for the named executor.

    Supported executors: ``omp`` (default), ``shell``, ``mock``.
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
    1. Acquire ProjectLock
    2. Load mission + tasks
    3. Evaluate scheduler state (RUNNABLE / COMPLETE / BLOCKED)
    4. While RUNNABLE: execute task -> verify -> (retry with safe delta rollback on failure) ->
       commit only after verification PASS -> mark COMPLETED
    5. Release ProjectLock and exit
    """

    def __init__(self, *args, **kwargs):
        """Initialize driver with flexible arguments."""
        self.events = EventEmitter()
        if "event_listener" in kwargs and kwargs["event_listener"]:
            self.events.subscribe(kwargs["event_listener"])

        if args and isinstance(args[0], State):
            self.state = args[0]
            self.db_path = kwargs.get("db_path") or (
                args[2] if len(args) > 2 else str(self.state.db_path)
            )
            self.timeout = kwargs.get("timeout") or (args[3] if len(args) > 3 else 600)
            self.execution_timeout = kwargs.get("execution_timeout", self.timeout)
            self.verification_timeout = kwargs.get("verification_timeout", 300)
            self.mission_id = (
                kwargs.get("mission_id") or self.state.get_last_mission_id()
            )
            mission_record = (
                self.state.get_mission(self.mission_id) if self.mission_id else None
            )
            mission_executor = (
                getattr(mission_record, "executor", None) if mission_record else None
            )
            mission_wd = (
                getattr(mission_record, "working_directory", None)
                if mission_record
                else None
            )

            self.executor = kwargs.get("executor") or mission_executor or "omp"
            self.working_directory = kwargs.get("working_directory") or mission_wd
            self.spec_working_directory = self.working_directory

            if "adapter" in kwargs and kwargs["adapter"] is not None:
                self.adapter = kwargs["adapter"]
            elif len(args) > 1 and args[1] is not None:
                self.adapter = args[1]
            else:
                self.adapter = build_adapter(self.executor, self.execution_timeout)

            self.repository = kwargs.get("repository", Repository(self.working_directory or "."))
            self._max_attempts = kwargs.get("max_attempts", 3)
            self.model = kwargs.get("model")
        else:
            spec = kwargs.get("spec") or (args[0] if args else None)
            db_path = kwargs.get("db_path") or (
                args[1] if len(args) > 1 else None
            )
            adapter = kwargs.get("adapter") or None
            timeout = kwargs.get("timeout") or (args[3] if len(args) > 3 else 600)

            self.state = State(db_path, cwd=kwargs.get("working_directory") or ".")
            self.db_path = str(self.state.db_path)
            self.timeout = timeout
            self.working_directory = kwargs.get("working_directory")

            # Resolve executor and timeouts from spec/defaults
            spec_executor = getattr(spec, "executor", None) if spec else None
            spec_defaults = getattr(spec, "defaults", None) if spec else None
            default_executor = (
                getattr(spec_defaults, "executor", None) if spec_defaults else None
            )
            self.executor = (
                kwargs.get("executor") or spec_executor or default_executor or "omp"
            )
            self.execution_timeout = (
                kwargs.get("execution_timeout")
                or (getattr(spec, "execution_timeout", None) if spec else None)
                or (getattr(spec_defaults, "execution_timeout", None) if spec_defaults else None)
                or timeout
            )
            self.verification_timeout = (
                kwargs.get("verification_timeout")
                or (getattr(spec, "verification_timeout", None) if spec else None)
                or (getattr(spec_defaults, "verification_timeout", None) if spec_defaults else None)
                or 300
            )

            self.adapter = adapter or (
                args[2] if len(args) > 2 else build_adapter(self.executor, self.execution_timeout)
            )

            if spec_defaults:
                self._max_attempts = getattr(spec_defaults, "max_attempts", 3)
                spec_wd = getattr(spec_defaults, "working_directory", None)
                if spec_wd:
                    self.spec_working_directory = spec_wd

            spec_wd = getattr(spec, "working_directory", None) if spec else None
            if spec_wd:
                self.spec_working_directory = spec_wd

            self.model = (
                kwargs.get("model")
                or (getattr(spec, "model", None) if spec else None)
                or (getattr(spec_defaults, "model", None) if spec_defaults else None)
            )

            self.repository = Repository(self.working_directory or getattr(self, "spec_working_directory", None) or ".")

            if spec:
                self.state.create_mission(spec)
                self.mission_id = spec.id if hasattr(spec, "id") else spec.get("id")
            else:
                self.mission_id = self.state.get_last_mission_id()

        self.verifier = Verifier(timeout=self.verification_timeout)

    def _emit(self, event_type: EventType, task_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None, message: str = "") -> None:
        """Emit domain event and record in state."""
        event = Event(
            event_type=event_type,
            mission_id=self.mission_id,
            task_id=task_id,
            timestamp=time.time(),
            payload=payload or {},
            message=message,
        )
        self.events.emit(event)
        self.state.record_event(event.to_dict())

    def run(self, mission_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute mission protected by project execution lock.
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

        # Resolve repository and lock directory
        target_dir = (
            self.working_directory
            or getattr(self, "spec_working_directory", None)
            or "."
        )
        repo = Repository(target_dir)
        lock_dir = repo.get_root_dir() / ".git" / "asc" if repo.is_git_repo() else Path(target_dir) / ".asc"

        lock = ProjectLock(lock_dir=lock_dir, mission_id=self.mission_id)
        try:
            lock.acquire()
            self._emit(EventType.LOCK_ACQUIRED, payload={"lock_dir": str(lock_dir)})
        except LockConflictError as exc:
            self._emit(EventType.LOCK_CONFLICT, payload={"error": str(exc)})
            result["error"] = str(exc)
            result["final_status"] = "BLOCKED"
            raise

        try:
            self._emit(EventType.MISSION_STARTED, payload={"mission_id": self.mission_id, "executor": self.executor, "model": self.model})
            self.state.update_mission_status(self.mission_id or "", "RUNNING")

            outcome = self._evaluate()

            while (
                outcome["state"] == SchedulerState.RUNNABLE
                or outcome["state"] == "RUNNABLE"
                or outcome["state"] == SchedulerState.RUNNING
                or outcome["state"] == "RUNNING"
            ):
                task = self._get_next_task()
                if task is None:
                    break

                self._emit(EventType.TASK_READY, task_id=task.id, payload={"title": task.title})
                is_success, exit_code = self._execute_task_with_retry(task)

                if is_success:
                    self._complete_task(task)
                    result["tasks_completed"] = int(result["tasks_completed"]) + 1
                    if task.commit_sha:
                        result["git_commits"].append(task.commit_sha)
                else:
                    task.status = TaskStatus.FAILED
                    self.state.update_task_status(task.id, TaskStatus.FAILED, exit_code=exit_code)
                    self._emit(EventType.TASK_FAILED, task_id=task.id, payload={"exit_code": exit_code})
                    result["tasks_failed"] = int(result["tasks_failed"]) + 1
                    self._block_task(task)
                    result["tasks_blocked"] = int(result["tasks_blocked"]) + 1

                outcome = self._evaluate()

            final_state = outcome["state"]
            status_str = final_state.value if hasattr(final_state, "value") else str(final_state)
            result["final_status"] = status_str

            if status_str == "COMPLETE":
                self._emit(EventType.MISSION_COMPLETED, payload={"tasks_completed": result["tasks_completed"]})
                self.state.update_mission_status(self.mission_id or "", "COMPLETE")
            else:
                self._emit(EventType.MISSION_BLOCKED, payload={"tasks_blocked": result["tasks_blocked"]})
                self.state.update_mission_status(self.mission_id or "", "BLOCKED")

            return result
        finally:
            lock.release()
            self._emit(EventType.LOCK_RELEASED)

    def _get_max_attempts(self, task: Task) -> int:
        """Get max_attempts from task metadata or defaults."""
        if task.metadata and "max_attempts" in task.metadata:
            return int(task.metadata["max_attempts"])
        return getattr(self, "_max_attempts", 3)

    def _execute_task_with_retry(self, task: Task) -> tuple[bool, int]:
        """Execute task through adapter then verify; retry with safe delta rollback on failure."""
        max_attempts = self._get_max_attempts(task)
        attempt = 0
        last_exit_code = 1

        repo_dir = (
            task.working_directory
            or self.working_directory
            or getattr(self, "spec_working_directory", None)
            or "."
        )
        task_repo = Repository(repo_dir)

        task_model = (
            task.model or getattr(self, "model", None) or os.environ.get("OMP_MODEL")
        )
        exec_timeout = task.execution_timeout or self.execution_timeout
        verify_timeout = (task.command.timeout if task.command else None) or self.verification_timeout

        def heartbeat(elapsed: float):
            self._emit(
                EventType.EXECUTOR_HEARTBEAT,
                task_id=task.id,
                payload={"attempt": attempt, "elapsed_seconds": round(elapsed, 1)},
            )

        context = {
            "working_directory": repo_dir,
            "model": task_model,
            "execution_timeout": exec_timeout,
            "heartbeat_callback": heartbeat,
        }

        while attempt < max_attempts:
            attempt = self.state.increment_attempt_count(task.id)

            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            self.state.update_task_status(task.id, TaskStatus.RUNNING, started_at=task.started_at)

            self._emit(
                EventType.TASK_STARTED,
                task_id=task.id,
                payload={"title": task.title, "attempt": attempt, "max_attempts": max_attempts, "executor": task.executor or self.executor, "model": task_model},
                message=f"Starting task '{task.id}' attempt {attempt}/{max_attempts}",
            )

            # Capture baseline dirty state before this attempt
            baseline_dirty = set(task_repo.get_dirty_files()) if task_repo.is_git_repo() else set()

            # Stage 1: EXECUTE via adapter
            if task.executor and task.executor.lower() != self.executor.lower():
                task_adapter = build_adapter(task.executor, exec_timeout)
            else:
                task_adapter = self.adapter

            self._emit(EventType.EXECUTOR_STARTED, task_id=task.id, payload={"attempt": attempt, "executor": task.executor or self.executor})
            adapter_res = task_adapter.execute(task, context)
            exec_exit = getattr(adapter_res, "exit_code", 1)
            exec_stdout = getattr(adapter_res, "stdout", "")
            exec_stderr = getattr(adapter_res, "stderr", "")
            exec_success = exec_exit == 0

            if exec_success:
                self._emit(EventType.EXECUTOR_COMPLETED, task_id=task.id, payload={"attempt": attempt, "exit_code": 0})
            else:
                self._emit(EventType.EXECUTOR_FAILED, task_id=task.id, payload={"attempt": attempt, "exit_code": exec_exit, "stderr": exec_stderr[:300]})

            # Record attempt
            self.state.record_attempt(
                task_id=task.id,
                attempt_number=attempt,
                status=TaskStatus.COMPLETED if exec_success else TaskStatus.FAILED,
                exit_code=exec_exit,
                stdout=exec_stdout,
                stderr=exec_stderr,
                timestamp=time.time(),
            )

            # Discover delta files produced by this attempt
            current_dirty = set(task_repo.get_dirty_files()) if task_repo.is_git_repo() else set()
            task_delta = sorted(current_dirty - baseline_dirty)
            if task_delta:
                self._emit(EventType.GIT_CHANGESET_DETECTED, task_id=task.id, payload={"delta_files": task_delta})

            if not exec_success:
                last_exit_code = exec_exit
                # Rollback only attempt delta files
                if task_delta:
                    task_repo.rollback_attempt(task_delta)
                if attempt < max_attempts:
                    self._emit(EventType.TASK_RETRY, task_id=task.id, payload={"attempt": attempt, "next_attempt": attempt + 1})
                continue

            # Stage 2: VERIFY if task has verification command
            if task.command and task.command.command:
                effective_cwd = str(repo_dir)
                self._emit(EventType.VERIFICATION_STARTED, task_id=task.id, payload={"command": task.command.command})
                vr = self.verifier.run_verification(
                    [task.command],
                    cwd=effective_cwd,
                )
                verify_exit = vr.exit_code
                verify_stdout = vr.stdout
                verify_stderr = vr.stderr

                self.state.record_attempt(
                    task_id=task.id,
                    attempt_number=attempt,
                    status=TaskStatus.COMPLETED if vr.success else TaskStatus.FAILED,
                    exit_code=verify_exit,
                    stdout=verify_stdout,
                    stderr=verify_stderr,
                    timestamp=time.time(),
                )

                if vr.success:
                    self._emit(EventType.VERIFICATION_PASSED, task_id=task.id, payload={"attempt": attempt})
                else:
                    self._emit(EventType.VERIFICATION_FAILED, task_id=task.id, payload={"attempt": attempt, "exit_code": verify_exit, "stderr": verify_stderr[:300]})
                    last_exit_code = verify_exit
                    # Rollback attempt delta
                    if task_delta:
                        task_repo.rollback_attempt(task_delta)
                    if attempt < max_attempts:
                        self._emit(EventType.TASK_RETRY, task_id=task.id, payload={"attempt": attempt, "next_attempt": attempt + 1})
                    continue

            # Execution + verification passed!
            return True, 0

        # Exhausted attempts
        task.status = TaskStatus.FAILED
        self.state.update_task_status(task.id, TaskStatus.FAILED, exit_code=last_exit_code)
        return False, last_exit_code

    def _complete_task(self, task: Task) -> None:
        """Mark task as completed and commit scoped changes."""
        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        self.state.update_task_status(task.id, TaskStatus.COMPLETED, completed_at=task.completed_at, exit_code=0)

        repo_dir = (
            task.working_directory
            or self.working_directory
            or getattr(self, "spec_working_directory", None)
            or "."
        )
        task_repo = Repository(repo_dir)

        if task_repo.has_changes():
            commit_msg = f"feat({task.id}): {task.title}"
            self._emit(EventType.GIT_COMMIT_STARTED, task_id=task.id, payload={"message": commit_msg})
            sha = task_repo.commit_scoped(
                commit_msg,
                commit_paths_filter=task.commit_paths,
            )
            task.commit_sha = sha
            if sha:
                self.state.update_task_status(task.id, TaskStatus.COMPLETED, commit_sha=sha)
                self._emit(EventType.GIT_COMMIT_CREATED, task_id=task.id, payload={"commit_sha": sha})

        self._emit(
            EventType.TASK_COMPLETED,
            task_id=task.id,
            payload={"title": task.title, "commit_sha": task.commit_sha},
            message=f"Completed task '{task.id}'",
        )

    def _block_task(self, task: Task) -> None:
        """Mark task as blocked."""
        task.status = TaskStatus.BLOCKED
        self.state.update_task_status(task.id, TaskStatus.BLOCKED)

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
