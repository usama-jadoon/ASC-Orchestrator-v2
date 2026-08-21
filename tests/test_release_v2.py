"""Unit tests for Universal ASC v2 Release Verifier."""

from __future__ import annotations

import unittest
from pathlib import Path

from asc.release import (
    CONSOLE_ENTRY_POINT,
    PRODUCTION_VERSION,
    PROJECT_NAME,
    RUNTIME_MODULES,
    ReleaseGate,
    ReleaseReport,
    render,
    verify,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestReleaseV2Constants(unittest.TestCase):
    """Verify the fixed constants for v2 release."""

    def test_production_version(self) -> None:
        self.assertEqual(PRODUCTION_VERSION, "2.2.0")

    def test_project_name(self) -> None:
        self.assertEqual(PROJECT_NAME, "asc-orchestrator")

    def test_entry_point(self) -> None:
        self.assertEqual(CONSOLE_ENTRY_POINT, "asc.cli:main")

    def test_runtime_modules_count(self) -> None:
        self.assertEqual(len(RUNTIME_MODULES), 15)


class TestReleaseV2Dataclass(unittest.TestCase):
    """Verify ReleaseGate and ReleaseReport behavior."""

    def test_gate_frozen(self) -> None:
        gate = ReleaseGate("test", True, "ok")
        with self.assertRaises(AttributeError):
            gate.name = "changed"  # type: ignore[misc]

    def test_report_all_pass(self) -> None:
        report = ReleaseReport(
            version="2.2.0",
            gates=(ReleaseGate("a", True), ReleaseGate("b", True)),
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.passed_count, 2)
        self.assertEqual(report.failed_gates(), ())


class TestReleaseV2Verify(unittest.TestCase):
    """Verify that verify() passes against the real v2 repository."""

    def test_real_repo_passes(self) -> None:
        report = verify(REPO_ROOT)
        self.assertTrue(
            report.passed,
            f"Expected PASS but got {[g.name for g in report.failed_gates()]}",
        )
        self.assertEqual(report.version, "2.2.0")

    def test_render_format(self) -> None:
        report = verify(REPO_ROOT)
        lines = list(render(report))
        self.assertEqual(lines[0], "release=PASS")
        self.assertEqual(lines[1], "version=2.2.0")
        self.assertIn("gate.version=PASS", lines)


if __name__ == "__main__":
    unittest.main()
