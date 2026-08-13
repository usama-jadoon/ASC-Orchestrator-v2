"""Regression tests for ASC Orchestrator v1.0.2 lifecycle deadlock fixes.

Defects under test (from real-world InboxShield mission analysis):
  D1 — dependent assignments stay PENDING forever because no runtime path
       promotes PENDING -> READY when a dependency completes.
  D2 — the Autonomous Workflow Scheduler can start a PENDING validation gate
       while assignments are still unfinished.
  D3 — EEF complete() may transition an ACTIVE mission to VALIDATING while
       assignments remain unfinished.

Each test reproduces the defect on v1.0.1 (fails) and locks in the corrected
behavior (passes) after the v1.0.2 maintenance patch.

Canonical chain (via assemble_team + mission() fixture):
    ASSIGNMENT:build  -->  ASSIGNMENT:review-build  -->  ASSIGNMENT:validate-functional
    (root, READY at start)       (PENDING)                 (PENDING)

Gate: GATE:MISSION:42:functional (PENDING at bind time)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asc_orchestrator.aex import AEX  # noqa: E402
from asc_orchestrator.aws import AutonomousScheduler  # noqa: E402
from asc_orchestrator.execution import (  # noqa: E402
    ExecutionSession,
    build_context,
)
from asc_orchestrator.pese import PESEStore  # noqa: E402
from asc_orchestrator.tbe import (  # noqa: E402
    assemble_team,
    bind_manifest_to_pese,
    team_manifest_relative_path,
)
from asc_orchestrator.validation import ValidationEngine  # noqa: E402
from tests.test_tbe import PROJECT, mission, registry  # noqa: E402

ORCHESTRATOR = "AGENT:orchestrator:123e4567-e89b-42d3-a456-426614174000"
ASSEMBLED_AT = "2026-08-04T00:00:00.000Z"

ASSIGN_BUILD = "ASSIGNMENT:build"
ASSIGN_REVIEW = "ASSIGNMENT:review-build"
ASSIGN_VALIDATE = "ASSIGNMENT:validate-functional"
GATE_FUNCTIONAL = "GATE:MISSION:42:functional"


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _LifecycleV102Base(unittest.TestCase):
    """Git-backed temp repo with a bound (but not started) enhancement mission.

    The canonical mission() fixture yields the chain
        build -> review-build -> validate-functional
    with one PENDING validation gate GATE:MISSION:42:functional.
    """

    def setUp(self) -> None:
        self._previous_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["GIT_CEILING_DIRECTORIES"] = str(self.root.parent)
        self._git("init")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "Lifecycle V102 Tests")
        (self.root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git("add", "tracked.txt")
        self._git("commit", "-m", "initial")
        (self.root / "asc-orchestrator.toml").write_text(
            '[runtime]\nproject_os_dir = ".project-os"\n'
            'registry_dir = ".project-os/COMPANY/DEPARTMENTS"\n'
            'audit_dir = ".project-os/AUDIT"\n'
            'protocol_version = "ACP/v1.0"\n',
            encoding="utf-8",
        )
        self.store = PESEStore(self.root)
        self.assertEqual(self.store.initialize(ORCHESTRATOR).code, "INITIALIZED")
        self.manifest = assemble_team(
            mission(), [PROJECT], registry(), assembled_at=ASSEMBLED_AT
        )
        self.reference = team_manifest_relative_path(self.manifest)
        self.mission_id = self.manifest.mission_id
        dest = self.root / self.reference
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.manifest.to_markdown(), encoding="utf-8", newline="\n")
        bind = bind_manifest_to_pese(
            self.manifest, self.store, manifest_ref=self.reference, actor=ORCHESTRATOR
        )
        self.assertEqual(bind.code, "UPDATED")
        self.actor = self.store.load().data["envelope"]["state"]["mission_state"][
            "missions"
        ][self.mission_id]["assigned_agent_ids"][0]
        self.aex = AEX(self.root)

    def tearDown(self) -> None:
        if self._previous_ceiling is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = self._previous_ceiling
        self.temp.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )

    def _state(self) -> dict:
        return self.store.load().data["envelope"]["state"]

    def _assignment(self, assignment_id: str) -> dict:
        return self._state()["execution_state"]["assignments"][assignment_id]

    def _gate_status(self) -> str:
        return self._state()["validation_state"]["gates"][GATE_FUNCTIONAL]["status"]

    def _start_mission(self) -> None:
        ctx, err = build_context(self.root, None, self.mission_id, self.actor)
        self.assertIsNone(err, f"build_context failed: {err}")
        assert ctx is not None
        outcome = ExecutionSession(ctx, actor=self.actor).start()
        self.assertEqual(outcome.code, "UPDATED")

    def _dispatch_and_complete(self, assignment_id: str) -> None:
        """Dispatch a READY assignment and complete it through AEX.

        Uses the assignment's own assigned_agent_id as the actor, which is
        the canonical agent-ownership model for AEX transitions.
        """
        agent = self._assignment(assignment_id)["assigned_agent_id"]
        dispatch_outcome = self.aex.dispatch(self.mission_id, assignment_id, agent)
        self.assertEqual(dispatch_outcome.code, "UPDATED")
        # AEX.complete() returns a result record dict (not a PESEOutcome).
        # If the transition fails it raises AEXError; success returns the record.
        record = self.aex.complete(self.mission_id, assignment_id, agent)
        self.assertEqual(record.get("status"), "COMPLETED")

    def _gate_validator(self) -> str:
        return self._state()["validation_state"]["gates"][GATE_FUNCTIONAL][
            "validator_agent_id"
        ]

    def _finish_gate_green(self) -> None:
        validator = self._gate_validator()
        engine = ValidationEngine(self.root)
        start_outcome = engine.start(self.mission_id, GATE_FUNCTIONAL, validator)
        self.assertEqual(start_outcome.code, "UPDATED")
        artifact_dir = self.root / "validation"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "qa-result.json"
        artifact_path.write_text('{"status":"PASS"}', encoding="utf-8")
        outcome = engine.finish(
            self.mission_id,
            GATE_FUNCTIONAL,
            validator,
            status="GREEN",
            artifacts=[
                {
                    "path": str(artifact_path.relative_to(self.root)),
                    "type": "validation-result",
                    "retention_class": "mission",
                }
            ],
        )
        self.assertEqual(outcome.code, "UPDATED")

    def _build_session(self) -> ExecutionSession:
        ctx, err = build_context(self.root, None, self.mission_id, self.actor)
        self.assertIsNone(err, f"build_context failed: {err}")
        assert ctx is not None
        return ExecutionSession(ctx, actor=self.actor)


# ---------------------------------------------------------------------------
# A — D1: direct dependent promotion
# ---------------------------------------------------------------------------


class TestD1DependentPromotion(_LifecycleV102Base):
    """D1 reproduction: completing a parent must promote its dependent."""

    def test_a_completing_parent_promotes_dependent_to_ready(self) -> None:
        """Completing build must transition review-build PENDING -> READY."""
        self._start_mission()
        self.assertEqual(self._assignment(ASSIGN_BUILD)["status"], "READY")
        self.assertEqual(self._assignment(ASSIGN_REVIEW)["status"], "PENDING")

        self._dispatch_and_complete(ASSIGN_BUILD)

        # BUG (v1.0.1): review-build remains PENDING — no runtime promotes it.
        # FIX (v1.0.2): AEX.complete() bundles dependent promotion.
        self.assertEqual(
            self._assignment(ASSIGN_REVIEW)["status"],
            "READY",
            "dependent assignment must be promoted to READY when parent completes",
        )


# ---------------------------------------------------------------------------
# B — D1: transitive chain promotion
# ---------------------------------------------------------------------------


class TestD1TransitiveChain(_LifecycleV102Base):
    """D1 reproduction: promotion must cascade through the full dependency chain."""

    def test_b_transitive_chain_promotes_through_all_dependents(self) -> None:
        """Complete build -> review-build becomes READY; complete review-build ->
        validate-functional becomes READY."""
        self._start_mission()

        self._dispatch_and_complete(ASSIGN_BUILD)
        self.assertEqual(
            self._assignment(ASSIGN_REVIEW)["status"],
            "READY",
            "review-build must be promoted after build completes",
        )

        self._dispatch_and_complete(ASSIGN_REVIEW)
        self.assertEqual(
            self._assignment(ASSIGN_VALIDATE)["status"],
            "READY",
            "validate-functional must be promoted after review-build completes",
        )

        self._dispatch_and_complete(ASSIGN_VALIDATE)
        self.assertEqual(
            self._assignment(ASSIGN_VALIDATE)["status"],
            "COMPLETED",
            "final assignment should reach COMPLETED",
        )


# ---------------------------------------------------------------------------
# C — D2: AWS VALIDATE prerequisite
# ---------------------------------------------------------------------------


class TestD2ValidationPrerequisite(_LifecycleV102Base):
    """D2 reproduction: VALIDATE must not fire while assignments are unfinished."""

    def test_c_scheduler_never_validates_while_assignments_pending(self) -> None:
        """With all assignments PENDING (not started), AWS must not fire VALIDATE.

        The mission is bound but not started.  All assignments are PENDING and
        the gate is PENDING.  Current v1.0.1 code returns VALIDATE (priority 60)
        because it only checks for a PENDING gate with no prerequisite on
        assignment completion.  The correct behavior is MONITOR_HEALTH.
        """
        scheduler = AutonomousScheduler(self.root)
        decision = scheduler.evaluate()
        self.assertNotEqual(
            decision.decision_type,
            "VALIDATE",
            "VALIDATE must not fire while assignments are unfinished",
        )
        self.assertEqual(decision.decision_type, "MONITOR_HEALTH")

    def test_c2_validate_fires_only_after_all_assignments_complete(self) -> None:
        """VALIDATE is lawful only when every assignment is COMPLETED."""
        self._start_mission()
        for aid in (ASSIGN_BUILD, ASSIGN_REVIEW, ASSIGN_VALIDATE):
            self._dispatch_and_complete(aid)
        self.assertEqual(self._gate_status(), "PENDING")

        scheduler = AutonomousScheduler(self.root)
        decision = scheduler.evaluate()
        self.assertEqual(
            decision.decision_type,
            "VALIDATE",
            "VALIDATE must fire once all assignments are COMPLETED and gate is PENDING",
        )
        self.assertEqual(decision.target_assignment_id, GATE_FUNCTIONAL)


# ---------------------------------------------------------------------------
# D — D3: EEF complete() prerequisite
# ---------------------------------------------------------------------------


class TestD3CompletePrerequisite(_LifecycleV102Base):
    """D3 reproduction: complete() must refuse when assignments are unfinished."""

    def test_d_complete_rejects_unfinished_assignments(self) -> None:
        """EEF complete() must return INVALID_TRANSITION while assignments
        remain PENDING/READY/IN_PROGRESS."""
        self._start_mission()
        # Only root is READY; two dependents are PENDING.
        self.assertEqual(self._assignment(ASSIGN_BUILD)["status"], "READY")
        self.assertEqual(self._assignment(ASSIGN_REVIEW)["status"], "PENDING")
        self.assertEqual(self._assignment(ASSIGN_VALIDATE)["status"], "PENDING")

        session = self._build_session()
        outcome = session.complete()

        # BUG (v1.0.1): outcome.code == "UPDATED" — mission transitions to
        # VALIDATING despite two PENDING assignments.
        # FIX (v1.0.2): outcome.code == "INVALID_TRANSITION".
        self.assertEqual(
            outcome.code,
            "INVALID_TRANSITION",
            "complete() must refuse ACTIVE -> VALIDATING while work is pending",
        )
        # Mission must remain ACTIVE.
        self.assertEqual(
            self._state()["mission_state"]["missions"][self.mission_id]["status"],
            "ACTIVE",
            "mission status must not change when complete() rejects",
        )


# ---------------------------------------------------------------------------
# E — D1 via schedule()
# ---------------------------------------------------------------------------


class TestD1SchedulePath(_LifecycleV102Base):
    """D1 via schedule(): schedule() must find a promoted dependent."""

    def test_e_schedule_returns_ready_for_promoted_dependent(self) -> None:
        """After root completes, schedule() must return READY for the promoted
        dependent rather than NO_WORK."""
        self._start_mission()
        self._dispatch_and_complete(ASSIGN_BUILD)

        session = self._build_session()
        result = session.schedule()

        # BUG (v1.0.1): result.code == "NO_WORK" — review-build is PENDING,
        # so resume() finds nothing.
        # FIX (v1.0.2): result.code == "READY", assignment_id = review-build.
        self.assertEqual(
            result.code,
            "READY",
            "schedule() must return READY for the promoted dependent",
        )
        self.assertEqual(result.assignment_id, ASSIGN_REVIEW)


# ---------------------------------------------------------------------------
# F — End-to-end lifecycle
# ---------------------------------------------------------------------------


class TestEndToEndLifecycle(_LifecycleV102Base):
    """Full mission lifecycle with dependent promotion, validation, and completion."""

    def test_f_full_mission_reaches_validating_with_all_work_green(self) -> None:
        """Start -> drain assignments -> validate gate GREEN -> complete() -> VALIDATING.

        On v1.0.1, the loop stalls after build completes (review-build stuck
        PENDING), preventing full lifecycle completion.  With D1/D2/D3 fixes,
        the entire chain completes and the mission reaches VALIDATING.
        """
        self._start_mission()
        self.assertEqual(self._gate_status(), "PENDING")

        # Drain every assignment as it becomes READY (transitively promoted).
        completed: list[str] = []
        for _ in range(5):
            ready = sorted(
                aid
                for aid, a in self._state()["execution_state"]["assignments"].items()
                if a.get("mission_id") == self.mission_id and a["status"] == "READY"
            )
            if not ready:
                break
            self._dispatch_and_complete(ready[0])
            completed.append(ready[0])

        # All three assignments must have been processed.
        self.assertEqual(
            sorted(completed),
            sorted([ASSIGN_BUILD, ASSIGN_REVIEW, ASSIGN_VALIDATE]),
            "all three assignments must be dispatched and completed",
        )
        for aid in (ASSIGN_BUILD, ASSIGN_REVIEW, ASSIGN_VALIDATE):
            self.assertEqual(
                self._assignment(aid)["status"],
                "COMPLETED",
                f"{aid} must be COMPLETED",
            )

        # Gate evaluates GREEN.
        self._finish_gate_green()
        self.assertEqual(self._gate_status(), "GREEN")

        # Mission advances to VALIDATING via EEF complete().
        session = self._build_session()
        outcome = session.complete()
        self.assertEqual(
            outcome.code,
            "UPDATED",
            "complete() should succeed when all work is done and gate is GREEN",
        )
        self.assertEqual(
            self._state()["mission_state"]["missions"][self.mission_id]["status"],
            "VALIDATING",
        )


if __name__ == "__main__":
    unittest.main()
