"""Comprehensive tests for the MSS v1.0 mission-intake runtime."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asc_orchestrator.mss import (  # noqa: E402
    AUTHORITY_SCOPE_VOCABULARY,
    BASELINE_GATES,
    MISSION_CLASSES,
    MISSION_TYPES,
    MSS_SCHEMA,
    MSS_VERSION,
    PRIORITIES,
    VALIDATION_GATES,
    MissionSpec,
    MSSError,
    load_mission_spec,
    validate_mission_file,
    validate_mission_spec,
)
from asc_orchestrator.tbe import MissionContract, derive_demands  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC_DOC = ROOT / "docs" / "MSS_v1.0.md"

PROJECT = {
    "type": "python-package",
    "root": "app",
    "languages": ["python"],
    "frameworks": [],
    "platform": "linux",
    "test_surface": "unittest",
}


def _entry(
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


def _registry():
    return {
        "developer": _entry("developer", competencies=("python", "implementation")),
        "reviewer": _entry(
            "reviewer",
            competencies=("python", "review"),
            writable=(),
            outputs=("REVIEW",),
            inputs=("EVIDENCE",),
        ),
        "qa-validator": _entry(
            "qa-validator",
            competencies=("python",),
            writable=(),
            outputs=("VALIDATION",),
            inputs=("EVIDENCE",),
            gates=("functional",),
        ),
    }


def _mission(**change):
    """Return a fully valid MSS mission-intake dict (overridable)."""
    value: dict = {
        "schema": "MSS",
        "version": "1.0",
        "mission_id": "MISSION:42",
        "mission_type": "enhancement",
        "mission_class": "bounded",
        "priority": "MEDIUM",
        "objective": "Add a deterministic capability.",
        "acceptance_criteria": [
            {
                "id": "AC-1",
                "description": "Works deterministically.",
                "evidence_ref": "tests/",
                "gate": "GATE:qa",
            }
        ],
        "constraints": [{"kind": "stack", "value": "Python 3.11"}],
        "constraint_tags": [],
        "value_streams": ["developer-tooling"],
        "boundaries": [],
        "stakeholders": ["product-strategist"],
        "validation_gates": ["GATE:qa", "GATE:release"],
        "authority_scope": [
            "Repository State: read/write within owned paths",
            "Mission State: update own mission facts",
        ],
        "created_at": "2026-08-04T00:00:00.000Z",
        "created_by": "AGENT:orchestrator:local",
        "source": "tests/test_mss.py",
        "extensions": {},
    }
    value.update(change)
    return value


def _spec_examples():
    text = SPEC_DOC.read_text(encoding="utf-8")
    documents = re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
    return [json.loads(document) for document in documents]


class MSSVocabularyTests(unittest.TestCase):
    """Guard the canonical enumerators against accidental mutation."""

    def test_vocabulary_sets_match_spec(self):
        self.assertEqual(MSS_SCHEMA, "MSS")
        self.assertEqual(MSS_VERSION, "1.0")
        self.assertEqual(len(MISSION_TYPES), 7)
        self.assertEqual(len(MISSION_CLASSES), 2)
        self.assertEqual(len(PRIORITIES), 4)
        self.assertEqual(len(VALIDATION_GATES), 5)
        self.assertEqual(len(AUTHORITY_SCOPE_VOCABULARY), 8)

    def test_baseline_gates_cover_all_mission_types(self):
        self.assertEqual(set(BASELINE_GATES.keys()), MISSION_TYPES)


class MSSParsingTests(unittest.TestCase):
    """Structural parsing from JSON objects into MissionSpec."""

    def test_parses_canonical_mission_dict(self):
        spec = MissionSpec.from_mapping(_mission())
        self.assertEqual(spec.schema, "MSS")
        self.assertEqual(spec.version, "1.0")
        self.assertEqual(spec.mission_id, "MISSION:42")
        self.assertEqual(spec.mission_type, "enhancement")
        self.assertEqual(spec.mission_class, "bounded")
        self.assertEqual(spec.priority, "MEDIUM")
        self.assertEqual(spec.objective, "Add a deterministic capability.")
        self.assertEqual(len(spec.acceptance_criteria), 1)
        self.assertEqual(len(spec.constraints), 1)
        self.assertEqual(spec.extensions, {})

    def test_spec_examples_all_parse(self):
        examples = _spec_examples()
        self.assertEqual(len(examples), 5)
        for example in examples:
            spec = MissionSpec.from_mapping(example)
            self.assertEqual(spec.schema, "MSS")
            self.assertEqual(spec.version, "1.0")

    def test_from_mapping_rejects_non_mapping(self):
        with self.assertRaises(MSSError):
            MissionSpec.from_mapping(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_from_mapping_rejects_missing_required_field(self):
        data = _mission()
        del data["objective"]
        with self.assertRaisesRegex(MSSError, "objective must be a non-empty string"):
            MissionSpec.from_mapping(data)

    def test_from_mapping_rejects_non_string_text_field(self):
        with self.assertRaisesRegex(MSSError, "mission_id"):
            MissionSpec.from_mapping(_mission(mission_id=42))

    def test_from_mapping_rejects_bad_acceptance_criteria_type(self):
        with self.assertRaisesRegex(MSSError, "acceptance_criteria must be a sequence"):
            MissionSpec.from_mapping(_mission(acceptance_criteria="bad"))

    def test_from_mapping_rejects_bad_constraints_element_type(self):
        with self.assertRaisesRegex(MSSError, "constraints must be a sequence"):
            MissionSpec.from_mapping(_mission(constraints=[123]))

    def test_from_mapping_rejects_non_list_constraint_tags(self):
        with self.assertRaisesRegex(MSSError, "constraint_tags must be a sequence"):
            MissionSpec.from_mapping(_mission(constraint_tags="bad"))

    def test_from_mapping_rejects_string_extensions(self):
        with self.assertRaisesRegex(MSSError, "extensions must be an object"):
            MissionSpec.from_mapping(_mission(extensions="bad"))

    def test_extensions_none_defaults_to_empty_mapping(self):
        data = _mission()
        del data["extensions"]
        spec = MissionSpec.from_mapping(data)
        self.assertEqual(len(spec.extensions), 0)


class MSSMappingInterfaceTests(unittest.TestCase):
    """MissionSpec as a Mapping[str, Any]."""

    def setUp(self):
        self.spec = MissionSpec.from_mapping(_mission())

    def test_length_matches_canonical_keys(self):
        self.assertEqual(len(self.spec), 19)

    def test_membership(self):
        self.assertIn("mission_id", self.spec)
        self.assertIn("extensions", self.spec)
        self.assertNotIn("project_class", self.spec)
        self.assertNotIn("id", self.spec)

    def test_getitem_returns_correct_values(self):
        self.assertEqual(self.spec["mission_id"], "MISSION:42")
        self.assertEqual(self.spec["mission_type"], "enhancement")
        self.assertEqual(self.spec["priority"], "MEDIUM")

    def test_getitem_raises_keyerror_for_unknown_key(self):
        with self.assertRaises(KeyError):
            self.spec["nonexistent"]
        with self.assertRaises(KeyError):
            self.spec["id"]

    def test_get_returns_default_for_unknown_key(self):
        self.assertEqual(self.spec.get("project_class", "small"), "small")
        self.assertEqual(self.spec.get("sequence", 1), 1)
        self.assertIsNone(self.spec.get("demands"))

    def test_iteration(self):
        keys = list(self.spec)
        self.assertEqual(len(keys), 19)
        self.assertIn("mission_id", keys)
        self.assertIn("extensions", keys)

    def test_round_trip_through_json(self):
        raw = json.dumps(self.spec.to_mapping())
        reparsed = MissionSpec.from_mapping(json.loads(raw))
        self.assertEqual(reparsed, self.spec)

    def test_to_mapping_is_json_serializable(self):
        mapping = self.spec.to_mapping()
        serialized = json.dumps(mapping)
        self.assertIsInstance(json.loads(serialized), dict)


class MSSSemanticValidationTests(unittest.TestCase):
    """validate_mission_spec: error-severity, warning-severity, and ok=True cases."""

    def test_all_spec_examples_validate_ok(self):
        examples = _spec_examples()
        for example in examples:
            spec = MissionSpec.from_mapping(example)
            result = validate_mission_spec(spec)
            self.assertTrue(
                result.ok, f"example {spec.mission_id} failed: {result.findings}"
            )
            self.assertFalse(
                any(f.severity == "error" for f in result.findings),
                f"example {spec.mission_id} has error findings: {result.findings}",
            )

    def test_schema_mismatch_is_error(self):
        spec = MissionSpec.from_mapping(_mission(schema="WRONG"))
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(any(f.code == "SCHEMA_MISMATCH" for f in result.findings))

    def test_unsupported_version_is_error(self):
        spec = MissionSpec.from_mapping(_mission(version="0.9"))
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(any(f.code == "VERSION_UNSUPPORTED" for f in result.findings))

    def test_unknown_mission_type_is_error(self):
        spec = MissionSpec.from_mapping(_mission(mission_type="nonsense"))
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(any(f.code == "MISSION_TYPE_UNKNOWN" for f in result.findings))

    def test_unknown_mission_class_is_error(self):
        spec = MissionSpec.from_mapping(_mission(mission_class="neither"))
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(any(f.code == "MISSION_CLASS_UNKNOWN" for f in result.findings))

    def test_unknown_priority_is_error(self):
        spec = MissionSpec.from_mapping(_mission(priority="BANANA"))
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(any(f.code == "PRIORITY_UNKNOWN" for f in result.findings))

    def test_invalid_mission_id_is_error(self):
        spec = MissionSpec.from_mapping(_mission(mission_id="bad-id"))
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(any(f.code == "MISSION_ID_INVALID" for f in result.findings))

    def test_invalid_created_at_is_error(self):
        spec = MissionSpec.from_mapping(_mission(created_at="not-a-date"))
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(any(f.code == "CREATED_AT_INVALID" for f in result.findings))

    def test_unknown_validation_gate_is_error(self):
        spec = MissionSpec.from_mapping(
            _mission(validation_gates=["GATE:qa", "GATE:bogus"])
        )
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(any(f.code == "GATE_UNKNOWN" for f in result.findings))

    def test_unknown_authority_scope_is_error(self):
        spec = MissionSpec.from_mapping(_mission(authority_scope=["Not a valid scope"]))
        result = validate_mission_spec(spec)
        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.code == "AUTHORITY_SCOPE_UNKNOWN" for f in result.findings)
        )

    def test_missing_baseline_gate_is_warning(self):
        spec = MissionSpec.from_mapping(
            _mission(mission_type="greenfield-project", validation_gates=["GATE:qa"])
        )
        result = validate_mission_spec(spec)
        self.assertTrue(result.ok)
        codes = [f.code for f in result.findings]
        self.assertIn("BASELINE_GATE_MISSING", codes)
        self.assertNotIn("GATE_UNKNOWN", codes)

    def test_empty_acceptance_criteria_is_warning(self):
        spec = MissionSpec.from_mapping(_mission(acceptance_criteria=[]))
        result = validate_mission_spec(spec)
        self.assertTrue(result.ok)
        codes = [f.code for f in result.findings]
        self.assertIn("NO_ACCEPTANCE_CRITERIA", codes)

    def test_incomplete_criterion_is_warning(self):
        spec = MissionSpec.from_mapping(
            _mission(acceptance_criteria=[{"incomplete": True}])
        )
        result = validate_mission_spec(spec)
        self.assertTrue(result.ok)
        self.assertTrue(
            any(f.code == "ACCEPTANCE_CRITERIA_INCOMPLETE" for f in result.findings)
        )

    def test_unknown_criterion_gate_is_warning(self):
        spec = MissionSpec.from_mapping(
            _mission(
                acceptance_criteria=[
                    {"id": "X", "description": "Y", "gate": "GATE:bogus"}
                ]
            )
        )
        result = validate_mission_spec(spec)
        self.assertTrue(result.ok)
        self.assertTrue(
            any(f.code == "CRITERION_GATE_UNKNOWN" for f in result.findings)
        )

    def test_incomplete_constraint_is_warning(self):
        spec = MissionSpec.from_mapping(_mission(constraints=[{"only_kind": "stack"}]))
        result = validate_mission_spec(spec)
        self.assertTrue(result.ok)
        self.assertTrue(
            any(f.code == "CONSTRAINTS_INCOMPLETE" for f in result.findings)
        )

    def test_invalid_extension_key_is_warning(self):
        spec = MissionSpec.from_mapping(_mission(extensions={"bad key!": 1}))
        result = validate_mission_spec(spec)
        self.assertTrue(result.ok)
        self.assertTrue(any(f.code == "EXTENSION_KEY_INVALID" for f in result.findings))

    def test_result_metadata_includes_severity_counts(self):
        spec = MissionSpec.from_mapping(_mission())
        result = validate_mission_spec(spec)
        self.assertIn("severity_counts", result.metadata)
        self.assertEqual(result.metadata["severity_counts"]["error"], 0)
        self.assertEqual(result.metadata["severity_counts"]["warning"], 0)

    def test_result_preserves_mission_identity(self):
        spec = MissionSpec.from_mapping(_mission())
        result = validate_mission_spec(spec)
        self.assertEqual(result.mission_id, "MISSION:42")
        self.assertEqual(result.mission_type, "enhancement")


class MSSFileLoadingTests(unittest.TestCase):
    """load_mission_spec and validate_mission_file file I/O."""

    def test_load_mission_spec_reads_json_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mission.json"
            path.write_text(json.dumps(_mission()), encoding="utf-8")
            spec = load_mission_spec(path)
            self.assertEqual(spec.mission_id, "MISSION:42")

    def test_load_mission_spec_rejects_invalid_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("not json {{", encoding="utf-8")
            with self.assertRaises(MSSError) as context:
                load_mission_spec(path)
            self.assertIn("LOAD_FAILED", str(context.exception))

    def test_load_mission_spec_rejects_non_object_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "list.json"
            path.write_text("[1,2,3]", encoding="utf-8")
            with self.assertRaisesRegex(MSSError, "INPUT_INVALID"):
                load_mission_spec(path)

    def test_load_mission_spec_rejects_missing_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with self.assertRaises(MSSError) as context:
                load_mission_spec(path)
            self.assertIn("LOAD_FAILED", str(context.exception))

    def test_validate_mission_file_ok(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mission.json"
            path.write_text(json.dumps(_mission()), encoding="utf-8")
            result = validate_mission_file(path)
            self.assertTrue(result.ok)
            self.assertEqual(result.mission_id, "MISSION:42")

    def test_validate_mission_file_semantic_fail(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mission.json"
            path.write_text(
                json.dumps(_mission(mission_type="unknown-type")),
                encoding="utf-8",
            )
            result = validate_mission_file(path)
            self.assertFalse(result.ok)
            self.assertTrue(
                any(f.code == "MISSION_TYPE_UNKNOWN" for f in result.findings)
            )


class MSSTBECompatibilityTests(unittest.TestCase):
    """Verify MissionSpec is consumed directly by TBE without adapter functions."""

    def test_mission_contract_from_mapping_accepts_mission_spec(self):
        spec = MissionSpec.from_mapping(_mission())
        contract = MissionContract.from_mapping(spec)
        self.assertEqual(contract.mission_id, "MISSION:42")
        self.assertEqual(contract.mission_type, "enhancement")
        self.assertEqual(contract.objective, "Add a deterministic capability.")
        self.assertEqual(len(tuple(contract.acceptance_criteria)), 1)
        self.assertEqual(tuple(contract.constraint_tags), ())
        self.assertEqual(contract.project_class, "small")
        self.assertEqual(contract.sequence, 1)
        self.assertEqual(contract.demands, ())

    def test_tbe_derive_demands_from_mission_spec_with_criteria_capabilities(self):
        criteria = [
            {
                "id": "AC-1",
                "description": "Works.",
                "capabilities": ["developer"],
                "project": "app",
                "mutable_paths": ["src/feature.py"],
                "validation_gates": ["functional"],
            }
        ]
        spec = MissionSpec.from_mapping(_mission(acceptance_criteria=criteria))
        demands = derive_demands(spec, [PROJECT])
        self.assertEqual(len(demands), 1)
        self.assertEqual(demands[0].capability, "developer")
        self.assertEqual(demands[0].demand_id, "CRITERION:001")
        self.assertIn("functional", demands[0].validation_gates)

    def test_build_team_accepts_mission_spec_as_mapping(self):
        from asc_orchestrator.tbe import build_team

        criteria = [
            {
                "id": "AC-1",
                "description": "Works.",
                "capabilities": ["developer"],
                "project": "app",
                "mutable_paths": ["src/feature.py"],
                "validation_gates": ["functional"],
            }
        ]
        spec = MissionSpec.from_mapping(_mission(acceptance_criteria=criteria))
        manifest = build_team(
            spec,
            [PROJECT],
            _registry(),
            assembled_at="2026-08-04T00:00:00.000Z",
        )
        self.assertEqual(manifest.team_id, "TEAM:MISSION:42:1")
        self.assertEqual(manifest.mission_id, "MISSION:42")
        agent_types = {m.agent_type for m in manifest.members}
        self.assertIn("developer", agent_types)
        self.assertIn("reviewer", agent_types)
        self.assertIn("qa-validator", agent_types)

    def test_spec_json_examples_validate_all_ok(self):
        for raw in _spec_examples():
            spec = MissionSpec.from_mapping(raw)
            result = validate_mission_spec(spec)
            self.assertTrue(result.ok, f"{raw['mission_id']}: {result.findings}")


if __name__ == "__main__":
    unittest.main()
