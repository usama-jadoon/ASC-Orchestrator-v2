"""
Universal ASC v2.0.0 Repository Inspector

Provides Git repository introspection for mission contexts.
"""

import subprocess
from pathlib import Path
from typing import List


class Repository:
    """
    Git repository inspector for mission contexts.
    
    Args:
        path: Repository path (defaults to current directory)
    """

    def __init__(self, path: str | Path = "."):
        self.path = Path(path)

    def _run(self, cmd: List[str]) -> str:
        """
        Execute git command and return stdout.
        
        Args:
            cmd: Git command list
            
        Returns:
            Command output stripped of trailing whitespace
        """
        result = subprocess.run(
            cmd,
            cwd=self.path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()

    def get_head_commit(self) -> str:
        """
        Get current HEAD commit hash.
        
        Returns:
            40-character SHA-1 hash
        """
        return self._run(["git", "rev-parse", "HEAD"])

    def get_current_branch(self) -> str:
        """
        Get current branch name.
        
        Returns:
            Branch name string
        """
        return self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])

    def get_dirty_files(self) -> List[str]:
        """
        Get list of modified/unstage files.
        
        Returns:
            List of file paths relative to repository root
        """
        out = self._run(["git", "diff", "--name-only"])
        return out.splitlines() if out else []