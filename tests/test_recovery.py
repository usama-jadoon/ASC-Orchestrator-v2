"""Unit tests for Recovery Engine (REC) v1.0."""

from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.agent import AgentLifecycle
from asc_orchestrator.cli import main
from asc_orchestrator.execution import EEFEventJournal
from asc_orchestrator.health import HealthStore
from asc_orchestrator.pese import PESEStore
from asc_orchestrator.recovery import (
    RecoveryDiagnosis,
    RecoveryEngine,
    RecoveryError,
    RecoveryOutcome,
    RecoveryRecord,
    RecoveryReport,
)

MISSION = {
    "mission_id": "MISSION:risk",
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
        "description": f"{agent_id} agent for REC tests.",
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


class TestDataclasses(unittest.TestCase):
    """Verify frozen dataclass field shapes."""

    def test_recovery_diagnosis(self) -> None:
        d = RecoveryDiagnosis(
            agent_id="AGENT:test:local",
            agent_status="FAILED",
            health_status="UNKNOWN",
            trigger="FAILED",
            recoverable=True,
            reason="",
            mission_id="MISSION:m",
            assignment_id="ASSIGNMENT:a",
            acr_ref="ACR:dev:specialist",
            suggested_replacement_id="AGENT:test:local:recovery:1",
        )
        self.assertEqual(d.agent_id, "AGENT:test:local")
        self.assertTrue(d.recoverable)
        self.assertEqual(d.acr_ref, "ACR:dev:specialist")

    def test_recovery_record(self) -> None:
        r = RecoveryRecord(
            recovery_id="RECOVERY:0001",
            format="REC/v1.0",
            agent_id="AGENT:test:local",
            trigger="FAILED",
            mission_id=None,
            assignment_id=None,
            acr_ref="ACR:dev:specialist",
            replacement_agent_id="AGENT:test:local:recovery:1",
            status="COMPLETED",
            actions=("QUARANTINED", "RELEASED"),
            created_at="2026-08-06T00:00:00Z",
            updated_at=None,
            completed_at=None,
            error=None,
        )
        self.assertEqual(r.format, "REC/v1.0")
        self.assertEqual(len(r.actions), 2)

    def test_recovery_outcome(self) -> None:
        o = RecoveryOutcome(
            recovery_id="RECOVERY:0001",
            status="COMPLETED",
            replacement_agent_id="AGENT:x:recovery:1",
            actions=("QUARANTINED",),
            mission_id=None,
            assignment_id=None,
            error=None,
        )
        self.assertEqual(o.status, "COMPLETED")

    def test_recovery_report(self) -> None:
        rr = RecoveryReport(
            total=0, in_progress_count=0, completed_count=0, failed_count=0
        )
        self.assertEqual(rr.total, 0)


class TestRecoveryError(unittest.TestCase):
    """Tests for RecoveryError."""

    def test_code_and_detail(self) -> None:
        err = RecoveryError("CODE", "detail")
        self.assertEqual(err.code, "CODE")
        self.assertEqual(err.detail, "detail")


class TestRecoveryEngine(unittest.TestCase):
    """RecoveryEngine unit tests over a temp git repo."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._dir = self._tmp.__enter__()
        self._root = self._setup_repo(self._dir)

    def tearDown(self) -> None:
        self._tmp.__exit__(None, None, None)

    # --- helpers -------------------------------------------------------------

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

    def _setup_repo(self, directory: str) -> Path:
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
            agent["description"] = f"{name} agent for REC tests."
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
        self._git(root, "config", "user.name", "REC Tests")
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

    def _engine(self) -> RecoveryEngine:
        return RecoveryEngine(self._root)

    def _actor(self) -> str:
        return "AGENT:orchestrator:local"

    def _make_failed_busy_agent(
        self,
        agent_id: str,
        mission_id: str = "MISSION:risk",
        assignment_id: str = "ASSIGNMENT:build",
    ) -> None:
        """register → activate → dep VERIFIED → ready → claim → fail (FAILED with mission)."""
        r = self._run
        r(
            self._root,
            "agent-register",
            "--agent",
            agent_id,
            "--acr-ref",
            "ACR:developer:specialist",
        )
        r(self._root, "agent-activate", "--agent", agent_id)
        r(
            self._root,
            "agent-dependency",
            "--agent",
            agent_id,
            "--dep-status",
            "VERIFIED",
            "--tool",
            "python=3.11",
        )
        r(self._root, "agent-ready", "--agent", agent_id)
        r(
            self._root,
            "agent-claim",
            "--agent",
            agent_id,
            "--mission-id",
            mission_id,
            "--assignment-id",
            assignment_id,
        )
        r(self._root, "agent-fail", "--agent", agent_id, "--reason", "gate failed")

    def _make_ready_agent(self, agent_id: str) -> None:
        """register → activate → dep VERIFIED → ready (no mission)."""
        r = self._run
        r(
            self._root,
            "agent-register",
            "--agent",
            agent_id,
            "--acr-ref",
            "ACR:developer:specialist",
        )
        r(self._root, "agent-activate", "--agent", agent_id)
        r(
            self._root,
            "agent-dependency",
            "--agent",
            agent_id,
            "--dep-status",
            "VERIFIED",
            "--tool",
            "python=3.11",
        )
        r(self._root, "agent-ready", "--agent", agent_id)

    def _stall_agent(self, agent_id: str) -> None:
        """Inject a heartbeat 1000s in the past to produce AHP STALLED status."""
        past = (
            (datetime.now(timezone.utc) - timedelta(seconds=1000))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        hp = HealthStore(self._root)
        hp.heartbeat(agent_id, occurred_at=past)

    # --- diagnose -----------------------------------------------------------

    def test_diagnose_failed_recoverable(self) -> None:
        agent_id = "AGENT:diag-f:dev"
        self._make_failed_busy_agent(agent_id)
        d = self._engine().diagnose(agent_id, self._actor())
        self.assertTrue(d.recoverable)
        self.assertEqual(d.trigger, "FAILED")
        self.assertEqual(d.agent_status, "FAILED")
        self.assertEqual(d.mission_id, "MISSION:risk")
        self.assertEqual(d.assignment_id, "ASSIGNMENT:build")
        self.assertEqual(d.acr_ref, "ACR:developer:specialist")
        self.assertIsNotNone(d.suggested_replacement_id)

    def test_diagnose_stalled_recoverable(self) -> None:
        agent_id = "AGENT:diag-s:dev"
        self._make_ready_agent(agent_id)
        self._stall_agent(agent_id)
        d = self._engine().diagnose(agent_id, self._actor())
        self.assertTrue(d.recoverable)
        self.assertEqual(d.trigger, "STALLED")
        self.assertEqual(d.health_status, "STALLED")

    def test_diagnose_healthy_not_recoverable(self) -> None:
        agent_id = "AGENT:diag-h:dev"
        self._make_ready_agent(agent_id)
        d = self._engine().diagnose(agent_id, self._actor())
        self.assertFalse(d.recoverable)
        self.assertIsNone(d.trigger)
        self.assertTrue(
            len(d.reason) > 0, "non-recoverable diagnosis must include a reason"
        )

    def test_diagnose_released_not_recoverable(self) -> None:
        agent_id = "AGENT:diag-r:dev"
        self._make_ready_agent(agent_id)
        code, _ = self._run(self._root, "agent-release", "--agent", agent_id)
        self.assertEqual(code, 0)
        d = self._engine().diagnose(agent_id, self._actor())
        self.assertFalse(d.recoverable)
        self.assertIn("RELEASED", d.reason)

    def test_diagnose_missing_raises(self) -> None:
        with self.assertRaises(RecoveryError) as ctx:
            self._engine().diagnose("AGENT:missing:local", self._actor())
        self.assertIn("AGENT_NOT_FOUND", ctx.exception.code)

    # --- run ----------------------------------------------------------------

    def test_run_failed_completes_with_claim(self) -> None:
        agent_id = "AGENT:run-f:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        actor = self._actor()
        result = engine.run(agent_id, actor)
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.mission_id, "MISSION:risk")
        self.assertEqual(result.assignment_id, "ASSIGNMENT:build")
        self.assertIn("CLAIMED", result.actions)
        self.assertEqual(len(result.actions), 7)
        self.assertIsNone(result.error)
        # Replacement should exist and be BUSY with the same mission.
        agc = AgentLifecycle(self._root)
        rec = agc.agent_status(result.replacement_agent_id, actor=actor)
        self.assertEqual(rec.status, "BUSY")
        self.assertEqual(rec.mission_id, "MISSION:risk")
        self.assertEqual(rec.acr_ref, "ACR:developer:specialist")
        self.assertEqual(rec.tool_dependencies.get("python"), "3.11")

    def test_run_stalled_busy_completes_with_claim(self) -> None:
        agent_id = "AGENT:run-s:dev"
        # Make agent BUSY then inject stale heartbeat
        r = self._run
        r(
            self._root,
            "agent-register",
            "--agent",
            agent_id,
            "--acr-ref",
            "ACR:developer:specialist",
        )
        r(self._root, "agent-activate", "--agent", agent_id)
        r(
            self._root,
            "agent-dependency",
            "--agent",
            agent_id,
            "--dep-status",
            "VERIFIED",
            "--tool",
            "python=3.11",
        )
        r(self._root, "agent-ready", "--agent", agent_id)
        r(
            self._root,
            "agent-claim",
            "--agent",
            agent_id,
            "--mission-id",
            "MISSION:risk",
            "--assignment-id",
            "ASSIGNMENT:build",
        )
        self._stall_agent(agent_id)
        engine = self._engine()
        result = engine.run(agent_id, self._actor())
        self.assertEqual(result.status, "COMPLETED")
        self.assertIn("CLAIMED", result.actions)
        agc = AgentLifecycle(self._root)
        rec = agc.agent_status(result.replacement_agent_id, actor=self._actor())
        self.assertEqual(rec.status, "BUSY")

    def test_run_without_assignment_no_claim(self) -> None:
        """FAILED agent without mission/assignment → claim skipped, replacement READY."""
        agent_id = "AGENT:run-noc:dev"
        self._make_ready_agent(agent_id)
        code, _ = self._run(
            self._root, "agent-fail", "--agent", agent_id, "--reason", "no mission"
        )
        self.assertEqual(code, 0)
        engine = self._engine()
        result = engine.run(agent_id, self._actor())
        self.assertEqual(result.status, "COMPLETED")
        self.assertNotIn("CLAIMED", result.actions)
        self.assertEqual(len(result.actions), 6)
        agc = AgentLifecycle(self._root)
        rec = agc.agent_status(result.replacement_agent_id, actor=self._actor())
        self.assertEqual(rec.status, "READY")

    def test_run_not_recoverable_raises(self) -> None:
        agent_id = "AGENT:run-nr:dev"
        self._make_ready_agent(agent_id)
        with self.assertRaises(RecoveryError) as ctx:
            self._engine().run(agent_id, self._actor())
        self.assertEqual(ctx.exception.code, "NOT_RECOVERABLE")

    def test_run_step_failure_record_failed(self) -> None:
        """Pre-register the replacement ID so register fails → record FAILED."""
        agent_id = "AGENT:run-sf:dev"
        self._make_failed_busy_agent(agent_id)
        # Pre-register the suggested replacement to force DUPLICATE_AGENT.
        self._run(
            self._root,
            "agent-register",
            "--agent",
            "AGENT:run-sf:dev:recovery:1",
            "--acr-ref",
            "ACR:developer:specialist",
        )
        engine = self._engine()
        # Force the replacement to the pre-registered ID so register → DUPLICATE_AGENT.
        result = engine.run(
            agent_id,
            self._actor(),
            replacement_agent_id="AGENT:run-sf:dev:recovery:1",
        )
        self.assertEqual(result.status, "FAILED")
        self.assertTrue(result.error, "expected error detail on FAILED recovery")
        self.assertIn("DUPLICATE_AGENT", result.error)
        # The record should be persisted as FAILED.
        rec = engine.status(result.recovery_id)
        self.assertEqual(rec.status, "FAILED")
        self.assertIsNotNone(rec.error)

    def test_duplicate_runs_separate_ids(self) -> None:
        """Two recovery runs produce different recovery IDs."""
        a1 = "AGENT:dup-a:dev"
        a2 = "AGENT:dup-b:dev"
        self._make_failed_busy_agent(a1)
        self._make_failed_busy_agent(a2)
        engine = self._engine()
        r1 = engine.run(a1, self._actor())
        r2 = engine.run(a2, self._actor())
        self.assertNotEqual(r1.recovery_id, r2.recovery_id)

    # --- status / list / report ---------------------------------------------

    def test_status_returns_record(self) -> None:
        agent_id = "AGENT:st-f:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        outcome = engine.run(agent_id, self._actor())
        rec = engine.status(outcome.recovery_id)
        self.assertEqual(rec.status, "COMPLETED")
        self.assertEqual(rec.agent_id, agent_id)
        self.assertEqual(rec.format, "REC/v1.0")

    def test_status_missing_raises(self) -> None:
        with self.assertRaises(RecoveryError) as ctx:
            self._engine().status("RECOVERY:9999")
        self.assertIn("RECOVERY_NOT_FOUND", ctx.exception.code)

    def test_list_all(self) -> None:
        agent_id = "AGENT:ls-a:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        engine.run(agent_id, self._actor())
        records = engine.list()
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[0].status, "COMPLETED")

    def test_list_filter_by_agent(self) -> None:
        a1 = "AGENT:ls-f1:dev"
        a2 = "AGENT:ls-f2:dev"
        self._make_failed_busy_agent(a1)
        self._make_failed_busy_agent(a2)
        engine = self._engine()
        engine.run(a1, self._actor())
        engine.run(a2, self._actor())
        records = engine.list(agent_id=a1)
        self.assertTrue(all(r.agent_id == a1 for r in records))

    def test_list_filter_by_status(self) -> None:
        agent_id = "AGENT:ls-f3:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        engine.run(agent_id, self._actor())
        completed = engine.list(status="COMPLETED")
        in_progress = engine.list(status="IN_PROGRESS")
        self.assertGreaterEqual(len(completed), 1)
        self.assertEqual(len(in_progress), 0)

    def test_list_filter_by_mission(self) -> None:
        agent_id = "AGENT:ls-f4:dev"
        self._make_failed_busy_agent(agent_id, mission_id="MISSION:special")
        engine = self._engine()
        engine.run(agent_id, self._actor())
        matching = engine.list(mission_id="MISSION:special")
        not_matching = engine.list(mission_id="MISSION:other")
        self.assertGreaterEqual(len(matching), 1)
        self.assertEqual(len(not_matching), 0)

    def test_report(self) -> None:
        agent_id = "AGENT:rp-f:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        engine.run(agent_id, self._actor())
        rpt = engine.report()
        self.assertEqual(rpt.total, 1)
        self.assertEqual(rpt.completed_count, 1)
        self.assertEqual(rpt.in_progress_count, 0)
        self.assertEqual(rpt.failed_count, 0)

    # --- event journal ------------------------------------------------------

    def test_event_journal_chain_integrity(self) -> None:
        agent_id = "AGENT:evt-f:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        engine.run(agent_id, self._actor())
        journal = EEFEventJournal(self._root)
        self.assertTrue(journal.verify_chain())

    def test_recovery_events_recorded(self) -> None:
        agent_id = "AGENT:evt-f2:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        engine.run(agent_id, self._actor())
        journal_path = self._root / ".project-os" / "AUDIT" / "execution-events.jsonl"
        self.assertTrue(journal_path.exists())
        lines = journal_path.read_text(encoding="utf-8").strip().splitlines()
        types_found = {json.loads(line).get("event_type") for line in lines}
        self.assertIn("RECOVERY_STARTED", types_found)
        self.assertIn("RECOVERY_COMPLETED", types_found)

    # --- backward compat ----------------------------------------------------

    def test_pese_state_validates_after_recovery(self) -> None:
        """PESE state including recovery_state passes validation."""
        agent_id = "AGENT:bkw-f:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        engine.run(agent_id, self._actor())
        # PESEStore.load should succeed with no shape errors.
        store = PESEStore(self._root)
        result = store.load(actor=self._actor())
        self.assertEqual(result.code, "STATE_LOADED")
        state = result.data["envelope"]["state"]
        self.assertIn("recovery_state", state)
        self.assertIn("agent_state", state)

    def test_existing_commands_still_work(self) -> None:
        agent_id = "AGENT:bkw-f2:dev"
        self._make_failed_busy_agent(agent_id)
        engine = self._engine()
        engine.run(agent_id, self._actor())
        code, output = self._run(self._root, "state")
        self.assertEqual(code, 0, output)
        self.assertIn("state_revision=", output)


if __name__ == "__main__":
    unittest.main()
