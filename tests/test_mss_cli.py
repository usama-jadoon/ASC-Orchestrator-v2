"""Black-box coverage for the MSS validate-mission CLI command."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main

CONFIG = """[runtime]
project_os_dir = ".project-os"
registry_dir = "registry"
audit_dir = ".project-os/AUDIT"
protocol_version = "ACP/v1.0"
"""

VALID_MISSION = {
    "schema": "MSS",
    "version": "1.0",
    "mission_id": "MISSION:cli-mss",
    "mission_type": "enhancement",
    "mission_class": "bounded",
    "priority": "MEDIUM",
    "objective": "CLI integration test for the MSS validate-mission command.",
    "acceptance_criteria": [
        {
            "id": "AC-1",
            "description": "The validate-mission CLI command returns validation=PASS.",
            "gate": "GATE:qa",
        }
    ],
    "constraints": [],
    "constraint_tags": [],
    "value_streams": [],
    "boundaries": [],
    "stakeholders": [],
    "validation_gates": ["GATE:qa"],
    "authority_scope": [
        "Repository State: read/write within owned paths",
    ],
    "created_at": "2026-08-04T00:00:00.000Z",
    "created_by": "AGENT:orchestrator:local",
    "source": "tests/test_mss_cli.py",
    "extensions": {},
}

INVALID_MISSION = {
    **VALID_MISSION,
    "mission_id": "MISSION:cli-mss",
    "mission_type": "bogus-type",
}


class MSSCliTests(unittest.TestCase):
    @staticmethod
    def _run(root: Path, *arguments: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(root), *arguments])
        return code, output.getvalue()

    def test_validate_mission_pass_for_valid_spec_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
            (root / "mission.json").write_text(
                json.dumps(VALID_MISSION), encoding="utf-8"
            )
            code, output = self._run(root, "validate-mission", "--file", "mission.json")
            self.assertEqual(code, 0, output)
            self.assertIn("validation=PASS", output)
            self.assertIn("mission_id=MISSION:cli-mss", output)
            self.assertIn("mission_type=enhancement", output)

    def test_validate_mission_fail_for_invalid_mission_type(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
            (root / "bad-mission.json").write_text(
                json.dumps(INVALID_MISSION), encoding="utf-8"
            )
            code, output = self._run(
                root, "validate-mission", "--file", "bad-mission.json"
            )
            self.assertEqual(code, 2, output)
            self.assertIn("validation=FAIL", output)
            self.assertIn("MISSION_TYPE_UNKNOWN", output)

    def test_validate_mission_error_for_missing_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
            code, output = self._run(root, "validate-mission", "--file", "nope.json")
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_validate_mission_error_for_invalid_json(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
            (root / "junk.json").write_text("}{", encoding="utf-8")
            code, output = self._run(root, "validate-mission", "--file", "junk.json")
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)


if __name__ == "__main__":
    unittest.main()
