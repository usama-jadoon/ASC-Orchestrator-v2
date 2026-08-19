"""Universal ASC v2.0.0 - Verification Module

Executes verification commands independently with exit code capture.
"""

import subprocess
import time
import sys
from typing import List, Union

from .models import VerificationCommand, VerificationResult


class Verifier:
    """Interface for verification command execution."""

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def run_verification(self, commands: List[Union[str, VerificationCommand]], cwd: str = ".", timeout: int = None) -> VerificationResult:
        """Execute verification commands and return results."""
        if timeout is None:
            timeout = self.timeout

        cmd = commands[0]
        if isinstance(cmd, str):
            command_str = cmd
            cmd_timeout = timeout
        else:
            command_str = cmd.command
            cmd_timeout = cmd.timeout

        # On Windows, use shell=True for built-ins like 'exit'
        shell = sys.platform == "win32"
        try:
            start_time = time.time()
            result = subprocess.run(
                command_str,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=min(timeout, cmd_timeout),
                shell=shell
            )
            end_time = time.time()
            vr = VerificationResult(
                command=cmd if isinstance(cmd, VerificationCommand) else VerificationCommand(command=command_str),
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration=end_time - start_time
            )
            return vr
        except subprocess.TimeoutExpired as e:
            vr = VerificationResult(
                command=cmd if isinstance(cmd, VerificationCommand) else VerificationCommand(command=command_str),
                stdout="",
                stderr=f"Timeout after {timeout}s",
                exit_code=124,
                duration=timeout
            )
            return vr
