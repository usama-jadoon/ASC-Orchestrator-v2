"""Universal ASC v2.2.0 - State Management Module.

Manages SQLite database for mission tracking with atomic transactions.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .models import (
    AttemptRecord,
    Mission,
    MissionSpec,
    Task,
    TaskStatus,
    VerificationCommand,
)
from .repo import Repository


def resolve_default_state_dir(cwd: str | Path = ".") -> Path:
    """
    Resolve safe location for ASC state storage without dirtying user repos.
    If cwd is inside a git repo, use <repo_root>/.git/asc/
    Otherwise use <cwd>/.asc/
    """
    cwd_path = Path(cwd).resolve()
    repo = Repository(cwd_path)
    if repo.is_git_repo():
        git_dir = repo.get_root_dir() / ".git"
        if git_dir.is_dir():
            asc_dir = git_dir / "asc"
            asc_dir.mkdir(parents=True, exist_ok=True)
            return asc_dir
    asc_dir = cwd_path / ".asc"
    asc_dir.mkdir(parents=True, exist_ok=True)
    return asc_dir


class State:
    """Handles database operations for mission and task tracking."""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        cwd: str | Path = ".",
    ):
        """Initialize database connection."""
        if db_path is not None and str(db_path) != ".asc/asc.db":
            self.db_path = Path(db_path)
        else:
            state_dir = resolve_default_state_dir(cwd)
            self.db_path = state_dir / "asc.db"

        self._conn = None
        self._ensure_dir()
        self.init_db()

    def _ensure_dir(self) -> None:
        """Ensure parent directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        """Close connection if open."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

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
                    updated_at REAL NOT NULL,
                    executor TEXT,
                    working_directory TEXT
                )""")

            try:
                cursor.execute("ALTER TABLE missions ADD COLUMN executor TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE missions ADD COLUMN working_directory TEXT")
            except sqlite3.OperationalError:
                pass

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

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_mission ON tasks(mission_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_attempts_task ON attempts(task_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_mission ON events(mission_id)"
            )

            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper settings."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def save_mission(self, spec: Union[MissionSpec, Dict[str, Any]]) -> None:
        """Save a mission and its tasks."""
        if isinstance(spec, MissionSpec):
            mission_id = spec.id
            goal = spec.goal
            executor = getattr(spec, "executor", None) or (
                getattr(spec.defaults, "executor", None)
                if hasattr(spec, "defaults")
                else None
            )
            working_directory = getattr(spec, "working_directory", None) or (
                getattr(spec.defaults, "working_directory", None)
                if hasattr(spec, "defaults")
                else None
            )
            tasks = spec.tasks
        else:
            mission_id = str(spec["id"])
            goal = str(spec["goal"])
            executor = spec.get("executor") or spec.get("defaults", {}).get("executor")
            working_directory = spec.get("working_directory") or spec.get(
                "defaults", {}
            ).get("working_directory")
            tasks = spec.get("tasks", [])

        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO missions (id, goal, status, created_at, updated_at, executor, working_directory)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (mission_id, goal, "PENDING", now, now, executor, working_directory),
            )
            conn.commit()

        for t in tasks:
            if isinstance(t, dict):
                t_obj = Task(
                    id=t["id"],
                    title=t["title"],
                    prompt=t.get("prompt", ""),
                    status=TaskStatus(t.get("status", "PENDING")),
                    depends_on=t.get("depends_on", []),
                    command=VerificationCommand(command=t["command"])
                    if t.get("command")
                    else None,
                    executor=t.get("executor"),
                    working_directory=t.get("working_directory"),
                    metadata=t.get("metadata", {}),
                )
                self.save_task(t_obj, mission_id)
            else:
                self.save_task(t, mission_id)

    def create_mission(self, spec: Union[MissionSpec, Dict[str, Any]]) -> None:
        """Create mission alias for save_mission."""
        self.save_mission(spec)

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
                    task.status.value
                    if hasattr(task.status, "value")
                    else str(task.status),
                    depends_json,
                    task.prompt,
                    command_str,
                    task.metadata.get("attempt_count", 0) if task.metadata else 0,
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
            conn.commit()

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        """Retrieve a mission by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM missions WHERE id = ?", (mission_id,))
            row = cursor.fetchone()
            if row:
                return Mission.from_row(row)
            return None

    def get_last_mission_id(self) -> Optional[str]:
        """Retrieve the ID of the most recently updated or created mission."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM missions ORDER BY updated_at DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return str(row["id"])
            return None

    def get_all_missions(self, limit: int = 50) -> List[Mission]:
        """Retrieve all missions ordered by recent update."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM missions ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
            rows = cursor.fetchall()
            return [Mission.from_row(r) for r in rows]

    def update_mission_status(self, mission_id: str, status: str) -> None:
        """Update mission status and timestamp."""
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE missions
                SET status = ?, updated_at = ?
                WHERE id = ?
            """,
                (status, now, mission_id),
            )
            conn.commit()

    def get_tasks(self, mission_id: str) -> List[Task]:
        """Retrieve all tasks for a mission."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tasks WHERE mission_id = ? ORDER BY rowid ASC",
                (mission_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_task(row)
            return None

    def update_task_status(
        self,
        task: Union[Task, str],
        status: Optional[TaskStatus] = None,
        started_at: Optional[float] = None,
        completed_at: Optional[float] = None,
        exit_code: Optional[int] = None,
        commit_sha: Optional[str] = None,
    ) -> None:
        """Update task status and related timestamps."""
        now = time.time()
        if isinstance(task, Task):
            task_id = task.id
            status_val = (
                task.status.value if hasattr(task.status, "value") else str(task.status)
            )
        else:
            task_id = str(task)
            status_val = (
                status.value
                if (status and hasattr(status, "value"))
                else str(status or "PENDING")
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()

            updates = ["status = ?", "updated_at = ?"]
            params: List[Any] = [status_val, now]

            if started_at is not None:
                updates.append("started_at = ?")
                params.append(started_at)

            if completed_at is not None:
                updates.append("completed_at = ?")
                params.append(completed_at)

            if exit_code is not None:
                updates.append("exit_code = ?")
                params.append(exit_code)

            if commit_sha is not None:
                updates.append("commit_sha = ?")
                params.append(commit_sha)

            params.append(task_id)

            query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()

    def increment_attempt_count(self, task_id: str) -> int:
        """
        Durably increment and return the attempt count for a task.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tasks SET attempt_count = COALESCE(attempt_count, 0) + 1 WHERE id = ?",
                (task_id,),
            )
            cursor.execute("SELECT attempt_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            conn.commit()
            if row and row["attempt_count"] is not None:
                return int(row["attempt_count"])
            return 1

    def record_attempt(self, *args, **kwargs) -> None:
        """
        Record task attempt details flexibly.
        Supports:
          record_attempt(attempt_record: AttemptRecord)
          record_attempt(task_id, attempt_number, status, exit_code, ...)
        """
        if args and isinstance(args[0], (AttemptRecord, dict)):
            attempt_data = args[0]
            if isinstance(attempt_data, dict):
                attempt_id = (
                    attempt_data.get("id")
                    or f"att_{attempt_data.get('task_id')}_{attempt_data.get('attempt_number', 1)}_{uuid.uuid4().hex[:8]}"
                )
                task_id = attempt_data.get("task_id")
                attempt_number = attempt_data.get("attempt_number", 1)
                st = attempt_data.get("status", TaskStatus.PENDING)
                status_value = st.value if hasattr(st, "value") else str(st)
                exit_code = attempt_data.get("exit_code", 0)
                stdout = attempt_data.get("stdout", "")
                stderr = attempt_data.get("stderr", "")
                timestamp = attempt_data.get("timestamp", time.time())
            else:
                attempt_id = (
                    attempt_data.id
                    or f"att_{attempt_data.task_id}_{attempt_data.attempt_number}_{uuid.uuid4().hex[:8]}"
                )
                task_id = attempt_data.task_id
                attempt_number = attempt_data.attempt_number
                status_value = (
                    attempt_data.status.value
                    if hasattr(attempt_data.status, "value")
                    else str(attempt_data.status)
                )
                exit_code = attempt_data.exit_code
                stdout = attempt_data.stdout
                stderr = attempt_data.stderr
                timestamp = attempt_data.timestamp
        else:
            task_id = kwargs.get("task_id") or (args[0] if len(args) > 0 else "")
            attempt_number = kwargs.get("attempt_number") or (
                args[1] if len(args) > 1 else 1
            )
            st = kwargs.get("status") or (
                args[2] if len(args) > 2 else TaskStatus.PENDING
            )
            status_value = st.value if hasattr(st, "value") else str(st)
            exit_code = kwargs.get("exit_code") or (args[3] if len(args) > 3 else 0)
            stdout = kwargs.get("stdout") or (args[4] if len(args) > 4 else "")
            stderr = kwargs.get("stderr") or (args[5] if len(args) > 5 else "")
            timestamp = kwargs.get("timestamp") or (
                args[6] if len(args) > 6 else time.time()
            )
            attempt_id = (
                kwargs.get("id")
                or f"att_{task_id}_{attempt_number}_{uuid.uuid4().hex[:8]}"
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO attempts
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
            cursor.execute(
                "SELECT * FROM attempts WHERE task_id = ? ORDER BY attempt_number ASC",
                (task_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def record_event(self, event_data: Dict[str, Any]) -> None:
        """Record mission/task event."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            event_id = event_data.get("id", f"evt_{time.time()}_{uuid.uuid4().hex[:6]}")
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

    def get_events(
        self,
        mission_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Retrieve events for a mission or task."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if mission_id and task_id:
                cursor.execute(
                    "SELECT * FROM events WHERE mission_id = ? AND task_id = ? ORDER BY timestamp ASC LIMIT ?",
                    (mission_id, task_id, limit),
                )
            elif mission_id:
                cursor.execute(
                    "SELECT * FROM events WHERE mission_id = ? ORDER BY timestamp ASC LIMIT ?",
                    (mission_id, limit),
                )
            elif task_id:
                cursor.execute(
                    "SELECT * FROM events WHERE task_id = ? ORDER BY timestamp ASC LIMIT ?",
                    (task_id, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM events ORDER BY timestamp ASC LIMIT ?", (limit,)
                )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get("payload_json"):
                    try:
                        d["payload"] = json.loads(d["payload_json"])
                    except Exception:
                        d["payload"] = {}
                results.append(d)
            return results

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
