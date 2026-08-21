"""Universal ASC v2.3.0 - State Management Module.

Manages SQLite database for mission tracking with atomic transactions,
schema migrations, composite task identity, and durable execution contracts.
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
    """Handles database operations for mission and task tracking with schema versioning."""

    SCHEMA_VERSION = 2

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

        self._conn: Optional[sqlite3.Connection] = None
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
        """Create or migrate database schema to latest version."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("PRAGMA user_version")
            row = cursor.fetchone()
            current_version = row[0] if row else 0

            if current_version < 1:
                # Initial baseline schema
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS missions (
                        id TEXT PRIMARY KEY,
                        goal TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        executor TEXT,
                        working_directory TEXT,
                        model TEXT,
                        execution_timeout INTEGER,
                        verification_timeout INTEGER,
                        max_attempts INTEGER,
                        metadata TEXT
                    )""")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id TEXT NOT NULL,
                        mission_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL,
                        depends_on TEXT NOT NULL,
                        prompt TEXT,
                        command TEXT,
                        commands_json TEXT,
                        attempt_count INTEGER DEFAULT 0,
                        commit_sha TEXT,
                        started_at REAL,
                        completed_at REAL,
                        exit_code INTEGER,
                        updated_at REAL NOT NULL,
                        working_directory TEXT,
                        executor TEXT,
                        model TEXT,
                        execution_timeout INTEGER,
                        commit_paths_json TEXT,
                        metadata TEXT,
                        PRIMARY KEY(mission_id, id),
                        FOREIGN KEY(mission_id) REFERENCES missions(id)
                    )""")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS attempts (
                        id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        mission_id TEXT,
                        attempt_number INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        exit_code INTEGER,
                        stdout TEXT,
                        stderr TEXT,
                        timestamp REAL NOT NULL,
                        duration REAL DEFAULT 0.0,
                        log_path TEXT
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
                    "CREATE INDEX IF NOT EXISTS idx_attempts_mission ON attempts(mission_id)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_mission ON events(mission_id)"
                )
                cursor.execute("PRAGMA user_version = 2")
                conn.commit()
                return

            if current_version < 2:
                # Migrate from v1 (single task id PK) to v2 (composite PK mission_id, id)
                cursor.execute("PRAGMA foreign_keys = OFF")

                # Check if tasks table needs migration
                cursor.execute("PRAGMA table_info(tasks)")
                columns = {col["name"] for col in cursor.fetchall()}

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tasks_v2 (
                        id TEXT NOT NULL,
                        mission_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL,
                        depends_on TEXT NOT NULL,
                        prompt TEXT,
                        command TEXT,
                        commands_json TEXT,
                        attempt_count INTEGER DEFAULT 0,
                        commit_sha TEXT,
                        started_at REAL,
                        completed_at REAL,
                        exit_code INTEGER,
                        updated_at REAL NOT NULL,
                        working_directory TEXT,
                        executor TEXT,
                        model TEXT,
                        execution_timeout INTEGER,
                        commit_paths_json TEXT,
                        metadata TEXT,
                        PRIMARY KEY(mission_id, id)
                    )""")

                # Copy existing task data
                cursor.execute("""
                    INSERT OR IGNORE INTO tasks_v2 (
                        id, mission_id, title, status, depends_on, prompt, command,
                        attempt_count, commit_sha, started_at, completed_at, exit_code,
                        updated_at, working_directory, executor, metadata
                    )
                    SELECT id, mission_id, title, status, depends_on, prompt, command,
                           attempt_count, commit_sha, started_at, completed_at, exit_code,
                           updated_at, working_directory, executor, metadata
                    FROM tasks
                """)

                cursor.execute("DROP TABLE tasks")
                cursor.execute("ALTER TABLE tasks_v2 RENAME TO tasks")

                # Ensure attempts has mission_id and duration
                cursor.execute("PRAGMA table_info(attempts)")
                att_cols = {col["name"] for col in cursor.fetchall()}
                if "mission_id" not in att_cols:
                    try:
                        cursor.execute("ALTER TABLE attempts ADD COLUMN mission_id TEXT")
                    except sqlite3.OperationalError:
                        pass
                if "duration" not in att_cols:
                    try:
                        cursor.execute("ALTER TABLE attempts ADD COLUMN duration REAL DEFAULT 0.0")
                    except sqlite3.OperationalError:
                        pass
                if "log_path" not in att_cols:
                    try:
                        cursor.execute("ALTER TABLE attempts ADD COLUMN log_path TEXT")
                    except sqlite3.OperationalError:
                        pass

                # Ensure missions has full contract columns
                cursor.execute("PRAGMA table_info(missions)")
                m_cols = {col["name"] for col in cursor.fetchall()}
                for col_name, col_type in [
                    ("model", "TEXT"),
                    ("execution_timeout", "INTEGER"),
                    ("verification_timeout", "INTEGER"),
                    ("max_attempts", "INTEGER"),
                    ("metadata", "TEXT"),
                ]:
                    if col_name not in m_cols:
                        try:
                            cursor.execute(f"ALTER TABLE missions ADD COLUMN {col_name} {col_type}")
                        except sqlite3.OperationalError:
                            pass

                cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_mission ON tasks(mission_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_attempts_task ON attempts(task_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_attempts_mission ON attempts(mission_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_mission ON events(mission_id)")
                cursor.execute("PRAGMA user_version = 2")
                conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper settings."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def save_mission(self, spec: Union[MissionSpec, Dict[str, Any]]) -> None:
        """Save or safely update a mission and its tasks."""
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
            model = getattr(spec, "model", None) or (
                getattr(spec.defaults, "model", None)
                if hasattr(spec, "defaults")
                else None
            )
            exec_timeout = getattr(spec, "execution_timeout", None) or (
                getattr(spec.defaults, "execution_timeout", None)
                if hasattr(spec, "defaults")
                else None
            )
            verify_timeout = getattr(spec, "verification_timeout", None) or (
                getattr(spec.defaults, "verification_timeout", None)
                if hasattr(spec, "defaults")
                else None
            )
            max_attempts = (
                getattr(spec.defaults, "max_attempts", 3)
                if hasattr(spec, "defaults")
                else 3
            )
            tasks = spec.tasks
        else:
            mission_id = str(spec["id"])
            goal = str(spec["goal"])
            defaults = spec.get("defaults", {})
            executor = spec.get("executor") or defaults.get("executor")
            working_directory = spec.get("working_directory") or defaults.get("working_directory")
            model = spec.get("model") or defaults.get("model")
            exec_timeout = spec.get("execution_timeout") or defaults.get("execution_timeout")
            verify_timeout = spec.get("verification_timeout") or defaults.get("verification_timeout")
            max_attempts = defaults.get("max_attempts", 3)
            tasks = spec.get("tasks", [])

        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check if mission already exists
            cursor.execute("SELECT id, status, created_at FROM missions WHERE id = ?", (mission_id,))
            existing = cursor.fetchone()
            if existing:
                # Update mission metadata without resetting status to PENDING if already running/complete
                cursor.execute(
                    """
                    UPDATE missions
                    SET goal = ?, updated_at = ?, executor = ?, working_directory = ?,
                        model = ?, execution_timeout = ?, verification_timeout = ?, max_attempts = ?
                    WHERE id = ?
                    """,
                    (goal, now, executor, working_directory, model, exec_timeout, verify_timeout, max_attempts, mission_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO missions (id, goal, status, created_at, updated_at, executor, working_directory,
                                         model, execution_timeout, verification_timeout, max_attempts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (mission_id, goal, "PENDING", now, now, executor, working_directory, model, exec_timeout, verify_timeout, max_attempts),
                )
            conn.commit()

        for t in tasks:
            if isinstance(t, dict):
                command_data = t.get("command") or t.get("verify")
                commands: List[VerificationCommand] = []
                if isinstance(command_data, str):
                    commands = [VerificationCommand(command=command_data)]
                elif isinstance(command_data, dict):
                    commands = [VerificationCommand(**command_data)]
                elif isinstance(command_data, list):
                    for c in command_data:
                        if isinstance(c, str):
                            commands.append(VerificationCommand(command=c))
                        elif isinstance(c, dict):
                            commands.append(VerificationCommand(**c))

                t_obj = Task(
                    id=t["id"],
                    title=t["title"],
                    prompt=t.get("prompt", ""),
                    status=TaskStatus(t.get("status", "PENDING")),
                    depends_on=t.get("depends_on", []),
                    command=commands[0] if commands else None,
                    commands=commands,
                    executor=t.get("executor"),
                    working_directory=t.get("working_directory"),
                    model=t.get("model"),
                    execution_timeout=t.get("execution_timeout"),
                    commit_paths=t.get("commit_paths"),
                    metadata=t.get("metadata", {}),
                )
                self.save_task(t_obj, mission_id)
            else:
                self.save_task(t, mission_id)

    def create_mission(self, spec: Union[MissionSpec, Dict[str, Any]]) -> None:
        """Create mission alias for save_mission."""
        self.save_mission(spec)

    def save_task(self, task: Task, mission_id: str) -> None:
        """Insert or update a task record with composite identity (mission_id, id)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status, attempt_count, commit_sha, started_at, completed_at FROM tasks WHERE mission_id = ? AND id = ?",
                (mission_id, task.id),
            )
            existing = cursor.fetchone()

            depends_json = json.dumps(task.depends_on)
            command_str = task.command.command if task.command else None
            commands_json = (
                json.dumps([c.__dict__ for c in task.commands])
                if task.commands
                else None
            )
            commit_paths_json = (
                json.dumps(task.commit_paths) if task.commit_paths else None
            )
            metadata_json = json.dumps(task.metadata) if task.metadata else None

            if existing:
                # Update task definition while preserving existing execution progress
                cursor.execute(
                    """
                    UPDATE tasks
                    SET title = ?, depends_on = ?, prompt = ?, command = ?, commands_json = ?,
                        updated_at = ?, working_directory = ?, executor = ?, model = ?,
                        execution_timeout = ?, commit_paths_json = ?, metadata = ?
                    WHERE mission_id = ? AND id = ?
                    """,
                    (
                        task.title,
                        depends_json,
                        task.prompt,
                        command_str,
                        commands_json,
                        time.time(),
                        task.working_directory,
                        task.executor,
                        task.model,
                        task.execution_timeout,
                        commit_paths_json,
                        metadata_json,
                        mission_id,
                        task.id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO tasks
                    (id, mission_id, title, status, depends_on, prompt, command, commands_json,
                     attempt_count, commit_sha, started_at, completed_at, exit_code, updated_at,
                     working_directory, executor, model, execution_timeout, commit_paths_json, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        commands_json,
                        task.metadata.get("attempt_count", 0) if task.metadata else 0,
                        task.commit_sha,
                        task.started_at,
                        task.completed_at,
                        None,
                        time.time(),
                        task.working_directory,
                        task.executor,
                        task.model,
                        task.execution_timeout,
                        commit_paths_json,
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

    def get_task(self, task_id: str, mission_id: Optional[str] = None) -> Optional[Task]:
        """Retrieve a task by ID, optionally scoped by mission_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if mission_id:
                cursor.execute(
                    "SELECT * FROM tasks WHERE mission_id = ? AND id = ?",
                    (mission_id, task_id),
                )
            else:
                cursor.execute(
                    "SELECT * FROM tasks WHERE id = ? ORDER BY updated_at DESC LIMIT 1",
                    (task_id,),
                )
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
        mission_id: Optional[str] = None,
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

            if mission_id:
                params.extend([mission_id, task_id])
                query = f"UPDATE tasks SET {', '.join(updates)} WHERE mission_id = ? AND id = ?"
            else:
                params.append(task_id)
                query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"

            cursor.execute(query, params)
            conn.commit()

    def increment_attempt_count(self, task_id: str, mission_id: Optional[str] = None) -> int:
        """Durably increment and return the attempt count for a task."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if mission_id:
                cursor.execute(
                    "UPDATE tasks SET attempt_count = COALESCE(attempt_count, 0) + 1 WHERE mission_id = ? AND id = ?",
                    (mission_id, task_id),
                )
                cursor.execute(
                    "SELECT attempt_count FROM tasks WHERE mission_id = ? AND id = ?",
                    (mission_id, task_id),
                )
            else:
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
                task_id = attempt_data.get("task_id", "")
                attempt_number = attempt_data.get("attempt_number", 1)
                attempt_id = (
                    attempt_data.get("id")
                    or f"att_{task_id}_{attempt_number}_{uuid.uuid4().hex[:8]}"
                )
                st = attempt_data.get("status", TaskStatus.PENDING)
                status_value = st.value if hasattr(st, "value") else str(st)
                exit_code = attempt_data.get("exit_code", 0)
                stdout = attempt_data.get("stdout", "")
                stderr = attempt_data.get("stderr", "")
                timestamp = attempt_data.get("timestamp", time.time())
                mission_id = attempt_data.get("mission_id")
                duration = attempt_data.get("duration", 0.0)
                log_path = attempt_data.get("log_path")
            else:
                task_id = attempt_data.task_id
                attempt_number = attempt_data.attempt_number
                attempt_id = (
                    attempt_data.id
                    or f"att_{task_id}_{attempt_number}_{uuid.uuid4().hex[:8]}"
                )
                status_value = (
                    attempt_data.status.value
                    if hasattr(attempt_data.status, "value")
                    else str(attempt_data.status)
                )
                exit_code = attempt_data.exit_code
                stdout = attempt_data.stdout
                stderr = attempt_data.stderr
                timestamp = attempt_data.timestamp
                mission_id = getattr(attempt_data, "mission_id", None)
                duration = getattr(attempt_data, "duration", 0.0)
                log_path = getattr(attempt_data, "log_path", None)
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
            mission_id = kwargs.get("mission_id") or (args[7] if len(args) > 7 else None)
            duration = kwargs.get("duration", 0.0)
            log_path = kwargs.get("log_path")
            attempt_id = (
                kwargs.get("id")
                or f"att_{task_id}_{attempt_number}_{uuid.uuid4().hex[:8]}"
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO attempts
                (id, task_id, mission_id, attempt_number, status, exit_code, stdout, stderr, timestamp, duration, log_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    attempt_id,
                    task_id,
                    mission_id,
                    attempt_number,
                    status_value,
                    exit_code,
                    stdout,
                    stderr,
                    timestamp,
                    duration,
                    log_path,
                ),
            )
            conn.commit()

    def get_attempts(self, task_id: str, mission_id: Optional[str] = None) -> List[AttemptRecord]:
        """Retrieve attempt history for a task."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if mission_id:
                cursor.execute(
                    "SELECT * FROM attempts WHERE mission_id = ? AND task_id = ? ORDER BY attempt_number ASC",
                    (mission_id, task_id),
                )
            else:
                cursor.execute(
                    "SELECT * FROM attempts WHERE task_id = ? ORDER BY attempt_number ASC",
                    (task_id,),
                )
            rows = cursor.fetchall()
            keys = rows[0].keys() if rows else []
            return [
                AttemptRecord(
                    id=row["id"],
                    task_id=row["task_id"],
                    mission_id=row["mission_id"] if "mission_id" in keys else None,
                    attempt_number=row["attempt_number"],
                    status=TaskStatus(row["status"]),
                    exit_code=row["exit_code"],
                    stdout=row["stdout"] if row["stdout"] else "",
                    stderr=row["stderr"] if row["stderr"] else "",
                    timestamp=row["timestamp"],
                    duration=row["duration"] if "duration" in keys and row["duration"] else 0.0,
                    log_path=row["log_path"] if "log_path" in keys else None,
                )
                for row in rows
            ]

    def record_event(self, event_data: Dict[str, Any]) -> None:
        """Record an audit event."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            event_id = event_data.get("id") or f"evt_{uuid.uuid4().hex[:12]}"
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
        """
        Retrieve recent events for a mission or task.
        Guarantees that LIMIT returns the newest N events, displayed in chronological order.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if mission_id and task_id:
                query = """
                    SELECT * FROM (
                        SELECT * FROM events
                        WHERE mission_id = ? AND task_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ) ORDER BY timestamp ASC
                """
                cursor.execute(query, (mission_id, task_id, limit))
            elif mission_id:
                query = """
                    SELECT * FROM (
                        SELECT * FROM events
                        WHERE mission_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ) ORDER BY timestamp ASC
                """
                cursor.execute(query, (mission_id, limit))
            elif task_id:
                query = """
                    SELECT * FROM (
                        SELECT * FROM events
                        WHERE task_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ) ORDER BY timestamp ASC
                """
                cursor.execute(query, (task_id, limit))
            else:
                query = """
                    SELECT * FROM (
                        SELECT * FROM events
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ) ORDER BY timestamp ASC
                """
                cursor.execute(query, (limit,))

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

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        """Convert a database row to a Task object with complete execution contract."""
        if row is None:
            return Task(
                id="unknown", title="unknown", prompt="", status=TaskStatus.PENDING
            )
        depends_on = json.loads(row["depends_on"]) if row["depends_on"] else []

        commands: List[VerificationCommand] = []
        keys = row.keys()
        if "commands_json" in keys and row["commands_json"]:
            try:
                cmd_list = json.loads(row["commands_json"])
                for c in cmd_list:
                    if isinstance(c, dict):
                        commands.append(VerificationCommand(**c))
                    elif isinstance(c, str):
                        commands.append(VerificationCommand(command=c))
            except Exception:
                pass

        if not commands and row["command"]:
            commands = [VerificationCommand(command=row["command"])]

        commit_paths = None
        if "commit_paths_json" in keys and row["commit_paths_json"]:
            try:
                commit_paths = json.loads(row["commit_paths_json"])
            except Exception:
                pass

        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        model = row["model"] if "model" in keys else None
        exec_timeout = row["execution_timeout"] if "execution_timeout" in keys else None

        return Task(
            id=row["id"],
            title=row["title"],
            prompt=row["prompt"] if row["prompt"] else "",
            status=TaskStatus(row["status"]),
            depends_on=depends_on,
            command=commands[0] if commands else None,
            commands=commands,
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            commit_sha=row["commit_sha"],
            working_directory=row["working_directory"],
            executor=row["executor"],
            model=model,
            execution_timeout=exec_timeout,
            commit_paths=commit_paths,
            metadata=metadata,
        )
