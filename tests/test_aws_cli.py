"""Black-box CLI integration tests for the AWS v1.0 scheduler-* commands."""

from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MISSION = {
    "mission_id": "MISSION:aws-cli",
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

CONFIG = """\
[runtime]
project_os_dir = ".project-os"
registry_dir = "registry"
audit_dir = ".project-os/AUDIT"
protocol_version = "ACP/v1.0"
"""


def _valid_entry(agent_id: str) -> dict[str, object]:
    return {
        "agent-id": agent_id,
        "version": "1.0.0",
        "display-name": agent_id,
        "description": f"{agent_id} for AWS CLI tests.",
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


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class AwsCliTests(unittest.TestCase):
    """Full CLI lifecycle: tick → status → cycle → list → report."""

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

    @staticmethod
    def _field(output: str, name: str) -> str:
        for line in output.splitlines():
            key, sep, value = line.partition("=")
            if sep and key == name:
                return value
        raise AssertionError(f"field {name!r} not found in output:\n{output}")

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        registry_dir = self.root / "registry"
        registry_dir.mkdir(parents=True, exist_ok=True)
        for name in ("developer", "reviewer"):
            (registry_dir / f"{name}.json").write_text(
                json.dumps(_valid_entry(name)), encoding="utf-8"
            )
        (self.root / "asc-orchestrator.toml").write_text(CONFIG, encoding="utf-8")
        (self.root / "mission.json").write_text(json.dumps(MISSION), encoding="utf-8")
        (self.root / "classification.json").write_text(
            json.dumps(CLASSIFICATION), encoding="utf-8"
        )
        self._git(self.root, "init")
        self._git(self.root, "config", "user.email", "cli-tests@example.invalid")
        self._git(self.root, "config", "user.name", "AWS CLI Tests")
        (self.root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git(self.root, "add", "tracked.txt")
        self._git(self.root, "commit", "-m", "initial")
        code, output = self._run(self.root, "state", "--initialize")
        self.assertEqual(code, 0, output)
        code, output = self._run(
            self.root,
            "team-build",
            "--mission",
            "mission.json",
            "--classification",
            "classification.json",
            "--bind-state",
        )
        self.assertEqual(code, 0, output)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _drain_mission(self, mission_id: str) -> None:
        """Start the mission and drive every assignment to COMPLETED via AEX."""
        self._run(self.root, "execution-start", "--mission-id", mission_id)
        from asc_orchestrator.pese import PESEStore

        store = PESEStore(self.root)
        for _ in range(10):
            loaded = store.load(actor="AGENT:orchestrator:local")
            self.assertEqual(loaded.code, "STATE_LOADED")
            assignments = (
                loaded.data["envelope"]["state"]
                .get("execution_state", {})
                .get("assignments", {})
            )
            ready = sorted(
                aid
                for aid, a in assignments.items()
                if a.get("mission_id") == mission_id and a.get("status") == "READY"
            )
            if not ready:
                break
            for aid in ready:
                agent = assignments[aid]["assigned_agent_id"]
                code, out = self._run(
                    self.root,
                    "aex-dispatch",
                    "--mission-id",
                    mission_id,
                    "--assignment-id",
                    aid,
                    "--actor",
                    agent,
                )
                self.assertEqual(code, 0, f"aex-dispatch {aid}: {out}")
                code, out = self._run(
                    self.root,
                    "aex-complete",
                    "--mission-id",
                    mission_id,
                    "--assignment-id",
                    aid,
                    "--actor",
                    agent,
                )
                self.assertEqual(code, 0, f"aex-complete {aid}: {out}")

    # -- scheduler-tick -------------------------------------------------------

    def test_tick_exit_zero(self) -> None:
        """scheduler-tick produces a cycle record and exits 0."""
        code, output = self._run(self.root, "scheduler-tick")
        self.assertEqual(code, 0, output)
        self.assertIn("cycle_id=CYCLE:00001", output)
        self.assertIn("status=COMPLETED", output)
        self.assertIn("success=true", output)

    def test_tick_output_fields(self) -> None:
        """scheduler-tick emits all required output fields."""
        code, output = self._run(self.root, "scheduler-tick")
        self.assertEqual(code, 0, output)
        for field in (
            "cycle_id",
            "status",
            "decision_type",
            "priority",
            "reason",
            "action_code",
            "success",
            "mission_id",
            "agent_id",
            "assignment_id",
            "detail",
        ):
            self.assertIn(f"{field}=", output)

    def test_tick_returns_zero_when_success(self) -> None:
        """scheduler-tick exits 0 when the action succeeds."""
        code, _ = self._run(self.root, "scheduler-tick")
        self.assertEqual(code, 0)

    def test_tick_disabled_still_ticks(self) -> None:
        """scheduler-tick still produces a cycle record when disabled."""
        code, output = self._run(self.root, "scheduler-disable")
        self.assertEqual(code, 0, output)
        code, output = self._run(self.root, "scheduler-tick")
        self.assertEqual(code, 0, output)
        self.assertIn("cycle_id=CYCLE:00001", output)
        self.assertIn("action_code=NONE", output)

    # -- scheduler-enable / scheduler-disable ----------------------------------

    def test_enable_exit_zero(self) -> None:
        """scheduler-enable exits 0 with outcome=UPDATED."""
        code, output = self._run(self.root, "scheduler-disable")
        self.assertEqual(code, 0, output)
        code, output = self._run(self.root, "scheduler-enable")
        self.assertEqual(code, 0, output)
        self.assertIn("outcome=UPDATED", output)

    def test_enable_no_change(self) -> None:
        """scheduler-enable on an already-enabled scheduler returns NO_CHANGE."""
        code, output = self._run(self.root, "scheduler-enable")
        self.assertEqual(code, 0, output)
        self.assertIn("outcome=NO_CHANGE", output)

    def test_disable_exit_zero(self) -> None:
        """scheduler-disable exits 0 with outcome=UPDATED."""
        code, output = self._run(self.root, "scheduler-disable")
        self.assertEqual(code, 0, output)
        self.assertIn("outcome=UPDATED", output)

    def test_disable_no_change(self) -> None:
        """scheduler-disable on an already-disabled scheduler returns NO_CHANGE."""
        self._run(self.root, "scheduler-disable")
        code, output = self._run(self.root, "scheduler-disable")
        self.assertEqual(code, 0, output)
        self.assertIn("outcome=NO_CHANGE", output)

    def test_enable_persists_toggle(self) -> None:
        """Toggle state persists: disable → status shows false, enable → true."""
        self._run(self.root, "scheduler-disable")
        _, output = self._run(self.root, "scheduler-status")
        self.assertIn("enabled=false", output)

        self._run(self.root, "scheduler-enable")
        _, output = self._run(self.root, "scheduler-status")
        self.assertIn("enabled=true", output)

    # -- scheduler-status -----------------------------------------------------

    def test_status_before_tick(self) -> None:
        """scheduler-status shows default values before any tick."""
        code, output = self._run(self.root, "scheduler-status")
        self.assertEqual(code, 0, output)
        self.assertIn("enabled=true", output)
        self.assertIn("cycle_count=0", output)
        self.assertIn("last_cycle_id=", output)
        self.assertIn("last_decision_type=", output)

    def test_status_after_tick(self) -> None:
        """scheduler-status reflects tick output."""
        self._run(self.root, "scheduler-tick")
        code, output = self._run(self.root, "scheduler-status")
        self.assertEqual(code, 0, output)
        self.assertIn("cycle_count=1", output)
        self.assertIn("last_cycle_id=CYCLE:00001", output)

    def test_status_active_mission(self) -> None:
        """scheduler-status reports the active mission from the bound fixture."""
        _, output = self._run(self.root, "scheduler-status")
        self.assertIn("active_mission_id=MISSION:aws-cli", output)

    # -- scheduler-cycle ------------------------------------------------------

    def test_cycle_lookup_after_tick(self) -> None:
        """scheduler-cycle returns the cycle record produced by tick."""
        self._run(self.root, "scheduler-tick")
        code, output = self._run(
            self.root, "scheduler-cycle", "--cycle-id", "CYCLE:00001"
        )
        self.assertEqual(code, 0, output)
        self.assertIn("cycle_id=CYCLE:00001", output)
        self.assertIn("format=", output)
        self.assertIn("status=COMPLETED", output)
        self.assertIn("created_at=", output)
        self.assertIn("completed_at=", output)

    def test_cycle_not_found_exits_two(self) -> None:
        """scheduler-cycle for a nonexistent cycle exits 2 with error code."""
        code, output = self._run(
            self.root, "scheduler-cycle", "--cycle-id", "CYCLE:99999"
        )
        self.assertEqual(code, 2, output)
        self.assertIn("CYCLE_NOT_FOUND", output)

    def test_cycle_preserves_decision_type(self) -> None:
        """scheduler-cycle records the decision type of the tick."""
        # D2: VALIDATE requires all assignments COMPLETED. Drain mission first.
        self._drain_mission("MISSION:aws-cli")
        self._run(self.root, "scheduler-tick")
        _, output = self._run(self.root, "scheduler-cycle", "--cycle-id", "CYCLE:00001")
        # After assignments done, first tick evaluates VALIDATE (PENDING gate).
        self.assertIn("decision_type=VALIDATE", output)
        self.assertIn("action_code=GATE_START", output)

    # -- scheduler-list -------------------------------------------------------

    def test_list_after_ticks(self) -> None:
        """scheduler-list shows the correct cycle count."""
        self._run(self.root, "scheduler-tick")
        self._run(self.root, "scheduler-tick")
        code, output = self._run(self.root, "scheduler-list")
        self.assertEqual(code, 0, output)
        self.assertIn("cycle_count=2", output)
        self.assertIn("cycle_id=CYCLE:00001", output)
        self.assertIn("cycle_id=CYCLE:00002", output)

    def test_list_empty(self) -> None:
        """scheduler-list reports zero cycles before any tick."""
        code, output = self._run(self.root, "scheduler-list")
        self.assertEqual(code, 0, output)
        self.assertIn("cycle_count=0", output)

    # -- scheduler-report -----------------------------------------------------

    def test_report_after_tick(self) -> None:
        """scheduler-report summarizes cycles and toggles."""
        self._run(self.root, "scheduler-tick")
        code, output = self._run(self.root, "scheduler-report")
        self.assertEqual(code, 0, output)
        self.assertIn("enabled=true", output)
        self.assertIn("total_cycles=1", output)
        self.assertIn("completed_cycles=1", output)
        self.assertIn("failed_cycles=0", output)
        self.assertIn("last_cycle_id=CYCLE:00001", output)

    def test_report_counts_decision_types(self) -> None:
        """scheduler-report aggregates decision counts per type."""
        # D2: VALIDATE requires all assignments COMPLETED. Drain mission first.
        self._drain_mission("MISSION:aws-cli")
        self._run(self.root, "scheduler-tick")
        _, output = self._run(self.root, "scheduler-report")
        self.assertIn("decision_counts=", output)
        # After assignments done, first tick produces VALIDATE (PENDING gate).
        self.assertIn("VALIDATE", output)

    def test_report_reflects_disable(self) -> None:
        """scheduler-report reports enabled=false after disable."""
        self._run(self.root, "scheduler-disable")
        _, output = self._run(self.root, "scheduler-report")
        self.assertIn("enabled=false", output)

    # -- event journal --------------------------------------------------------

    def test_tick_emits_cycle_completed_event(self) -> None:
        """scheduler-tick appends SCHEDULER_CYCLE_COMPLETED to the journal."""
        self._run(self.root, "scheduler-tick")
        journal_path = self.root / ".project-os" / "AUDIT" / "execution-events.jsonl"
        self.assertTrue(journal_path.exists(), "journal file missing")
        events = [
            json.loads(line)
            for line in journal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        event_types = [e.get("event_type") for e in events]
        self.assertIn("SCHEDULER_CYCLE_COMPLETED", event_types)

    def test_toggle_emits_enabled_disabled_events(self) -> None:
        """scheduler-disable/enable appends SCHEDULER_DISABLED and SCHEDULER_ENABLED."""
        self._run(self.root, "scheduler-disable")
        self._run(self.root, "scheduler-enable")
        journal_path = self.root / ".project-os" / "AUDIT" / "execution-events.jsonl"
        events = [
            json.loads(line)
            for line in journal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        event_types = [e.get("event_type") for e in events]
        self.assertIn("SCHEDULER_DISABLED", event_types)
        self.assertIn("SCHEDULER_ENABLED", event_types)

    # -- actor flag -----------------------------------------------------------

    def test_tick_with_actor_flag(self) -> None:
        """scheduler-tick --actor runs with the specified actor."""
        code, output = self._run(
            self.root, "scheduler-tick", "--actor", "AGENT:custom:test"
        )
        self.assertEqual(code, 0, output)
        self.assertIn("cycle_id=CYCLE:00001", output)

    def test_status_with_actor_flag(self) -> None:
        """scheduler-status --actor runs with the specified actor."""
        code, output = self._run(
            self.root, "scheduler-status", "--actor", "AGENT:custom:test"
        )
        self.assertEqual(code, 0, output)
        self.assertIn("enabled=true", output)


if __name__ == "__main__":
    unittest.main()
