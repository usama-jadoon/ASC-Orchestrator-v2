"""Universal ASC v2.3.0 - Mission Driver.

Core execution loop for mission orchestration with centralized repository preflight,
strict path precedence, composite task identity, stale execution reconciliation,
scoped git delta commits, and multi-command verification.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .adapters.mock import MockAdapter
from .adapters.omp import OMPAdapter
from .adapters.shell import ShellAdapter
from .dag import evaluate_mission, get_runnable_tasks
from .events import Event, EventEmitter, EventType
from .lock import LockConflictError, ProjectLock
from .models import (
    SchedulerState,
    Task,
    TaskStatus,
)
from .repo import Repository
from .state import State
from .verifier import Verifier


class TaskExecutionOutcome(tuple):
    """Execution outcome tuple supporting both (success, exit_code) and .delta access."""

    delta: List[str]

    def __new__(cls, success: bool, exit_code: int, delta: Optional[List[str]] = None):
        instance = super().__new__(cls, (success, exit_code))
        instance.delta = delta or []
        return instance

    @property
    def success(self) -> bool:
        return self[0]

    @property
    def exit_code(self) -> int:
        return self[1]


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
    2. Centralized repository preflight (clean working tree verification)
    3. Reconcile stale interrupted tasks if resuming from crash
    4. Evaluate scheduler state (RUNNABLE / COMPLETE / BLOCKED)
    5. Execute tasks with retry & non-destructive rollback
    6. Multi-command verification & strict task delta commit
    7. Release ProjectLock and exit
    """

    def __init__(self, *args, **kwargs):
        """Initialize driver with strict path precedence and options."""
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
            self.cli_cwd = kwargs.get("working_directory") or kwargs.get("cwd")
            self.working_directory = self.cli_cwd or mission_wd
            self.spec_working_directory = self.working_directory

            if "adapter" in kwargs and kwargs["adapter"] is not None:
                self.adapter = kwargs["adapter"]
            elif len(args) > 1 and args[1] is not None:
                self.adapter = args[1]
            else:
                self.adapter = build_adapter(self.executor, self.execution_timeout)

            self.repository = kwargs.get(
                "repository", Repository(self.working_directory or ".")
            )
            self._max_attempts = kwargs.get("max_attempts", 3)
            self.model = kwargs.get("model")
        else:
            spec = kwargs.get("spec") or (args[0] if args else None)
            adapter = kwargs.get("adapter") or None
            timeout = kwargs.get("timeout") or (args[3] if len(args) > 3 else 600)

            # Resolve path precedence
            cli_override_cwd = kwargs.get("working_directory") or kwargs.get("cwd")
            spec_wd = getattr(spec, "working_directory", None) if spec else None
            spec_defaults = getattr(spec, "defaults", None) if spec else None
            default_wd = (
                getattr(spec_defaults, "working_directory", None)
                if spec_defaults
                else None
            )

            effective_wd = cli_override_cwd or spec_wd or default_wd or "."
            self.working_directory = effective_wd
            self.spec_working_directory = spec_wd or default_wd

            db_path = kwargs.get("db_path") or (args[1] if len(args) > 1 else None)
            self.state = State(db_path, cwd=effective_wd)
            self.db_path = str(self.state.db_path)
            self.timeout = timeout

            # Resolve executor and timeouts
            spec_executor = getattr(spec, "executor", None) if spec else None
            default_executor = (
                getattr(spec_defaults, "executor", None) if spec_defaults else None
            )
            self.executor = (
                kwargs.get("executor") or spec_executor or default_executor or "omp"
            )
            self.execution_timeout = (
                kwargs.get("execution_timeout")
                or (getattr(spec, "execution_timeout", None) if spec else None)
                or (
                    getattr(spec_defaults, "execution_timeout", None)
                    if spec_defaults
                    else None
                )
                or timeout
            )
            self.verification_timeout = (
                kwargs.get("verification_timeout")
                or (getattr(spec, "verification_timeout", None) if spec else None)
                or (
                    getattr(spec_defaults, "verification_timeout", None)
                    if spec_defaults
                    else None
                )
                or 300
            )

            self.adapter = adapter or (
                args[2]
                if len(args) > 2
                else build_adapter(self.executor, self.execution_timeout)
            )

            self._max_attempts = kwargs.get("max_attempts") or (
                getattr(spec_defaults, "max_attempts", 3) if spec_defaults else 3
            )
            self.model = (
                kwargs.get("model")
                or (getattr(spec, "model", None) if spec else None)
                or (getattr(spec_defaults, "model", None) if spec_defaults else None)
            )

            self.repository = Repository(self.working_directory)

            if spec:
                self.state.save_mission(spec)
                self.mission_id = spec.id if hasattr(spec, "id") else spec.get("id")
            else:
                self.mission_id = self.state.get_last_mission_id()

        self.verifier = Verifier(timeout=self.verification_timeout)

    def _emit(
        self,
        event_type: EventType,
        task_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        message: str = "",
    ) -> None:
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

    def _reconcile_stale_tasks(self) -> None:
        """
        Reconcile tasks that were left in RUNNING status due to a process crash or interruption.
        Restores them to INTERRUPTED (runnable) if attempts remain, preserving evidence.
        """
        if not self.mission_id:
            return
        tasks = self.state.get_tasks(self.mission_id)
        for t in tasks:
            if t.status == TaskStatus.RUNNING:
                max_att = self._get_max_attempts(t)
                attempts = self.state.get_attempts(t.id, mission_id=self.mission_id)
                current_att_count = len(attempts)

                self._emit(
                    EventType.TASK_FAILED,
                    task_id=t.id,
                    payload={
                        "reason": "Process interruption detected; reconciling stale RUNNING state",
                        "attempt_count": current_att_count,
                    },
                    message=f"Reconciling interrupted task '{t.id}'",
                )

                if current_att_count < max_att:
                    new_status = TaskStatus.INTERRUPTED
                else:
                    new_status = TaskStatus.FAILED

                self.state.update_task_status(
                    t.id,
                    new_status,
                    mission_id=self.mission_id,
                    completed_at=time.time(),
                )
                t.status = new_status

    def run(self, mission_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute mission protected by project lock and centralized repository preflight.
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
        target_dir = self.working_directory or getattr(
            self, "spec_working_directory", None
        )
        repo = Repository(target_dir) if target_dir else self.repository
        lock_dir = (
            repo.get_root_dir() / ".git" / "asc"
            if repo.is_git_repo()
            else Path(target_dir or ".") / ".asc"
        )

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
            # Centralized Repository Preflight Safety Invariant
            if repo.is_git_repo() and not repo.is_clean():
                dirty_files = repo.get_dirty_files()
                err_msg = (
                    f"Repository preflight check failed: target repository '{repo.path}' "
                    f"has {len(dirty_files)} uncommitted/untracked change(s): {dirty_files[:5]}"
                )
                self._emit(
                    EventType.MISSION_BLOCKED,
                    payload={"error": err_msg, "dirty_files": dirty_files},
                )
                result["error"] = err_msg
                result["final_status"] = "BLOCKED"
                raise RuntimeError(err_msg)

            # Reconcile any stale RUNNING tasks from previous interrupted executions
            self._reconcile_stale_tasks()

            self._emit(
                EventType.MISSION_STARTED,
                payload={
                    "mission_id": self.mission_id,
                    "executor": self.executor,
                    "model": self.model,
                    "working_directory": str(repo.path),
                },
            )
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

                self._emit(
                    EventType.TASK_READY, task_id=task.id, payload={"title": task.title}
                )
                exec_outcome = self._execute_task_with_retry(task)
                is_success, exit_code = exec_outcome[0], exec_outcome[1]
                task_delta = getattr(exec_outcome, "delta", [])

                if is_success:
                    self._complete_task(task, task_delta)
                    result["tasks_completed"] = int(result["tasks_completed"]) + 1
                    if task.commit_sha:
                        result["git_commits"].append(task.commit_sha)
                else:
                    task.status = TaskStatus.FAILED
                    self.state.update_task_status(
                        task.id,
                        TaskStatus.FAILED,
                        exit_code=exit_code,
                        mission_id=self.mission_id,
                    )
                    self._emit(
                        EventType.TASK_FAILED,
                        task_id=task.id,
                        payload={"exit_code": exit_code},
                    )
                    result["tasks_failed"] = int(result["tasks_failed"]) + 1
                    self._block_task(task)
                    result["tasks_blocked"] = int(result["tasks_blocked"]) + 1

                outcome = self._evaluate()

            final_state = outcome["state"]
            status_str = (
                final_state.value if hasattr(final_state, "value") else str(final_state)
            )
            result["final_status"] = status_str

            if status_str == "COMPLETE":
                self._emit(
                    EventType.MISSION_COMPLETED,
                    payload={"tasks_completed": result["tasks_completed"]},
                )
                self.state.update_mission_status(self.mission_id or "", "COMPLETE")
            else:
                self._emit(
                    EventType.MISSION_BLOCKED,
                    payload={"tasks_blocked": result["tasks_blocked"]},
                )
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

    def _execute_task_with_retry(self, task: Task) -> TaskExecutionOutcome:
        """
        Execute task through adapter then verify with multi-command support.
        Retries with safe attempt delta rollback on failure.
        """
        max_attempts = self._get_max_attempts(task)
        attempt = 0
        last_exit_code = 1
        last_delta: List[str] = []

        if task.working_directory:
            task_repo = Repository(task.working_directory)
            effective_cwd = task.working_directory
        elif self.working_directory and self.working_directory != ".":
            task_repo = Repository(self.working_directory)
            effective_cwd = self.working_directory
        else:
            task_repo = self.repository
            effective_cwd = str(self.repository.path)

        task_model = (
            task.model or getattr(self, "model", None) or os.environ.get("OMP_MODEL")
        )
        exec_timeout = task.execution_timeout or self.execution_timeout
        verify_timeout = (
            task.command.timeout if task.command else None
        ) or self.verification_timeout

        def heartbeat(elapsed: float):
            self._emit(
                EventType.EXECUTOR_HEARTBEAT,
                task_id=task.id,
                payload={"attempt": attempt, "elapsed_seconds": round(elapsed, 1)},
            )

        context = {
            "working_directory": effective_cwd,
            "model": task_model,
            "execution_timeout": exec_timeout,
            "heartbeat_callback": heartbeat,
        }

        while attempt < max_attempts:
            attempt = self.state.increment_attempt_count(
                task.id, mission_id=self.mission_id
            )

            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            self.state.update_task_status(
                task.id,
                TaskStatus.RUNNING,
                started_at=task.started_at,
                mission_id=self.mission_id,
            )

            self._emit(
                EventType.TASK_STARTED,
                task_id=task.id,
                payload={
                    "title": task.title,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "executor": task.executor or self.executor,
                    "model": task_model,
                },
                message=f"Starting task '{task.id}' attempt {attempt}/{max_attempts}",
            )

            # Capture baseline dirty state before this attempt
            baseline_dirty = (
                set(task_repo.get_dirty_files()) if task_repo.is_git_repo() else set()
            )

            # Stage 1: EXECUTE via adapter
            if task.executor and task.executor.lower() != self.executor.lower():
                task_adapter = build_adapter(task.executor, exec_timeout)
            else:
                task_adapter = self.adapter

            self._emit(
                EventType.EXECUTOR_STARTED,
                task_id=task.id,
                payload={
                    "attempt": attempt,
                    "executor": task.executor or self.executor,
                },
            )
            adapter_res = task_adapter.execute(task, context)
            exec_exit = getattr(adapter_res, "exit_code", 1)
            exec_stdout = getattr(adapter_res, "stdout", "")
            exec_stderr = getattr(adapter_res, "stderr", "")
            exec_duration = getattr(adapter_res, "duration", 0.0)
            exec_log_path = getattr(adapter_res, "log_path", None)
            exec_success = exec_exit == 0

            if exec_success:
                self._emit(
                    EventType.EXECUTOR_COMPLETED,
                    task_id=task.id,
                    payload={"attempt": attempt, "exit_code": 0},
                )
            else:
                self._emit(
                    EventType.EXECUTOR_FAILED,
                    task_id=task.id,
                    payload={
                        "attempt": attempt,
                        "exit_code": exec_exit,
                        "stderr": exec_stderr[:300],
                    },
                )

            # Record attempt
            self.state.record_attempt(
                task_id=task.id,
                attempt_number=attempt,
                status=TaskStatus.COMPLETED if exec_success else TaskStatus.FAILED,
                exit_code=exec_exit,
                stdout=exec_stdout,
                stderr=exec_stderr,
                timestamp=time.time(),
                mission_id=self.mission_id,
                duration=exec_duration,
                log_path=exec_log_path,
            )

            # Discover delta files produced by this attempt
            current_dirty = (
                set(task_repo.get_dirty_files()) if task_repo.is_git_repo() else set()
            )
            task_delta = sorted(current_dirty - baseline_dirty)
            last_delta = task_delta
            if task_delta:
                self._emit(
                    EventType.GIT_CHANGESET_DETECTED,
                    task_id=task.id,
                    payload={"delta_files": task_delta},
                )

            if not exec_success:
                last_exit_code = exec_exit
                # Rollback only attempt delta files safely
                if task_delta:
                    task_repo.rollback_attempt(task_delta)
                if attempt < max_attempts:
                    self._emit(
                        EventType.TASK_RETRY,
                        task_id=task.id,
                        payload={"attempt": attempt, "next_attempt": attempt + 1},
                    )
                continue

            # Stage 2: VERIFY with multi-command support
            verify_commands = task.commands or ([task.command] if task.command else [])
            if verify_commands:
                self._emit(
                    EventType.VERIFICATION_STARTED,
                    task_id=task.id,
                    payload={
                        "commands": [c.command for c in verify_commands if c],
                        "count": len(verify_commands),
                    },
                )

                try:
                    vr = self.verifier.run_verification(
                        verify_commands,
                        cwd=effective_cwd,
                        timeout=verify_timeout,
                    )
                except TypeError:
                    # Backward compatibility with simple custom test verifiers
                    vr = self.verifier.run_verification(
                        verify_commands,
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
                    mission_id=self.mission_id,
                    duration=getattr(vr, "duration", 0.0),
                )

                if vr.success:
                    self._emit(
                        EventType.VERIFICATION_PASSED,
                        task_id=task.id,
                        payload={
                            "attempt": attempt,
                            "duration": getattr(vr, "duration", 0.0),
                        },
                    )
                else:
                    self._emit(
                        EventType.VERIFICATION_FAILED,
                        task_id=task.id,
                        payload={
                            "attempt": attempt,
                            "exit_code": verify_exit,
                            "stderr": verify_stderr[:300],
                        },
                    )
                    last_exit_code = verify_exit
                    # Rollback attempt delta
                    if task_delta:
                        task_repo.rollback_attempt(task_delta)
                    if attempt < max_attempts:
                        self._emit(
                            EventType.TASK_RETRY,
                            task_id=task.id,
                            payload={"attempt": attempt, "next_attempt": attempt + 1},
                        )
                    continue

            # Execution + verification passed!
            return TaskExecutionOutcome(True, 0, task_delta)

        # Exhausted attempts
        task.status = TaskStatus.FAILED
        self.state.update_task_status(
            task.id,
            TaskStatus.FAILED,
            exit_code=last_exit_code,
            mission_id=self.mission_id,
        )
        return TaskExecutionOutcome(False, last_exit_code, last_delta)

    def _complete_task(
        self, task: Task, task_delta: Optional[List[str]] = None
    ) -> None:
        """Mark task as completed and commit only task-owned delta."""
        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        self.state.update_task_status(
            task.id,
            TaskStatus.COMPLETED,
            completed_at=task.completed_at,
            exit_code=0,
            mission_id=self.mission_id,
        )

        if task.working_directory:
            task_repo = Repository(task.working_directory)
        elif self.working_directory and self.working_directory != ".":
            task_repo = Repository(self.working_directory)
        else:
            task_repo = self.repository

        if task_repo.has_changes():
            commit_msg = f"feat({task.id}): {task.title}"
            self._emit(
                EventType.GIT_COMMIT_STARTED,
                task_id=task.id,
                payload={"message": commit_msg, "paths": task_delta or []},
            )
            sha = task_repo.commit_scoped(
                commit_msg,
                paths=task_delta
                if (task_delta is not None and len(task_delta) > 0)
                else None,
                commit_paths_filter=task.commit_paths,
            )
            task.commit_sha = sha
            if sha:
                self.state.update_task_status(
                    task.id,
                    TaskStatus.COMPLETED,
                    commit_sha=sha,
                    mission_id=self.mission_id,
                )
                self._emit(
                    EventType.GIT_COMMIT_CREATED,
                    task_id=task.id,
                    payload={"commit_sha": sha},
                )

        self._emit(
            EventType.TASK_COMPLETED,
            task_id=task.id,
            payload={"title": task.title, "commit_sha": task.commit_sha},
            message=f"Completed task '{task.id}'",
        )

    def _block_task(self, task: Task) -> None:
        """Mark task as blocked."""
        task.status = TaskStatus.BLOCKED
        self.state.update_task_status(
            task.id, TaskStatus.BLOCKED, mission_id=self.mission_id
        )

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
