"""Focused contract tests for the stdlib PESE persistence runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from asc_orchestrator.pese import PESEError, PESEStore, canonical_json, canonical_sha256

ACTOR = "AGENT:orchestrator:test"
MISSION = "MISSION:007"
ASSIGNMENT = "ASSIGNMENT:implement-pese"


def team_manifest() -> str:
    return f"""## TEAM IDENTITY
Manifest Version: 1
## PROJECT CLASSIFICATION
| Root | Type |
| --- | --- |
| . | Python |
## MEMBERSHIP TABLE
| Agent ID | Role | Department | ACR registry reference |
| --- | --- | --- | --- |
| {ACTOR} | Orchestrator | ENGINEERING | docs/ACR_v1.0.md |
## OWNERSHIP MATRIX
| Mutable area or artifact | Owner |
| --- | --- |
| {ASSIGNMENT} | {ACTOR} |
## EXECUTION GRAPH
| Agent | Phase |
| --- | --- |
| {ACTOR} | 1 |
## REVIEW MATRIX
| Deliverable | Reviewer |
| --- | --- |
| PESE | {ACTOR} |
## VALIDATOR ASSIGNMENT
| Gate | Validator |
| --- | --- |
| GATE:qa | {ACTOR} |
## ESCALATION ROUTES
| Level | Destination |
| --- | --- |
| 1 | {ACTOR} |
## CAPACITY RECORD
| Agent | Capacity |
| --- | --- |
| {ACTOR} | 1 |
## ACTIVE POLICIES
| Policy | Evidence |
| --- | --- |
| default | docs/TBE_v1.0.md |
"""


def state_with_work(store: PESEStore) -> dict:
    state = store.default_state()
    state["company_state"]["status"] = "ACTIVE"
    state["mission_state"] = {
        "active_mission_id": MISSION,
        "missions": {
            MISSION: {
                "status": "PLANNED",
                "priority": "HIGH",
                "manifest_ref": "team.md",
                "manifest_version": 1,
                "assigned_agent_ids": [ACTOR],
                "started_at": None,
                "completed_at": None,
                "last_checkpoint_id": None,
                "acceptance_evidence_refs": [],
            }
        },
    }
    state["execution_state"] = {
        "current_milestone_id": "IMPLEMENT",
        "milestones": [{"id": "IMPLEMENT", "order": 10, "status": "ACTIVE"}],
        "assignments": {
            ASSIGNMENT: {
                "mission_id": MISSION,
                "milestone_id": "IMPLEMENT",
                "status": "READY",
                "assigned_agent_id": ACTOR,
                "manifest_version": 1,
                "depends_on": [],
                "input_refs": [],
                "output_refs": [],
                "started_at": None,
                "completed_at": None,
                "last_checkpoint_id": None,
                "position_id": "POSITION:implement-pese",
                "replacement_count": 0,
                "replacement_lineage": [],
                "interruption": None,
            }
        },
        "next_task_candidates": [ASSIGNMENT],
    }
    state["agent_state"] = {
        "agents": {
            ACTOR: {
                "agent_id": ACTOR,
                "status": "READY",
                "mission_id": MISSION,
                "assignment_id": ASSIGNMENT,
                "manifest_version": 1,
                "last_heartbeat_at": None,
                "last_checkpoint_id": None,
                "acr_ref": "docs/ACR_v1.0.md",
                "dependency_environment_state": {
                    "status": "VERIFIED",
                    "verified_at": None,
                    "tool_dependencies": [],
                    "environment_dependencies": [],
                },
                "interruption": None,
            }
        }
    }
    return state


class PESEStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        # Default tempfile roots on Windows live under the user's home,
        # which may itself be a Git worktree. Cap the ceiling so PESE's
        # authoritative repository check observes the temp dir as a
        # non-Git root while still allowing the explicit git-init tests
        # below to discover a freshly created `.git` inside `self.root`.
        self._previous_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.environ["GIT_CEILING_DIRECTORIES"] = str(self.root.parent)
        self.store = PESEStore(self.root)
        self._write_team_manifest(self.root)
        self.assertEqual(
            self.store.initialize(ACTOR, state_with_work(self.store)).code,
            "INITIALIZED",
        )

    def _write_team_manifest(self, root: Path) -> None:
        (root / "team.md").write_text(team_manifest(), encoding="utf-8", newline="\n")

    @staticmethod
    def _git(root: Path, *arguments: str) -> None:
        try:
            subprocess.run(
                ["git", *arguments],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            raise unittest.SkipTest("Git is not installed")

    def _git_worktree(self, name: str) -> tuple[Path, PESEStore]:
        """Create a Git worktree with one commit and PESE bound to it."""
        root = self.root / name
        root.mkdir()
        self._git(root, "init")
        self._git(root, "config", "user.email", "test@example.invalid")
        self._git(root, "config", "user.name", "PESE Tests")
        self._write_team_manifest(root)
        (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self._git(root, "add", "team.md", "tracked.txt")
        self._git(root, "commit", "-m", "initial")
        store = PESEStore(root)
        self.assertEqual(
            store.initialize(ACTOR, state_with_work(store)).code, "INITIALIZED"
        )
        return root, store

    def _git_commit(self, root: Path, message: str) -> str:
        (root / "tracked.txt").write_text(message + "\n", encoding="utf-8")
        self._git(root, "add", "tracked.txt")
        self._git(root, "commit", "-m", message)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return head.stdout.strip()

    def tearDown(self) -> None:
        if self._previous_ceiling is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = self._previous_ceiling
        self.temp.cleanup()

    def update(self, kind: str, subject: str, old: str, new: str, mutator):
        return self.store.update(
            expected_revision=1,
            actor=ACTOR,
            transition_type=kind,
            subject=subject,
            from_value=old,
            to_value=new,
            mutate=mutator,
        )

    def test_canonical_json_hash_is_order_independent_and_hash_excludes_field(
        self,
    ) -> None:
        self.assertEqual(canonical_json({"b": 1, "a": "é"}), b'{"a":"\xc3\xa9","b":1}')
        value = {"a": 1, "file_sha256": "x"}
        self.assertEqual(
            canonical_sha256(value, "file_sha256"), canonical_sha256({"a": 1})
        )

    def test_initialization_creates_canonical_layout_and_valid_chain(self) -> None:
        for relative in (
            "state/live.json",
            "state/history/1.json",
            "checkpoints",
            "locks",
            "migrations",
            "audit/access",
            "audit/transitions",
            "recovery",
        ):
            self.assertTrue((self.store.base / relative).exists(), relative)
        self.assertEqual(self.store.validate(check_repository=False).code, "VALID")
        self.assertEqual(self.store.load().state_revision, 1)

    def test_update_commits_revision_transition_audit_and_start_checkpoint(
        self,
    ) -> None:
        result = self.update(
            "MISSION_STATUS",
            MISSION,
            "PLANNED",
            "ACTIVE",
            lambda s: s["mission_state"]["missions"][MISSION].__setitem__(
                "status", "ACTIVE"
            ),
        )
        self.assertEqual(result.code, "UPDATED")
        self.assertEqual(result.state_revision, 2)
        self.assertTrue(result.data["checkpoint"])
        self.assertTrue(list((self.store.base / "audit/transitions").glob("*.json")))
        self.assertEqual(self.store.validate(check_repository=False).code, "VALID")

    def test_checkpoint_duplicate_is_idempotent_and_checkpoint_chain_is_checked(
        self,
    ) -> None:
        one = self.store.checkpoint(MISSION, "MANUAL", actor=ACTOR)
        two = self.store.checkpoint(MISSION, "MANUAL", actor=ACTOR)
        self.assertEqual(one.code, "CHECKPOINTED")
        self.assertTrue(two.data["duplicate"])
        path = self.store.base / "checkpoints" / (one.data["checkpoint_id"] + ".json")
        item = json.loads(path.read_text())
        item["snapshot"]["mission_id"] = "MISSION-bad"
        path.write_bytes(canonical_json(item) + b"\n")
        report = self.store.validate(check_repository=False)
        self.assertIn("CHECKPOINT_CHAIN_INVALID", [x["code"] for x in report.findings])

    def test_chain_tampering_is_reported_without_repairing_evidence(self) -> None:
        history = self.store.base / "state/history/1.json"
        item = json.loads(history.read_text())
        item["state"]["company_state"]["status"] = "HALTED"
        history.write_text(json.dumps(item) + "\n", encoding="utf-8")
        self.assertEqual(self.store.load().code, "STATE_CORRUPT")
        self.assertTrue(history.exists())

    def test_lock_is_exclusive_and_expired_dead_owner_is_preserved_on_recovery(
        self,
    ) -> None:
        first = self.store.acquire_lock(ACTOR, 1)
        self.assertEqual(first.code, "LOCK_ACQUIRED")
        other = PESEStore(self.root, liveness_check=lambda _: False)
        self.assertEqual(other.acquire_lock("AGENT:other:test", 1).code, "LOCKED")
        lock = json.loads(self.store.lock_path.read_text())
        lock["lease_expires_at"] = (
            (datetime.now(UTC) - timedelta(minutes=3))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        lock["file_sha256"] = canonical_sha256(lock, "file_sha256")
        self.store.lock_path.write_bytes(canonical_json(lock) + b"\n")
        recovered = other.recover(actor="AGENT:other:test", stale_lock=True)
        self.assertEqual(recovered.code, "RECOVERED")
        self.assertTrue(list((self.store.base / "recovery").glob("STALE-LOCK-*.json")))

    def test_ambiguous_lock_is_a_safety_halt(self) -> None:
        self.assertEqual(self.store.acquire_lock(ACTOR, 1).code, "LOCK_ACQUIRED")
        other = PESEStore(self.root, liveness_check=lambda _: None)
        result = other.recover(actor="AGENT:other:test", stale_lock=True)
        self.assertEqual(result.code, "SAFETY_HALT")

    def test_atomic_lock_race_allows_exactly_one_writer(self) -> None:
        first, second = PESEStore(self.root), PESEStore(self.root)
        barrier = threading.Barrier(3)
        results = []

        def acquire(store: PESEStore, actor: str) -> None:
            barrier.wait()
            results.append((store, actor, store.acquire_lock(actor, 1)))

        workers = [
            threading.Thread(target=acquire, args=(first, ACTOR)),
            threading.Thread(target=acquire, args=(second, "AGENT:other:race")),
        ]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join()
        self.assertEqual(
            sorted(result.code for _, _, result in results), ["LOCKED", "LOCK_ACQUIRED"]
        )
        for store, actor, result in results:
            if result.code == "LOCK_ACQUIRED":
                self.assertEqual(store.release_lock(actor).code, "LOCK_RELEASED")

    def test_initialization_race_creates_exactly_one_revision_one(self) -> None:
        root = self.root / "initialize-race"
        first, second = PESEStore(root), PESEStore(root)
        barrier = threading.Barrier(3)
        results = []

        def initialize(store: PESEStore, actor: str) -> None:
            barrier.wait()
            results.append(store.initialize(actor))

        workers = [
            threading.Thread(target=initialize, args=(first, ACTOR)),
            threading.Thread(
                target=initialize, args=(second, "AGENT:other:initialize")
            ),
        ]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join()
        self.assertEqual(sum(result.code == "INITIALIZED" for result in results), 1)
        self.assertEqual(
            len(list((root / ".project-os/PESE/state/history").glob("*.json"))), 1
        )
        self.assertEqual(PESEStore(root).validate(check_repository=False).code, "VALID")

    def test_concurrent_loads_keep_access_audit_chain_valid(self) -> None:
        barrier = threading.Barrier(5)
        outcomes = []

        def read() -> None:
            barrier.wait()
            outcomes.append(self.store.load())

        workers = [threading.Thread(target=read) for _ in range(4)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join()
        self.assertTrue(all(result.code == "STATE_LOADED" for result in outcomes))
        self.assertEqual(self.store.validate(check_repository=False).code, "VALID")

    def test_separate_process_loads_keep_access_audit_chain_valid(self) -> None:
        command = (
            "from asc_orchestrator.pese import PESEStore; "
            f"assert PESEStore({str(self.root)!r}).load().code == 'STATE_LOADED'"
        )
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
        processes = [
            subprocess.Popen([sys.executable, "-c", command], env=env) for _ in range(8)
        ]
        self.assertTrue(all(process.wait(timeout=20) == 0 for process in processes))
        self.assertEqual(self.store.validate(check_repository=False).code, "VALID")

    def test_existing_lock_prevents_update_without_history_write(self) -> None:
        holder = PESEStore(self.root)
        self.assertEqual(holder.acquire_lock(ACTOR, 1).code, "LOCK_ACQUIRED")
        blocked = PESEStore(self.root).update(
            expected_revision=1,
            actor=ACTOR,
            transition_type="MISSION_STATUS",
            subject=MISSION,
            from_value="PLANNED",
            to_value="ACTIVE",
            mutate=lambda s: s["mission_state"]["missions"][MISSION].__setitem__(
                "status", "ACTIVE"
            ),
        )
        self.assertEqual(blocked.code, "LOCKED")
        self.assertFalse((self.store.base / "state/history/2.json").exists())
        holder.release_lock(ACTOR)

    def test_invalid_lock_is_integrity_finding(self) -> None:
        self.store.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.store.lock_path.write_bytes(b"not-json\n")
        report = self.store.validate(check_repository=False)
        self.assertIn("LOCK_INVALID", [finding["code"] for finding in report.findings])

    def test_failed_required_checkpoint_does_not_report_updated(self) -> None:
        original = self.store.checkpoint
        self.store.checkpoint = lambda *args, **kwargs: original(
            "MISSION:missing", "MISSION_START", actor=ACTOR
        )  # type: ignore[method-assign]
        outcome = self.update(
            "MISSION_STATUS",
            MISSION,
            "PLANNED",
            "ACTIVE",
            lambda s: s["mission_state"]["missions"][MISSION].__setitem__(
                "status", "ACTIVE"
            ),
        )
        self.assertEqual(outcome.code, "HALTED")
        self.assertEqual(outcome.state_revision, 2)

    def test_assignment_transition_rejects_non_assigned_actor(self) -> None:
        outcome = self.store.update(
            expected_revision=1,
            actor="AGENT:other:1",
            transition_type="ASSIGNMENT_STATUS",
            subject=ASSIGNMENT,
            from_value="READY",
            to_value="IN_PROGRESS",
            mutate=lambda state: state["execution_state"]["assignments"][
                ASSIGNMENT
            ].__setitem__("status", "IN_PROGRESS"),
        )
        self.assertEqual(outcome.code, "UNAUTHORIZED")
        self.assertIn("UNAUTHORIZED", [finding["code"] for finding in outcome.findings])

    def test_team_manifest_semantic_alternate_heading_style_is_accepted(self) -> None:
        (self.root / "team.md").write_text(
            f"""# team-identity
