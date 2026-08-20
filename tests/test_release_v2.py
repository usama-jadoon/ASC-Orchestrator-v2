"""Tests for Universal ASC v2 release verifier."""

from __future__ import annotations

import unittest
from pathlib import Path

from asc.release_v2 import (
    CONSOLE_ENTRY_POINT,
    CONSOLE_SCRIPT,
    LEGACY_ENTRY_POINT,
    LEGACY_SCRIPT,
    PRODUCTION_VERSION,
    REQUIRED_DEPENDENCY,
    verify,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestReleaseV2Constants(unittest.TestCase):
    def test_release_v2_constants(self) -> None:
        self.assertEqual(PRODUCTION_VERSION, "2.0.0")
        self.assertEqual(CONSOLE_SCRIPT, "asc")
        self.assertEqual(CONSOLE_ENTRY_POINT, "asc.cli:main")
        self.assertEqual(LEGACY_SCRIPT, "asc-orchestrator")
        self.assertEqual(LEGACY_ENTRY_POINT, "asc_orchestrator.cli:main")
        self.assertEqual(REQUIRED_DEPENDENCY, "pyyaml")


class TestVerifyRealRepo(unittest.TestCase):
    def test_release_v2_passes_on_real_repo(self) -> None:
        report = verify(REPO_ROOT)
        self.assertTrue(
            report.passed,
            f"Expected PASS but got {[g.name for g in report.failed_gates()]}",
        )
        self.assertEqual(report.version, PRODUCTION_VERSION)
        for gate in report.gates:
            self.assertTrue(gate.passed, f"Gate {gate.name} failed: {gate.detail}")


if __name__ == "__main__":
    unittest.main()
