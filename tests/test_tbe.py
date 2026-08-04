"""Focused deterministic tests for the TBE v1.0 planning boundary."""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asc_orchestrator.pese import PESEStore  # noqa: E402
from asc_orchestrator.tbe import (  # noqa: E402
    DependencyEdge,
    TBEError,
    assemble_team,
    bind_manifest_to_pese,
    derive_demands,
    team_manifest_relative_path,
    validate_manifest,
)


def entry(
    agent_id: str,
    *,
    competencies=(),
    writable=("src/**",),
    outputs=("EVIDENCE", "REVIEW"),
    inputs=("EVIDENCE", "REVIEW"),
    gates=(),
    version="1.0.0",
    missions=("enhancement",),
):
    """Small ACR-shaped contract; TBE only consumes the public ACR fields."""
    input_messages = tuple(dict.fromkeys((*inputs, "REVIEW"))) if gates else inputs
    return {
        "agent-id": agent_id,
        "version": version,
        "purpose": {"mission-types": list(missions)},
        "required-skills": {"competencies": list(competencies)},
        "owned-repository-areas": {
            "owned-paths": list(writable),
            "writable-paths": list(writable),
            "path-restrictions": ["/.git/", "/.project-os/"],
        },
        "parallel-execution-rules": {
            "resource-limits": "max: 3",
            "shared-resources": "none",
        },
        "validation-duties": {
            "validation-gates": list(gates),
            "evidence-requirements": {"gate": ["evidence"]} if gates else {},
        },
        "input-contracts": {
            "input-message-types": list(input_messages),
            "input-schema": {
                message: {"required": ["REFERENCE"]} for message in input_messages
            },
        },
        "output-contracts": {
            "output-message-types": list(outputs),
            "output-schema": {
                message: {"required": ["REFERENCE"]} for message in outputs
            },
        },
    }


def registry():
    return {
        "developer": entry("developer", competencies=("python", "implementation")),
        "reviewer": entry(
            "reviewer",
            competencies=("python", "review"),
            writable=(),
            outputs=("REVIEW",),
            inputs=("EVIDENCE",),
        ),
        "qa-validator": entry(
            "qa-validator",
            competencies=("python",),
            writable=(),
            outputs=("VALIDATION",),
            inputs=("EVIDENCE",),
            gates=("functional",),
        ),
        "security-auditor": entry(
            "security-auditor",
            competencies=("security",),
            writable=(),
            outputs=("VALIDATION",),
            inputs=("EVIDENCE",),
            gates=("security",),
        ),
        "compliance-validator": entry(
            "compliance-validator",
            competencies=("compliance",),
            writable=(),
            outputs=("VALIDATION",),
            inputs=("EVIDENCE",),
            gates=("compliance",),
        ),
        "fallback-validator": entry(
            "fallback-validator",
            competencies=("compliance",),
            writable=(),
            outputs=("VALIDATION",),
            inputs=("EVIDENCE",),
            gates=("compliance",),
        ),
        "team-lead": entry("team-lead", writable=()),
        "department-lead": entry("department-lead", writable=()),
    }


