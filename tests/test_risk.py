"""Unit tests for Risk Management (RKM) v1.0."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.cli import main
from asc_orchestrator.execution import EEFEventJournal
from asc_orchestrator.risk import (
    BlockingRisk,
    RiskCheck,
    RiskEngine,
    RiskError,
    RiskRecord,
    RiskReport,
)

MISSION = {
    "mission_id": "MISSION:risk",
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


class TestRiskDataclasses(unittest.TestCase):
    """Tests for RKM data class construction."""

    def test_risk_record(self) -> None:
        rec = RiskRecord(
            risk_id="RISK:test",
            status="OPEN",
            severity="HIGH",
            description="test risk",
            mission_id="MISSION:test",
            evidence_refs=("ref1",),
            owner_agent_id="AGENT:test:local",
            opened_at="2026-08-05T00:00:00Z",
            resolved_at=None,
        )
        self.assertEqual(rec.risk_id, "RISK:test")
        self.assertEqual(rec.status, "OPEN")
        self.assertEqual(rec.severity, "HIGH")
        self.assertIsNone(rec.resolved_at)

    def test_blocking_risk(self) -> None:
        br = BlockingRisk(
            risk_id="RISK:test",
            severity="CRITICAL",
            status="OPEN",
            mission_id="MISSION:test",
            reason="unresolved-critical",
        )
        self.assertEqual(br.reason, "unresolved-critical")
        self.assertTrue(br.severity == "CRITICAL")

    def test_risk_check(self) -> None:
        rc = RiskCheck(blocked=True, blocking_risks=(), reason="test")
        self.assertTrue(rc.blocked)

    def test_risk_report(self) -> None:
        rr = RiskReport(
            mission_id=None,
            total=0,
            open_count=0,
            mitigating_count=0,
            accepted_count=0,
            resolved_count=0,
            halt_count=0,
            low_count=0,
            medium_count=0,
            high_count=0,
            critical_count=0,
            critical_unresolved_count=0,
            blocked=False,
        )
        self.assertEqual(rr.total, 0)
        self.assertFalse(rr.blocked)


class TestRiskError(unittest.TestCase):
    """Tests for RiskError."""

    def test_code_and_detail(self) -> None:
        err = RiskError("CODE", "detail")
        self.assertEqual(err.code, "CODE")
        self.assertEqual(err.detail, "detail")


class TestRiskEngine(unittest.TestCase):
    """RiskEngine unit tests over a temp git repo."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._dir = self._tmp.__enter__()
        self._root = self._setup_repo(self._dir)

    def tearDown(self) -> None:
        self._tmp.__exit__(None, None, None)

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
        self._git(root, "config", "user.name", "RKM Tests")
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

    def _engine(self) -> RiskEngine:
        return RiskEngine(self._root)

    def _actor(self) -> str:
        return "AGENT:orchestrator:local"

    # --- open ---------------------------------------------------------------

    def test_open_creates_risk(self) -> None:
        engine = self._engine()
        actor = self._actor()
        outcome = engine.open(
            "RISK:test:1",
            "MEDIUM",
            "Test risk",
            "MISSION:risk",
            actor,
        )
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.status("RISK:test:1")
        self.assertEqual(rec.status, "OPEN")
        self.assertEqual(rec.severity, "MEDIUM")
        self.assertEqual(rec.description, "Test risk")
        self.assertEqual(rec.mission_id, "MISSION:risk")
        self.assertEqual(rec.owner_agent_id, actor)
        self.assertNotEqual(rec.opened_at, "")
        self.assertIsNone(rec.resolved_at)

    def test_open_rejects_duplicate(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:dup", "LOW", "risk", None, actor)
        with self.assertRaises(RiskError) as ctx:
            engine.open("RISK:dup", "LOW", "risk", None, actor)
        self.assertEqual(ctx.exception.code, "DUPLICATE_RISK_ID")

    def test_open_rejects_invalid_severity(self) -> None:
        engine = self._engine()
        with self.assertRaises(RiskError) as ctx:
            engine.open("RISK:x", "INVALID", "risk", None, self._actor())
        self.assertEqual(ctx.exception.code, "INVALID_SEVERITY")

    def test_open_empty_risk_id_rejected(self) -> None:
        engine = self._engine()
        with self.assertRaises(RiskError) as ctx:
            engine.open("", "LOW", "risk", None, self._actor())
        self.assertEqual(ctx.exception.code, "INVALID_RISK_ID")

    def test_open_with_evidence_refs(self) -> None:
        engine = self._engine()
        outcome = engine.open(
            "RISK:ev",
            "LOW",
            "risk",
            None,
            self._actor(),
            evidence_refs=["ref1", "ref2"],
        )
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.status("RISK:ev")
        self.assertEqual(rec.evidence_refs, ("ref1", "ref2"))

    def test_open_high_with_block_condition(self) -> None:
        engine = self._engine()
        outcome = engine.open(
            "RISK:hc",
            "HIGH",
            "risky",
            "MISSION:risk",
            self._actor(),
            block_condition={"description": "blocks on deploy"},
        )
        self.assertEqual(outcome.code, "UPDATED")
        check = engine.check()
        self.assertTrue(check.blocked)
        reasons = [br.risk_id for br in check.blocking_risks]
        self.assertIn("RISK:hc", reasons)

    # --- list ---------------------------------------------------------------

    def test_list_returns_sorted(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:b", "LOW", "b", None, actor)
        engine.open("RISK:a", "LOW", "a", None, actor)
        recs = engine.list()
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0].risk_id, "RISK:a")
        self.assertEqual(recs[1].risk_id, "RISK:b")

    def test_list_filters_by_mission(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:m1", "LOW", "m1", "MISSION:risk", actor)
        engine.open("RISK:m2", "LOW", "m2", "MISSION:other", actor)
        engine.open("RISK:cw", "LOW", "cw", None, actor)
        recs = engine.list(mission_id="MISSION:risk")
        ids = [r.risk_id for r in recs]
        self.assertIn("RISK:m1", ids)
        self.assertIn("RISK:cw", ids)  # company-wide
        self.assertNotIn("RISK:m2", ids)

    # --- status -------------------------------------------------------------

    def test_status_returns_record(self) -> None:
        engine = self._engine()
        engine.open("RISK:s1", "MEDIUM", "s1", "MISSION:risk", self._actor())
        rec = engine.status("RISK:s1")
        self.assertEqual(rec.risk_id, "RISK:s1")
        self.assertEqual(rec.severity, "MEDIUM")

    def test_status_raises_not_found(self) -> None:
        engine = self._engine()
        with self.assertRaises(RiskError) as ctx:
            engine.status("RISK:missing")
        self.assertEqual(ctx.exception.code, "RISK_NOT_FOUND")

    # --- mitigate -----------------------------------------------------------

    def test_mitigate_open_to_mitigating(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:mit", "LOW", "mit", None, actor)
        outcome = engine.mitigate("RISK:mit", actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.status("RISK:mit")
        self.assertEqual(rec.status, "MITIGATING")

    def test_mitigate_rejects_non_open(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:m2", "LOW", "m2", None, actor)
        engine.mitigate("RISK:m2", actor)
        with self.assertRaises(RiskError) as ctx:
            engine.mitigate("RISK:m2", actor)
        self.assertEqual(ctx.exception.code, "RISK_NOT_OPEN")

    # --- accept -------------------------------------------------------------

    def test_accept_open_to_accepted(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:acc", "HIGH", "acc", None, actor)
        outcome = engine.accept("RISK:acc", actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.status("RISK:acc")
        self.assertEqual(rec.status, "ACCEPTED")

    def test_accept_rejects_non_open(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:a2", "LOW", "a2", None, actor)
        engine.accept("RISK:a2", actor)
        with self.assertRaises(RiskError) as ctx:
            engine.accept("RISK:a2", actor)
        self.assertEqual(ctx.exception.code, "RISK_NOT_OPEN")

    # --- resolve ------------------------------------------------------------

    def test_resolve_open_to_resolved(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:res", "MEDIUM", "res", None, actor)
        outcome = engine.resolve("RISK:res", actor, evidence_refs=["ev1"])
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.status("RISK:res")
        self.assertEqual(rec.status, "RESOLVED")
        self.assertIsNotNone(rec.resolved_at)
        self.assertEqual(rec.evidence_refs, ("ev1",))

    def test_resolve_mitigating_to_resolved(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:rm", "LOW", "rm", None, actor)
        engine.mitigate("RISK:rm", actor)
        outcome = engine.resolve("RISK:rm", actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.status("RISK:rm")
        self.assertEqual(rec.status, "RESOLVED")

    def test_resolve_rejects_halt(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:rh", "LOW", "rh", None, actor)
        engine.halt("RISK:rh", actor, "blocking issue")
        with self.assertRaises(RiskError) as ctx:
            engine.resolve("RISK:rh", actor)
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    def test_resolve_rejects_resolved(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:rr", "LOW", "rr", None, actor)
        engine.resolve("RISK:rr", actor)
        with self.assertRaises(RiskError) as ctx:
            engine.resolve("RISK:rr", actor)
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    # --- halt ---------------------------------------------------------------

    def test_halt_open_to_halt(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:h1", "CRITICAL", "h1", "MISSION:risk", actor)
        outcome = engine.halt("RISK:h1", actor, "critical failure")
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.status("RISK:h1")
        self.assertEqual(rec.status, "HALT")

    def test_halt_rejects_non_open(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:h2", "LOW", "h2", None, actor)
        engine.accept("RISK:h2", actor)
        with self.assertRaises(RiskError) as ctx:
            engine.halt("RISK:h2", actor, "reason")
        self.assertEqual(ctx.exception.code, "RISK_NOT_OPEN")

    # --- check (hold mechanism) ---------------------------------------------

    def test_check_blocks_on_halt(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:h1", "CRITICAL", "halt risk", "MISSION:risk", actor)
        engine.halt("RISK:h1", actor, "critical")
        check = engine.check()
        self.assertTrue(check.blocked)
        reasons = [br.reason for br in check.blocking_risks]
        self.assertIn("halt-risk", reasons)

    def test_check_blocks_on_unresolved_critical(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:c1", "CRITICAL", "critical risk", "MISSION:risk", actor)
        check = engine.check()
        self.assertTrue(check.blocked)
        reasons = [br.reason for br in check.blocking_risks]
        self.assertIn("unresolved-critical", reasons)

    def test_check_does_not_block_resolved_critical(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:c2", "CRITICAL", "resolved", "MISSION:risk", actor)
        engine.resolve("RISK:c2", actor)
        check = engine.check()
        self.assertFalse(check.blocked)

    def test_check_does_not_block_accepted_critical(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:c3", "CRITICAL", "accepted", "MISSION:risk", actor)
        engine.accept("RISK:c3", actor)
        check = engine.check()
        self.assertFalse(check.blocked)

    def test_check_does_not_block_high_without_block_condition(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:h1", "HIGH", "high risk", "MISSION:risk", actor)
        check = engine.check()
        self.assertFalse(check.blocked)

    def test_check_blocks_high_with_block_condition(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open(
            "RISK:h2",
            "HIGH",
            "conditioned",
            "MISSION:risk",
            actor,
            block_condition={"description": "blocks on deploy"},
        )
        check = engine.check()
        self.assertTrue(check.blocked)
        reasons = [br.reason for br in check.blocking_risks]
        self.assertIn("high-block-condition-declared", reasons)

    def test_check_mission_scoped_filters_correctly(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:ms1", "CRITICAL", "scoped", "MISSION:risk", actor)
        engine.open("RISK:ms2", "CRITICAL", "other", "MISSION:other", actor)
        check = engine.check(mission_id="MISSION:risk")
        self.assertTrue(check.blocked)
        ids = [br.risk_id for br in check.blocking_risks]
        self.assertIn("RISK:ms1", ids)
        self.assertNotIn("RISK:ms2", ids)

    def test_company_wide_risk_blocks_all_missions(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:cw", "CRITICAL", "company-wide", None, actor)
        check = engine.check(mission_id="MISSION:any")
        self.assertTrue(check.blocked)
        ids = [br.risk_id for br in check.blocking_risks]
        self.assertIn("RISK:cw", ids)

    def test_check_no_blocking_risks(self) -> None:
        engine = self._engine()
        check = engine.check()
        self.assertFalse(check.blocked)
        self.assertEqual(check.reason, "no blocking risks")

    # --- report -------------------------------------------------------------

    def test_report_summary(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:r1", "LOW", "low", "MISSION:risk", actor)
        engine.open("RISK:r2", "CRITICAL", "crit", "MISSION:risk", actor)
        engine.resolve("RISK:r1", actor)
        report = engine.report(mission_id="MISSION:risk")
        self.assertEqual(report.total, 2)
        self.assertEqual(report.open_count, 1)
        self.assertEqual(report.resolved_count, 1)
        self.assertEqual(report.critical_count, 1)
        self.assertEqual(report.critical_unresolved_count, 1)
        self.assertTrue(report.blocked)

    def test_report_empty(self) -> None:
        engine = self._engine()
        report = engine.report()
        self.assertEqual(report.total, 0)
        self.assertFalse(report.blocked)

    # --- event journal ------------------------------------------------------

    def test_event_journal_chain_integrity(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.open("RISK:e1", "LOW", "e1", "MISSION:risk", actor)
        engine.open(
            "RISK:e2",
            "HIGH",
            "e2",
            "MISSION:risk",
            actor,
            block_condition={"description": "deploy gate"},
        )
        engine.mitigate("RISK:e2", actor)
        engine.resolve("RISK:e1", actor)
        engine.open("RISK:e3", "CRITICAL", "e3", "MISSION:risk", actor)
        engine.halt("RISK:e3", actor, "blocked")

        journal = EEFEventJournal(self._root)
        result = journal.verify_chain()
        self.assertTrue(result)

    def test_risk_opened_emits_correct_event(self) -> None:
        engine = self._engine()
        outcome = engine.open(
            "RISK:evt",
            "MEDIUM",
            "event test",
            "MISSION:risk",
            self._actor(),
        )
        self.assertEqual(outcome.code, "UPDATED")
        # Read the journal to verify the event type was recorded.
        journal_path = self._root / ".project-os" / "AUDIT" / "execution-events.jsonl"
        self.assertTrue(journal_path.exists())
        lines = journal_path.read_text(encoding="utf-8").strip().splitlines()
        # Find the RISK_OPENED event.
        found = False
        for line in lines:
            entry = json.loads(line)
            if entry.get("event_type") == "RISK_OPENED":
                self.assertEqual(entry["assignment_id"], "RISK:evt")
                self.assertIn("severity", entry.get("detail", {}))
                found = True
                break
        self.assertTrue(found, "RISK_OPENED event not found in journal")

    # --- backward compat ----------------------------------------------------

    def test_existing_pese_commands_still_work(self) -> None:
        code, output = self._run(self._root, "state")
        self.assertEqual(code, 0, output)
        self.assertIn("state_revision=", output)

    def test_existing_execution_commands_still_work(self) -> None:
        code, output = self._run(
            self._root, "execution-status", "--mission-id", "MISSION:risk"
        )
        self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()
