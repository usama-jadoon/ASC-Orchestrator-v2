"""Shell adapter implementation."""

import subprocess
import sys
import time
from typing import Any

from ..models import Task, VerificationResult
from .base import AgentAdapter, AgentResult


class ShellAdapter:
    """Concrete shell command adapter."""

    def can_execute(self, command: str) -> bool:
        """Check if command can execute."""
        return True

    def prepare(self, command: str) -> None:
        """Prepare environment for command."""
        pass

    def execute(self, task: Task, context: dict) -> Any:
        """Execute command and return verification result."""
        command_str = task.prompt
        shell = sys.platform == "win32"
        try:
            start_time = time.time()
            result = subprocess.run(
                command_str,
                capture_output=True,
                text=True,
                timeout=300,
                shell=shell
            )
            end_time = time.time()
            return VerificationResult(
                command=command_str,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration=end_time - start_time
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(
                command=command_str,
                stdout="",
                stderr="Timeout exceeded",
                exit_code=124,
                duration=300
            )
