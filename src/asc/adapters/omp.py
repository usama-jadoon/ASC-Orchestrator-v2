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
            omp_path = self.config.omp_path
            if os.path.exists(omp_path) and os.access(omp_path, os.X_OK):
                return omp_path
            # Try as just a name in PATH
            found = shutil.which(omp_path)
            if found:
                return found

        # Check common names
        for name in ["omp", "omp-cli", "open-model-platform"]:
            found = shutil.which(name)
            if found:
                return found

        # Check common install locations on Windows
        if os.name == "nt":
            for install_path in [
                r"C:\Program Files\OMP\omp.exe",
                r"C:\Program Files (x86)\OMP\omp.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\OMP\omp.exe"),
                os.path.expandvars(r"%APPDATA%\OMP\omp.exe"),
            ]:
                if os.path.exists(install_path):
                    return install_path

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

    def _resolve_working_dir(self, context: Dict[str, Any]) -> str:
        """Resolve the working directory for execution.

        Priority: task-level working_directory, then adapter config, then
        context, then current directory.
        """
        work_dir = (
            context.get("working_directory") or self.config.working_directory or "."
        )
        return str(work_dir)

    def execute(self, task: Task, context: Dict[str, Any]) -> VerificationResult:
        """Execute task through the real OMP CLI.

        Uses the verified OMP invocation:
            omp launch [MESSAGES...] [FLAGS]
        where MESSAGES are positional (the task prompt), and supported flags
        include --cwd, -p/--print (non-interactive), and --auto-approve.
        There is no `run` subcommand and no `--timeout` flag; the timeout is
        enforced by this harness via subprocess.
        """
        try:
            omp_executable = self._get_omp_executable()
            work_dir = self._resolve_working_dir(context)

            # Real OMP CLI invocation. The prompt is passed as a positional
            # argument; no invented --prompt flag. Windows paths with spaces
            # are passed as a single argv element (no shell), so quoting is
            # handled by subprocess/argv, not by the harness.
            cmd = [omp_executable, "launch", "-p", "--auto-approve"]
            if work_dir and work_dir != ".":
                cmd.extend(["--cwd", work_dir])
            cmd.append(task.prompt)

            start_time = time.time()
            result = subprocess.run(
                cmd,
                cwd=work_dir if work_dir != "." else None,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
            )
            end_time = time.time()

            return VerificationResult(
                command=VerificationCommand(
                    command=" ".join(shlex.quote(c) for c in cmd)
                ),
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
