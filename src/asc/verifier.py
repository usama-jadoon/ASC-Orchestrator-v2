"""Universal ASC v2.3.0 - Verification Module

Executes verification commands independently with sequential execution,
fail-fast semantics, per-command timeout/cwd, and exit code capture.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Union

from .models import VerificationCommand, VerificationResult


class Verifier:
    """Interface for multi-command verification execution."""

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def run_verification(
        self,
        commands: List[Union[str, VerificationCommand]],
        cwd: str = ".",
        timeout: Optional[int] = None,
    ) -> VerificationResult:
        """
        Execute verification commands in sequence and return aggregate result.
        Stops on first command failure (fail-fast).
        """
        if not commands:
            cmd = VerificationCommand(command="true")
            return VerificationResult(command=cmd, exit_code=0, stdout="", stderr="", duration=0.0)

        overall_timeout = timeout if timeout is not None else self.timeout
        results: List[Dict[str, Any]] = []
        combined_stdout: List[str] = []
        combined_stderr: List[str] = []
        total_duration = 0.0
        final_exit_code = 0
        last_cmd_obj: VerificationCommand = (
            commands[0]
            if isinstance(commands[0], VerificationCommand)
            else VerificationCommand(command=commands[0])
        )

        for i, cmd in enumerate(commands):
            if isinstance(cmd, str):
                cmd_obj = VerificationCommand(command=cmd)
            else:
                cmd_obj = cmd
            last_cmd_obj = cmd_obj

            cmd_timeout = (
                cmd_obj.timeout
                if cmd_obj.timeout is not None
                else overall_timeout
            )
            cmd_cwd = cmd_obj.cwd if cmd_obj.cwd else cwd
            effective_cwd = cmd_cwd if (cmd_cwd and os.path.exists(cmd_cwd)) else None

            start_time = time.time()
            try:
                result = subprocess.run(
                    cmd_obj.command,
                    cwd=effective_cwd,
                    capture_output=True,
                    text=True,
                    timeout=cmd_timeout,
                    shell=True,
                )
                dur = time.time() - start_time
                total_duration += dur
                cmd_exit = result.returncode

                results.append({
                    "command": cmd_obj.command,
                    "exit_code": cmd_exit,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "duration": dur,
                })
                if result.stdout:
                    combined_stdout.append(result.stdout)
                if result.stderr:
                    combined_stderr.append(result.stderr)

                if cmd_exit != 0:
                    final_exit_code = cmd_exit
                    break

            except subprocess.TimeoutExpired:
                dur = time.time() - start_time
                total_duration += dur
                final_exit_code = 124
                timeout_msg = f"Timeout after {cmd_timeout}s executing '{cmd_obj.command}'"
                results.append({
                    "command": cmd_obj.command,
                    "exit_code": 124,
                    "stdout": "",
                    "stderr": timeout_msg,
                    "duration": dur,
                })
                combined_stderr.append(timeout_msg)
                break
            except Exception as exc:
                dur = time.time() - start_time
                total_duration += dur
                final_exit_code = 1
                err_msg = f"Error executing '{cmd_obj.command}': {exc}"
                results.append({
                    "command": cmd_obj.command,
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": err_msg,
                    "duration": dur,
                })
                combined_stderr.append(err_msg)
                break

        vr = VerificationResult(
            command=last_cmd_obj,
            exit_code=final_exit_code,
            stdout="\n".join(combined_stdout),
            stderr="\n".join(combined_stderr),
            duration=total_duration,
            results=results,
        )
        return vr
