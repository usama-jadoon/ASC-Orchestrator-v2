"""Black-box coverage for the PESE command-line boundary."""

from __future__ import annotations

import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main

CONFIG = """[runtime]
project_os_dir = \".project-os\"
registry_dir = \".project-os/COMPANY/DEPARTMENTS\"
audit_dir = \".project-os/AUDIT\"
protocol_version = \"ACP/v1.0\"
"""


class PESECliTests(unittest.TestCase):
    def _root(self) -> TemporaryDirectory[str]:
        temporary = TemporaryDirectory()
        root = Path(temporary.name)
        (root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
        self._git(root, "init")
        self._git(root, "config", "user.email", "tests@example.invalid")
        self._git(root, "config", "user.name", "PESE Tests")
        (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git(root, "add", "tracked.txt")
        self._git(root, "commit", "-m", "initial")
        return temporary

    @staticmethod
    def _git(root: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _run(root: Path, *arguments: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            result = main(["--root", str(root), *arguments])
        return result, output.getvalue()

    def test_state_validate_and_resume_commands_have_deterministic_outcomes(
        self,
    ) -> None:
        with self._root() as directory:
            root = Path(directory)
            result, output = self._run(root, "state", "--initialize")
            self.assertEqual(result, 0)
            self.assertIn("outcome=INITIALIZED", output)

            result, output = self._run(root, "state")
            self.assertEqual(result, 0)
            self.assertIn("outcome=STATE_LOADED", output)

            result, output = self._run(root, "validate-state")
            self.assertEqual(result, 0)
            self.assertIn("outcome=VALID", output)

            result, output = self._run(root, "resume")
            self.assertEqual(result, 0)
            self.assertIn("outcome=NO_WORK", output)

    def test_checkpoint_command_rejects_an_unknown_mission_without_writing(
        self,
    ) -> None:
        with self._root() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "state", "--initialize")[0], 0)
            result, output = self._run(
                root, "checkpoint", "--mission-id", "MISSION-007"
            )
            self.assertEqual(result, 2)
            self.assertIn("outcome=INVALID", output)

    def test_reconcile_repository_command_unblocks_validated_state(self) -> None:
        with self._root() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "state", "--initialize")[0], 0)
            # Advance Git HEAD the way an authorized commit does.
            (root / "tracked.txt").write_text("second\n", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "second")
            result, output = self._run(root, "validate-state")
            self.assertEqual(result, 2)
            self.assertIn("REPOSITORY_DIVERGENCE", output)

            result, output = self._run(root, "reconcile-repository")
            self.assertEqual(result, 0)
            self.assertIn("outcome=RECONCILIATED", output)

            result, output = self._run(root, "validate-state")
            self.assertEqual(result, 0)
            self.assertIn("outcome=VALID", output)

    def test_reconcile_repository_command_rejects_a_stale_expected_revision(
        self,
    ) -> None:
        with self._root() as directory:
            root = Path(directory)
            self.assertEqual(self._run(root, "state", "--initialize")[0], 0)
            result, output = self._run(
                root, "reconcile-repository", "--expected-revision", "99"
            )
            self.assertEqual(result, 2)
            self.assertIn("outcome=CONFLICT", output)
