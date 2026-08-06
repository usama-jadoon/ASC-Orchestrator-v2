"""Black-box CLI boundary tests for Recovery Engine (REC) v1.0."""

from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main
from asc_orchestrator.health import HealthStore

MISSION = {
    "mission_id": "MISSION:cli",
    "mission_type": "enhancement",
    "objective": "Add a deterministic agent-recovery capability.",
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
        "description": f"{agent_id} agent for REC CLI tests.",
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


class RecoveryCliTests(unittest.TestCase):
    """Full recovery CLI lifecycle in a temp git repo."""

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
            agent["description"] = f"{name} agent for REC CLI tests."
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
        self._git(root, "config", "user.name", "REC CLI Tests")
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

    def _make_failed_busy_agent(self, root: Path, agent_id: str) -> None:
        """register → activate → dep VERIFIED → ready → claim → fail."""
        r = self._run
        r(
            root,
            "agent-register",
            "--agent",
            agent_id,
            "--acr-ref",
            "ACR:developer:specialist",
        )
        r(root, "agent-activate", "--agent", agent_id)
        r(
            root,
            "agent-dependency",
            "--agent",
            agent_id,
            "--dep-status",
            "VERIFIED",
            "--tool",
            "python=3.11",
        )
        r(root, "agent-ready", "--agent", agent_id)
        r(
            root,
            "agent-claim",
            "--agent",
            agent_id,
            "--mission-id",
            "MISSION:cli",
            "--assignment-id",
            "ASSIGNMENT:build",
        )
        code, output = r(
            root, "agent-fail", "--agent", agent_id, "--reason", "gate failed"
        )
        self.assertEqual(code, 0, output)

    def _make_busy_agent(self, root: Path, agent_id: str) -> None:
        """register → activate → dep VERIFIED → ready → claim (BUSY, healthy)."""
        r = self._run
        r(
            root,
            "agent-register",
            "--agent",
            agent_id,
            "--acr-ref",
            "ACR:developer:specialist",
        )
        r(root, "agent-activate", "--agent", agent_id)
        r(
            root,
            "agent-dependency",
            "--agent",
            agent_id,
            "--dep-status",
            "VERIFIED",
            "--tool",
            "python=3.11",
        )
        r(root, "agent-ready", "--agent", agent_id)
        code, output = r(
            root,
            "agent-claim",
            "--agent",
            agent_id,
            "--mission-id",
            "MISSION:cli",
            "--assignment-id",
            "ASSIGNMENT:build",
        )
        self.assertEqual(code, 0, output)

    def _stall_agent(self, root: Path, agent_id: str) -> None:
        """Inject a heartbeat 1000s in the past to produce AHP STALLED status."""
        past = (
            (datetime.now(timezone.utc) - timedelta(seconds=1000))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        HealthStore(root).heartbeat(agent_id, occurred_at=past)

    # -- diagnose -------------------------------------------------------------

    def test_recovery_diagnose_failed_agent(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:diag:dev"
            self._make_failed_busy_agent(root, agent)
            code, output = self._run(root, "recovery-diagnose", "--agent", agent)
            self.assertEqual(code, 0, output)
            self.assertIn("recoverable=true", output)
            self.assertIn("trigger=FAILED", output)
            self.assertIn(f"suggested_replacement_id={agent}:recovery:1", output)

    def test_recovery_diagnose_healthy_not_recoverable(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:diag-h:dev"
            self._make_busy_agent(root, agent)
            code, output = self._run(root, "recovery-diagnose", "--agent", agent)
            self.assertEqual(code, 0, output)
            self.assertIn("recoverable=false", output)
            self.assertIn("trigger=", output)

    def test_recovery_diagnose_missing_agent_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root, "recovery-diagnose", "--agent", "AGENT:missing:local"
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    # -- run / status / list / report lifecycle -------------------------------

    def test_recovery_run_lifecycle(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:run:dev"
            self._make_failed_busy_agent(root, agent)
            code, output = self._run(root, "recovery-run", "--agent", agent)
            self.assertEqual(code, 0, output)
            self.assertIn("status=COMPLETED", output)
            self.assertIn("replacement_agent_id=", output)
            self.assertIn(
                "actions=QUARANTINED,RELEASED,REGISTERED,ACTIVATED,DEPENDENCY_VERIFIED,READY,CLAIMED",
                output,
            )
            self.assertIn("mission_id=MISSION:cli", output)
            self.assertIn("assignment_id=ASSIGNMENT:build", output)
            self.assertIn("error=", output)

            recovery_id = self._field(output, "recovery_id")
            self.assertTrue(recovery_id.startswith("RECOVERY:"))

            # replacement agent is now BUSY on the same mission
            code, output = self._run(
                root, "agent-status", "--agent", f"{agent}:recovery:1"
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=BUSY", output)
            self.assertIn("mission_id=MISSION:cli", output)

            # recovery-status
            code, output = self._run(
                root, "recovery-status", "--recovery-id", recovery_id
            )
            self.assertEqual(code, 0, output)
            self.assertIn(f"recovery_id={recovery_id}", output)
            self.assertIn("status=COMPLETED", output)
            self.assertIn("format=REC/v1.0", output)

            # recovery-list
            code, output = self._run(root, "recovery-list")
            self.assertEqual(code, 0, output)
            self.assertIn("recovery_count=1", output)
            self.assertIn(f"recovery_id={recovery_id}", output)

            # recovery-report
            code, output = self._run(root, "recovery-report")
            self.assertEqual(code, 0, output)
            self.assertIn("total=1", output)
            self.assertIn("completed_count=1", output)
            self.assertIn("failed_count=0", output)

    def test_recovery_run_stalled_completes_with_claim(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:run-stall:dev"
            self._make_busy_agent(root, agent)
            self._stall_agent(root, agent)
            code, output = self._run(root, "recovery-diagnose", "--agent", agent)
            self.assertEqual(code, 0, output)
            self.assertIn("trigger=STALLED", output)
            code, output = self._run(root, "recovery-run", "--agent", agent)
            self.assertEqual(code, 0, output)
            self.assertIn("status=COMPLETED", output)
            self.assertIn("CLAIMED", output)

    def test_recovery_run_without_assignment_no_claim(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:run-noc:dev"
            # Register → ready but never claim; then fail with no mission.
            r = self._run
            r(
                root,
                "agent-register",
                "--agent",
                agent,
                "--acr-ref",
                "ACR:developer:specialist",
            )
            r(root, "agent-activate", "--agent", agent)
            r(root, "agent-dependency", "--agent", agent, "--dep-status", "VERIFIED")
            r(root, "agent-ready", "--agent", agent)
            code, output = r(
                root, "agent-fail", "--agent", agent, "--reason", "no mission"
            )
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "recovery-run", "--agent", agent)
            self.assertEqual(code, 0, output)
            self.assertIn("status=COMPLETED", output)
            self.assertNotIn("CLAIMED", output)
            # replacement is left READY
            code, output = self._run(
                root, "agent-status", "--agent", f"{agent}:recovery:1"
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=READY", output)

    # -- error handling -------------------------------------------------------

    def test_recovery_run_not_recoverable_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:run-nr:dev"
            self._make_busy_agent(root, agent)
            code, output = self._run(root, "recovery-run", "--agent", agent)
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_recovery_run_missing_agent_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root, "recovery-run", "--agent", "AGENT:missing:local"
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_recovery_run_step_failure_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = "AGENT:run-sf:dev"
            self._make_failed_busy_agent(root, agent)
            # Register a fresh agent so it's guaranteed to be in agent_state.agents,
            # then force register to fail by using it as the replacement.
            code, output = self._run(
                root,
                "agent-register",
                "--agent",
                "AGENT:pre-exists:dev",
                "--acr-ref",
                "ACR:developer:specialist",
            )
            self.assertEqual(code, 0, output)
            code, output = self._run(
                root,
                "recovery-run",
                "--agent",
                agent,
                "--replacement",
                "AGENT:pre-exists:dev",
            )
            self.assertEqual(code, 2, output)
            self.assertIn("status=FAILED", output)
            self.assertIn("recovery_id=", output)
            # The failed record is persisted.
            recovery_id = self._field(output, "recovery_id")
            code, output = self._run(
                root, "recovery-status", "--recovery-id", recovery_id
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=FAILED", output)

    def test_recovery_status_missing_exits_2(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root, "recovery-status", "--recovery-id", "RECOVERY:9999"
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error:", output)

    def test_recovery_list_filters(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            a1 = "AGENT:ls1:dev"
            a2 = "AGENT:ls2:dev"
            self._make_failed_busy_agent(root, a1)
            self._make_failed_busy_agent(root, a2)
            code, output = self._run(root, "recovery-run", "--agent", a1)
            self.assertEqual(code, 0, output)
            code, output = self._run(root, "recovery-run", "--agent", a2)
            self.assertEqual(code, 0, output)
            # filter by status
            code, output = self._run(root, "recovery-list", "--status", "COMPLETED")
            self.assertEqual(code, 0, output)
            self.assertIn("recovery_count=2", output)
            # filter by agent
            code, output = self._run(root, "recovery-list", "--agent-id", a1)
            self.assertEqual(code, 0, output)
            self.assertIn("recovery_count=1", output)
            self.assertIn(f"agent_id={a1}", output)
            # filter by mission
            code, output = self._run(
                root, "recovery-list", "--mission-id", "MISSION:cli"
            )
            self.assertEqual(code, 0, output)
            self.assertIn("recovery_count=2", output)

    @staticmethod
    def _field(output: str, name: str) -> str:
        for line in output.splitlines():
            key, sep, value = line.partition("=")
            if sep and key == name:
                return value
        raise AssertionError(f"field {name!r} not found in output:\n{output}")


if __name__ == "__main__":
    unittest.main()
