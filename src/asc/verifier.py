"""Universal ASC v2.0.0 - Verification Module

Executes verification commands independently with exit code capture.
"""

import os
import subprocess
import time
from typing import List, Optional, Union

from .models import VerificationCommand, VerificationResult


class Verifier:
    """Interface for verification command execution."""

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def run_verification(
        self,
        commands: List[Union[str, VerificationCommand]],
        cwd: str = ".",
        timeout: Optional[int] = None,
    ) -> VerificationResult:
        """Execute verification commands and return results."""
        if timeout is None:
            timeout = self.timeout

        cmd = commands[0]
        if isinstance(cmd, str):
            command_str = cmd
            cmd_timeout = timeout
        else:
            command_str = cmd.command
            cmd_timeout = cmd.timeout if cmd.timeout is not None else timeout

        # On Windows, use shell=True for built-ins like 'exit'
        # Use shell=True for string commands to ensure cross-platform compatibility (e.g., 'exit', 'echo')
        shell = True
        try:
            start_time = time.time()
            effective_cwd = cwd if (cwd and os.path.exists(cwd)) else None
            result = subprocess.run(
                command_str,
                cwd=effective_cwd,
                capture_output=True,
                text=True,
                timeout=min(timeout, cmd_timeout),
                shell=shell,
            )
            end_time = time.time()
            vr = VerificationResult(
                command=cmd
                if isinstance(cmd, VerificationCommand)
                else VerificationCommand(command=command_str),
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration=end_time - start_time,
            )
            return vr
        except subprocess.TimeoutExpired:
            vr = VerificationResult(
                command=cmd
                if isinstance(cmd, VerificationCommand)
                else VerificationCommand(command=command_str),
                stdout="",
                stderr=f"Timeout after {timeout}s",
                exit_code=124,
                duration=timeout,
            )
            return vr
