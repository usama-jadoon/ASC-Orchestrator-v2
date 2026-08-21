"""Universal ASC v2.0.0 - Models module.

Core data structures for the Universal ASC orchestrator.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(Enum):
    """Task execution status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class SchedulerState(Enum):
    """Mission scheduler state."""

    RUNNABLE = "RUNNABLE"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


@dataclass
class VerificationCommand:
    """A verification command to execute for task completion."""

    command: str
    cwd: Optional[str] = None
    timeout: Optional[int] = None


@dataclass
class VerificationResult:
    """Result of verification command execution."""

    command: VerificationCommand
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    success: bool = field(init=False)

    def __post_init__(self):
        self.success = self.exit_code == 0


@dataclass
class Task:
    """A task in a mission specification."""

    id: str
    title: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    depends_on: List[str] = field(default_factory=list)
    command: Optional[VerificationCommand] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    commit_sha: Optional[str] = None
    executor: Optional[str] = None
    working_directory: Optional[str] = None


@dataclass
class MissionDefaults:
    """Default settings for mission execution."""

    max_attempts: int = 3
    verification_timeout: int = 300
    executor: str = "omp"
    working_directory: Optional[str] = None


@dataclass
class MissionSpec:
    """Mission specification parsed from YAML/JSON."""

    id: str
    goal: str
    tasks: List[Task]
    defaults: MissionDefaults = field(default_factory=MissionDefaults)
    executor: Optional[str] = None
    working_directory: Optional[str] = None


@dataclass
class Mission:
    """Mission record for persistence layer."""

    id: str
    goal: str
    status: str
    created_at: float
    updated_at: float
    executor: Optional[str] = None
    working_directory: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Mission":
        """Create Mission from database row."""
        keys = row.keys() if hasattr(row, "keys") else []
        return cls(
            id=row["id"],
            goal=row["goal"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            executor=row["executor"] if "executor" in keys else None,
            working_directory=row["working_directory"] if "working_directory" in keys else None,
        )


@dataclass
class AttemptRecord:
    """Record of a task execution attempt."""

    id: str
    task_id: str
    attempt_number: int
    status: TaskStatus
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timestamp: float = field(default_factory=lambda: 0.0)


@dataclass
class MissionStateRecord:
    """Record of mission state for persistence."""

    mission_id: str
    state: SchedulerState
    runnable_tasks: List[str] = field(default_factory=list)
    blocked_tasks: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentResult:
    """Result of agent execution."""

    output: str
    exit_code: int = 0
