"""
Universal ASC v2.0.0 Mission Driver

Core execution loop for mission orchestration.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
import subprocess

from .state import State
from .repo import Repository
from .verifier import Verifier
from .adapters.base import AgentResult
from .models import Task, TaskStatus
from .dag import evaluate_mission, get_runnable_tasks
from .adapters.mock import MockAdapter


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
        """Initialize driver with both old and new signatures.
        
        Old: MissionDriver(spec, db_path, adapter, timeout)
        New: MissionDriver(state, adapter, repository=None)
        """
        # Check for new signature (State first)
        if args and isinstance(args[0], State):
            self.state = args[0]
            self.adapter = kwargs.get('adapter') or (args[1] if len(args) > 1 else None)
            self.repository = kwargs.get('repository', Repository())
            self.db_path = kwargs.get('db_path') or (args[2] if len(args) > 2 else '.asc/asc.db')
            self.timeout = kwargs.get('timeout') or (args[3] if len(args) > 3 else 300)
        else:
            # Old signature (spec, db_path, adapter, timeout)
            spec = kwargs.get('spec') or (args[0] if args else None)
            db_path = kwargs.get('db_path') or (args[1] if len(args) > 1 else '.asc/asc.db')
            adapter = kwargs.get('adapter') or (args[2] if len(args) > 2 else MockAdapter())
            timeout = kwargs.get('timeout') or (args[3] if len(args) > 3 else 300)
            
            self.state = State(db_path)
            self.adapter = adapter
            self.db_path = db_path
            self.timeout = timeout
            self.repository = Repository()
            
            # Save mission spec and set mission_id
            if spec:
                self.state.create_mission(spec)
                self.mission_id = spec.mission.id if hasattr(spec, 'mission') else (spec.get('id') if isinstance(spec, dict) else spec.id)
            else:
                self.mission_id = None
        
        self.verifier = Verifier()
        if not hasattr(self, 'mission_id'):
            self.mission_id = None

    def run(self, mission_id: str = None) -> Dict[str, Any]:
        """
        Execute mission from given mission ID.

        Args:
            mission_id: ID of mission to execute

        Returns:
            Summary dict with execution results
        """
        if mission_id:
            self.mission_id = mission_id
        # If no mission_id set, use one from save_mission
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
        while outcome["state"] == "RUNNABLE":
            # Get next task to run
            task = self._get_next_task()
            if task is None:
                break

            # Execute task
            exec_result = self._execute_task(task)

            # On verification PASS: mark COMPLETED, create git commit
            if exec_result.success:
                self._complete_task(task)
                result["tasks_completed"] += 1
            else:
                # On FAIL: increment attempt count
                self.state.increment_task_attempt(self.mission_id, task.id)
                result["tasks_failed"] += 1

                # Check max attempts
                attempt_count = self.state.get_task_attempt_count(self.mission_id, task.id)
                max_attempts = task.max_attempts if hasattr(task, 'max_attempts') else 3
                if attempt_count >= max_attempts:
                    self._block_task(task)
                    result["tasks_blocked"] += 1

            # Re-evaluate state
            outcome = self._evaluate()

        result["final_status"] = outcome["state"]
        return result

    def _evaluate(self) -> Dict[str, Any]:
        """Evaluate current mission state."""
        tasks = self._get_all_tasks()
        state, runnable, diagnostics = evaluate_mission(tasks)
        return {
            "state": state,
            "runnable": runnable,
            "diagnostics": diagnostics,
        }

    def _get_next_task(self) -> Optional[Task]:
        """Get the next task to execute."""
        tasks = self._get_all_tasks()
        runnable = get_runnable_tasks(tasks)
        return runnable[0] if runnable else None

    def _execute_task(self, task: Task) -> AgentResult:
        """
        Execute a task through the adapter.
        
        Args:
            task: Task to execute
            
        Returns:
            AgentResult from execution
        """
        # Update task status to RUNNING
        self.state.update_task_status(self.mission_id, task.id, TaskStatus.RUNNING)
        
        # Execute via adapter
        result = self.adapter.execute(task)
        
        # If successful, verify the result
        if result.success:
            verification = self.verifier.verify(result, self.repository)
            result.verification = verification
            result.success = verification.passed
        
        return result

    def _complete_task(self, task: Task) -> None:
        """
        Mark task as completed and create git commit.
        
        Args:
            task: Task to complete
        """
        self.state.update_task_status(self.mission_id, task.id, TaskStatus.COMPLETED)
        
        # Create git commit
        if self.repository.has_changes():
            commit_msg = f"feat: complete task {task.id}"
            self.repository.commit(commit_msg)

    def _block_task(self, task: Task) -> None:
        """
        Mark task as blocked.
        
        Args:
            task: Task to block
        """
        self.state.update_task_status(self.mission_id, task.id, TaskStatus.BLOCKED)

    def _get_all_tasks(self) -> Dict[str, Task]:
        """Get all tasks for the current mission."""
        mission = self.state.get_mission(self.mission_id)
        return mission.tasks if mission else {}
