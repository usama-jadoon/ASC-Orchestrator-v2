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
            cmd, cwd=self.path, capture_output=True, text=True, check=True
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

    def is_git_repo(self) -> bool:
        """Check if path is a git repository."""
        return (self.path / ".git").exists()

    def get_dirty_files(self) -> List[str]:
        """
        Get list of modified/unstage files.

        Returns:
            List of file paths relative to repository root
        """
        if not self.is_git_repo():
            return []
        try:
            out = self._run(["git", "diff", "--name-only"])
            return out.splitlines() if out else []
        except Exception:
            return []

    def has_changes(self) -> bool:
        """Check if repository has uncommitted changes or untracked files."""
        if not self.is_git_repo():
            return False
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.path,
                capture_output=True,
                text=True,
                check=False,
            )
            return bool(res.stdout.strip())
        except Exception:
            return False

    def commit(self, message: str) -> str | None:
        """Stage and commit changes if git repository exists."""
        if not self.is_git_repo():
            return None
        try:
            subprocess.run(
                ["git", "add", "."], cwd=self.path, capture_output=True, check=False
            )
            res = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.path,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                return self.get_head_commit()
        except Exception:
            pass
        return None
