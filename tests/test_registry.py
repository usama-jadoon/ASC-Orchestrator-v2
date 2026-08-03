"""Tests for the ACR v1.0 registry foundation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from asc_orchestrator.registry import (  # noqa: E402
    DuplicateAgentIdError,
    RegistryLoadError,
    RegistryValidationError,
    load_project_registry,
    load_registry,
    validate_entry,
)


ROOT = Path(__file__).resolve().parents[1]


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = load_project_registry(ROOT)

    def test_current_canonical_entries_load_in_filename_order(self) -> None:
        self.assertEqual(list(self.entries), ["investigator", "security-auditor"])
        self.assertEqual(self.entries["investigator"]["version"], "1.2.0")
        self.assertEqual(self.entries["security-auditor"]["version"], "2.1.0")

    def test_each_seeded_entry_has_every_mandatory_section(self) -> None:
        for entry in self.entries.values():
            validate_entry(entry)

    def test_rejects_mismatched_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "wrong-name.json"
            path.write_text(json.dumps(self.entries["investigator"]), encoding="utf-8")
            with self.assertRaisesRegex(RegistryValidationError, "must match filename"):
                load_registry(path.parent)

    def test_rejects_invalid_identity_and_ownership(self) -> None:
        invalid = json.loads(json.dumps(self.entries["investigator"]))
        invalid["agent-id"] = "Not-valid"
        with self.assertRaisesRegex(RegistryValidationError, "kebab-case"):
            validate_entry(invalid)

        invalid = json.loads(json.dumps(self.entries["investigator"]))
        invalid["owned-artifacts"]["artifact-ownership"]["investigation-report"] = "unowned"
        with self.assertRaisesRegex(RegistryValidationError, "shared-with"):
            validate_entry(invalid)

    def test_requires_complete_and_exact_artifact_metadata(self) -> None:
        invalid = json.loads(json.dumps(self.entries["investigator"]))
        del invalid["owned-artifacts"]["artifact-retention"]["language-statistics"]
        with self.assertRaisesRegex(RegistryValidationError, "missing metadata.*language-statistics"):
            validate_entry(invalid)

        invalid = json.loads(json.dumps(self.entries["investigator"]))
        invalid["owned-artifacts"]["artifact-locations"]["undeclared-artifact"] = "tmp/"
        with self.assertRaisesRegex(RegistryValidationError, "undeclared artifact type.*undeclared-artifact"):
            validate_entry(invalid)

    def test_rejects_malformed_json_and_missing_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "investigator.json").write_text("{ not json", encoding="utf-8")
            with self.assertRaises(RegistryLoadError):
                load_registry(directory)
        with self.assertRaises(RegistryLoadError):
            load_registry(ROOT / "not-a-registry")

    def test_rejects_duplicate_ids_before_filename_correspondence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            duplicate = json.loads(json.dumps(self.entries["investigator"]))
            (directory / "investigator.json").write_text(json.dumps(duplicate), encoding="utf-8")
            (directory / "investigator1.json").write_text(json.dumps(duplicate), encoding="utf-8")
            with self.assertRaises(DuplicateAgentIdError):
                load_registry(directory)


if __name__ == "__main__":
    unittest.main()
