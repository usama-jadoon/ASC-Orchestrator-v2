"""Universal ASC v2.2.0 - Event and Progress Architecture.

Provides decoupled domain events, progress reporting, and heartbeat streaming.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class EventType(str, Enum):
    """Domain events emitted during mission and task orchestration."""

    MISSION_STARTED = "MISSION_STARTED"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    MISSION_BLOCKED = "MISSION_BLOCKED"

    TASK_READY = "TASK_READY"
    TASK_STARTED = "TASK_STARTED"
    TASK_RETRY = "TASK_RETRY"
    TASK_FAILED = "TASK_FAILED"
    TASK_COMPLETED = "TASK_COMPLETED"

    EXECUTOR_STARTED = "EXECUTOR_STARTED"
    EXECUTOR_HEARTBEAT = "EXECUTOR_HEARTBEAT"
    EXECUTOR_COMPLETED = "EXECUTOR_COMPLETED"
    EXECUTOR_FAILED = "EXECUTOR_FAILED"

    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"

    GIT_CHANGESET_DETECTED = "GIT_CHANGESET_DETECTED"
    GIT_COMMIT_STARTED = "GIT_COMMIT_STARTED"
    GIT_COMMIT_CREATED = "GIT_COMMIT_CREATED"

    LOCK_ACQUIRED = "LOCK_ACQUIRED"
    LOCK_RELEASED = "LOCK_RELEASED"
    LOCK_CONFLICT = "LOCK_CONFLICT"


@dataclass
class Event:
    """An observable domain event in ASC."""

    event_type: EventType
    mission_id: Optional[str] = None
    task_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary representation."""
        return {
            "event_type": self.event_type.value,
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "message": self.message,
        }


EventListener = Callable[[Event], None]


class EventEmitter:
    """Dispatches events to registered listeners."""

    def __init__(self) -> None:
        self._listeners: List[EventListener] = []

    def subscribe(self, listener: EventListener) -> None:
        """Register an event listener."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: EventListener) -> None:
        """Remove a registered event listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event: Event) -> None:
        """Dispatch event to all registered listeners."""
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                # Event listeners must not break core driver execution
                pass