version = 1
### project.classification
text
#### membership_table
Member: {ACTOR}
## ownership-matrix
| {ASSIGNMENT} | {ACTOR} |
### execution.graph
text
## review_matrix
text
### validator-assignment
text
## escalation.routes
text
### capacity_record
text
## active-policies
text
""",
            encoding="utf-8",
            newline="\n",
        )
        outcome = self.store.update(
            expected_revision=1,
            actor=ACTOR,
            transition_type="ASSIGNMENT_STATUS",
            subject=ASSIGNMENT,
            from_value="READY",
            to_value="IN_PROGRESS",
            mutate=lambda state: state["execution_state"]["assignments"][
                ASSIGNMENT
            ].__setitem__("status", "IN_PROGRESS"),
        )
        self.assertEqual(outcome.code, "UPDATED")

    def test_tbe_scheduled_review_and_validation_assignments_are_authorized(
        self,
    ) -> None:
        """TBE control work is authorized by its own manifest sections, not files."""
        root = self.root / "scheduled-control-work"
        root.mkdir()
        store = PESEStore(root)
        reviewer = "AGENT:reviewer:1"
        validator = "AGENT:validator:1"
        attacker = "AGENT:attacker:1"
        (root / "team.md").write_text(
            f"""## TEAM IDENTITY
