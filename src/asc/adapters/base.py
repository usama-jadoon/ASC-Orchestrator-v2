"""Universal ASC v2.0.0 - Adapter Base Module.

Defines the AgentAdapter abstract base class for all adapters.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from ..models import Task


class AgentAdapter(ABC):
    """Abstract base class for task executors."""

    @abstractmethod
    async def execute(self, task: Task, context: Dict[str, Any]) -> Any:
        """Execute a task and return the result."""
        pass

    @abstractmethod
    def can_execute(self, task: Task) -> bool:
        """Check if this adapter can execute the given task."""
        pass

    @abstractmethod
    def prepare(self, context: Dict[str, Any]) -> None:
        """Prepare the adapter for execution."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up adapter resources."""
        pass


class ActionFailed(Exception):
    """Raised when a task action fails."""

    pass