def mission(**change):
    value = {
        "mission_id": "MISSION:42",
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
    value.update(change)
    return value


PROJECT = {
    "type": "python-package",
    "root": "app",
    "languages": ["python"],
    "frameworks": [],
    "platform": "linux",
    "test_surface": "unittest",
}


class TBETests(unittest.TestCase):
    def build(self, value=None, entries=None):
        return assemble_team(
            value or mission(),
            [PROJECT],
            entries or registry(),
            assembled_at="2026-08-04T00:00:00.000Z",
        )

    def test_deterministic_manifest_and_canonical_pese_compatible_shape(self):
        one, two = self.build(), self.build()
        self.assertEqual(one.to_markdown(), two.to_markdown())
        rendered = one.to_markdown()
        headings = [
            "TEAM IDENTITY",
            "PROJECT CLASSIFICATION",
            "MEMBERSHIP TABLE",
            "OWNERSHIP MATRIX",
            "EXECUTION GRAPH",
            "REVIEW MATRIX",
            "VALIDATOR ASSIGNMENT",
            "ESCALATION ROUTES",
            "CAPACITY RECORD",
            "ACTIVE POLICIES",
        ]
        self.assertEqual(
            [rendered.index(item) for item in headings],
            sorted(rendered.index(item) for item in headings),
        )
        self.assertIn("Manifest Version: 1", rendered)
        self.assertRegex(
            rendered,
            r"\| ASSIGNMENT:build \| src/feature\.py \| AGENT:developer:[0-9a-f-]{36} \|",
        )
        validate_manifest(one, registry=registry())

    def test_registry_only_selection_and_capability_gap(self):
        entries = registry()
        del entries["developer"]
        with self.assertRaisesRegex(TBEError, "CAPABILITY_GAP"):
            self.build(entries=entries)
        value = mission(
            demands=[
                {
                    "id": "ASSIGNMENT:x",
                    "capability": "not-registered",
                    "paths": ["src/x.py"],
                }
            ]
        )
        with self.assertRaisesRegex(TBEError, "CAPABILITY_GAP"):
            self.build(value)

    def test_section_six_tiebreak_prefers_scope_then_skill_then_stability(self):
        entries = registry()
        entries["developer"]["required-skills"]["competencies"] = ["python"]
        entries["generalist"] = entry(
            "generalist", competencies=("implementation",), version="9.0.0"
        )
        entries["precise"] = entry(
            "precise", competencies=("implementation", "python"), version="1.0.0"
        )
        value = mission(
            demands=[
                {
                    "id": "ASSIGNMENT:x",
                    "capability": "implementation",
                    "paths": ["src/x.py"],
                    "validation_gates": ["functional"],
                }
            ]
        )
        built = self.build(value, entries)
        self.assertTrue(
            any(m.agent_id.startswith("AGENT:precise:") for m in built.members)
        )

    def test_ownership_overlap_is_rejected(self):
        entries = registry()
        entries["developer-two"] = entry(
            "developer-two", competencies=("implementation", "python")
        )
        value = mission(
            demands=[
                {"id": "ASSIGNMENT:a", "capability": "developer", "paths": ["src/**"]},
                {
                    "id": "ASSIGNMENT:b",
                    "capability": "developer-two",
                    "paths": ["src/a.py"],
                },
            ]
        )
        with self.assertRaisesRegex(TBEError, "OWNERSHIP_CONFLICT"):
            self.build(value, entries)

    def test_incompatible_contract_dependency_is_rejected(self):
        entries = registry()
        entries["developer-two"] = entry(
            "developer-two", competencies=("python",), inputs=("ASSIGNMENT",)
        )
        value = mission(
            demands=[
                {
                    "id": "ASSIGNMENT:a",
                    "capability": "developer",
                    "paths": ["src/a.py"],
                },
                {
                    "id": "ASSIGNMENT:b",
                    "capability": "developer-two",
                    "paths": ["src/b.py"],
                    "depends_on": ["ASSIGNMENT:a"],
                },
            ]
        )
        with self.assertRaisesRegex(TBEError, "CONTRACT_INCOMPATIBLE"):
            self.build(value, entries)

    def test_dependency_schema_required_fields_are_rejected(self):
        entries = registry()
        entries["developer-two"] = entry(
            "developer-two", competencies=("python",), inputs=("EVIDENCE",)
        )
        entries["developer-two"]["input-contracts"]["input-schema"]["EVIDENCE"] = {
            "required": ["NOT-PRODUCED"]
        }
        value = mission(
            demands=[
                {
                    "id": "ASSIGNMENT:a",
                    "capability": "developer",
                    "paths": ["src/a.py"],
                },
                {
                    "id": "ASSIGNMENT:b",
                    "capability": "developer-two",
                    "paths": ["src/b.py"],
                    "depends_on": ["ASSIGNMENT:a"],
                },
            ]
        )
        with self.assertRaisesRegex(TBEError, "CONTRACT_INCOMPATIBLE"):
            self.build(value, entries)

    def test_dependency_removes_parallelism_and_contract_compatible_edge_is_kept(self):
        entries = registry()
        entries["developer-two"] = entry(
            "developer-two", competencies=("python",), inputs=("EVIDENCE",)
        )
        value = mission(
            demands=[
                {
                    "id": "ASSIGNMENT:a",
                    "capability": "developer",
                    "paths": ["src/a.py"],
                },
                {
                    "id": "ASSIGNMENT:b",
                    "capability": "developer-two",
                    "paths": ["src/b.py"],
                    "depends_on": ["ASSIGNMENT:a"],
                },
            ]
        )
        built = self.build(value, entries)
        phase = dict(built.phases)
        developer = next(
            agent for agent in phase if agent.startswith("AGENT:developer:")
        )
        developer_two = next(
            agent for agent in phase if agent.startswith("AGENT:developer-two:")
        )
        self.assertLess(phase[developer], phase[developer_two])
        self.assertEqual(built.dependencies[0].edge_type, "INPUT")

    def test_capacity_splits_disjoint_builder_positions_and_records_headroom(self):
        entries = registry()
        entries["developer"]["parallel-execution-rules"]["resource-limits"] = "max: 1"
        value = mission(
            demands=[
                {
                    "id": "ASSIGNMENT:a",
                    "capability": "developer",
                    "paths": ["src/a.py"],
                },
                {
                    "id": "ASSIGNMENT:b",
                    "capability": "developer",
                    "paths": ["src/b.py"],
                },
            ]
        )
        built = self.build(value, entries)
        builders = [
            member for member in built.members if member.agent_type == "developer"
        ]
        self.assertEqual(len(builders), 2)
        self.assertEqual({member.headroom for member in builders}, {0})

    def test_selection_records_are_unique_and_explain_rejections(self):
        built = self.build()
        records = built.selection_records
        self.assertEqual(len(records), len({record[0] for record in records}))
        self.assertTrue(all(rejected for _, _, rejected, _ in records))
        self.assertTrue(
            all(
                any("Rule 6." in reason for reason in rejected)
                for _, _, rejected, _ in records
            )
        )

    def test_validator_independence_is_enforced(self):
        entries = registry()
        del entries["qa-validator"]
        # The only remaining functional validator is the builder itself, so a
        # registry-capability match still cannot violate §14.2 independence.
        entries["developer"]["validation-duties"] = {
            "validation-gates": ["functional"],
            "evidence-requirements": {"functional": ["x"]},
        }
        with self.assertRaisesRegex(TBEError, "VALIDATOR_GAP|VALIDATOR_INVALID"):
            self.build(entries=entries)

    def test_constraint_demands_and_regulated_fallback_are_explicit(self):
        value = mission(constraint_tags=["regulated:healthcare"])
        demands = derive_demands(value, [PROJECT])
        self.assertTrue(any(d.capability == "compliance-validator" for d in demands))
        built = self.build(value)
        compliance = next(row for row in built.validators if row[0] == "compliance")
        self.assertTrue(compliance[1].startswith("AGENT:compliance-validator:"))
        self.assertTrue(compliance[2].startswith("AGENT:fallback-validator:"))

    def test_pese_handoff_binds_exact_manifest_to_mission_facts(self):
        built = self.build()
        with tempfile.TemporaryDirectory() as temporary:
            store = PESEStore(temporary)
            actor = "AGENT:orchestrator:123e4567-e89b-42d3-a456-426614174000"
            self.assertEqual(store.initialize(actor).code, "INITIALIZED")
            reference = team_manifest_relative_path(built)
            destination = Path(temporary) / reference
            destination.parent.mkdir(parents=True)
            destination.write_text(built.to_markdown(), encoding="utf-8", newline="\n")
            outcome = bind_manifest_to_pese(
                built, store, manifest_ref=reference, actor=actor
            )
            self.assertEqual(outcome.code, "UPDATED")
            state = store.load().data["envelope"]["state"]
            bound = state["mission_state"]["missions"][built.mission_id]
            self.assertEqual(bound["manifest_ref"], reference)
            self.assertEqual(bound["manifest_version"], built.version)
            self.assertIn(built.mission_id, state["extensions"]["org.asc.tbe"])
            self.assertNotIn("tbe", state["extensions"])
            self.assertIn("ASSIGNMENT:build", state["execution_state"]["assignments"])
            self.assertTrue(state["validation_state"]["gates"])
            self.assertEqual(store.validate(check_repository=False).code, "VALID")

    def test_same_member_dependency_is_assignment_level_and_binds_to_pese(self):
        value = mission(
            demands=[
                {
                    "id": "ASSIGNMENT:a",
                    "capability": "developer",
                    "paths": ["src/a.py"],
                },
                {
                    "id": "ASSIGNMENT:b",
                    "capability": "developer",
                    "paths": ["src/b.py"],
                    "depends_on": ["ASSIGNMENT:a"],
                },
            ]
        )
        built = self.build(value)
        self.assertEqual(
            built.dependencies,
            (DependencyEdge("ASSIGNMENT:a", "ASSIGNMENT:b", "INPUT"),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = PESEStore(temporary)
            actor = "AGENT:orchestrator:123e4567-e89b-42d3-a456-426614174000"
            store.initialize(actor)
            reference = team_manifest_relative_path(built)
            destination = Path(temporary) / reference
            destination.parent.mkdir(parents=True)
            destination.write_text(built.to_markdown(), encoding="utf-8", newline="\n")
            self.assertEqual(
                bind_manifest_to_pese(
                    built, store, manifest_ref=reference, actor=actor
                ).code,
                "UPDATED",
            )
            execution = store.load().data["envelope"]["state"]["execution_state"]
            self.assertEqual(
                execution["assignments"]["ASSIGNMENT:b"]["depends_on"], ["ASSIGNMENT:a"]
            )
            self.assertEqual(execution["next_task_candidates"], ["ASSIGNMENT:a"])

    def test_resource_conflicts_become_assignment_edges_and_sequential_phases(self):
        entries = registry()
        entries["developer"]["parallel-execution-rules"]["shared-resources"] = (
            "build-cache"
        )
        entries["developer-two"] = entry("developer-two", competencies=("python",))
        entries["developer-two"]["parallel-execution-rules"]["shared-resources"] = (
            "build-cache"
        )
        built = self.build(
            mission(
                demands=[
                    {
                        "id": "ASSIGNMENT:a",
                        "capability": "developer",
                        "paths": ["src/a.py"],
                    },
                    {
                        "id": "ASSIGNMENT:b",
                        "capability": "developer-two",
                        "paths": ["src/b.py"],
                    },
                ]
            ),
            entries,
        )
        self.assertIn(
            DependencyEdge("ASSIGNMENT:a", "ASSIGNMENT:b", "RESOURCE"),
            built.dependencies,
        )
        phase = dict(built.phases)
        source = next(
            item.owner_agent_id
            for item in built.ownership
            if item.assignment_id == "ASSIGNMENT:a"
        )
        target = next(
            item.owner_agent_id
            for item in built.ownership
            if item.assignment_id == "ASSIGNMENT:b"
        )
        self.assertLess(phase[source], phase[target])

    def test_required_leadership_is_materialized_as_real_members(self):
        entries = registry()
        entries["developer"]["parallel-execution-rules"]["resource-limits"] = "max: 1"
        demands = [
            {
                "id": f"ASSIGNMENT:{index}",
                "capability": "developer",
                "paths": [f"src/{index}.py"],
            }
            for index in range(6)
        ]
        built = self.build(mission(demands=demands), entries)
        leads = [member for member in built.members if member.role == "team-lead"]
        self.assertEqual(len(leads), 1)
        department_leads = [
            member for member in built.members if member.role == "department-lead"
        ]
        self.assertTrue(department_leads)
        route = dict(built.escalation_routes)[
            next(
                member.agent_id for member in built.members if member.role == "builder"
            )
        ]
        self.assertIn(leads[0].agent_id, route)
        self.assertTrue(all(endpoint != "TEAM-LEAD" for endpoint in route))
        for member_id, member_route in built.escalation_routes:
            self.assertEqual(member_route[0], member_id)
            self.assertEqual(len(member_route), len(set(member_route)))
            self.assertEqual(member_route[-2:], ("ORCHESTRATOR", "HUMAN-STAKEHOLDER"))
        team_route = dict(built.escalation_routes)[leads[0].agent_id]
        self.assertNotIn(leads[0].agent_id, team_route[1:])

    def test_schema_incompatible_reviewer_handoff_is_rejected(self):
        entries = registry()
        entries["reviewer"]["input-contracts"]["input-schema"]["EVIDENCE"] = {
            "required": ["NOT-PRODUCED"]
        }
        with self.assertRaisesRegex(TBEError, "CONTRACT_INCOMPATIBLE"):
            self.build(
                mission(
                    demands=[
                        *mission()["demands"],
                        {
                            "id": "ASSIGNMENT:review",
                            "capability": "reviewer",
                            "role": "reviewer",
                        },
                    ]
                ),
                entries,
            )

    def test_registry_artifact_ownership_is_recorded_and_checked(self):
        entries = registry()
        entries["developer"]["owned-artifacts"] = {
            "artifact-ownership": {"build-report": "shared-with-validator"}
        }
        value = mission(
            demands=[
                {
                    "id": "ASSIGNMENT:artifact",
                    "capability": "developer",
                    "paths": ["src/report.py"],
                    "artifact_class": "build-report",
                }
            ]
        )
        built = self.build(value, entries)
        self.assertEqual(built.ownership[0].ownership_class, "shared-with-validator")
        self.assertEqual(built.ownership[0].artifact_class, "build-report")
        with self.assertRaisesRegex(TBEError, "ARTIFACT_OWNERSHIP_INVALID"):
            validate_manifest(
                replace(
                    built,
                    ownership=(
                        replace(built.ownership[0], ownership_class="exclusive"),
                    ),
                ),
                registry=entries,
            )
        with self.assertRaisesRegex(TBEError, "ARTIFACT_OWNERSHIP_INVALID"):
            self.build(
                mission(demands=[{**value["demands"][0], "artifact_class": "unknown"}]),
                entries,
            )

    def test_manifest_validation_rejects_bad_graph_group_and_escalation_endpoints(self):
        built = self.build()
        invalid_edge = replace(
            built,
            dependencies=(
                DependencyEdge("ASSIGNMENT:missing", "ASSIGNMENT:build", "INPUT"),
            ),
        )
        with self.assertRaisesRegex(TBEError, "DEPENDENCY_INVALID"):
            validate_manifest(invalid_edge, registry=registry())
        invalid_group = replace(
            built, parallel_groups=(("PHASE-2", ("AGENT:missing",)),)
        )
        with self.assertRaisesRegex(TBEError, "PARALLEL_GROUP_INVALID"):
            validate_manifest(invalid_group, registry=registry())
        self.assertIn("Selection records", built.to_markdown())

    def test_pese_binding_schedules_review_and_validation_before_release(self):
        built = self.build()
        with tempfile.TemporaryDirectory() as temporary:
            store = PESEStore(temporary)
            actor = "AGENT:orchestrator:123e4567-e89b-42d3-a456-426614174000"
            store.initialize(actor)
            reference = team_manifest_relative_path(built)
            destination = Path(temporary) / reference
            destination.parent.mkdir(parents=True)
            destination.write_text(built.to_markdown(), encoding="utf-8", newline="\n")
            self.assertEqual(
                bind_manifest_to_pese(
                    built,
                    store,
                    manifest_ref=reference,
                    actor=actor,
                    registry=registry(),
                ).code,
                "UPDATED",
            )
            state = store.load().data["envelope"]["state"]
            assignments = state["execution_state"]["assignments"]
            self.assertEqual(
                assignments["ASSIGNMENT:review-build"]["depends_on"],
                ["ASSIGNMENT:build"],
            )
            self.assertEqual(
                assignments["ASSIGNMENT:validate-functional"]["depends_on"],
                ["ASSIGNMENT:review-build"],
            )
            self.assertEqual(
                state["execution_state"]["next_task_candidates"], ["ASSIGNMENT:build"]
            )
            gate = state["validation_state"]["gates"]["GATE:MISSION:42:functional"]
            self.assertEqual(gate["status"], "PENDING")
            self.assertEqual(
                gate["criteria_refs"], [f"{reference}#validation-gate-functional"]
            )


if __name__ == "__main__":
    unittest.main()