Manifest Version: 1
## PROJECT CLASSIFICATION
| Root | Type |
| --- | --- |
| . | Python |
## MEMBERSHIP TABLE
| Agent ID | Role | Department | ACR registry reference |
| --- | --- | --- | --- |
| {ACTOR} | Builder | ENGINEERING | docs/ACR_v1.0.md |
| {reviewer} | Reviewer | QUALITY | docs/ACR_v1.0.md |
| {validator} | Validator | QUALITY | docs/ACR_v1.0.md |
| {attacker} | Reviewer | QUALITY | docs/ACR_v1.0.md |
## OWNERSHIP MATRIX
| Assignment | Mutable area or artifact | Owner |
| --- | --- | --- |
| ASSIGNMENT:build | src/ | {ACTOR} |
## EXECUTION GRAPH
| Agent | Phase |
| --- | --- |
| {ACTOR} | 1 |
## REVIEW MATRIX
| Deliverable type | Owning builder | Assigned reviewer | Rotation state |
| --- | --- | --- | --- |
| ASSIGNMENT:build | {ACTOR} | {reviewer} | R0 |
## VALIDATOR ASSIGNMENT
| Gate | Validator | Fallback validator |
| --- | --- | --- |
| functional | {validator} | - |
## ESCALATION ROUTES
| Level | Destination |
| --- | --- |
| 1 | {ACTOR} |
## CAPACITY RECORD
| Agent | Capacity |
| --- | --- |
| {ACTOR} | 1 |
## ACTIVE POLICIES
| Policy | Evidence |
| --- | --- |
| default | docs/TBE_v1.0.md |
""",
            encoding="utf-8",
            newline="\n",
        )
        state = state_with_work(store)
        state["mission_state"]["missions"][MISSION]["assigned_agent_ids"] = [
            ACTOR,
            reviewer,
            validator,
            attacker,
        ]

        def assignment(agent_id: str) -> dict[str, object]:
            return {
                "mission_id": MISSION,
                "milestone_id": "IMPLEMENT",
                "status": "PENDING",
                "assigned_agent_id": agent_id,
                "manifest_version": 1,
                "depends_on": [],
                "input_refs": [],
                "output_refs": [],
                "started_at": None,
                "completed_at": None,
                "last_checkpoint_id": None,
                "position_id": "POSITION:control",
                "replacement_count": 0,
                "replacement_lineage": [],
                "interruption": None,
            }

        review_assignment = "ASSIGNMENT:review-build"
        validator_assignment = "ASSIGNMENT:validate-functional"
        state["execution_state"]["assignments"] = {
            review_assignment: assignment(reviewer),
            validator_assignment: assignment(validator),
            "ASSIGNMENT:review-attacker": assignment(attacker),
        }
        state["execution_state"]["next_task_candidates"] = sorted(
            state["execution_state"]["assignments"]
        )
        template = state["agent_state"]["agents"][ACTOR]
        state["agent_state"]["agents"] = {
            agent_id: {
                **template,
                "agent_id": agent_id,
                "assignment_id": next(
                    (
                        assignment_id
                        for assignment_id, item in state["execution_state"][
                            "assignments"
                        ].items()
                        if item["assigned_agent_id"] == agent_id
                    ),
                    None,
                ),
            }
            for agent_id in (ACTOR, reviewer, validator, attacker)
        }
        self.assertEqual(store.initialize(ACTOR, state).code, "INITIALIZED")

        def ready(assignment_id: str):
            return lambda target: target["execution_state"]["assignments"][
                assignment_id
            ].__setitem__("status", "READY")

        review_ready = store.update(
            expected_revision=1,
            actor=reviewer,
            transition_type="ASSIGNMENT_STATUS",
            subject=review_assignment,
            from_value="PENDING",
            to_value="READY",
            mutate=ready(review_assignment),
        )
        self.assertEqual(review_ready.code, "UPDATED")
        validator_ready = store.update(
            expected_revision=2,
            actor=validator,
            transition_type="ASSIGNMENT_STATUS",
            subject=validator_assignment,
            from_value="PENDING",
            to_value="READY",
            mutate=ready(validator_assignment),
        )
        self.assertEqual(validator_ready.code, "UPDATED")
        attacker_outcome = store.update(
            expected_revision=3,
            actor=attacker,
            transition_type="ASSIGNMENT_STATUS",
            subject="ASSIGNMENT:review-attacker",
            from_value="PENDING",
            to_value="READY",
            mutate=ready("ASSIGNMENT:review-attacker"),
        )
        self.assertEqual(attacker_outcome.code, "UNAUTHORIZED")

    def test_computed_milestone_requires_mission_gates_to_be_green(self) -> None:
        state = state_with_work(self.store)
        state["execution_state"]["assignments"][ASSIGNMENT]["status"] = "COMPLETED"
        state["validation_state"]["gates"] = {
            "GATE:qa": {
                "mission_id": MISSION,
                "milestone_id": "IMPLEMENT",
                "status": "PENDING",
                "validator_agent_id": ACTOR,
                "manifest_version": 1,
                "criteria_refs": [],
                "artifact_ids": [],
                "last_checkpoint_id": None,
                "verdict_at": None,
            }
        }
        self.assertEqual(self.store._computed_milestone(state), "IMPLEMENT")
        state["validation_state"]["gates"]["GATE:qa"]["status"] = "GREEN"
        self.assertIsNone(self.store._computed_milestone(state))

    def test_extensions_require_reverse_dns_keys(self) -> None:
        store = PESEStore(self.root / "extensions")
        state = state_with_work(store)
        state["extensions"] = {"tbe": {}}
        with self.assertRaisesRegex(PESEError, "reverse-DNS"):
            store.initialize(ACTOR, state)

    def test_git_repository_without_origin_has_local_identity(self) -> None:
        git_root = self.root / "git-no-origin"
        git_root.mkdir()
        try:
            subprocess.run(
                ["git", "init"], cwd=git_root, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=git_root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=git_root, check=True
            )
            (git_root / "tracked.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=git_root, check=True)
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=git_root,
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            self.skipTest("Git is not installed")
        observed = PESEStore(git_root).repository_observation()
        self.assertEqual(
            observed["origin_identity"], "local:" + git_root.resolve().as_posix()
        )

    def test_initialization_in_git_remains_repository_consistent(self) -> None:
        git_root = self.root / "git-initialize"
        git_root.mkdir()
        try:
            subprocess.run(
                ["git", "init"], cwd=git_root, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=git_root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=git_root, check=True
            )
            (git_root / "tracked.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=git_root, check=True)
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=git_root,
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            self.skipTest("Git is not installed")
        store = PESEStore(git_root)
        self.assertEqual(store.initialize(ACTOR).code, "INITIALIZED")
        self.assertEqual(store.validate().code, "VALID")

    def test_resume_plan_uses_ready_assignment_and_requires_checkpoint(self) -> None:
        self.assertEqual(
            self.store.checkpoint(MISSION, "MANUAL", actor=ACTOR).code, "CHECKPOINTED"
        )
        plan = self.store.resume()
        # This temp root is not Git-backed, so authoritative repository check
        # correctly stops an autonomous resume rather than guessing.
        self.assertEqual(plan.code, "SAFETY_HALT")
        self.assertTrue(
            any(x["code"] == "REPOSITORY_DIVERGENCE" for x in plan.findings)
        )

    def test_recovery_reconciles_a_published_history_revision_to_live(self) -> None:
        active = self.update(
            "MISSION_STATUS",
            MISSION,
            "PLANNED",
            "ACTIVE",
            lambda s: s["mission_state"]["missions"][MISSION].__setitem__(
                "status", "ACTIVE"
            ),
        )
        self.store.live_path.write_bytes(
            (self.store.base / "state/history/1.json").read_bytes()
        )
        self.assertEqual(self.store.validate(check_repository=False).code, "INVALID")
        repaired = self.store.recover(actor=ACTOR)
        self.assertEqual(repaired.code, "RECOVERED")
        self.assertEqual(
            json.loads(self.store.live_path.read_text())["revision"],
            active.state_revision,
        )

    def test_migration_creates_record_and_new_revision(self) -> None:
        result = self.store.migrate(
            actor=ACTOR,
            to_schema_version="1.0.1",
            mission_id=MISSION,
            transform=lambda state: state,
        )
        self.assertEqual(result.code, "MIGRATED")
        self.assertTrue(list((self.store.base / "migrations").glob("MIG-*.json")))
        self.assertEqual(
            self.store.load().data["envelope"]["state"]["schema_version"], "1.0.1"
        )

    def test_artifact_path_escape_is_reported(self) -> None:
        state = json.loads(self.store.live_path.read_text())["state"]
        state["validation_state"]["artifacts"] = {
            "bad": {
                "path": "../secret",
                "sha256": sha256(b"x").hexdigest(),
                "type": "test",
                "produced_at": "2026-08-03T00:00:00.000Z",
                "producer_agent_id": ACTOR,
                "retention_class": "MISSION",
            }
        }
        # Constructing a separate initialized store makes this a persisted input
        # validation test instead of bypassing the public persistence boundary.
        other_root = self.root / "other"
        other = PESEStore(other_root)
        other.initialize(ACTOR, state)
        report = other.validate(check_repository=False)
        self.assertIn("CONTRACT_INVALID", [x["code"] for x in report.findings])

    def test_reconcile_repository_records_authorized_head_advance_and_unblocks_resume(
        self,
    ) -> None:
        """The production defect: HEAD advances, resume halts, reconcile fixes."""
        root, store = self._git_worktree("git-reconcile")
        self.assertEqual(store.validate().code, "VALID")
        old_head = store.repository_observation()["HEAD"]
        self.assertEqual(
            store.checkpoint(MISSION, "MANUAL", actor=ACTOR).code, "CHECKPOINTED"
        )
        new_head = self._git_commit(root, "advance")
        self.assertNotEqual(new_head, old_head)

        report = store.validate()
        self.assertEqual(report.code, "INVALID")
        self.assertIn(
            "REPOSITORY_DIVERGENCE", [finding["code"] for finding in report.findings]
        )
        halted = store.resume()
        self.assertEqual(halted.code, "SAFETY_HALT")
        self.assertTrue(
            any(
                finding["code"] == "REPOSITORY_DIVERGENCE"
                for finding in halted.findings
            )
        )

        result = store.reconcile_repository(actor=ACTOR, expected_revision=1)
        self.assertEqual(result.code, "RECONCILIATED")
        self.assertEqual(result.data["old_HEAD"], old_head)
        self.assertEqual(result.data["new_HEAD"], new_head)
        self.assertEqual(
            result.data["repository_id"],
            store.repository_observation()["repository_id"],
        )
        self.assertEqual(result.state_revision, 2)
        self.assertEqual(result.state_sha256, store.load().state_sha256)
        self.assertEqual(store.validate().code, "VALID")
        self.assertEqual(store.resume().code, "RESUME_PLAN")

    def test_reconcile_repository_refresh_with_unchanged_head_stays_valid(
        self,
    ) -> None:
        root, store = self._git_worktree("git-refresh")
        before = store.repository_observation()
        result = store.reconcile_repository(actor=ACTOR, expected_revision=1)
        self.assertEqual(result.code, "RECONCILIATED")
        self.assertEqual(result.data["old_HEAD"], result.data["new_HEAD"])
        self.assertEqual(result.data["new_HEAD"], before["HEAD"])
        self.assertEqual(store.validate().code, "VALID")

    def test_reconcile_repository_rejects_a_non_descendant_head(self) -> None:
        root, store = self._git_worktree("git-divergent")
        first = store.repository_observation()["HEAD"]
        # Advance main and reconcile, so the stored HEAD becomes `second`.
        second = self._git_commit(root, "second")
        ok = store.reconcile_repository(actor=ACTOR, expected_revision=1)
        self.assertEqual(ok.code, "RECONCILIATED")
        # Branch from the ORIGINAL commit: its tip is not a descendant of the
        # stored HEAD, so reconciliation must refuse to rebind to it.
        self._git(root, "checkout", "-b", "side", first)
        self._git_commit(root, "side")
        self.assertFalse(
            store._is_ancestor(second, store.repository_observation()["HEAD"])
        )
        report = store.reconcile_repository(actor=ACTOR, expected_revision=2)
        self.assertEqual(report.code, "SAFETY_HALT")
        self.assertTrue(
            any(
                finding["code"] == "REPOSITORY_NON_DESCENDANT"
                for finding in report.findings
            )
        )
        # No new state revision was committed and no checkpoint was written.
        self.assertEqual(store.load().state_revision, 2)

    def test_reconcile_repository_rejects_a_different_repository(self) -> None:
        root, store = self._git_worktree("git-mismatch")
        # Legitimately persist a forked repository identity (simulates PESE
        # state captured from a different checkout being offered for rebinding).
        forged = store.update(
            expected_revision=1,
            actor=ACTOR,
            transition_type="TEST_MUTATION",
            subject="state",
            from_value="",
            to_value="",
            mutate=lambda s: s["repo_state"].update({"repository_id": "REPO:forged"}),
        )
        self.assertEqual(forged.code, "UPDATED")
        report = store.reconcile_repository(actor=ACTOR, expected_revision=2)
        self.assertEqual(report.code, "SAFETY_HALT")
        self.assertTrue(
            any(finding["code"] == "REPOSITORY_MISMATCH" for finding in report.findings)
        )

    def test_reconcile_repository_requires_orchestrator_authority(self) -> None:
        root, store = self._git_worktree("git-unauthorized")
        report = store.reconcile_repository(
            actor="AGENT:builder:1", expected_revision=1
        )
        self.assertEqual(report.code, "SAFETY_HALT")
        self.assertTrue(
            any(finding["code"] == "UNAUTHORIZED" for finding in report.findings)
        )
        self.assertEqual(store.load().state_revision, 1)

    def test_reconcile_repository_writes_audit_trail_and_preserves_hash_chain(
        self,
    ) -> None:
        root, store = self._git_worktree("git-audit")
        old_head = store.repository_observation()["HEAD"]
        new_head = self._git_commit(root, "advance")
        result = store.reconcile_repository(actor=ACTOR, expected_revision=1)
        self.assertEqual(result.code, "RECONCILIATED")
        records = [
            json.loads(path.read_text())
            for path in (store.base / "audit/transitions").glob("*.json")
            if json.loads(path.read_text()).get("transition_type")
            == "REPOSITORY_RECONCILIATION"
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["from"], old_head)
        self.assertEqual(records[0]["to"], new_head)
        self.assertEqual(records[0]["after_state_sha256"], result.state_sha256)
        # The reconcile state revision carries the COMMIT checkpoint and the
        # full chain (history + checkpoints + audits) validates cleanly.
        self.assertEqual(store.validate(check_repository=False).code, "VALID")
        self.assertEqual(store.load().data["envelope"]["revision"], 2)
        envelope = json.loads(store.live_path.read_text())
        observed = store.repository_observation()
        self.assertEqual(envelope["state"]["repo_state"]["HEAD"], new_head)
        self.assertEqual(envelope["state"]["repo_state"]["BRANCH"], observed["BRANCH"])


if __name__ == "__main__":
    unittest.main()
