"""Pure DAG evaluation functions for Universal ASC v2.3.0.

Provides task readiness checks, runnable task discovery, and mission evaluation
with stale execution reconciliation and interrupted state support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Union

from .models import SchedulerState, Task, TaskStatus


@dataclass
class MissionEvaluationResult:
    """Result of mission evaluation."""

    state: SchedulerState
    runnable_tasks: List[Task] = field(default_factory=list)
    blocked_ids: List[str] = field(default_factory=list)


def is_task_ready(task: Task, all_tasks: Union[List[Task], Dict[str, Task]]) -> bool:
    """
    Determine if a task is ready to run.

    - All dependencies must exist and be in COMPLETED status.
    - Task must be in PENDING or INTERRUPTED status (not already COMPLETED/FAILED/RUNNING).
    """
    # Convert list to dict registry if needed
    if isinstance(all_tasks, list):
        task_registry = {t.id: t for t in all_tasks}
    else:
        task_registry = all_tasks

    if task.status not in (TaskStatus.PENDING, TaskStatus.INTERRUPTED):
        return False
    for dep in task.depends_on:
        dep_task = task_registry.get(dep)
        if not dep_task or dep_task.status != TaskStatus.COMPLETED:
            return False
    return True


def get_runnable_tasks(all_tasks: Union[List[Task], Dict[str, Task]]) -> List[Task]:
    """
    Return list of tasks that are ready to run
    (PENDING or INTERRUPTED with all dependencies COMPLETED).
    """
    # Convert list to dict registry if needed
    if isinstance(all_tasks, list):
        task_registry = {t.id: t for t in all_tasks}
    else:
        task_registry = all_tasks

    runnable = []
    for task in task_registry.values():
        if is_task_ready(task, task_registry):
            runnable.append(task)
    return runnable


def evaluate_mission(
    mission_id: str,
    all_tasks: Union[List[Task], Dict[str, Task]],
) -> MissionEvaluationResult:
    """
    Evaluate mission state and return scheduler outcome.

    - If all tasks completed: return COMPLETE
    - If any task is currently RUNNING: return RUNNING
    - If runnable tasks exist: return RUNNABLE with runnable list
    - Otherwise: return BLOCKED with blocked task IDs
    """
    # Convert list to dict registry if needed
    if isinstance(all_tasks, list):
        task_registry = {t.id: t for t in all_tasks}
    else:
        task_registry = all_tasks

    completed_count = sum(
        1 for task in task_registry.values() if task.status == TaskStatus.COMPLETED
    )
    total_task_count = len(task_registry)

    if completed_count == total_task_count and total_task_count > 0:
        return MissionEvaluationResult(state=SchedulerState.COMPLETE)

    # Check if any task is actively running
    running_tasks = [
        task for task in task_registry.values() if task.status == TaskStatus.RUNNING
    ]
    if running_tasks:
        runnable = get_runnable_tasks(task_registry)
        return MissionEvaluationResult(
            state=SchedulerState.RUNNING,
            runnable_tasks=runnable,
        )

    runnable = get_runnable_tasks(task_registry)
    if runnable:
        return MissionEvaluationResult(
            state=SchedulerState.RUNNABLE, runnable_tasks=runnable
        )

    # BLOCKED: tasks exist but none are running or runnable
    blocked_ids = [
        task.id
        for task in task_registry.values()
        if task.status not in (TaskStatus.COMPLETED, TaskStatus.RUNNING)
    ]
    return MissionEvaluationResult(
        state=SchedulerState.BLOCKED, blocked_ids=blocked_ids
    )
