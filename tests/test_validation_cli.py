"""Black-box CLI boundary tests for the Validation Engine (VAL) v1.0."""

from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main

MISSION = {
    "mission_id": "MISSION:cli",
    "mission_type": "enhancement",
    "objective": "Add a deterministic validation capability.",
    "demands": [
        {
            "id": "ASSIGNMENT:build",
            "capability": "developer",
            "project": "app",
            "criterion": "works",
            "paths": ["src/feature.py"],
            "validation_gates": ["functional"],
        }
    ],
}
CLASSIFICATION = [
    {
        "type": "python-package",
        "root": "app",
        "languages": ["python"],
        "frameworks": [],
        "platform": "linux",
        "test_surface": "unittest",
    }
]
GATE_ID = "GATE:MISSION:cli:functional"


def _valid_entry(
    agent_id: str,
    *,
    competencies: tuple[str, ...] = (),
    writable: tuple[str, ...] = ("src/**",),
    outputs: tuple[str, ...] = ("EVIDENCE", "REVIEW"),
    inputs: tuple[str, ...] = ("EVIDENCE", "REVIEW"),
    gates: tuple[str, ...] = (),
) -> dict[str, object]:
    skills = list(competencies) or [agent_id]
    validation_gates = list(gates) or ["functional"]
    return {
        "agent-id": agent_id,
        "version": "1.0.0",
        "display-name": agent_id.replace("-", " ").title(),
        "description": f"{agent_id} agent for CLI tests.",
        "purpose": {
            "mission-types": ["enhancement"],
            "value-streams": ["delivery"],
            "strategic-objectives": ["reliability"],
        },
        "responsibilities": {
            "primary-duties": ["complete assigned work"],
            "excluded-duties": ["unrelated work"],
        },
        "authority": {
            "autonomous-decisions": ["choose implementation details"],
            "escalation-decisions": ["change mission scope"],
            "authority-scope": ["assigned mission"],
        },
        "decision-rights": {
            "decision-types": ["implementation"],
            "decision-criteria": {"implementation": ["mission criterion"]},
            "reversibility": {"implementation": "reversible"},
        },
        "escalation-rights": {
            "escalation-triggers": ["blocked"],
            "escalation-paths": {"blocked": "orchestrator"},
            "escalation-timeout": "30",
        },
        "required-skills": {
            "competencies": skills,
            "proficiency-levels": {skill: "intermediate" for skill in skills},
            "skill-validators": {skill: "test evidence" for skill in skills},
        },
        "allowed-tools": {
            "tool-categories": ["development"],
            "specific-tools": ["python"],
            "tool-restrictions": ["no network"],
            "tool-validation": ["approved"],
        },
        "allowed-mcp-servers": {
            "mcp-server-types": ["filesystem"],
            "specific-servers": ["filesystem:local"],
            "mcp-restrictions": ["no network"],
        },
        "owned-artifacts": {
            "artifact-types": ["evidence"],
            "artifact-locations": {"evidence": "artifacts/"},
            "artifact-ownership": {"evidence": "exclusive"},
            "artifact-retention": {"evidence": "mission"},
        },
        "owned-repository-areas": {
            "owned-paths": list(writable),
            "writable-paths": list(writable),
            "path-restrictions": ["/.git/", "/.project-os/"],
            "path-validation": ["paths are checked"],
        },
        "communication-rights": {
            "message-types-sent": ["PROGRESS"],
            "message-types-received": ["ASSIGNMENT"],
            "communication-restrictions": ["mission scope only"],
            "correlation-rules": ["retain mission correlation"],
        },
        "validation-duties": {
            "validation-gates": validation_gates,
            "validation-criteria": {g: ["criterion"] for g in validation_gates},
            "evidence-requirements": {g: ["evidence"] for g in validation_gates},
            "validation-automation": {g: "automated" for g in validation_gates},
        },
        "recovery-duties": {
            "recovery-scenarios": ["agent failure"],
            "recovery-procedures": {"agent failure": ["reassign"]},
            "state-checkpoints": {"before work": ["execution-state"]},
            "recovery-validation": {"agent failure": "state restored"},
        },
        "kpis-and-success-metrics": {
            "kpi-definitions": {"completion": {"target": "100%"}},
            "metric-collection-method": {"completion": "assignment state"},
            "success-thresholds": {"completion": "green"},
            "metric-reporting-frequency": {"completion": "per mission"},
        },
        "parallel-execution-rules": {
            "can-run-concurrently": "yes",
            "shared-resources": "none",
            "conflict-resolution": "deterministic order",
            "resource-limits": "max: 3",
        },
        "dependencies": {
            "agent-dependencies": "none",
            "tool-dependencies": ["python"],
            "environment-dependencies": ["temporary directory"],
            "dependency-validation": ["versions checked"],
        },
        "input-contracts": {
            "input-message-types": list(inputs),
            "input-schema": {
                message: {"required": ["REFERENCE"]} for message in inputs
            },
            "input-validation": ["reference is valid"],
            "input-state-requirements": ["active mission"],
        },
        "output-contracts": {
            "output-message-types": list(outputs),
            "output-schema": {
                message: {"required": ["REFERENCE"]} for message in outputs
            },
            "output-state-changes": ["assignment progress"],
            "output-validation": ["reference is valid"],
        },
    }


