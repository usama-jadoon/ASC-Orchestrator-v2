"""Unit tests for Autonomous Workflow Scheduler (AWS) v1.0."""

from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.aws import (
    ACTOR_ORCHESTRATOR,
    AWS_EXTENSION_KEY,
    AWS_FORMAT,
    DECISION_TYPES,
    AutonomousScheduler,
    AwsError,
    SchedulerReport,
    SchedulerStatus,
    SchedulingAction,
    SchedulingCycle,
    SchedulingDecision,
)
from asc_orchestrator.cli import main
from asc_orchestrator.execution import EEFEventJournal
from asc_orchestrator.pese import PESEStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MISSION = {
    "mission_id": "MISSION:aws",
    "mission_type": "enhancement",
    "objective": "Add a deterministic autonomous workflow scheduler.",
    "demands": [
        {
            "id": "ASSIGNMENT:build",
            "capability": "developer",
            "project": "app",
            "criterion": "works",
            "paths": ["src/scheduler.py"],
            "validation_gates": ["functional"],
        },
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


def _valid_entry(agent_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "agent-id": agent_id,
        "version": "1.0.0",
        "display-name": agent_id,
        "description": f"{agent_id} for AWS tests.",
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
            "competencies": [agent_id],
            "proficiency-levels": {agent_id: "intermediate"},
            "skill-validators": {agent_id: "test evidence"},
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
            "owned-paths": ["src/**"],
            "writable-paths": ["src/**"],
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
            "validation-gates": ["functional"],
            "validation-criteria": {"functional": ["criterion"]},
            "evidence-requirements": {"functional": ["evidence"]},
            "validation-automation": {"functional": "automated"},
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
            "input-message-types": ["EVIDENCE", "REVIEW"],
            "input-schema": {
                m: {"required": ["REFERENCE"]} for m in ("EVIDENCE", "REVIEW")
            },
            "input-validation": ["reference is valid"],
            "input-state-requirements": ["active mission"],
        },
        "output-contracts": {
            "output-message-types": ["EVIDENCE", "REVIEW"],
            "output-schema": {
                m: {"required": ["REFERENCE"]} for m in ("EVIDENCE", "REVIEW")
            },
            "output-state-changes": ["assignment progress"],
            "output-validation": ["reference is valid"],
        },
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


class _AWSBaseTestCase(unittest.TestCase):
    """Shared setUp for tests that need a fully initialized ASC repository."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._dir = self._tmp.__enter__()
        self._root = self._setup_repo(self._dir)

    def tearDown(self) -> None:
        self._tmp.__exit__(None, None, None)

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
        for name in ("developer", "reviewer"):
            (registry_dir / f"{name}.json").write_text(
                json.dumps(_valid_entry(name)), encoding="utf-8"
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
        self._git(root, "config", "user.name", "AWS Tests")
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


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses(unittest.TestCase):
    """Verify frozen dataclass field shapes."""

    def test_scheduling_decision_fields(self) -> None:
        decision = SchedulingDecision("IDLE", 0, "no work")
        self.assertEqual(decision.decision_type, "IDLE")
        self.assertEqual(decision.priority, 0)
        self.assertEqual(decision.reason, "no work")
        self.assertIsNone(decision.target_mission_id)
        self.assertIsNone(decision.target_agent_id)
        self.assertIsNone(decision.target_assignment_id)
        self.assertEqual(decision.detail, {})
        self.assertFalse(decision.requires_ai)

    def test_scheduling_action_fields(self) -> None:
        action = SchedulingAction("NONE", True, "IDLE")
        self.assertEqual(action.action_code, "NONE")
        self.assertTrue(action.success)
        self.assertEqual(action.decision_type, "IDLE")
        self.assertEqual(action.detail, {})

    def test_scheduling_cycle_fields(self) -> None:
        cycle = SchedulingCycle(
            cycle_id="CYCLE:00001",
            format=AWS_FORMAT,
            status="COMPLETED",
            decision_type="IDLE",
            priority=0,
            reason="no work",
            action_code="NONE",
            success=True,
            created_at="2026-08-07T00:00:00.000Z",
            completed_at="2026-08-07T00:00:00.000Z",
            mission_id=None,
            agent_id=None,
            assignment_id=None,
        )
        self.assertEqual(cycle.cycle_id, "CYCLE:00001")
        self.assertEqual(cycle.format, AWS_FORMAT)
        self.assertTrue(cycle.success)

    def test_scheduler_status_fields(self) -> None:
        status = SchedulerStatus(
            enabled=True,
            active_mission_id=None,
            cycle_count=0,
            last_cycle_id=None,
            last_decision_type=None,
            last_action_code=None,
            reason="",
        )
        self.assertTrue(status.enabled)
        self.assertIsNone(status.active_mission_id)
        self.assertEqual(status.cycle_count, 0)

    def test_scheduler_report_fields(self) -> None:
        report = SchedulerReport(
            enabled=True,
            total_cycles=0,
            completed_cycles=0,
            failed_cycles=0,
            decision_counts={},
            action_counts={},
            last_cycle_id=None,
        )
        self.assertTrue(report.enabled)
        self.assertEqual(report.total_cycles, 0)
        self.assertEqual(report.decision_counts, {})


# ---------------------------------------------------------------------------
# AwsError tests
# ---------------------------------------------------------------------------


class TestAwsError(unittest.TestCase):
    def test_code_and_detail(self) -> None:
        error = AwsError("CYCLE_NOT_FOUND", "cycle CYCLE:00001 not found")
        self.assertEqual(error.code, "CYCLE_NOT_FOUND")
        self.assertEqual(error.detail, "cycle CYCLE:00001 not found")
        self.assertIn("CYCLE_NOT_FOUND", str(error))


# ---------------------------------------------------------------------------
# Decision model tests
# ---------------------------------------------------------------------------


class TestDecisionModel(_AWSBaseTestCase):
    """Test all eight deterministic decision types."""

    def _scheduler(self) -> AutonomousScheduler:
        return AutonomousScheduler(self._root)

    def _crafted(self, **state: object) -> SchedulingDecision:
        """Evaluate a synthetic state dict through the pure decision function."""
        return self._scheduler()._evaluate(state, ACTOR_ORCHESTRATOR)

    def test_idle_when_no_missions(self) -> None:
        """IDLE: no planned or active mission."""
        decision = self._crafted()
        self.assertEqual(decision.decision_type, "IDLE")
        self.assertEqual(decision.priority, 0)
        self.assertEqual(decision.reason, "no missions and no actionable work")

    def test_start_mission_when_planned(self) -> None:
        """START_MISSION: PLANNED mission exists, no active mission."""
        state = {
            "mission_state": {
                "active_mission_id": None,
                "missions": {
                    "MISSION:aws": {"status": "PLANNED"},
                },
            },
        }
        decision = self._crafted(**state)
        self.assertEqual(decision.decision_type, "START_MISSION")
        self.assertEqual(decision.priority, 80)
        self.assertEqual(decision.target_mission_id, "MISSION:aws")

    def test_dispatch_when_ready(self) -> None:
        """DISPATCH: active mission with a READY assignment (via EEF schedule)."""
        # Start the bound mission and advance the EEF schedule to READY.
        code, output = self._run(
            self._root, "execution-start", "--mission", "MISSION:aws"
        )
        self.assertEqual(code, 0, output)
        code, output = self._run(
            self._root, "execution-schedule", "--mission", "MISSION:aws"
        )
        self.assertEqual(code, 0, output)
        self.assertIn("READY", output)
        decision = self._scheduler().evaluate()
        self.assertEqual(decision.decision_type, "DISPATCH")
        self.assertEqual(decision.priority, 70)
        self.assertEqual(decision.target_assignment_id, "ASSIGNMENT:build")

    def test_validate_when_gate_pending(self) -> None:
        """VALIDATE: active mission with a PENDING validation gate."""
        decision = self._scheduler().evaluate()
        self.assertEqual(decision.decision_type, "VALIDATE")
        self.assertEqual(decision.priority, 60)
        self.assertEqual(decision.target_mission_id, "MISSION:aws")
        self.assertEqual(decision.target_assignment_id, "GATE:MISSION:aws:functional")

    def test_complete_mission_when_all_done(self) -> None:
        """COMPLETE_MISSION: active mission with all assignments COMPLETED."""
        state = {
            "mission_state": {"active_mission_id": "MISSION:aws"},
            "validation_state": {"gates": {}},
            "execution_state": {
                "assignments": {
                    "ASSIGNMENT:build": {
                        "mission_id": "MISSION:aws",
                        "status": "COMPLETED",
                    },
                },
            },
        }
        decision = self._crafted(**state)
        self.assertEqual(decision.decision_type, "COMPLETE_MISSION")
        self.assertEqual(decision.priority, 50)
        self.assertEqual(decision.target_mission_id, "MISSION:aws")

    def test_monitor_health_when_nothing_to_do(self) -> None:
        """MONITOR_HEALTH: active mission, no ready assignment or pending gate."""
        scheduler = self._scheduler()
        # Consume the PENDING gate so no actionable decision remains.
        cycle = scheduler.tick()
        self.assertEqual(cycle.decision_type, "VALIDATE")
        decision = scheduler.evaluate()
        self.assertEqual(decision.decision_type, "MONITOR_HEALTH")
        self.assertEqual(decision.priority, 40)
        self.assertEqual(decision.target_mission_id, "MISSION:aws")

    def test_hold_when_blocking_risk(self) -> None:
        """HOLD: RKM reports an unresolved CRITICAL risk."""
        code, output = self._run(
            self._root,
            "risk-open",
            "--risk-id",
            "RISK:blocker",
            "--severity",
            "CRITICAL",
            "--description",
            "blocking risk for scheduler test",
            "--mission-id",
            "MISSION:aws",
        )
        self.assertEqual(code, 0, output)
        decision = self._scheduler().evaluate()
        self.assertEqual(decision.decision_type, "HOLD")
        self.assertEqual(decision.priority, 100)
        self.assertIn("blocked", decision.reason)

    def test_hold_when_risk_check_errors(self) -> None:
        """HOLD: a risk hold-mechanism evaluation failure fails closed.

        RB-10: the scheduler must not proceed on an unverifiable risk
        posture; an exception from the risk engine forces HOLD.
        """
        scheduler = self._scheduler()

        class _RaisingRiskEngine:
            def check(self, *args: object, **kwargs: object) -> object:
                raise RuntimeError("simulated risk evaluation failure")

        scheduler._risk = _RaisingRiskEngine()  # type: ignore[assignment]
        decision = scheduler._evaluate({}, ACTOR_ORCHESTRATOR)
        self.assertEqual(decision.decision_type, "HOLD")
        self.assertEqual(decision.priority, 100)
        self.assertEqual(decision.reason, "risk-evaluation-failed")

    def test_recover_when_agent_failed(self) -> None:
        """RECOVER: a FAILED agent needs recovery (sorted deterministically)."""
        state = {
            "mission_state": {"active_mission_id": "MISSION:aws"},
            "agent_state": {
                "agents": {
                    "AGENT:a:1": {"status": "READY"},
                    "AGENT:b:1": {"status": "FAILED"},
                },
            },
        }
        decision = self._crafted(**state)
        self.assertEqual(decision.decision_type, "RECOVER")
        self.assertEqual(decision.priority, 90)
        self.assertEqual(decision.target_agent_id, "AGENT:b:1")

    def test_decision_types_exhaustive(self) -> None:
        """All eight decision types are registered."""
        self.assertEqual(len(DECISION_TYPES), 8)
        expected = {
            "HOLD",
            "RECOVER",
            "START_MISSION",
            "DISPATCH",
            "VALIDATE",
            "COMPLETE_MISSION",
            "MONITOR_HEALTH",
            "IDLE",
        }
        self.assertEqual(DECISION_TYPES, expected)


# ---------------------------------------------------------------------------
# Enable / disable tests
# ---------------------------------------------------------------------------


class TestSchedulerToggle(_AWSBaseTestCase):
    def test_enable_by_default(self) -> None:
        scheduler = self._scheduler()
        status = scheduler.status()
        self.assertTrue(status.enabled)

    def test_disable(self) -> None:
        scheduler = self._scheduler()
        outcome = scheduler.disable()
        self.assertEqual(outcome.code, "UPDATED")
        status = scheduler.status()
        self.assertFalse(status.enabled)

    def test_enable_after_disable(self) -> None:
        scheduler = self._scheduler()
        scheduler.disable()
        outcome = scheduler.enable()
        self.assertEqual(outcome.code, "UPDATED")
        status = scheduler.status()
        self.assertTrue(status.enabled)

    def test_enable_no_change(self) -> None:
        scheduler = self._scheduler()
        outcome = scheduler.enable()
        self.assertEqual(outcome.code, "NO_CHANGE")

    def test_disable_no_change(self) -> None:
        scheduler = self._scheduler()
        scheduler.disable()
        outcome = scheduler.disable()
        self.assertEqual(outcome.code, "NO_CHANGE")

    def _scheduler(self) -> AutonomousScheduler:
        return AutonomousScheduler(self._root)


# ---------------------------------------------------------------------------
# Tick and cycle tests
# ---------------------------------------------------------------------------


class TestTick(_AWSBaseTestCase):
    def test_tick_produces_cycle(self) -> None:
        scheduler = self._scheduler()
        cycle = scheduler.tick()
        self.assertIsInstance(cycle, SchedulingCycle)
        self.assertEqual(cycle.status, "COMPLETED")
        self.assertEqual(cycle.cycle_id, "CYCLE:00001")

    def test_tick_persists_cycle_record(self) -> None:
        scheduler = self._scheduler()
        cycle = scheduler.tick()
        loaded = scheduler.cycle(cycle.cycle_id)
        self.assertEqual(loaded.cycle_id, cycle.cycle_id)
        self.assertEqual(loaded.status, "COMPLETED")

    def test_multiple_ticks_increment_cycle_id(self) -> None:
        scheduler = self._scheduler()
        c1 = scheduler.tick()
        c2 = scheduler.tick()
        self.assertEqual(c1.cycle_id, "CYCLE:00001")
        self.assertEqual(c2.cycle_id, "CYCLE:00002")

    def test_tick_disabled_records_noop(self) -> None:
        scheduler = self._scheduler()
        scheduler.disable()
        cycle = scheduler.tick()
        self.assertTrue(cycle.success)
        # Decision is evaluated but action is not executed.
        self.assertEqual(cycle.action_code, "NONE")

    def test_status_reflects_tick(self) -> None:
        scheduler = self._scheduler()
        scheduler.tick()
        status = scheduler.status()
        self.assertEqual(status.cycle_count, 1)
        self.assertEqual(status.last_cycle_id, "CYCLE:00001")
        self.assertIsNotNone(status.last_decision_type)

    def test_cycle_not_found(self) -> None:
        scheduler = self._scheduler()
        with self.assertRaises(AwsError) as ctx:
            scheduler.cycle("CYCLE:99999")
        self.assertEqual(ctx.exception.code, "CYCLE_NOT_FOUND")

    def test_list_cycles(self) -> None:
        scheduler = self._scheduler()
        scheduler.tick()
        scheduler.tick()
        cycles = scheduler.list_cycles()
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[0].cycle_id, "CYCLE:00001")
        self.assertEqual(cycles[1].cycle_id, "CYCLE:00002")

    def test_report(self) -> None:
        scheduler = self._scheduler()
        scheduler.tick()
        report = scheduler.report()
        self.assertTrue(report.enabled)
        self.assertEqual(report.total_cycles, 1)
        self.assertEqual(report.completed_cycles, 1)
        self.assertEqual(report.failed_cycles, 0)
        # The first tick on the bound fixture evaluates VALIDATE (PENDING gate).
        self.assertIn("VALIDATE", report.decision_counts)

    def test_report_after_disable(self) -> None:
        scheduler = self._scheduler()
        scheduler.disable()
        scheduler.tick()
        report = scheduler.report()
        self.assertFalse(report.enabled)
        self.assertEqual(report.total_cycles, 1)

    def _scheduler(self) -> AutonomousScheduler:
        return AutonomousScheduler(self._root)


# ---------------------------------------------------------------------------
# Event journal tests
# ---------------------------------------------------------------------------


class TestEventJournal(_AWSBaseTestCase):
    def test_tick_emits_cycle_completed_event(self) -> None:
        scheduler = self._scheduler()
        scheduler.tick()
        journal = EEFEventJournal(self._root)
        events = journal.events()
        cycle_events = [
            e for e in events if e.get("event_type") == "SCHEDULER_CYCLE_COMPLETED"
        ]
        self.assertEqual(len(cycle_events), 1)
        # The first tick targets MISSION:aws (PENDING gate).
        self.assertEqual(cycle_events[0]["mission_id"], "MISSION:aws")

    def test_enable_emits_enabled_event(self) -> None:
        scheduler = self._scheduler()
        scheduler.disable()
        scheduler.enable()
        journal = EEFEventJournal(self._root)
        events = journal.events()
        enabled_events = [
            e for e in events if e.get("event_type") == "SCHEDULER_ENABLED"
        ]
        self.assertEqual(len(enabled_events), 1)

    def test_disable_emits_disabled_event(self) -> None:
        scheduler = self._scheduler()
        scheduler.disable()
        journal = EEFEventJournal(self._root)
        events = journal.events()
        disabled_events = [
            e for e in events if e.get("event_type") == "SCHEDULER_DISABLED"
        ]
        self.assertEqual(len(disabled_events), 1)

    def _scheduler(self) -> AutonomousScheduler:
        return AutonomousScheduler(self._root)


# ---------------------------------------------------------------------------
# PESE integration tests
# ---------------------------------------------------------------------------


class TestPESEIntegration(_AWSBaseTestCase):
    def test_cycle_record_in_pese_extension(self) -> None:
        scheduler = self._scheduler()
        scheduler.tick()
        store = PESEStore(self._root)
        loaded = store.load(actor=ACTOR_ORCHESTRATOR)
        state = loaded.data["envelope"]["state"]
        aws_ext = state.get("extensions", {}).get(AWS_EXTENSION_KEY, {})
        self.assertIn("CYCLE:00001", aws_ext.get("cycles", {}))
        self.assertEqual(aws_ext["config"]["cycle_count"], 1)

    def test_scheduler_status_in_config(self) -> None:
        scheduler = self._scheduler()
        scheduler.disable()
        store = PESEStore(self._root)
        loaded = store.load(actor=ACTOR_ORCHESTRATOR)
        state = loaded.data["envelope"]["state"]
        aws_ext = state.get("extensions", {}).get(AWS_EXTENSION_KEY, {})
        self.assertFalse(aws_ext["config"]["enabled"])

    def test_cycle_record_detail(self) -> None:
        scheduler = self._scheduler()
        cycle = scheduler.tick()
        self.assertIsInstance(cycle.detail, dict)
        # The VALIDATE tick records the GATE_START outcome in its detail.
        self.assertIn("outcome", cycle.detail)
        self.assertEqual(cycle.detail["gate_id"], "GATE:MISSION:aws:functional")

    def _scheduler(self) -> AutonomousScheduler:
        return AutonomousScheduler(self._root)


if __name__ == "__main__":
    unittest.main()
