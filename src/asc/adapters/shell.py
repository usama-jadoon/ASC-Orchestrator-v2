"""Shell adapter implementation."""

import subprocess
import time
from typing import Any

from ..models import Task, VerificationCommand, VerificationResult
from .base import AgentAdapter


class ShellAdapter(AgentAdapter):
    """Concrete shell command adapter."""

    def can_execute(self, task: Task) -> bool:
        """Check if command can execute."""
        return True

    def prepare(self, context: dict) -> None:
        """Prepare environment for command."""
        pass

    def cleanup(self) -> None:
        """Clean up adapter resources."""
        pass

    def execute(self, task: Task, context: dict) -> Any:
        """Execute command and return verification result."""
        command_str = task.prompt
        # Use shell=True for string commands to ensure cross-platform compatibility (e.g., 'exit', 'echo')
        shell = True
        try:
            start_time = time.time()
            result = subprocess.run(
                command_str, capture_output=True, text=True, timeout=300, shell=shell
            )
            end_time = time.time()
            return VerificationResult(
                command=VerificationCommand(command=command_str),
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration=end_time - start_time,
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(
                command=VerificationCommand(command=command_str),
                stdout="",
                stderr="Timeout exceeded",
                exit_code=124,
                duration=300,
            )
