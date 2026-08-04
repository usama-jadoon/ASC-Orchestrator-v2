"""Black-box coverage for deterministic TBE CLI assembly."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = (ROOT / ".project-os" / "COMPANY" / "DEPARTMENTS").as_posix()
CONFIG = f'''[runtime]
project_os_dir = ".project-os"
registry_dir = "{REGISTRY}"
audit_dir = ".project-os/AUDIT"
protocol_version = "ACP/v1.0"
'''
MISSION = {
    "mission_id": "MISSION:cli",
    "mission_type": "Investigation",
    "objective": "Inspect the repository without autonomous execution.",
    "demands": [
        {
            "id": "ASSIGNMENT:inspect",
            "capability": "investigator",
            "project": ".",
            "criterion": "classify",
            "paths": [],
            "role": "investigator",
        }
    ],
}
CLASSIFICATION = [
    {
        "type": "python-package",
        "root": ".",
        "languages": ["python"],
        "frameworks": [],
        "platform": "local",
        "test_surface": "unittest",
        "deployment_surface": "",
        "constraint_tags": [],
    }
]


class TBECliTests(unittest.TestCase):
    @staticmethod
    def _run(root: Path, *arguments: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(root), *arguments])
        return code, output.getvalue()

    def test_team_build_persists_reversible_canonical_manifest_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
            (root / "mission.json").write_text(json.dumps(MISSION), encoding="utf-8")
            (root / "classification.json").write_text(
                json.dumps(CLASSIFICATION), encoding="utf-8"
            )
            code, output = self._run(
                root,
                "team-build",
                "--mission",
                "mission.json",
                "--classification",
                "classification.json",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("team_id=TEAM:MISSION:cli:1", output)
            manifest = (
                root
                / ".project-os"
                / "COMPANY"
                / "TEAMS"
                / "TEAM%3AMISSION%3Acli%3A1"
                / "TEAM.md"
            )
            self.assertTrue(manifest.is_file())
            self.assertIn("## TEAM IDENTITY", manifest.read_text(encoding="utf-8"))

    def test_team_build_is_byte_reproducible_when_timestamp_is_an_input(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
            (root / "mission.json").write_text(json.dumps(MISSION), encoding="utf-8")
            (root / "classification.json").write_text(
                json.dumps(CLASSIFICATION), encoding="utf-8"
            )
            arguments = (
                "team-build",
                "--mission",
                "mission.json",
                "--classification",
                "classification.json",
                "--assembled-at",
                "2026-08-04T00:00:00.000Z",
            )
            self.assertEqual(self._run(root, *arguments)[0], 0)
            manifest = (
                root
                / ".project-os"
                / "COMPANY"
                / "TEAMS"
                / "TEAM%3AMISSION%3Acli%3A1"
                / "TEAM.md"
            )
            first = manifest.read_bytes()
            self.assertEqual(self._run(root, *arguments)[0], 0)
            self.assertEqual(manifest.read_bytes(), first)

    def test_team_build_can_bind_its_written_manifest_to_initialized_pese(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
            (root / "mission.json").write_text(json.dumps(MISSION), encoding="utf-8")
            (root / "classification.json").write_text(
                json.dumps(CLASSIFICATION), encoding="utf-8"
            )
            self.assertEqual(self._run(root, "state", "--initialize")[0], 0)
            code, output = self._run(
                root,
                "team-build",
                "--mission",
                "mission.json",
                "--classification",
                "classification.json",
                "--bind-state",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("validation=PASS", output)
            self.assertEqual(self._run(root, "state")[0], 0)
