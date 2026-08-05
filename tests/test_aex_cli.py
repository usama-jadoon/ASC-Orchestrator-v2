"""Black-box coverage for the AEX v1.0 execution CLI boundary."""

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
    """Build a compact but complete ACR entry for CLI integration tests."""
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


class AexCliTests(unittest.TestCase):
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
        """Git-backed temp repo with an enhancement mission bound to PESE."""
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
        self._git(root, "config", "user.name", "AEX CLI Tests")
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

    def _assigned_agent(self, root: Path) -> str:
        """Read the assigned_agent_id for ASSIGNMENT:build via aex-status."""
        code, output = self._run(
            root,
            "aex-status",
            "--mission-id",
            "MISSION:cli",
            "--assignment-id",
            "ASSIGNMENT:build",
        )
        self.assertEqual(code, 0, output)
        for line in output.splitlines():
            if line.startswith("agent_id="):
                return line.split("=", 1)[1]
        self.fail(f"agent_id not found in aex-status output: {output!r}")

    def _start_mission(self, root: Path) -> None:
        code, output = self._run(root, "execution-start", "--mission-id", "MISSION:cli")
        self.assertEqual(code, 0, output)
        self.assertIn("outcome=UPDATED", output)

    def _dispatch(self, root: Path, agent: str) -> None:
        code, output = self._run(
            root,
            "aex-dispatch",
            "--mission-id",
            "MISSION:cli",
            "--assignment-id",
            "ASSIGNMENT:build",
            "--actor",
            agent,
        )
        self.assertEqual(code, 0, output)
        self.assertIn("assignment_id=ASSIGNMENT:build", output)

    def test_full_aex_lifecycle_via_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = self._assigned_agent(root)
            self._start_mission(root)

            code, output = self._run(
                root,
                "aex-status",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=READY", output)
            self.assertIn(f"agent_id={agent}", output)

            self._dispatch(root, agent)

            code, output = self._run(
                root,
                "aex-status",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--actor",
                agent,
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=IN_PROGRESS", output)
            self.assertTrue(
                any(line.startswith("started_at=") for line in output.splitlines())
            )

            code, output = self._run(
                root,
                "aex-complete",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--actor",
                agent,
                "--output",
                "work completed",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=COMPLETED", output)
            self.assertIn("artifact_count=0", output)
            self.assertIn("signed=false", output)
            entry_hash = None
            for line in output.splitlines():
                if line.startswith("entry_hash="):
                    entry_hash = line.split("=", 1)[1]
            self.assertIsNotNone(entry_hash)
            assert entry_hash is not None

            code, output = self._run(
                root,
                "aex-status",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=COMPLETED", output)

            code, output = self._run(
                root,
                "aex-result",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=COMPLETED", output)
            self.assertIn("output_text=work completed", output)
            self.assertIn(f"entry_hash={entry_hash}", output)

    def test_aex_result_not_found_before_completion(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "aex-result",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 2, output)
            self.assertIn("outcome=RESULT_NOT_FOUND", output)

    def test_aex_fail_via_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = self._assigned_agent(root)
            self._start_mission(root)
            self._dispatch(root, agent)

            code, output = self._run(
                root,
                "aex-fail",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--actor",
                agent,
                "--reason",
                "gate failed",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("assignment_id=ASSIGNMENT:build", output)

            code, output = self._run(
                root,
                "aex-status",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=FAILED", output)

    def test_aex_block_unblock_via_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = self._assigned_agent(root)
            self._start_mission(root)

            code, output = self._run(
                root,
                "aex-block",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--actor",
                agent,
                "--reason",
                "waiting on input",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("assignment_id=ASSIGNMENT:build", output)

            code, output = self._run(
                root,
                "aex-status",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=BLOCKED", output)

            code, output = self._run(
                root,
                "aex-unblock",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--actor",
                agent,
            )
            self.assertEqual(code, 0, output)
            self.assertIn("assignment_id=ASSIGNMENT:build", output)

            code, output = self._run(
                root,
                "aex-status",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=READY", output)

            self._dispatch(root, agent)
            code, output = self._run(
                root,
                "aex-complete",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--actor",
                agent,
            )
            self.assertEqual(code, 0, output)
            self.assertIn("status=COMPLETED", output)

    def test_aex_complete_with_artifact_and_signature(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            agent = self._assigned_agent(root)
            self._start_mission(root)
            self._dispatch(root, agent)

            code, output = self._run(
                root, "key-create", "--actor", "AGENT:orchestrator:local"
            )
            self.assertEqual(code, 0, output)
            key_id = None
            for line in output.splitlines():
                if line.startswith("key_id="):
                    key_id = line.split("=", 1)[1]
            self.assertIsNotNone(key_id)
            assert key_id is not None

            (root / "feature.py").write_text(
                "def feature(): return 42\n", encoding="utf-8"
            )
            code, output = self._run(
                root,
                "aex-complete",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--actor",
                agent,
                "--output",
                "implemented",
                "--artifact",
                "feature.py",
                "--key-id",
                key_id,
            )
            self.assertEqual(code, 0, output)
            self.assertIn("artifact_count=1", output)
            self.assertIn("signed=true", output)

            code, output = self._run(
                root,
                "aex-result",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
            )
            self.assertEqual(code, 0, output)
            self.assertIn("output_text=implemented", output)
            self.assertTrue(
                any(line.startswith("signature=") for line in output.splitlines())
            )
            signature_line = next(
                line for line in output.splitlines() if line.startswith("signature=")
            )
            signature = json.loads(signature_line.split("=", 1)[1])
            self.assertEqual(signature["key_id"], key_id)
            self.assertTrue(
                signature["signature_hex"] and len(signature["signature_hex"]) == 64
            )

            # The artifact is persisted under the percent-encoded layout.
            artifact = (
                root
                / ".project-os"
                / "ARTIFACTS"
                / "MISSION%3Acli"
                / "ASSIGNMENT%3Abuild"
                / "artifacts"
                / "feature.py"
            )
            self.assertTrue(artifact.exists())
            self.assertEqual(
                artifact.read_text(encoding="utf-8"), "def feature(): return 42\n"
            )

    def test_aex_dispatch_rejects_unauthorized_actor(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            self._start_mission(root)
            code, output = self._run(
                root,
                "aex-dispatch",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:build",
                "--actor",
                "AGENT:impostor:local",
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error: UNAUTHORIZED:", output)

    def test_aex_status_rejects_unknown_assignment(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._bound_mission(directory)
            code, output = self._run(
                root,
                "aex-status",
                "--mission-id",
                "MISSION:cli",
                "--assignment-id",
                "ASSIGNMENT:ghost",
            )
            self.assertEqual(code, 2, output)
            self.assertIn("error: ASSIGNMENT_NOT_FOUND:", output)


if __name__ == "__main__":
    unittest.main()
