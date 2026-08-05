"""Unit tests for the Validation Engine (VAL) v1.0."""

from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main
from asc_orchestrator.execution import EEFEventJournal
from asc_orchestrator.validation import (
    ArtifactRecord,
    ArtifactVerification,
    GateStatus,
    VALError,
    ValidationEngine,
    ValidationReport,
)

MISSION = {
    "mission_id": "MISSION:val",
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
        "description": f"{agent_id} agent for tests.",
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


class _ValTestBase(unittest.TestCase):
    """Shared setup: temp git repo with PESE + TBE bound mission."""

    @staticmethod
    def _run(root: Path, *arguments: str) -> tuple[int, str]:
        from contextlib import redirect_stdout
        from io import StringIO

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

    def _setup_repo(self, directory: str) -> Path:
        """Git-backed temp repo with an enhancement mission bound to PESE."""
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
            agent["description"] = f"{name} agent for tests."
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
        self._git(root, "config", "user.name", "VAL Tests")
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

    def _validator_agent_id(self, root: Path) -> str:
        """Discover the actual validator agent ID from PESE state."""
        code, output = self._run(
            root,
            "aex-status",
            "--mission-id",
            "MISSION:val",
            "--assignment-id",
            "ASSIGNMENT:validate-functional",
        )
        # The validator assignment might not exist; discover from gate instead.
        # Read PESE state directly to find the gate's validator_agent_id.
        from asc_orchestrator.pese import PESEStore

        store = PESEStore(root)
        loaded = store.load(actor="AGENT:orchestrator:local")
        gates = (
            loaded.data["envelope"]["state"]
            .get("validation_state", {})
            .get("gates", {})
        )
        gate_id = "GATE:MISSION:val:functional"
        gate = gates.get(gate_id, {})
        return gate.get("validator_agent_id", "AGENT:qa-validator:unknown")

    def _start_mission(self, root: Path) -> None:
        code, output = self._run(root, "execution-start", "--mission-id", "MISSION:val")
        self.assertEqual(code, 0, output)

    def _gate_id(self) -> str:
        return "GATE:MISSION:val:functional"


class GateStatusDataclassTests(unittest.TestCase):
    def test_creation(self) -> None:
        gs = GateStatus(
            gate_id="GATE:MISSION:val:functional",
            mission_id="MISSION:val",
            status="PENDING",
            validator_agent_id="AGENT:qa-validator:abc",
            manifest_version=1,
            criteria_refs=(),
            artifact_ids=(),
            last_checkpoint_id=None,
            verdict_at=None,
        )
        self.assertEqual(gs.status, "PENDING")
        self.assertEqual(gs.gate_id, "GATE:MISSION:val:functional")
        self.assertEqual(gs.mission_id, "MISSION:val")
        self.assertIsNone(gs.verdict_at)

    def test_immutable(self) -> None:
        gs = GateStatus(
            gate_id="X",
            mission_id="M",
            status="GREEN",
            validator_agent_id="V",
            manifest_version=1,
            criteria_refs=("r",),
            artifact_ids=("a",),
            last_checkpoint_id=None,
            verdict_at="2026-01-01T00:00:00.000Z",
        )
        with self.assertRaises(AttributeError):
            gs.status = "RED"  # type: ignore[misc]


class ArtifactRecordDataclassTests(unittest.TestCase):
    def test_creation(self) -> None:
        ar = ArtifactRecord(
            artifact_id="ARTIFACT:VAL:M:G:0001",
            path="validation/qa/result.json",
            sha256="a" * 64,
            type="validation-result",
            produced_at="2026-01-01T00:00:00.000Z",
            producer_agent_id="AGENT:qa-validator:abc",
            retention_class="mission",
        )
        self.assertEqual(ar.artifact_id, "ARTIFACT:VAL:M:G:0001")
        self.assertEqual(ar.sha256, "a" * 64)


class ArtifactVerificationDataclassTests(unittest.TestCase):
    def test_match(self) -> None:
        av = ArtifactVerification(
            artifact_id="A",
            path="file.txt",
            status="MATCH",
            expected_sha256="a" * 64,
            actual_sha256="a" * 64,
        )
        self.assertEqual(av.status, "MATCH")

    def test_missing(self) -> None:
        av = ArtifactVerification(
            artifact_id="A",
            path="file.txt",
            status="MISSING",
            expected_sha256="a" * 64,
            actual_sha256=None,
        )
        self.assertIsNone(av.actual_sha256)


class ValidationReportDataclassTests(unittest.TestCase):
    def test_creation(self) -> None:
        vr = ValidationReport(
            mission_id="MISSION:val",
            gate_count=2,
            green_count=2,
            red_count=0,
            blocked_count=0,
            pending_count=0,
            running_count=0,
            invalidated_count=0,
            waived_count=0,
            overall="PASS",
        )
        self.assertEqual(vr.overall, "PASS")
        self.assertEqual(vr.gate_count, 2)


class VALErrorTests(unittest.TestCase):
    def test_code_and_detail(self) -> None:
        err = VALError("TEST_CODE", "test detail")
        self.assertEqual(err.code, "TEST_CODE")
        self.assertEqual(err.detail, "test detail")
        self.assertIn("TEST_CODE", str(err))


class StartGateTests(_ValTestBase):
    def test_start_pending_to_running(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            outcome = engine.start("MISSION:val", gate_id, validator)
            self.assertEqual(outcome.code, "UPDATED")
            self.assertIsNotNone(outcome.state_revision)
            self.assertGreaterEqual(outcome.state_revision, 1)  # type: ignore[arg-type]
            # Verify gate is RUNNING
            gs = engine.gates("MISSION:val", validator)
            self.assertEqual(len(gs), 1)
            self.assertEqual(gs[0].status, "RUNNING")

    def test_start_rejects_non_pending(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            # Second start should fail: RUNNING != PENDING
            with self.assertRaises(VALError) as ctx:
                engine.start("MISSION:val", gate_id, validator)
            self.assertEqual(ctx.exception.code, "GATE_NOT_PENDING")

    def test_start_rejects_unauthorized_actor(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            with self.assertRaises(VALError) as ctx:
                engine.start("MISSION:val", gate_id, "AGENT:impostor:local")
            self.assertIn("UNAUTHORIZED", ctx.exception.code)

    def test_start_rejects_unknown_gate(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            with self.assertRaises(VALError) as ctx:
                engine.start("MISSION:val", "GATE:MISSION:val:bogus", validator)
            self.assertEqual(ctx.exception.code, "GATE_NOT_FOUND")


class FinishGateTests(_ValTestBase):
    def _start_and_create_artifact(self, root: Path, validator: str) -> Path:
        """Start the gate and create a validation artifact file."""
        engine = ValidationEngine(root)
        gate_id = self._gate_id()
        engine.start("MISSION:val", gate_id, validator)
        # Create an artifact file
        artifact_dir = root / "validation"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "qa-result.json"
        artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        return artifact_path

    def test_finish_green_with_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            artifact_path = self._start_and_create_artifact(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            outcome = engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            self.assertEqual(outcome.code, "UPDATED")
            gs = engine.gates("MISSION:val", validator)
            self.assertEqual(gs[0].status, "GREEN")
            self.assertIsNotNone(gs[0].verdict_at)
            self.assertEqual(len(gs[0].artifact_ids), 1)
            # Verify artifacts
            arts = engine.artifacts("MISSION:val", gate_id, validator)
            self.assertEqual(len(arts), 1)
            self.assertEqual(arts[0].type, "validation-result")

    def test_finish_red_no_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._start_and_create_artifact(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            outcome = engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="RED",
                reason="tests failed",
            )
            self.assertEqual(outcome.code, "UPDATED")
            gs = engine.gates("MISSION:val", validator)
            self.assertEqual(gs[0].status, "RED")

    def test_finish_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._start_and_create_artifact(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            outcome = engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="BLOCKED",
                reason="missing precondition",
            )
            self.assertEqual(outcome.code, "UPDATED")
            gs = engine.gates("MISSION:val", validator)
            self.assertEqual(gs[0].status, "BLOCKED")

    def test_finish_rejects_non_running(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            with self.assertRaises(VALError) as ctx:
                engine.finish(
                    "MISSION:val",
                    gate_id,
                    validator,
                    status="GREEN",
                    artifacts=[{"path": "x", "type": "t", "retention_class": "m"}],
                )
            self.assertEqual(ctx.exception.code, "GATE_NOT_RUNNING")

    def test_finish_green_requires_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._start_and_create_artifact(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            with self.assertRaises(VALError) as ctx:
                engine.finish("MISSION:val", gate_id, validator, status="GREEN")
            self.assertEqual(ctx.exception.code, "ARTIFACTS_REQUIRED")

    def test_finish_rejects_invalid_verdict(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._start_and_create_artifact(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            with self.assertRaises(VALError) as ctx:
                engine.finish(
                    "MISSION:val",
                    gate_id,
                    validator,
                    status="PENDING",
                )
            self.assertEqual(ctx.exception.code, "INVALID_VERDICT")

    def test_finish_rejects_missing_artifact_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._start_and_create_artifact(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            with self.assertRaises(VALError) as ctx:
                engine.finish(
                    "MISSION:val",
                    gate_id,
                    validator,
                    status="GREEN",
                    artifacts=[
                        {
                            "path": "nonexistent.json",
                            "type": "validation-result",
                            "retention_class": "mission",
                        }
                    ],
                )
            self.assertEqual(ctx.exception.code, "ARTIFACT_NOT_FOUND")

    def test_finish_rejects_path_escape(self) -> None:
        """Artifact path escaping the repository root is rejected."""
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._start_and_create_artifact(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            with self.assertRaises(VALError) as ctx:
                engine.finish(
                    "MISSION:val",
                    gate_id,
                    validator,
                    status="GREEN",
                    artifacts=[
                        {
                            "path": "../../etc/passwd",
                            "type": "validation-result",
                            "retention_class": "mission",
                        }
                    ],
                )
            self.assertEqual(ctx.exception.code, "ARTIFACT_ESCAPE")


class VerifyGateTests(_ValTestBase):
    def test_verify_all_match(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            content = json.dumps({"status": "PASS"})
            artifact_path.write_text(content, encoding="utf-8")
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            result = engine.verify("MISSION:val", gate_id, validator)
            self.assertTrue(result.all_match)
            self.assertEqual(len(result.artifact_verifications), 1)
            self.assertEqual(result.artifact_verifications[0].status, "MATCH")

    def test_verify_tampered_artifact(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            # Tamper with the file
            artifact_path.write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")
            result = engine.verify("MISSION:val", gate_id, validator)
            self.assertFalse(result.all_match)
            self.assertEqual(result.artifact_verifications[0].status, "MISMATCH")

    def test_verify_missing_artifact_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            # Delete the file
            artifact_path.unlink()
            result = engine.verify("MISSION:val", gate_id, validator)
            self.assertFalse(result.all_match)
            self.assertEqual(result.artifact_verifications[0].status, "MISSING")


class InvalidateGateTests(_ValTestBase):
    def _finish_green(self, root: Path, validator: str) -> None:
        """Start gate and finish with GREEN verdict + artifact."""
        engine = ValidationEngine(root)
        gate_id = self._gate_id()
        engine.start("MISSION:val", gate_id, validator)
        artifact_dir = root / "validation"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "qa-result.json"
        artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        engine.finish(
            "MISSION:val",
            gate_id,
            validator,
            status="GREEN",
            artifacts=[
                {
                    "path": str(artifact_path.relative_to(root)),
                    "type": "validation-result",
                    "retention_class": "mission",
                }
            ],
        )

    def test_invalidate_tampered_halts_state(self) -> None:
        """Tamper breaks state integrity; invalidate raises STATE_LOAD_FAILED."""
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._finish_green(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            # Tamper with the artifact file.
            artifact_path = root / "validation" / "qa-result.json"
            artifact_path.write_text(
                json.dumps({"status": "TAMPERED"}), encoding="utf-8"
            )
            # Verify detects tamper via raw fallback.
            vr = engine.verify("MISSION:val", gate_id, validator)
            self.assertFalse(vr.all_match)
            self.assertEqual(vr.artifact_verifications[0].status, "MISMATCH")
            # Invalidate on tampered state: PESE halts (secure behavior).
            with self.assertRaises(VALError) as ctx:
                engine.invalidate("MISSION:val", gate_id, validator)
            self.assertEqual(ctx.exception.code, "STATE_LOAD_FAILED")

    def test_invalidate_via_repo_divergence(self) -> None:
        """GREEN gate invalidated when repository binding diverges (spec 5.3)."""
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._finish_green(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            # The artifact file is untracked, making the repo dirty.
            # This causes REPOSITORY_DIVERGENCE vs the frozen repo_state.
            self.assertTrue((root / "validation" / "qa-result.json").exists())
            outcome = engine.invalidate("MISSION:val", gate_id, validator)
            self.assertEqual(outcome.code, "UPDATED")
            gs = engine.gates("MISSION:val", validator)
            self.assertEqual(gs[0].status, "INVALIDATED")

    def test_invalidate_rejects_non_green(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="RED",
                reason="failed",
            )
            with self.assertRaises(VALError) as ctx:
                engine.invalidate("MISSION:val", gate_id, validator)
            self.assertEqual(ctx.exception.code, "GATE_NOT_GREEN")

    def test_invalidate_rejects_unauthorized_actor(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._finish_green(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            with self.assertRaises(VALError) as ctx:
                engine.invalidate("MISSION:val", gate_id, "AGENT:impostor:local")
            self.assertIn("UNAUTHORIZED", ctx.exception.code)

    def test_invalidate_rejects_when_binding_intact(self) -> None:
        """BINDING_INTACT when artifact hash matches and repo hasn't diverged."""
        with TemporaryDirectory() as directory:
            from asc_orchestrator.pese import PESEStore

            root = Path(directory)
            registry_dir = root / "registry"
            registry_dir.mkdir(parents=True, exist_ok=True)
            for name, agent in [
                (
                    "developer",
                    _valid_entry(
                        "developer", competencies=("python", "implementation")
                    ),
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
            # Create the artifact file BEFORE initialize so it appears in
            # dirty_paths captured at initialize time.
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            self._git(root, "init")
            self._git(root, "config", "user.email", "tests@example.invalid")
            self._git(root, "config", "user.name", "VAL Binding Test")
            (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "initial")
            code, output = self._run(root, "state", "--initialize")
            self.assertEqual(code, 0, output)
            # team-build binds the manifest (gate is created).
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
            # Get validator and gate from the bound state.
            store = PESEStore(root)
            loaded = store.load(actor="AGENT:orchestrator:local")
            state = loaded.data["envelope"]["state"]
            gate = state["validation_state"]["gates"]["GATE:MISSION:val:functional"]
            validator = gate["validator_agent_id"]
            # Start and finish GREEN with the pre-existing artifact.
            engine = ValidationEngine(root)
            gate_id = "GATE:MISSION:val:functional"
            engine.start("MISSION:val", gate_id, validator)
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": "validation/qa-result.json",
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            # The artifact file exists, hash matches, and the repo dirty_paths
            # include it from initialize time -> binding is intact.
            with self.assertRaises(VALError) as ctx:
                engine.invalidate("MISSION:val", gate_id, validator)
            self.assertEqual(ctx.exception.code, "BINDING_INTACT")

    def test_invalidate_rejects_missing_artifact(self) -> None:
        """A deleted artifact is tamper; invalidation halts at load (no sweep)."""
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            self._finish_green(root, validator)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            # Delete the artifact file. PESE's artifact contract check treats a
            # missing file as STATE_CORRUPT, so invalidate() halts instead of
            # letting the tamper be swept under the rug.
            artifact_path = root / "validation" / "qa-result.json"
            artifact_path.unlink()
            with self.assertRaises(VALError) as ctx:
                engine.invalidate("MISSION:val", gate_id, validator)
            self.assertEqual(ctx.exception.code, "STATE_LOAD_FAILED")


class ReportTests(_ValTestBase):
    def test_report_all_green(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            report = engine.report("MISSION:val", validator)
            self.assertEqual(report.overall, "PASS")
            self.assertEqual(report.green_count, 1)
            self.assertEqual(report.gate_count, 1)
            self.assertEqual(report.mission_id, "MISSION:val")

    def test_report_with_pending_gate(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            # Don't start the gate — it stays PENDING
            report = engine.report("MISSION:val", validator)
            self.assertEqual(report.overall, "HOLD")
            self.assertEqual(report.pending_count, 1)

    def test_report_with_red_gate(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="RED",
                reason="tests failed",
            )
            report = engine.report("MISSION:val", validator)
            self.assertEqual(report.overall, "FAIL")
            self.assertEqual(report.red_count, 1)


class ListGatesTests(_ValTestBase):
    def test_list_gates(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gs = engine.gates("MISSION:val", validator)
            self.assertEqual(len(gs), 1)
            self.assertEqual(gs[0].status, "PENDING")
            self.assertEqual(gs[0].mission_id, "MISSION:val")
            self.assertEqual(gs[0].validator_agent_id, validator)

    def test_list_gates_returns_empty_for_wrong_mission(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gs = engine.gates("MISSION:other", validator)
            self.assertEqual(len(gs), 0)


class ArtifactListTests(_ValTestBase):
    def test_list_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            arts = engine.artifacts("MISSION:val", gate_id, validator)
            self.assertEqual(len(arts), 1)
            # The recorded hash is the real SHA-256 of the artifact file bytes.
            expected = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            self.assertEqual(arts[0].sha256, expected)
            self.assertTrue(len(arts[0].sha256) == 64)

    def test_list_artifacts_empty_for_pending_gate(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            arts = engine.artifacts("MISSION:val", gate_id, validator)
            self.assertEqual(len(arts), 0)


class EventJournalIntegrityTests(_ValTestBase):
    def test_event_journal_chain_integrity(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            journal = EEFEventJournal(root)
            self.assertTrue(journal.verify_chain())
            events = journal.events()
            event_types = [e.get("event_type") for e in events]
            self.assertIn("GATE_STARTED", event_types)
            self.assertIn("GATE_PASSED", event_types)

    def test_invalidate_emits_gate_invalidated_event(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()
            engine.start("MISSION:val", gate_id, validator)
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            # The artifact file is untracked, so the repository binding has
            # diverged from the frozen baseline -> invalidation is permitted.
            outcome = engine.invalidate("MISSION:val", gate_id, validator)
            self.assertEqual(outcome.code, "UPDATED")
            journal = EEFEventJournal(root)
            self.assertTrue(journal.verify_chain())
            events = journal.events()
            event_types = [e.get("event_type") for e in events]
            self.assertIn("GATE_INVALIDATED", event_types)


class FullLifecycleTests(_ValTestBase):
    def test_start_finish_verify_invalidate(self) -> None:
        """Full lifecycle: start -> finish GREEN -> verify -> invalidate."""
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            validator = self._validator_agent_id(root)
            engine = ValidationEngine(root)
            gate_id = self._gate_id()

            # Start
            outcome = engine.start("MISSION:val", gate_id, validator)
            self.assertEqual(outcome.code, "UPDATED")

            # Create artifact
            artifact_dir = root / "validation"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / "qa-result.json"
            artifact_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

            # Finish GREEN
            outcome = engine.finish(
                "MISSION:val",
                gate_id,
                validator,
                status="GREEN",
                artifacts=[
                    {
                        "path": str(artifact_path.relative_to(root)),
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                ],
            )
            self.assertEqual(outcome.code, "UPDATED")

            # Verify all artifacts match
            vr = engine.verify("MISSION:val", gate_id, validator)
            self.assertTrue(vr.all_match)
            self.assertEqual(vr.artifact_verifications[0].status, "MATCH")

            # The artifact file is untracked, so the repository binding has
            # diverged from the frozen baseline -> invalidation is permitted.
            outcome = engine.invalidate("MISSION:val", gate_id, validator)
            self.assertEqual(outcome.code, "UPDATED")
            self.assertEqual(
                engine.gates("MISSION:val", validator)[0].status, "INVALIDATED"
            )

            # Final report
            report = engine.report("MISSION:val", validator)
            self.assertEqual(report.invalidated_count, 1)
            self.assertEqual(report.overall, "FAIL")


class BackwardCompatibilityTests(_ValTestBase):
    def test_existing_pese_commands_still_work(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            code, output = self._run(root, "validate-state")
            self.assertEqual(code, 0, output)
            self.assertIn("outcome=VALID", output)

    def test_existing_execution_commands_still_work(self) -> None:
        with TemporaryDirectory() as directory:
            root = self._setup_repo(directory)
            self._start_mission(root)
            code, output = self._run(
                root, "execution-status", "--mission-id", "MISSION:val"
            )
            self.assertEqual(code, 0, output)
            self.assertIn("mission_status=ACTIVE", output)


if __name__ == "__main__":
    unittest.main()
