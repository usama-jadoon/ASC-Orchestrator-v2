"""
Universal ASC v2.0.0 Scheduler

Handles mission scheduling logic, task readiness, and execution ordering.
"""

from __future__ import annotations

from typing import Dict, Optional

from .dag import SchedulerOutcome, evaluate_mission, get_runnable_tasks, is_task_ready
from .models import Task, TaskStatus
from .state import State


class Scheduler:
    """Scheduler for mission execution."""

    def __init__(self, state: State):
        self.state = state

    def load_mission(self, mission_id: str) -> Optional[Dict[str, Task]]:
        """
        Load mission tasks from state.

        Args:
            mission_id: Mission ID

        Returns:
            Dictionary of tasks by ID or None if mission not found
        """
        mission_record = self.state.get_mission(mission_id)
        if mission_record is None:
            return None
        return mission_record.tasks

    def save_mission(self, mission_id: str, tasks: Dict[str, Task]) -> None:
        """
        Save mission tasks to state.

        Args:
            mission_id: Mission ID
            tasks: Dictionary of tasks by ID
        """
        # Update each task's status in the database
        for task in tasks.values():
            self.state.update_task_status(mission_id, task.id, task.status, task.commit_sha)

    def get_next_task(self, mission_id: str) -> Optional[Task]:
        """
        Get the next task to run based on readiness and priority.

        Args:
            mission_id: Mission ID

        Returns:
            Next task to run or None if no runnable tasks
        """
        tasks = self.load_mission(mission_id)
        if tasks is None:
            return None

        runnable = get_runnable_tasks(tasks)
        if not runnable:
            return None

        # Simple priority: first task in list (could be enhanced with priority field)
        return runnable[0]

    def evaluate_mission(self, mission_id: str) -> SchedulerOutcome:
        """
        Evaluate the current state of a mission.

        Args:
            mission_id: Mission ID

        Returns:
            SchedulerOutcome with current state
        """
        tasks = self.load_mission(mission_id)
        if tasks is None:
            # Return a completed outcome for non-existent mission
            return SchedulerOutcome(
                state="COMPLETE",
                runnable_tasks=[],
                blocked_tasks=[],
                completed_tasks=[],
                pending_tasks=[],
                diagnostic="Mission not found"
            )

        return evaluate_mission(mission_id, tasks)

    def mark_task_running(self, mission_id: str, task_id: str) -> bool:
        """
        Mark a task as running.

        Args:
            mission_id: Mission ID
            task_id: Task ID

        Returns:
            True if successful, False if task not found or not runnable
        """
        tasks = self.load_mission(mission_id)
        if tasks is None:
            return False

        task = tasks.get(task_id)
        if task is None:
            return False

        if not is_task_ready(task, tasks):
            return False

        task.status = TaskStatus.RUNNING
        self.state.update_task_status(mission_id, task_id, TaskStatus.RUNNING)
        return True

    def mark_task_completed(
        self,
        mission_id: str,
        task_id: str,
        commit_sha: Optional[str] = None
    ) -> bool:
        """
        Mark a task as completed.

        Args:
            mission_id: Mission ID
            task_id: Task ID
            commit_sha: Optional commit SHA for verification

        Returns:
            True if successful, False if task not found
        """
        tasks = self.load_mission(mission_id)
        if tasks is None:
            return False

        task = tasks.get(task_id)
        if task is None:
            return False

        task.status = TaskStatus.COMPLETED
        task.commit_sha = commit_sha
        self.state.update_task_status(mission_id, task_id, TaskStatus.COMPLETED, commit_sha)
        return True

    def mark_task_failed(self, mission_id: str, task_id: str) -> bool:
        """
        Mark a task as failed.

        Args:
            mission_id: Mission ID
            task_id: Task ID

        Returns:
            True if successful, False if task not found
        """
        tasks = self.load_mission(mission_id)
        if tasks is None:
            return False

        task = tasks.get(task_id)
        if task is None:
            return False

        task.status = TaskStatus.FAILED
        self.state.update_task_status(mission_id, task_id, TaskStatus.FAILED)
        return True

    def mark_task_blocked(self, mission_id: str, task_id: str) -> bool:
        """
        Mark a task as blocked.

        Args:
            mission_id: Mission ID
            task_id: Task ID

        Returns:
            True if successful, False if task not found
        """
        tasks = self.load_mission(mission_id)
        if tasks is None:
            return False

        task = tasks.get(task_id)
        if task is None:
            return False

        task.status = TaskStatus.BLOCKED
        self.state.update_task_status(mission_id, task_id, TaskStatus.BLOCKED)
        return True

    def increment_task_attempt(self, mission_id: str, task_id: str) -> int:
        """
        Increment the attempt count for a task.

        Args:
            mission_id: Mission ID
            task_id: Task ID

        Returns:
            New attempt count
        """
        return self.state.increment_task_attempt(mission_id, task_id)