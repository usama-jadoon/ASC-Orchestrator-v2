"""Black-box CLI boundary tests for Risk Management (RKM) v1.0."""

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
    "objective": "Add a deterministic risk-management capability.",
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


class RiskCliTests(unittest.TestCase):
    """Full risk CLI lifecycle in a temp git repo."""

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
        self._git(root, "config", "user.name", "RKM CLI Tests")
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

    def _open(
        self,
        root: Path,
        risk_id: str,
        severity: str,
        *,
        mission: str = "MISSION:cli",
        block_condition: str | None = None,
    ) -> None:
        arguments = [
            "risk-open",
            "--risk-id",
            risk_id,
            "--severity",
            severity,
            "--description",
            f"{risk_id} description",
            "--mission-id",
            mission,
        ]
        if block_condition:
            arguments += ["--block-condition", block_condition]
        code, output = self._run(root, *arguments)
        self.assertEqual(code, 0, output)

    # -- lifecycle ------------------------------------------------------------

    def test_risk_open_list_status_mitigate_resolve_lifecycle(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "risk-open",
                "--risk-id",
                "RISK:1",
                "--severity",
                "MEDIUM",
                "--description",
                "medium risk",
                "--mission-id",
                "MISSION:cli",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("risk_id=RISK:1", output)
            self.assertIn("status=OPEN", output)
            # list
            code, output = self._run(root, "risk-list")
            self.assertEqual(code, 0, output)
            self.assertIn("risk_count=1", output)
            self.assertIn("risk_id=RISK:1", output)
            # status
            code, output = self._run(root, "risk-status", "--risk-id", "RISK:1")
            self.assertEqual(code, 0, output)
            self.assertIn("status=OPEN", output)
            self.assertIn("severity=MEDIUM", output)
            # mitigate
            code, output = self._run(root, "risk-mitigate", "--risk-id", "RISK:1")
            self.assertEqual(code, 0, output)
            self.assertIn("risk_id=RISK:1", output)
            code, output = self._run(root, "risk-status", "--risk-id", "RISK:1")
            self.assertIn("status=MITIGATING", output)
            # resolve
            code, output = self._run(root, "risk-resolve", "--risk-id", "RISK:1")
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "risk-status", "--risk-id", "RISK:1")
            self.assertIn("status=RESOLVED", output)
            self.assertNotIn("resolved_at=\n", output)

    # -- hold mechanism: halt -------------------------------------------------

    def test_risk_halt_then_check_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:H", "HIGH")
            code, output = self._run(
                root, "risk-halt", "--risk-id", "RISK:H", "--reason", "investigation"
            )
            self.assertEqual(code, 0, output)
            self.assertIn("risk_id=RISK:H", output)
            code, output = self._run(root, "risk-check")
            self.assertEqual(code, 2, output)
            self.assertIn("blocked=true", output)
            self.assertIn("blocking_reason=halt-risk", output)

    # -- hold mechanism: unresolved CRITICAL ----------------------------------

    def test_risk_critical_then_check_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:C", "CRITICAL")
            code, output = self._run(root, "risk-check")
            self.assertEqual(code, 2, output)
            self.assertIn("blocked=true", output)
            self.assertIn("blocking_reason=unresolved-critical", output)

    def test_risk_resolve_critical_then_check_exits_0(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:C", "CRITICAL")
            code, _ = self._run(root, "risk-check")
            self.assertEqual(code, 2)
            code, output = self._run(root, "risk-resolve", "--risk-id", "RISK:C")
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "risk-check")
            self.assertEqual(code, 0, output)
            self.assertIn("blocked=false", output)

    def test_risk_accept_critical_then_check_exits_0(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:A", "CRITICAL")
            code, output = self._run(root, "risk-accept", "--risk-id", "RISK:A")
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "risk-check")
            self.assertEqual(code, 0, output)
            self.assertIn("blocked=false", output)

    def test_risk_high_without_condition_does_not_block(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:H", "HIGH")
            code, output = self._run(root, "risk-check")
            self.assertEqual(code, 0, output)
            self.assertIn("blocked=false", output)

    def test_risk_high_with_block_condition_blocks(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:H", "HIGH", block_condition="deploy gate pending")
            code, output = self._run(root, "risk-check")
            self.assertEqual(code, 2, output)
            self.assertIn("blocking_reason=high-block-condition-declared", output)

    # -- mission scoping ------------------------------------------------------

    def test_risk_check_mission_scoped_ignores_other_mission(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:H", "HIGH", mission="MISSION:other")
            code, output = self._run(root, "risk-check")
            # Company-wide check sees every risk.
            self.assertEqual(code, 0, output)
            self.assertIn("blocked=false", output)
            # Mission-scoped check ignores the other mission's risk.
            code, output = self._run(root, "risk-check", "--mission-id", "MISSION:cli")
            self.assertEqual(code, 0, output)

    def test_risk_check_mission_scoped_sees_own_mission(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:C", "CRITICAL", mission="MISSION:cli")
            code, output = self._run(root, "risk-check", "--mission-id", "MISSION:cli")
            self.assertEqual(code, 2, output)
            self.assertIn("blocking_risk_id=RISK:C", output)

    def test_risk_list_mission_scoped(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:1", "LOW", mission="MISSION:cli")
            self._open(root, "RISK:2", "LOW", mission="MISSION:other")
            code, output = self._run(root, "risk-list", "--mission-id", "MISSION:cli")
            self.assertEqual(code, 0, output)
            self.assertIn("risk_count=1", output)
            self.assertIn("risk_id=RISK:1", output)
            self.assertNotIn("risk_id=RISK:2", output)

    # -- report ---------------------------------------------------------------

    def test_risk_report_summary(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:1", "LOW")
            self._open(root, "RISK:2", "HIGH")
            self._open(root, "RISK:3", "CRITICAL")
            code, output = self._run(root, "risk-report")
            self.assertEqual(code, 0, output)
            self.assertIn("total=3", output)
            self.assertIn("open_count=3", output)
            self.assertIn("low_count=1", output)
            self.assertIn("high_count=1", output)
            self.assertIn("critical_count=1", output)
            self.assertIn("critical_unresolved_count=1", output)
            self.assertIn("blocked=true", output)

    def test_risk_report_empty(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(root, "risk-report")
            self.assertEqual(code, 0, output)
            self.assertIn("total=0", output)
            self.assertIn("blocked=false", output)

    # -- error handling -------------------------------------------------------

    def test_risk_status_missing_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(root, "risk-status", "--risk-id", "RISK:nope")
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_risk_open_duplicate_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:dup", "LOW")
            code, output = self._run(
                root,
                "risk-open",
                "--risk-id",
                "RISK:dup",
                "--severity",
                "LOW",
                "--description",
                "duplicate",
                "--mission-id",
                "MISSION:cli",
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_risk_mitigate_non_open_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._open(root, "RISK:r", "LOW")
            code, _ = self._run(root, "risk-resolve", "--risk-id", "RISK:r")
            self.assertEqual(code, 0)
            code, output = self._run(root, "risk-mitigate", "--risk-id", "RISK:r")
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)


if __name__ == "__main__":
    unittest.main()
