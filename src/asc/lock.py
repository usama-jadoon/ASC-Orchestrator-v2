"""Universal ASC v2.2.0 - Project Execution Lock.

Ensures single-driver mutual exclusion per repository with stale lock recovery.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


class LockConflictError(RuntimeError):
    """Raised when another active ASC driver already holds the project lock."""

    def __init__(self, lock_info: Dict[str, Any], lock_file: Path) -> None:
        self.lock_info = lock_info
        self.lock_file = lock_file
        pid = lock_info.get("pid", "unknown")
        mission_id = lock_info.get("mission_id", "unknown")
        super().__init__(
            f"Project execution lock is already held by PID {pid} (Mission: '{mission_id}'). "
            f"Lock file: {lock_file}"
        )


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is currently active."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(
            SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            # Check exit code
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                kernel32.CloseHandle(handle)
                # STILL_ACTIVE is 259
                return exit_code.value == 259
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


class ProjectLock:
    """Guards repository against concurrent ASC driver executions."""

    def __init__(
        self,
        lock_dir: str | Path,
        mission_id: Optional[str] = None,
        stale_threshold_seconds: float = 3600.0,
    ) -> None:
        self.lock_dir = Path(lock_dir)
        self.lock_file = self.lock_dir / "lock"
        self.mission_id = mission_id or "unknown"
        self.stale_threshold_seconds = stale_threshold_seconds
        self._acquired = False

    def acquire(self) -> bool:
        """Acquire project lock, recovering from stale locks if needed."""
        self.lock_dir.mkdir(parents=True, exist_ok=True)

        if self.lock_file.exists():
            try:
                data = json.loads(self.lock_file.read_text(encoding="utf-8"))
                lock_pid = int(data.get("pid", 0))
                lock_time = float(data.get("timestamp", 0))

                # Check if current process already owns this lock
                if lock_pid == os.getpid():
                    self._acquired = True
                    return True

                # Check if the locking process is still running
                now = time.time()
                is_stale = (now - lock_time > self.stale_threshold_seconds) or (
                    not is_process_running(lock_pid)
                )

                if not is_stale:
                    raise LockConflictError(data, self.lock_file)
            except (json.JSONDecodeError, ValueError):
                # Corrupted lock file - treat as stale
                pass

        # Write fresh lock
        payload = {
            "pid": os.getpid(),
            "mission_id": self.mission_id,
            "timestamp": time.time(),
            "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
        }
        self.lock_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._acquired = True
        return True

    def release(self) -> None:
        """Release project lock if owned by current process."""
        if not self._acquired and not self.lock_file.exists():
            return

        try:
            if self.lock_file.exists():
                data = json.loads(self.lock_file.read_text(encoding="utf-8"))
                if data.get("pid") == os.getpid():
                    self.lock_file.unlink(missing_ok=True)
        except Exception:
            self.lock_file.unlink(missing_ok=True)
        finally:
            self._acquired = False

    def is_locked(self) -> bool:
        """Check if a valid, non-stale lock currently exists."""
        if not self.lock_file.exists():
            return False
        try:
            data = json.loads(self.lock_file.read_text(encoding="utf-8"))
            lock_pid = int(data.get("pid", 0))
            lock_time = float(data.get("timestamp", 0))
            if not is_process_running(lock_pid):
                return False
            if time.time() - lock_time > self.stale_threshold_seconds:
                return False
            return True
        except Exception:
            return False

    def get_lock_info(self) -> Optional[Dict[str, Any]]:
        """Return information about the current lock if present."""
        if not self.lock_file.exists():
            return None
        try:
            return json.loads(self.lock_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def __enter__(self) -> "ProjectLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
