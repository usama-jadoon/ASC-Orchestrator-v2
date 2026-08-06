"""Black-box CLI boundary tests for Agent Lifecycle Control (AGC) v1.0."""

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
    "objective": "Add a deterministic agent-lifecycle capability.",
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


class AgentCliTests(unittest.TestCase):
    """Full agent CLI lifecycle in a temp git repo."""

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
        self._git(root, "config", "user.name", "AGC CLI Tests")
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

    def _register(self, root: Path, agent_id: str = "AGENT:cli:dev") -> None:
        code, output = self._run(
            root,
            "agent-register",
            "--agent",
            agent_id,
            "--acr-ref",
            "ACR:developer:specialist",
        )
        self.assertEqual(code, 0, output)

    def _ready(self, root: Path, agent_id: str = "AGENT:cli:dev") -> None:
        self._register(root, agent_id)
        code, output = self._run(root, "agent-activate", "--agent", agent_id)
        self.assertEqual(code, 0, output)
        code, output = self._run(
            root,
            "agent-dependency",
            "--agent",
            agent_id,
            "--dep-status",
            "VERIFIED",
        )
        self.assertEqual(code, 0, output)
        code, output = self._run(root, "agent-ready", "--agent", agent_id)
        self.assertEqual(code, 0, output)

    # -- lifecycle -----------------------------------------------------------

    def test_full_register_to_release_lifecycle(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:lifecycle:dev"
            # register
            code, output = self._run(
                root,
                "agent-register",
                "--agent",
                agent,
                "--acr-ref",
                "ACR:developer:specialist",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("agent_id=" + agent, output)
            self.assertIn("status=INITIALIZING", output)
            # activate
            code, output = self._run(root, "agent-activate", "--agent", agent)
            self.assertEqual(code, 0, output)
            # dependency
            code, output = self._run(
                root,
                "agent-dependency",
                "--agent",
                agent,
                "--dep-status",
                "VERIFIED",
                "--tool",
                "python=3.11",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("dep_status=VERIFIED", output)
            # ready
            code, output = self._run(root, "agent-ready", "--agent", agent)
            self.assertEqual(code, 0, output)
            # claim
            code, output = self._run(
                root,
                "agent-claim",
                "--agent",
                agent,
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=BUSY", output)
            # status
            code, output = self._run(root, "agent-status", "--agent", agent)
            self.assertEqual(code, 0, output)
            self.assertIn("status=BUSY", output)
            self.assertIn("mission_id=MISSION:cli", output)
            # complete
            code, output = self._run(root, "agent-complete", "--agent", agent)
            self.assertEqual(code, 0, output)
            # release
            code, output = self._run(root, "agent-release", "--agent", agent)
            self.assertEqual(code, 0, output)

    # -- block / unblock -----------------------------------------------------

    def test_block_then_unblock(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:block:dev"
            self._ready(root, agent)
            code, output = self._run(
                root,
                "agent-block",
                "--agent",
                agent,
                "--reason",
                "waiting on input",
            )
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "agent-status", "--agent", agent)
            self.assertIn("status=BLOCKED", output)
            code, output = self._run(root, "agent-unblock", "--agent", agent)
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "agent-status", "--agent", agent)
            self.assertIn("status=READY", output)

    # -- fail / quarantine / replace -----------------------------------------

    def test_fail_quarantine_replace_lifecycle(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:fail:dev"
            self._ready(root, agent)
            code, output = self._run(
                root,
                "agent-fail",
                "--agent",
                agent,
                "--reason",
                "gate failed",
            )
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "agent-status", "--agent", agent)
            self.assertIn("status=FAILED", output)
            code, output = self._run(
                root,
                "agent-quarantine",
                "--agent",
                agent,
                "--reason",
                "diagnosis",
            )
            self.assertEqual(code, 0, output)
            code, output = self._run(
                root,
                "agent-replace",
                "--agent",
                agent,
                "--reason",
                "replacing",
            )
            self.assertEqual(code, 0, output)

    # -- list / report -------------------------------------------------------

    def test_agent_list(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._register(root, "AGENT:list1:dev")
            self._register(root, "AGENT:list2:dev")
            code, output = self._run(root, "agent-list")
            self.assertEqual(code, 0, output)
            # 3 team-bound + 2 registered = 5
            self.assertIn("agent_count=5", output)
            self.assertIn("agent_id=AGENT:list1:dev", output)
            self.assertIn("agent_id=AGENT:list2:dev", output)

    def test_agent_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._register(root, "AGENT:rpt:dev")
            code, output = self._run(root, "agent-report")
            self.assertEqual(code, 0, output)
            # 3 team-bound READY + 1 INITIALIZING = 4
            self.assertIn("total=4", output)
            self.assertIn("initializing_count=1", output)
            self.assertIn("ready_count=3", output)

    # -- error handling ------------------------------------------------------

    def test_agent_status_missing_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root, "agent-status", "--agent", "AGENT:missing:local"
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_agent_activate_wrong_status_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._register(root, "AGENT:wrong:dev")
            code, output = self._run(
                root, "agent-activate", "--agent", "AGENT:wrong:dev"
            )
            self.assertEqual(code, 0, output)
            code, output = self._run(
                root, "agent-activate", "--agent", "AGENT:wrong:dev"
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_agent_ready_without_dependency_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._register(root, "AGENT:nod:dev")
            code, output = self._run(root, "agent-activate", "--agent", "AGENT:nod:dev")
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "agent-ready", "--agent", "AGENT:nod:dev")
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_agent_release_already_released_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._ready(root, "AGENT:rel:dev")
            code, output = self._run(root, "agent-release", "--agent", "AGENT:rel:dev")
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "agent-release", "--agent", "AGENT:rel:dev")
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)


if __name__ == "__main__":
    unittest.main()
