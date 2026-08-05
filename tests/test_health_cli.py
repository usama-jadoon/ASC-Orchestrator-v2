"""Black-box coverage for the AHP v1.0 health CLI boundary."""

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
    "objective": "Add a deterministic capability.",
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


def valid_entry(
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
            "validation-criteria": {gate: ["criterion"] for gate in validation_gates},
            "evidence-requirements": {gate: ["evidence"] for gate in validation_gates},
            "validation-automation": {gate: "automated" for gate in validation_gates},
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


class HealthCliTests(unittest.TestCase):
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
                valid_entry("developer", competencies=("python", "implementation")),
            ),
            (
                "reviewer",
                valid_entry(
                    "reviewer",
                    competencies=("python", "review"),
                    writable=(),
                    outputs=("REVIEW",),
                    inputs=("EVIDENCE",),
                ),
            ),
            (
                "qa-validator",
                valid_entry(
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
        self._git(root, "config", "user.name", "Health CLI Tests")
        (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git(root, "add", "tracked.txt")
        self._git(root, "commit", "-m", "initial")
        code, output = self._run(root, "state", "--initialize")
        self.assertEqual(code, 0, output)
        self.assertIn("outcome=INITIALIZED", output)
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
        return root

    def test_heartbeat_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "health-heartbeat",
                "--agent",
                "AGENT:developer:local",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--note",
                "starting work",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("agent_id=AGENT:developer:local", output)
            self.assertIn("occurred_at=", output)
            self.assertIn("sequence=1", output)

    def test_heartbeat_and_status_alive(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, _ = self._run(
                root,
                "health-heartbeat",
                "--agent",
                "AGENT:developer:local",
            )
            self.assertEqual(code, 0)
            code, output = self._run(
                root,
                "health-status",
                "--agent",
                "AGENT:developer:local",
                "--timeout",
                "300",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=ALIVE", output)
            self.assertIn("agent_id=AGENT:developer:local", output)

    def test_status_unknown_no_heartbeat(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "health-status",
                "--agent",
                "AGENT:developer:local",
                "--timeout",
                "300",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=UNKNOWN", output)
            self.assertIn("heartbeat_count=0", output)

    def test_report_for_mission(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "health-report",
                "--mission-id",
                "MISSION:cli",
                "--timeout",
                "300",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("agent_count=", output)

    def test_check_all_alive_exit0(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "health-check",
                "--mission-id",
                "MISSION:cli",
                "--timeout",
                "300",
            )
            # No heartbeats → UNKNOWN, not STALLED → exit 0
            self.assertEqual(code, 0, output)
            self.assertIn("stalled_count=0", output)

    def test_check_stalled_returns_exit2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            # Register an agent, emit a heartbeat in the past
            from asc_orchestrator.health import HealthStore
            from asc_orchestrator.pese import PESEStore

            loaded = PESEStore(root).load(actor="AGENT:orchestrator:local")
            assigned = loaded.data["envelope"]["state"]["mission_state"]["missions"][
                "MISSION:cli"
            ]["assigned_agent_ids"]
            developer_id = next(
                agent for agent in assigned if agent.startswith("AGENT:developer:")
            )

            hs = HealthStore(root)
            hs.heartbeat(
                developer_id,
                mission_id="MISSION:cli",
                assignment_id="ASSIGNMENT:build",
                occurred_at="2026-01-01T00:00:00.000Z",
            )
            code, output = self._run(
                root,
                "health-check",
                "--mission-id",
                "MISSION:cli",
                "--timeout",
                "1",
            )
            self.assertEqual(code, 2, output)
            self.assertIn("stalled_count=1", output)
            self.assertIn(developer_id, output)

    def test_heartbeat_with_metadata_via_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "health-heartbeat",
                "--agent",
                "AGENT:developer:local",
                "--mission-id",
                "MISSION:cli",
                "--note",
                "testing metadata",
            )
            self.assertEqual(code, 0, output)
            code, output = self._run(
                root,
                "health-status",
                "--agent",
                "AGENT:developer:local",
                "--timeout",
                "300",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("last_mission_id=MISSION:cli", output)


if __name__ == "__main__":
    unittest.main()
