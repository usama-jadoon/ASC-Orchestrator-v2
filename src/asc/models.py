"""Universal ASC v2.3.0 - Models module.

Core data structures for the Universal ASC orchestrator.
"""

from __future__ import annotations

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
    INTERRUPTED = "INTERRUPTED"


class SchedulerState(Enum):
    """Mission scheduler state."""

    RUNNABLE = "RUNNABLE"
    RUNNING = "RUNNING"
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
    results: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        self.success = self.exit_code == 0


@dataclass
class StructuredExecutorResult:
    """Stable structured executor observation for control plane and adapters."""

    executor: str
    mission_id: Optional[str] = None
    task_id: Optional[str] = None
    attempt_number: int = 1
    session_id: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration: float = 0.0
    exit_code: int = 0
    timed_out: bool = False
    stdout_summary: str = ""
    stderr_summary: str = ""
    changed_files: List[str] = field(default_factory=list)
    model: Optional[str] = None
    provider: Optional[str] = None
    log_path: Optional[str] = None
    error_classification: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class Task:
    """A task in a mission specification."""

    id: str
    title: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    depends_on: List[str] = field(default_factory=list)
    command: Optional[VerificationCommand] = None
    commands: List[VerificationCommand] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    commit_sha: Optional[str] = None
    executor: Optional[str] = None
    working_directory: Optional[str] = None
    model: Optional[str] = None
    execution_timeout: Optional[int] = None
    commit_paths: Optional[List[str]] = None

    def __post_init__(self):
        # Synchronize command and commands
        if self.command and not self.commands:
            self.commands = [self.command]
        elif self.commands and not self.command:
            self.command = self.commands[0]


@dataclass
class MissionDefaults:
    """Default settings for mission execution."""

    max_attempts: int = 3
    execution_timeout: int = 600
    verification_timeout: int = 300
    executor: str = "omp"
    working_directory: Optional[str] = None
    model: Optional[str] = None
    system_changes: str = "DENIED"


@dataclass
class MissionSpec:
    """Mission specification parsed from YAML/JSON."""

    id: str
    goal: str
    tasks: List[Task]
    defaults: MissionDefaults = field(default_factory=MissionDefaults)
    executor: Optional[str] = None
    working_directory: Optional[str] = None
    model: Optional[str] = None
    execution_timeout: Optional[int] = None
    verification_timeout: Optional[int] = None
    system_changes: str = "DENIED"


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
    model: Optional[str] = None
    execution_timeout: Optional[int] = None
    verification_timeout: Optional[int] = None
    max_attempts: Optional[int] = None

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
            working_directory=row["working_directory"]
            if "working_directory" in keys
            else None,
            model=row["model"] if "model" in keys else None,
            execution_timeout=row["execution_timeout"]
            if "execution_timeout" in keys
            else None,
            verification_timeout=row["verification_timeout"]
            if "verification_timeout" in keys
            else None,
            max_attempts=row["max_attempts"] if "max_attempts" in keys else None,
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
    mission_id: Optional[str] = None
    duration: float = 0.0
    log_path: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


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
    duration: float = 0.0
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    changed_files: List[str] = field(default_factory=list)
    log_path: Optional[str] = None
