"""Unit tests for Agent Lifecycle Control (AGC) v1.0."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.agent import (
    AGCError,
    AgentLifecycle,
    AgentRecord,
    AgentReport,
)
from asc_orchestrator.cli import main
from asc_orchestrator.execution import EEFEventJournal

MISSION = {
    "mission_id": "MISSION:agent",
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

AGENT_ID = "AGENT:developer:test"


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


class TestAgentDataclasses(unittest.TestCase):
    """Tests for AGC data class construction."""

    def test_agent_record(self) -> None:
        rec = AgentRecord(
            agent_id=AGENT_ID,
            status="READY",
            mission_id=None,
            assignment_id=None,
            manifest_version=None,
            last_heartbeat_at=None,
            last_checkpoint_id=None,
            acr_ref="ACR:developer:specialist",
            dep_status="VERIFIED",
            verified_at="2026-08-05T00:00:00Z",
            tool_dependencies={"python": "3.11"},
            environment_dependencies={},
            interruption=None,
        )
        self.assertEqual(rec.agent_id, AGENT_ID)
        self.assertEqual(rec.status, "READY")
        self.assertEqual(rec.dep_status, "VERIFIED")
        self.assertIsNone(rec.mission_id)

    def test_agent_report(self) -> None:
        report = AgentReport(
            total=0,
            initializing_count=0,
            registered_count=0,
            ready_count=0,
            busy_count=0,
            blocked_count=0,
            failed_count=0,
            quarantined_count=0,
            replaced_count=0,
            released_count=0,
        )
        self.assertEqual(report.total, 0)
        self.assertEqual(report.ready_count, 0)


class TestAGCError(unittest.TestCase):
    """Tests for AGCError."""

    def test_code_and_detail(self) -> None:
        err = AGCError("CODE", "detail")
        self.assertEqual(err.code, "CODE")
        self.assertEqual(err.detail, "detail")


class TestAgentLifecycle(unittest.TestCase):
    """AgentLifecycle unit tests over a temp git repo."""

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
        self._git(root, "config", "user.name", "AGC Tests")
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

    def _engine(self) -> AgentLifecycle:
        return AgentLifecycle(self._root)

    def _actor(self) -> str:
        return "AGENT:orchestrator:local"

    def _ready_agent(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:developer:specialist", actor)
        engine.activate(AGENT_ID, actor)
        engine.set_dependency(AGENT_ID, "VERIFIED", actor)
        engine.ready(AGENT_ID, actor)

    # --- register -----------------------------------------------------------

    def test_register_creates_initializing(self) -> None:
        engine = self._engine()
        outcome = engine.register(AGENT_ID, "ACR:developer:specialist", self._actor())
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "INITIALIZING")
        self.assertEqual(rec.acr_ref, "ACR:developer:specialist")
        self.assertEqual(rec.dep_status, "UNKNOWN")
        self.assertIsNone(rec.mission_id)

    def test_register_rejects_empty_agent_id(self) -> None:
        engine = self._engine()
        with self.assertRaises(AGCError) as ctx:
            engine.register("", "ACR:x", self._actor())
        self.assertEqual(ctx.exception.code, "INVALID_AGENT")

    def test_register_rejects_empty_acr_ref(self) -> None:
        engine = self._engine()
        with self.assertRaises(AGCError) as ctx:
            engine.register(AGENT_ID, "", self._actor())
        self.assertEqual(ctx.exception.code, "INVALID_ACR_REF")

    def test_register_rejects_duplicate(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        with self.assertRaises(AGCError) as ctx:
            engine.register(AGENT_ID, "ACR:x", actor)
        self.assertEqual(ctx.exception.code, "DUPLICATE_AGENT")

    # --- activate -----------------------------------------------------------

    def test_activate_initializing_to_registered(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        outcome = engine.activate(AGENT_ID, actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "REGISTERED")

    def test_activate_rejects_wrong_status(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        engine.activate(AGENT_ID, actor)
        with self.assertRaises(AGCError) as ctx:
            engine.activate(AGENT_ID, actor)
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    # --- dependency ---------------------------------------------------------

    def test_set_dependency_verified(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        outcome = engine.set_dependency(
            AGENT_ID,
            "VERIFIED",
            actor,
            tool_dependencies={"python": "3.11"},
        )
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.dep_status, "VERIFIED")
        self.assertEqual(rec.tool_dependencies, {"python": "3.11"})

    def test_set_dependency_rejects_invalid_status(self) -> None:
        engine = self._engine()
        engine.register(AGENT_ID, "ACR:x", self._actor())
        with self.assertRaises(AGCError) as ctx:
            engine.set_dependency(AGENT_ID, "INVALID", self._actor())
        self.assertEqual(ctx.exception.code, "INVALID_DEP_STATUS")

    # --- ready --------------------------------------------------------------

    def test_ready_requires_verified_dependency(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        engine.activate(AGENT_ID, actor)
        with self.assertRaises(AGCError) as ctx:
            engine.ready(AGENT_ID, actor)
        self.assertEqual(ctx.exception.code, "DEPENDENCY_UNVERIFIED")

    def test_ready_after_verified_dependency(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        engine.activate(AGENT_ID, actor)
        engine.set_dependency(AGENT_ID, "VERIFIED", actor)
        outcome = engine.ready(AGENT_ID, actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "READY")

    # --- claim / complete ---------------------------------------------------

    def test_claim_ready_to_busy(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        outcome = engine.claim(AGENT_ID, "MISSION:agent", "ASSIGNMENT:build", actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "BUSY")
        self.assertEqual(rec.mission_id, "MISSION:agent")
        self.assertEqual(rec.assignment_id, "ASSIGNMENT:build")

    def test_claim_rejects_non_ready(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        with self.assertRaises(AGCError) as ctx:
            engine.claim(AGENT_ID, "MISSION:agent", "ASSIGNMENT:build", actor)
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    def test_complete_busy_to_ready(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.claim(AGENT_ID, "MISSION:agent", "ASSIGNMENT:build", actor)
        outcome = engine.complete(AGENT_ID, actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "READY")
        self.assertIsNone(rec.mission_id)
        self.assertIsNone(rec.assignment_id)

    # --- block / unblock ----------------------------------------------------

    def test_block_busy_to_blocked(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.claim(AGENT_ID, "MISSION:agent", "ASSIGNMENT:build", actor)
        outcome = engine.block(AGENT_ID, actor, "waiting on input")
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "BLOCKED")

    def test_unblock_blocked_to_ready(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.block(AGENT_ID, actor, "waiting")
        outcome = engine.unblock(AGENT_ID, actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "READY")

    def test_unblock_rejects_non_blocked(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        with self.assertRaises(AGCError) as ctx:
            engine.unblock(AGENT_ID, actor)
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    # --- fail ---------------------------------------------------------------

    def test_fail_busy_to_failed(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.claim(AGENT_ID, "MISSION:agent", "ASSIGNMENT:build", actor)
        outcome = engine.fail(AGENT_ID, actor, "gate failed")
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "FAILED")
        self.assertIsNotNone(rec.interruption)

    def test_fail_rejects_non_active(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        with self.assertRaises(AGCError) as ctx:
            engine.fail(AGENT_ID, actor, "reason")
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    # --- quarantine ---------------------------------------------------------

    def test_quarantine_failed_to_quarantined(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.fail(AGENT_ID, actor, "gate failed")
        outcome = engine.quarantine(AGENT_ID, actor, "needs diagnosis")
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "QUARANTINED")

    # --- replace ------------------------------------------------------------

    def test_replace_quarantined_to_replaced(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.fail(AGENT_ID, actor, "gate failed")
        engine.quarantine(AGENT_ID, actor, "diagnosis")
        outcome = engine.replace(AGENT_ID, actor, "replacing agent")
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "REPLACED")

    def test_replace_rejects_non_failed_quarantined(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        with self.assertRaises(AGCError) as ctx:
            engine.replace(AGENT_ID, actor, "reason")
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    # --- release ------------------------------------------------------------

    def test_release_to_released(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        outcome = engine.release(AGENT_ID, actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.status, "RELEASED")

    def test_release_rejects_already_released(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.release(AGENT_ID, actor)
        with self.assertRaises(AGCError) as ctx:
            engine.release(AGENT_ID, actor)
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    # --- heartbeat / checkpoint ---------------------------------------------

    def test_heartbeat_updates_reference(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        outcome = engine.heartbeat(AGENT_ID, actor, at="2026-08-05T00:00:00Z")
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.last_heartbeat_at, "2026-08-05T00:00:00Z")

    def test_checkpoint_updates_reference(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        outcome = engine.update_checkpoint(AGENT_ID, "CHECKPOINT:1", actor)
        self.assertEqual(outcome.code, "UPDATED")
        rec = engine.agent_status(AGENT_ID)
        self.assertEqual(rec.last_checkpoint_id, "CHECKPOINT:1")

    # --- authority ----------------------------------------------------------

    def test_unauthorized_actor_rejected(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        with self.assertRaises(AGCError) as ctx:
            engine.activate(AGENT_ID, "AGENT:intruder:evil")
        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")

    def test_self_management_allowed(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        outcome = engine.activate(AGENT_ID, AGENT_ID)
        self.assertEqual(outcome.code, "UPDATED")

    def test_register_rejects_non_orchestrator(self) -> None:
        engine = self._engine()
        with self.assertRaises(AGCError) as ctx:
            engine.register("AGENT:intruder:evil", "ACR:x", "AGENT:intruder:evil")
        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")

    def test_heartbeat_rejects_unauthorized(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        with self.assertRaises(AGCError) as ctx:
            engine.heartbeat(AGENT_ID, "AGENT:intruder:evil")
        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")

    def test_heartbeat_allows_orchestrator(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        outcome = engine.heartbeat(AGENT_ID, actor)
        self.assertEqual(outcome.code, "UPDATED")

    def test_heartbeat_allows_self(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        outcome = engine.heartbeat(AGENT_ID, AGENT_ID)
        self.assertEqual(outcome.code, "UPDATED")

    def test_checkpoint_rejects_unauthorized(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        with self.assertRaises(AGCError) as ctx:
            engine.update_checkpoint(AGENT_ID, "CP:1", "AGENT:intruder:evil")
        self.assertEqual(ctx.exception.code, "UNAUTHORIZED")

    def test_checkpoint_allows_orchestrator(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        outcome = engine.update_checkpoint(AGENT_ID, "CP:1", actor)
        self.assertEqual(outcome.code, "UPDATED")

    def test_checkpoint_allows_self(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register(AGENT_ID, "ACR:x", actor)
        outcome = engine.update_checkpoint(AGENT_ID, "CP:1", AGENT_ID)
        self.assertEqual(outcome.code, "UPDATED")

    # --- list / status / report ---------------------------------------------

    def test_list_returns_sorted(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register("AGENT:aaa:local", "ACR:x", actor)
        engine.register("AGENT:bbb:local", "ACR:x", actor)
        records = engine.list()
        # 3 team-bound agents + 2 registered = 5
        self.assertEqual(len(records), 5)
        ids = [r.agent_id for r in records]
        self.assertIn("AGENT:aaa:local", ids)
        self.assertIn("AGENT:bbb:local", ids)
        # full list is sorted by agent_id
        self.assertEqual(ids, sorted(ids))

    def test_list_filters_by_status(self) -> None:
        engine = self._engine()
        actor = self._actor()
        engine.register("AGENT:a:local", "ACR:x", actor)
        engine.register("AGENT:b:local", "ACR:x", actor)
        records = engine.list(status="INITIALIZING")
        self.assertEqual(len(records), 2)
        # team-bound agents are READY
        records = engine.list(status="READY")
        self.assertEqual(len(records), 3)

    def test_status_raises_not_found(self) -> None:
        engine = self._engine()
        with self.assertRaises(AGCError) as ctx:
            engine.agent_status("AGENT:missing:local")
        self.assertEqual(ctx.exception.code, "AGENT_NOT_FOUND")

    def test_report_summary(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.claim(AGENT_ID, "MISSION:agent", "ASSIGNMENT:build", actor)
        engine.register("AGENT:other:local", "ACR:x", actor)
        report = engine.report()
        # 3 team-bound READY + 1 READY from _ready_agent → claim → 1 BUSY + 1 INITIALIZING = 5
        self.assertEqual(report.total, 5)
        self.assertEqual(report.busy_count, 1)
        self.assertEqual(report.initializing_count, 1)
        self.assertEqual(report.ready_count, 3)

    def test_report_empty(self) -> None:
        engine = self._engine()
        report = engine.report()
        # 3 team-bound READY agents from setup
        self.assertEqual(report.total, 3)
        self.assertEqual(report.ready_count, 3)
        self.assertEqual(report.initializing_count, 0)

    # --- event journal ------------------------------------------------------

    def test_event_journal_chain_integrity(self) -> None:
        engine = self._engine()
        actor = self._actor()
        self._ready_agent()
        engine.claim(AGENT_ID, "MISSION:agent", "ASSIGNMENT:build", actor)
        engine.fail(AGENT_ID, actor, "gate failed")
        engine.quarantine(AGENT_ID, actor, "diagnosis")
        engine.replace(AGENT_ID, actor, "replacement")
        engine.release(AGENT_ID, actor)

        journal = EEFEventJournal(self._root)
        result = journal.verify_chain()
        self.assertTrue(result)

    def test_agent_registered_emits_correct_event(self) -> None:
        engine = self._engine()
        outcome = engine.register(AGENT_ID, "ACR:developer:specialist", self._actor())
        self.assertEqual(outcome.code, "UPDATED")
        journal_path = self._root / ".project-os" / "AUDIT" / "execution-events.jsonl"
        self.assertTrue(journal_path.exists())
        lines = journal_path.read_text(encoding="utf-8").strip().splitlines()
        found = False
        for line in lines:
            entry = json.loads(line)
            if entry.get("event_type") == "AGENT_REGISTERED":
                self.assertEqual(entry["assignment_id"], AGENT_ID)
                self.assertIn("acr_ref", entry.get("detail", {}))
                found = True
                break
        self.assertTrue(found, "AGENT_REGISTERED event not found in journal")

    # --- backward compat ----------------------------------------------------

    def test_existing_pese_commands_still_work(self) -> None:
        code, output = self._run(self._root, "state")
        self.assertEqual(code, 0, output)
        self.assertIn("state_revision=", output)

    def test_existing_execution_commands_still_work(self) -> None:
        code, output = self._run(
            self._root, "execution-status", "--mission-id", "MISSION:agent"
        )
        self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()
