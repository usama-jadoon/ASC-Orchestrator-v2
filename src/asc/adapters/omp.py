"""Universal ASC v2.0.0 - OMP Adapter Module.

Real OMP (Open Model Platform) adapter for executing coding tasks.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ..models import AgentResult, Task, VerificationCommand, VerificationResult
from .base import AgentAdapter


@dataclass
class OMPConfig:
    """Configuration for OMP adapter."""
    timeout: int = 300
    omp_path: Optional[str] = None
    working_directory: Optional[str] = None


class OMPAdapter(AgentAdapter):
    """OMP (Open Model Platform) adapter for executing coding tasks."""

    def __init__(self, config: Optional[OMPConfig] = None):
        self.config = config or OMPConfig()
        self._omp_executable: Optional[str] = None

    def can_execute(self, task: Task) -> bool:
        """Check if OMP can execute the task."""
        return True

    def prepare(self, context: Dict[str, Any]) -> None:
        """Prepare OMP adapter for execution."""
        # Validate working directory
        if self.config.working_directory:
            work_dir = Path(self.config.working_directory)
            if not work_dir.exists():
                work_dir.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        """Clean up adapter resources."""
        pass

    def _discover_omp_executable(self) -> Optional[str]:
        """Discover OMP executable from PATH or config."""
        # Check explicit config first
        if self.config.omp_path:
            path = Path(self.config.omp_path)
            if path.exists() and os.access(path, os.X_OK):
                return str(path)
            # Try as just a name in PATH
            found = shutil.which(self.config.omp_path)
            if found:
                return found

        # Check common names
        for name in ["omp", "omp-cli", "open-model-platform"]:
            found = shutil.which(name)
            if found:
                return found

        # Check common install locations on Windows
        if os.name == "nt":
            for path in [
                r"C:\Program Files\OMP\omp.exe",
                r"C:\Program Files (x86)\OMP\omp.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\OMP\omp.exe"),
                os.path.expandvars(r"%APPDATA%\OMP\omp.exe"),
            ]:
                if os.path.exists(path):
                    return path

        return None

    def _get_omp_executable(self) -> str:
        """Get OMP executable, discovering if needed."""
        if self._omp_executable is None:
            self._omp_executable = self._discover_omp_executable()
        if self._omp_executable is None:
            raise RuntimeError(
                "OMP executable not found. Install OMP or set OMP_PATH environment variable."
            )
        return self._omp_executable

    def _sanitize_prompt(self, prompt: str) -> str:
        """Sanitize task prompt for safe execution."""
        # Basic sanitization - remove dangerous patterns
        dangerous = ["rm -rf", "sudo ", "del /f", "format ", "mkfs"]
        sanitized = prompt
        for danger in dangerous:
            if danger in sanitized.lower():
                sanitized = sanitized.replace(danger, "# BLOCKED: " + danger)
        return sanitized

    def execute(self, task: Task, context: Dict[str, Any]) -> VerificationResult:
        """Execute task through OMP CLI."""
        try:
            omp_executable = self._get_omp_executable()
            work_dir = self.config.working_directory or context.get("working_directory", ".")

            # Build OMP command
            # OMP CLI typically uses: omp run --prompt "task description"
            cmd = [omp_executable, "run", "--prompt", task.prompt]

            # Add working directory if specified
            if work_dir != ".":
                cmd.extend(["--working-dir", work_dir])

            # Execute with timeout
            start_time = time.time()
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
            )
            end_time = time.time()

            return VerificationResult(
                command=VerificationCommand(command=" ".join(shlex.quote(c) for c in cmd)),
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration=end_time - start_time,
            )

        except subprocess.TimeoutExpired as exc:
            return VerificationResult(
                command=VerificationCommand(command="OMP execution"),
                stdout="",
                stderr=f"Timeout exceeded after {self.config.timeout}s: {exc}",
                exit_code=124,
                duration=self.config.timeout,
            )
        except Exception as exc:
            return VerificationResult(
                command=VerificationCommand(command="OMP execution"),
                stdout="",
                stderr=str(exc),
                exit_code=1,
                duration=0.0,
            )


class OMPAgentResult(AgentResult):
    """Agent result from OMP execution."""

    def __init__(
        self,
        success: bool,
        output: str,
        exit_code: int,
        working_directory: Optional[str] = None,
    ):
        self.success = success
        self.output = output
        self.exit_code = exit_code
        self.working_directory = working_directory