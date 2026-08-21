"""Universal ASC v2.3.0 - Repository Inspector & Git Safety Module.

Provides Git repository introspection, porcelain status inspection,
scoped staging, dirty-state protection, and safe attempt rollback.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set


@dataclass
class GitStatus:
    """Detailed porcelain status of a Git repository."""

    staged: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    untracked: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True if there are no staged, modified, untracked, or deleted files."""
        return not (self.staged or self.modified or self.untracked or self.deleted)

    @property
    def all_dirty(self) -> List[str]:
        """All files that diverge from clean HEAD."""
        dirty = set(self.staged + self.modified + self.untracked + self.deleted)
        return sorted(dirty)


class Repository:
    """
    Git repository inspector and safe change-set operator for ASC missions.

    Args:
        path: Repository path (defaults to current directory)
    """

    def __init__(self, path: str | Path = "."):
        self.path = Path(path).resolve()

    def _run(self, cmd: List[str]) -> str:
        """Execute git command and return stdout stripped."""
        result = subprocess.run(
            cmd, cwd=self.path, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    def is_git_repo(self) -> bool:
        """Check if path is inside a git repository."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.path,
                capture_output=True,
                text=True,
                check=False,
            )
            return res.returncode == 0 and res.stdout.strip() == "true"
        except Exception:
            return False

    def get_root_dir(self) -> Path:
        """Get the top-level repository root directory."""
        if not self.is_git_repo():
            return self.path
        try:
            out = self._run(["git", "rev-parse", "--show-toplevel"])
            return Path(out).resolve()
        except Exception:
            return self.path

    def get_repo_name(self) -> str:
        """Get repository name from root directory."""
        return self.get_root_dir().name

    def get_head_commit(self) -> str:
        """Get current HEAD commit hash."""
        if not self.is_git_repo():
            return ""
        try:
            return self._run(["git", "rev-parse", "HEAD"])
        except Exception:
            return ""

    def get_current_branch(self) -> str:
        """Get current branch name."""
        if not self.is_git_repo():
            return ""
        try:
            return self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        except Exception:
            return ""

    def get_porcelain_status(self) -> GitStatus:
        """Inspect full porcelain status of repository."""
        if not self.is_git_repo():
            return GitStatus()

        try:
            res = subprocess.run(
                ["git", "status", "--porcelain=v1"],
                cwd=self.path,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                return GitStatus()

            staged: List[str] = []
            modified: List[str] = []
            untracked: List[str] = []
            deleted: List[str] = []

            for line in res.stdout.splitlines():
                if not line or len(line) < 4:
                    continue
                code = line[:2]
                filepath = line[3:].strip()
                if " -> " in filepath:
                    filepath = filepath.split(" -> ")[1].strip()

                x, y = code[0], code[1]

                if x in ("M", "A", "D", "R", "C"):
                    staged.append(filepath)
                if y == "M":
                    modified.append(filepath)
                if y == "D" or x == "D":
                    deleted.append(filepath)
                if code == "??":
                    untracked.append(filepath)

            return GitStatus(
                staged=sorted(set(staged)),
                modified=sorted(set(modified)),
                untracked=sorted(set(untracked)),
                deleted=sorted(set(deleted)),
            )
        except Exception:
            return GitStatus()

    def is_clean(self) -> bool:
        """Check if repository has zero uncommitted changes and no untracked files."""
        return self.get_porcelain_status().is_clean

    def get_dirty_files(self) -> List[str]:
        """Get list of all dirty files (staged, modified, untracked, deleted)."""
        return self.get_porcelain_status().all_dirty

    def has_changes(self) -> bool:
        """Check if repository has uncommitted changes or untracked files."""
        return not self.is_clean()

    def get_tracked_and_untracked_files(self) -> Set[str]:
        """Capture snapshot of all files currently existing in repo."""
        if not self.is_git_repo():
            return set()
        status = self.get_porcelain_status()
        return set(status.all_dirty)

    def commit_scoped(
        self,
        message: str,
        paths: Optional[List[str]] = None,
        commit_paths_filter: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Stage and commit only allowed task delta.
        Never blindly runs 'git add .'.

        Args:
            message: Git commit message
            paths: Specific file paths created/modified by this task (task delta)
            commit_paths_filter: Optional allowable commit scope from task spec
        """
        if not self.is_git_repo():
            return None

        # If paths not explicitly provided, discover current dirty files
        files_to_stage = paths if paths is not None else self.get_dirty_files()
        if not files_to_stage:
            return None

        # Enforce commit_paths filter if provided
        if commit_paths_filter is not None:
            allowed_set = set(commit_paths_filter)
            disallowed = [f for f in files_to_stage if f not in allowed_set]
            if disallowed:
                raise ValueError(
                    f"Changes detected outside allowed task commit_paths: {disallowed}"
                )

        # Stage ONLY specific task files
        for f in files_to_stage:
            target_file = self.path / f
            if target_file.exists():
                subprocess.run(
                    ["git", "add", "--", f],
                    cwd=self.path,
                    capture_output=True,
                    check=False,
                )
            else:
                # File was deleted
                subprocess.run(
                    ["git", "rm", "--cached", "--ignore-unmatch", "--", f],
                    cwd=self.path,
                    capture_output=True,
                    check=False,
                )

        # Commit staged files
        res = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=self.path,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return self.get_head_commit()
        return None

    def commit(self, message: str) -> Optional[str]:
        """Backward-compatible commit method using scoped staging."""
        return self.commit_scoped(message=message)

    def rollback_attempt(self, delta_paths: List[str]) -> None:
        """
        Roll back only task-created changes after a failed attempt.
        Never runs broad 'git reset --hard' or 'git clean -fd' on the repository.
        Never recursively deletes entire unknown directories.
        """
        if not self.is_git_repo() or not delta_paths:
            return

        status = self.get_porcelain_status()
        untracked_set = set(status.untracked)
        modified_or_staged = set(status.modified + status.staged)

        for path_str in delta_paths:
            p = self.path / path_str
            if not p.exists():
                continue

            if path_str in untracked_set:
                try:
                    if p.is_file():
                        p.unlink(missing_ok=True)
                        # Clean up empty parent directory safely if inside repo
                        parent = p.parent
                        if parent != self.path and parent.exists():
                            try:
                                os.rmdir(parent)  # Only succeeds if directory is completely empty
                            except OSError:
                                pass
                except Exception:
                    pass
            elif path_str in modified_or_staged:
                # Checkout tracked file back to HEAD
                subprocess.run(
                    ["git", "checkout", "HEAD", "--", path_str],
                    cwd=self.path,
                    capture_output=True,
                    check=False,
                )
