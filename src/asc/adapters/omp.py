"""Universal ASC v2.2.0 - OMP Adapter Module.

Real OMP (Open Model Platform) adapter for executing coding tasks with
heartbeat reporting and process isolation.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..models import AgentResult, Task, VerificationCommand, VerificationResult
from .base import AgentAdapter


@dataclass
class OMPConfig:
    """Configuration for OMP adapter."""

    timeout: int = 600
    omp_path: Optional[str] = None
    working_directory: Optional[str] = None
    model: Optional[str] = None


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
        if self.config.working_directory:
            work_dir = Path(self.config.working_directory)
            if not work_dir.exists():
                work_dir.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        """Clean up adapter resources."""
        pass

    def _discover_omp_executable(self) -> Optional[str]:
        """Discover OMP executable from PATH or config."""
        if self.config.omp_path:
            omp_path = self.config.omp_path
            if os.path.exists(omp_path) and os.access(omp_path, os.X_OK):
                return omp_path
            found = shutil.which(omp_path)
            if found:
                return found

        env_omp = os.environ.get("OMP_PATH")
        if env_omp and os.path.exists(env_omp) and os.access(env_omp, os.X_OK):
            return env_omp

        for name in ["omp", "omp.exe", "omp-cli", "open-model-platform"]:
            found = shutil.which(name)
            if found:
                return found

        home = Path.home()
        for bun_candidate in [
            home / ".bun" / "bin" / "omp.exe",
            home / ".bun" / "bin" / "omp",
        ]:
            if bun_candidate.exists():
                return str(bun_candidate)

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
        """Resolve the working directory for execution."""
        work_dir = (
            context.get("working_directory") or self.config.working_directory or "."
        )
        return str(work_dir)

    def execute(self, task: Task, context: Dict[str, Any]) -> VerificationResult:
        """Execute task through the real OMP CLI.

        Invocation:
            omp -p --auto-approve [--model <model>] [--cwd <target>] <prompt>
        """
        try:
            omp_executable = self._get_omp_executable()
            work_dir = self._resolve_working_dir(context)
            timeout = (
                task.execution_timeout
                or context.get("execution_timeout")
                or self.config.timeout
            )

            cmd = [omp_executable, "-p", "--auto-approve"]
            model = (
                (context or {}).get("model")
                or (task.metadata or {}).get("model")
                or getattr(self.config, "model", None)
                or os.environ.get("OMP_MODEL")
            )
            if model:
                cmd.extend(["--model", model])
            if work_dir and work_dir != ".":
                cmd.extend(["--cwd", work_dir])
            cmd.append(task.prompt)

            heartbeat_callback: Optional[Callable[[float], None]] = (context or {}).get(
                "heartbeat_callback"
            )

            start_time = time.time()

            if heartbeat_callback is not None:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=work_dir if work_dir != "." else None,
                    text=True,
                )
                while True:
                    ret = proc.poll()
                    elapsed = time.time() - start_time
                    if ret is not None:
                        break
                    if elapsed > timeout:
                        proc.kill()
                        return VerificationResult(
                            command=VerificationCommand(command="OMP execution"),
                            stdout="",
                            stderr=f"Timeout exceeded after {timeout}s",
                            exit_code=124,
                            duration=timeout,
                        )
                    heartbeat_callback(elapsed)
                    time.sleep(0.5)

                stdout_out, stderr_out = proc.communicate()
                end_time = time.time()
                return VerificationResult(
                    command=VerificationCommand(
                        command=" ".join(shlex.quote(c) for c in cmd)
                    ),
                    stdout=stdout_out or "",
                    stderr=stderr_out or "",
                    exit_code=proc.returncode,
                    duration=end_time - start_time,
                )
            else:
                result = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    cwd=work_dir if work_dir != "." else None,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
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
                stderr=f"Timeout exceeded after {timeout}s: {exc}",
                exit_code=124,
                duration=timeout,
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