class ValCliTests(unittest.TestCase):
    """Full validation CLI lifecycle in a temp git repo."""

    @staticmethod
    def _run(root: Path, *arguments: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(root), *arguments])
        return code, output.getvalue()

    @staticmethod
    def _git(root: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    def _bound_mission(self, directory: str) -> Path:
        root = Path(directory)
        registry_dir = root / "registry"
        registry_dir.mkdir(parents=True, exist_ok=True)
        for name, agent in [
            (
                "developer",
                _valid_entry("developer", competencies=("python", "implementation")),
            ),
            (
                "reviewer",
                _valid_entry(
                    "reviewer",
                    competencies=("python", "review"),
                    writable=(),
                    outputs=("REVIEW",),
                    inputs=("EVIDENCE",),
                ),
            ),
            (
                "qa-validator",
                _valid_entry(
                    "qa-validator",
                    competencies=("python",),
                    writable=(),
                    outputs=("VALIDATION",),
                    inputs=("EVIDENCE", "REVIEW"),
                    gates=("functional",),
                ),
            ),
        ]:
            agent["display-name"] = name.replace("-", " ").title()
            agent["description"] = f"{name} agent for CLI tests."
            (registry_dir / f"{name}.json").write_text(
                json.dumps(agent), encoding="utf-8"
            )
        config = (
            '[runtime]\nproject_os_dir = ".project-os"\n'
            'registry_dir = "registry"\n'
            'audit_dir = ".project-os/AUDIT"\n'
            'protocol_version = "ACP/v1.0"\n'
        )
        (root / "asc-orchestrator.toml").write_text(config, encoding="utf-8")
        (root / "mission.json").write_text(json.dumps(MISSION), encoding="utf-8")
        (root / "classification.json").write_text(
            json.dumps(CLASSIFICATION), encoding="utf-8"
        )
        self._git(root, "init")
        self._git(root, "config", "user.email", "tests@example.invalid")
        self._git(root, "config", "user.name", "VAL CLI Tests")
        (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git(root, "add", "tracked.txt")
        self._git(root, "commit", "-m", "initial")
        code, output = self._run(root, "state", "--initialize")
        self.assertEqual(code, 0, output)
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
        return root

    # -- gates listing -------------------------------------------------------

    def test_validation_gates_initial(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root, "validation-gates", "--mission-id", "MISSION:cli"
            )
            self.assertEqual(code, 0, output)
            self.assertIn("gate_count=1", output)
            self.assertIn(f"gate_id={GATE_ID}", output)
            self.assertIn("status=PENDING", output)

    # -- start ---------------------------------------------------------------

    def test_validation_start_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0, output)
            self.assertIn("outcome=UPDATED", output)
            # Verify RUNNING
            code, output = self._run(
                root, "validation-gates", "--mission-id", "MISSION:cli"
            )
            self.assertIn("status=RUNNING", output)

    def test_validation_start_rejects_non_pending(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            # Second start: RUNNING → not PENDING
            code, output = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    # -- finish --------------------------------------------------------------

    def test_validation_finish_green_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            # Start
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            # Create artifact
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            rel = str(artifact_path.relative_to(root))
            # Finish GREEN
            code, output = self._run(
                root,
                "validation-finish",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
                "--verdict",
                "GREEN",
                "--artifact",
                rel,
            )
            self.assertEqual(code, 0, output)
            self.assertIn("outcome=UPDATED", output)

    def test_validation_finish_red_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            code, output = self._run(
                root,
                "validation-finish",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
                "--verdict",
                "RED",
                "--reason",
                "tests failed",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("outcome=UPDATED", output)

    def test_validation_finish_blocked_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            code, output = self._run(
                root,
                "validation-finish",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
                "--verdict",
                "BLOCKED",
                "--reason",
                "waiting on external precondition",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("outcome=UPDATED", output)
            code, output = self._run(
                root, "validation-gates", "--mission-id", "MISSION:cli"
            )
            self.assertIn("status=BLOCKED", output)

    # -- verify --------------------------------------------------------------

    def test_validation_verify_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            # Start
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            # Create and finish GREEN
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            rel = str(artifact_path.relative_to(root))
            code, _ = self._run(
                root,
                "validation-finish",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
                "--verdict",
                "GREEN",
                "--artifact",
                rel,
            )
            self.assertEqual(code, 0)
            # Verify
            code, output = self._run(
                root,
                "validation-verify",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0, output)
            self.assertIn("all_match=true", output)
            self.assertIn("status=MATCH", output)

    def test_validation_verify_tampered_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            rel = str(artifact_path.relative_to(root))
            code, _ = self._run(
                root,
                "validation-finish",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
                "--verdict",
                "GREEN",
                "--artifact",
                rel,
            )
            self.assertEqual(code, 0)
            # Tamper
            artifact_path.write_text(
                json.dumps({"status": "TAMPERED"}), encoding="utf-8"
            )
            code, output = self._run(
                root,
                "validation-verify",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 2, output)
            self.assertIn("all_match=false", output)
            self.assertIn("status=MISMATCH", output)

    # -- invalidate ----------------------------------------------------------

    def test_validation_invalidate_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            # Start + finish GREEN
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            rel = str(artifact_path.relative_to(root))
            code, _ = self._run(
                root,
                "validation-finish",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
                "--verdict",
                "GREEN",
                "--artifact",
                rel,
            )
            self.assertEqual(code, 0)
            # Invalidate (repo divergence: artifact untracked)
            code, output = self._run(
                root,
                "validation-invalidate",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0, output)
            self.assertIn("outcome=UPDATED", output)
            # Confirm INVALIDATED
            code, output = self._run(
                root, "validation-gates", "--mission-id", "MISSION:cli"
            )
            self.assertIn("status=INVALIDATED", output)

    # -- report --------------------------------------------------------------

    def test_validation_report_pass(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            # Full GREEN lifecycle
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            rel = str(artifact_path.relative_to(root))
            code, _ = self._run(
                root,
                "validation-finish",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
                "--verdict",
                "GREEN",
                "--artifact",
                rel,
            )
            self.assertEqual(code, 0)
            code, output = self._run(
                root, "validation-report", "--mission-id", "MISSION:cli"
            )
            self.assertEqual(code, 0, output)
            self.assertIn("overall=PASS", output)
            self.assertIn("green_count=1", output)

    def test_validation_report_fail(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, _ = self._run(
                root,
                "validation-start",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
            )
            self.assertEqual(code, 0)
            code, _ = self._run(
                root,
                "validation-finish",
                "--mission-id",
                "MISSION:cli",
                "--gate-id",
                GATE_ID,
                "--verdict",
                "RED",
                "--reason",
                "broken",
            )
            self.assertEqual(code, 0)
            code, output = self._run(
                root, "validation-report", "--mission-id", "MISSION:cli"
            )
            self.assertEqual(code, 2, output)
            self.assertIn("overall=FAIL", output)
            self.assertIn("red_count=1", output)

    def test_validation_report_hold_pending(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root, "validation-report", "--mission-id", "MISSION:cli"
            )
            self.assertEqual(code, 0, output)
            self.assertIn("overall=HOLD", output)
            self.assertIn("pending_count=1", output)


if __name__ == "__main__":
    unittest.main()
