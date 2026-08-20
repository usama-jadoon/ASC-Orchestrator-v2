"""Universal ASC v2.0.0 - State Management Module.

Manages SQLite database for mission tracking with atomic transactions.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    Mission,
    MissionSpec,
    Task,
    TaskStatus,
    VerificationCommand,
)


class State:
    """Handles database operations for mission and task tracking."""

    def __init__(self, db_path: str = ".asc/asc.db"):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self._conn = None
        self._ensure_dir()
        self.init_db()

    def _ensure_dir(self) -> None:
        """Ensure parent directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_db(self) -> None:
        """Create database schema if not exists."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS missions (
                    id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )""")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    prompt TEXT,
                    command TEXT,
                    attempt_count INTEGER DEFAULT 0,
                    commit_sha TEXT,
                    started_at REAL,
                    completed_at REAL,
                    exit_code INTEGER,
                    updated_at REAL NOT NULL,
                    working_directory TEXT,
                    executor TEXT,
                    metadata TEXT,
                    FOREIGN KEY(mission_id) REFERENCES missions(id)
                )""")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    stdout TEXT,
                    stderr TEXT,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                )""")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT,
                    timestamp REAL NOT NULL
                )""")

            conn.commit()

    def close(self) -> None:
        """Close any open database connections."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _get_connection(self) -> sqlite3.Connection:
        """Get a new database connection with row factory enabled."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        """Retrieve mission by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM missions WHERE id = ?", (mission_id,))
            row = cursor.fetchone()
            if row:
                return Mission.from_row(row)
            return None

    def get_all_missions(self) -> List[Mission]:
        """Retrieve all missions ordered by creation time."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM missions ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [Mission.from_row(row) for row in rows]

    def get_last_mission_id(self) -> Optional[str]:
        """Get the ID of the most recent mission."""
        missions = self.get_all_missions()
        return missions[0].id if missions else None

    def get_attempt_count(self, task_id: str) -> int:
        """Get the number of attempts for a task."""
        attempts = self.get_attempts(task_id)
        return len(attempts) if attempts else 0

    def save_mission(self, spec: Any) -> None:
        """Save a complete mission spec including all its tasks."""
        mission_id = spec.id if hasattr(spec, "id") else spec.get("id")
        goal = spec.goal if hasattr(spec, "goal") else spec.get("goal", "")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = time.time()
            cursor.execute(
                "INSERT OR REPLACE INTO missions (id, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (mission_id, goal, "PENDING", now, now),
            )
            conn.commit()
        tasks = spec.tasks if hasattr(spec, "tasks") else spec.get("tasks", [])
        for task in tasks:
            self.save_task(task, mission_id)

    def create_mission(self, mission: MissionSpec) -> None:
        """Create new mission record."""
        self.save_mission(mission)

    def get_tasks(self, mission_id: str) -> List[Task]:
        """Retrieve all tasks for a mission."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE mission_id = ?", (mission_id,))
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def update_task_status(self, task: Task, exit_code: Optional[int] = None) -> bool:
        """Update task status in database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updated_at = time.time()
            if exit_code is not None:
                cursor.execute(
                    "UPDATE tasks SET status = ?, exit_code = ?, updated_at = ? WHERE id = ?",
                    (task.status.value, exit_code, updated_at, task.id),
                )
            else:
                cursor.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (task.status.value, updated_at, task.id),
                )
    def save_task(self, task: Task, mission_id: str) -> None:
        """Insert or update a task record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            depends_json = json.dumps(task.depends_on)
            command_str = task.command.command if task.command else None
            metadata_json = json.dumps(task.metadata) if task.metadata else None
            cursor.execute(
                """
                INSERT OR REPLACE INTO tasks
                (id, mission_id, title, status, depends_on, prompt, command,
                 attempt_count, commit_sha, started_at, completed_at, exit_code, updated_at,
                 working_directory, executor, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    task.id,
                    mission_id,
                    task.title,
                    task.status.value,
                    depends_json,
                    task.prompt,
                    command_str,
                    task.metadata.get("attempt_count", 0),
                    task.commit_sha,
                    task.started_at,
                    task.completed_at,
                    None,
                    time.time(),
                    task.working_directory,
                    task.executor,
                    metadata_json,
                ),
            )


    def record_attempt(self, attempt_data: Any) -> None:
        """Record task attempt details."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Handle both AttemptRecord objects and dicts
            if isinstance(attempt_data, dict):
                attempt_id = attempt_data.get("id", f"attempt_{time.time()}")
                task_id = attempt_data.get("task_id")
                attempt_number = attempt_data.get("attempt_number", 1)
                status = attempt_data.get("status", TaskStatus.PENDING)
                if isinstance(status, TaskStatus):
                    status_value = status.value
                else:
                    status_value = str(status)
                exit_code = attempt_data.get("exit_code")
                stdout = attempt_data.get("stdout", "")
                stderr = attempt_data.get("stderr", "")
                timestamp = attempt_data.get("timestamp", time.time())
            else:
                attempt_id = attempt_data.id
                task_id = attempt_data.task_id
                attempt_number = attempt_data.attempt_number
                status_value = attempt_data.status.value
                exit_code = attempt_data.exit_code
                stdout = attempt_data.stdout
                stderr = attempt_data.stderr
                timestamp = attempt_data.timestamp

            cursor.execute(
                """
                INSERT INTO attempts
                (id, task_id, attempt_number, status, exit_code, stdout, stderr, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    attempt_id,
                    task_id,
                    attempt_number,
                    status_value,
                    exit_code,
                    stdout,
                    stderr,
                    timestamp,
                ),
            )
            conn.commit()

    def get_attempts(self, task_id: str) -> List[Dict[str, Any]]:
        """Retrieve all attempts for a task."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM attempts WHERE task_id = ?", (task_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def record_event(self, event_data: Dict[str, Any]) -> None:
        """Record mission/task event."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            event_id = event_data.get("id", f"evt_{time.time()}")
            cursor.execute(
                """
                INSERT INTO events
                (id, mission_id, task_id, event_type, payload_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    event_id,
                    event_data.get("mission_id"),
                    event_data.get("task_id"),
                    event_data.get("event_type", "UNKNOWN"),
                    json.dumps(event_data.get("payload", {})),
                    event_data.get("timestamp", time.time()),
                ),
            )
            conn.commit()
    def get_events(self, mission_id: str) -> List[Dict[str, Any]]:
        """Retrieve events for a mission."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM events WHERE mission_id = ? ORDER BY timestamp ASC",
                (mission_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def _row_to_task(self, row) -> Task:
        """Convert a database row to a Task object."""
        if row is None:
            return Task(
                id="unknown", title="unknown", prompt="", status=TaskStatus.PENDING
            )
        depends_on = json.loads(row["depends_on"]) if row["depends_on"] else []
        command = None
        if row["command"]:
            command = VerificationCommand(command=row["command"])
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        return Task(
            id=row["id"],
            title=row["title"],
            prompt=row["prompt"] if row["prompt"] else "",
            status=TaskStatus(row["status"]),
            depends_on=depends_on,
            command=command,
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            commit_sha=row["commit_sha"],
            working_directory=row["working_directory"],
            executor=row["executor"],
            metadata=metadata,
        )
