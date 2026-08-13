"""Unit tests for Production Release (REL) v1.0."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from asc_orchestrator.release import (
    CANONICAL_SPECS,
    CONSOLE_ENTRY_POINT,
    PRODUCTION_VERSION,
    PROJECT_NAME,
    RUNTIME_MODULES,
    TERMINAL_MARKER,
    TEST_MODULES,
    ReleaseError,
    ReleaseGate,
    ReleaseReport,
    render,
    verify,
)

# ---------------------------------------------------------------------------
# Root of the checked-out repository (two parents up from tests/test_release.py)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pyproject(
    root: Path,
    *,
    version: str = PRODUCTION_VERSION,
    name: str = PROJECT_NAME,
    dependencies: list[str] | None = None,
    entry_point: str = CONSOLE_ENTRY_POINT,
    package_dir: str = "src",
) -> None:
    """Write a minimal pyproject.toml to root."""
    root.mkdir(parents=True, exist_ok=True)
    deps = "[]" if dependencies is None else json.dumps(dependencies)
    content = f'''\
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "{name}"
version = "{version}"
dependencies = {deps}

[project.scripts]
asc-orchestrator = "{entry_point}"

[tool.setuptools]
package-dir = {{ "" = "{package_dir}" }}

[tool.setuptools.packages.find]
where = ["{package_dir}"]
'''
    (root / "pyproject.toml").write_text(content, encoding="utf-8")


def _write_pyproject_minimal(root: Path, content: str) -> None:
    """Write arbitrary pyproject.toml content."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(content, encoding="utf-8")


def _report_by_name(report: ReleaseReport) -> dict[str, ReleaseGate]:
    return {gate.name: gate for gate in report.gates}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReleaseConstants(unittest.TestCase):
    """Verify the fixed constants that define the release vocabulary."""

    def test_production_version(self) -> None:
        self.assertEqual(PRODUCTION_VERSION, "1.0.2")

    def test_project_name(self) -> None:
        self.assertEqual(PROJECT_NAME, "asc-orchestrator")

    def test_entry_point(self) -> None:
        self.assertEqual(CONSOLE_ENTRY_POINT, "asc_orchestrator.cli:main")

    def test_canonical_specs_count(self) -> None:
        self.assertEqual(len(CANONICAL_SPECS), 16)

    def test_runtime_modules_count(self) -> None:
        self.assertEqual(len(RUNTIME_MODULES), 19)

    def test_test_modules_count(self) -> None:
        self.assertEqual(len(TEST_MODULES), 30)

    def test_terminal_marker(self) -> None:
        self.assertTrue(TERMINAL_MARKER.startswith("**END"))


class TestReleaseDataclass(unittest.TestCase):
    """Verify ReleaseGate and ReleaseReport behavior."""

    def test_gate_frozen(self) -> None:
        gate = ReleaseGate("test", True, "ok")
        with self.assertRaises(AttributeError):
            gate.name = "changed"  # type: ignore[misc]

    def test_report_all_pass(self) -> None:
        report = ReleaseReport(
            version="1.0.0",
            gates=(ReleaseGate("a", True), ReleaseGate("b", True)),
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.passed_count, 2)
        self.assertEqual(report.failed_gates(), ())

    def test_report_one_fail(self) -> None:
        fail = ReleaseGate("x", False, "broken")
        report = ReleaseReport(version="1.0.0", gates=(fail,))
        self.assertFalse(report.passed)
        self.assertEqual(report.passed_count, 0)
        self.assertEqual(report.failed_gates(), (fail,))

    def test_report_mixed(self) -> None:
        gates = (
            ReleaseGate("a", True),
            ReleaseGate("b", False, "nope"),
            ReleaseGate("c", True),
        )
        report = ReleaseReport(version="1.0.0", gates=gates)
        self.assertFalse(report.passed)
        self.assertEqual(report.passed_count, 2)
        self.assertEqual(len(report.failed_gates()), 1)
        self.assertEqual(report.failed_gates()[0].name, "b")


class TestRender(unittest.TestCase):
    """Verify the machine-readable render format."""

    def test_pass_render(self) -> None:
        report = ReleaseReport(
            version="1.0.0",
            gates=(ReleaseGate("gate_a", True, "all good"),),
        )
        lines = list(render(report))
        self.assertEqual(lines[0], "release=PASS")
        self.assertEqual(lines[1], "version=1.0.0")
        self.assertIn("gate.gate_a=PASS", lines)

    def test_fail_render_includes_detail(self) -> None:
        report = ReleaseReport(
            version="1.0.0",
            gates=(ReleaseGate("gate_b", False, "missing X"),),
        )
        lines = list(render(report))
        self.assertEqual(lines[0], "release=FAIL")
        self.assertIn("gate.gate_b=FAIL", lines)
        self.assertIn("gate.gate_b.detail=missing X", lines)


class TestVerifyRealRepo(unittest.TestCase):
    """Run the verifier against the real checked-out repository."""

    def test_release_passes_on_real_repo(self) -> None:
        report = verify(REPO_ROOT)
        self.assertTrue(
            report.passed,
            f"Expected PASS but got {[g.name for g in report.failed_gates()]}",
        )
        self.assertEqual(report.version, PRODUCTION_VERSION)
        for gate in report.gates:
            self.assertTrue(gate.passed, f"Gate {gate.name} failed: {gate.detail}")


class TestVersionGate(unittest.TestCase):
    """Tamper the version in pyproject.toml."""

    def test_wrong_version(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_pyproject(root, version="0.1.0")
            # Provide minimum docs and tests so only version gate fails.
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            for spec in CANONICAL_SPECS:
                (root / "docs" / spec).write_text(
                    "text\n\n**END OF SPECIFICATION**", encoding="utf-8"
                )
            for mod in TEST_MODULES:
                (root / "tests" / f"{mod}.py").write_text("# test", encoding="utf-8")
            report = verify(root)
            by_name = _report_by_name(report)
            self.assertFalse(report.passed)
            self.assertFalse(by_name["version"].passed)
            self.assertIn(PRODUCTION_VERSION, by_name["version"].detail)


class TestPackageNameGate(unittest.TestCase):
    """Tamper the package name."""

    def test_wrong_name(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_pyproject(root, name="wrong-package")
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            for spec in CANONICAL_SPECS:
                (root / "docs" / spec).write_text(
                    "text\n\n**END OF SPECIFICATION**", encoding="utf-8"
                )
            for mod in TEST_MODULES:
                (root / "tests" / f"{mod}.py").write_text("# test", encoding="utf-8")
            report = verify(root)
            by_name = _report_by_name(report)
            self.assertFalse(by_name["package_name"].passed)
            self.assertEqual(PROJECT_NAME, PROJECT_NAME)  # const is correct


class TestNoDependenciesGate(unittest.TestCase):
    """Provide non-empty dependencies in pyproject.toml."""

    def test_has_dependency(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_pyproject(root, dependencies=["requests"])
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            for spec in CANONICAL_SPECS:
                (root / "docs" / spec).write_text(
                    "text\n\n**END OF SPECIFICATION**", encoding="utf-8"
                )
            for mod in TEST_MODULES:
                (root / "tests" / f"{mod}.py").write_text("# test", encoding="utf-8")
            report = verify(root)
            by_name = _report_by_name(report)
            self.assertFalse(by_name["no_dependencies"].passed)


class TestCanonicalSpecsGate(unittest.TestCase):
    """Remove a canonical spec from the docs/ directory."""

    def test_missing_spec(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_pyproject(root)
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            # Create all specs except the last one (REL_v1.0.md).
            for spec in CANONICAL_SPECS[:-1]:
                (root / "docs" / spec).write_text(
                    "text\n\n**END OF SPECIFICATION**", encoding="utf-8"
                )
            for mod in TEST_MODULES:
                (root / "tests" / f"{mod}.py").write_text("# test", encoding="utf-8")
            report = verify(root)
            by_name = _report_by_name(report)
            self.assertFalse(by_name["canonical_specs"].passed)
            self.assertIn("REL_v1.0.md", by_name["canonical_specs"].detail)


class TestTestSuitesGate(unittest.TestCase):
    """Remove a test module from tests/."""

    def test_missing_test(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_pyproject(root)
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            for spec in CANONICAL_SPECS:
                (root / "docs" / spec).write_text(
                    "text\n\n**END OF SPECIFICATION**", encoding="utf-8"
                )
            # Create all test modules except test_release.
            for mod in TEST_MODULES:
                if mod != "test_release":
                    (root / "tests" / f"{mod}.py").write_text(
                        "# test", encoding="utf-8"
                    )
            report = verify(root)
            by_name = _report_by_name(report)
            self.assertFalse(by_name["test_suites"].passed)
            self.assertIn("test_release", by_name["test_suites"].detail)


class TestReleaseSpecGate(unittest.TestCase):
    """REL_v1.0.md exists but is missing the terminal marker."""

    def test_missing_terminal_marker(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_pyproject(root)
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            for spec in CANONICAL_SPECS:
                if spec == "REL_v1.0.md":
                    (root / "docs" / spec).write_text(
                        "# Production Release\n\nNo terminal marker here.\n",
                        encoding="utf-8",
                    )
                else:
                    (root / "docs" / spec).write_text(
                        "text\n\n**END OF SPECIFICATION**", encoding="utf-8"
                    )
            for mod in TEST_MODULES:
                (root / "tests" / f"{mod}.py").write_text("# test", encoding="utf-8")
            report = verify(root)
            by_name = _report_by_name(report)
            self.assertFalse(by_name["release_spec"].passed)
            self.assertIn("terminal marker", by_name["release_spec"].detail)

    def test_spec_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_pyproject(root)
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            for spec in CANONICAL_SPECS:
                if spec == "REL_v1.0.md":
                    continue  # do not create
                (root / "docs" / spec).write_text(
                    "text\n\n**END OF SPECIFICATION**", encoding="utf-8"
                )
            for mod in TEST_MODULES:
                (root / "tests" / f"{mod}.py").write_text("# test", encoding="utf-8")
            report = verify(root)
            by_name = _report_by_name(report)
            self.assertFalse(by_name["release_spec"].passed)
            self.assertIn("REL_v1.0.md", by_name["release_spec"].detail)


class TestMissingPyprojectGate(unittest.TestCase):
    """pyproject.toml does not exist."""

    def test_missing_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "tests").mkdir()
            for spec in CANONICAL_SPECS:
                (root / "docs" / spec).write_text(
                    "text\n\n**END OF SPECIFICATION**", encoding="utf-8"
                )
            for mod in TEST_MODULES:
                (root / "tests" / f"{mod}.py").write_text("# test", encoding="utf-8")
            report = verify(root)
            by_name = _report_by_name(report)
            self.assertFalse(by_name["version"].passed)
            self.assertFalse(by_name["package_name"].passed)
            self.assertFalse(by_name["no_dependencies"].passed)
            self.assertFalse(by_name["console_entry_point"].passed)
            self.assertFalse(by_name["src_layout"].passed)


class TestReleaseError(unittest.TestCase):
    """ReleaseError inherits from ValueError."""

    def test_is_value_error(self) -> None:
        self.assertTrue(issubclass(ReleaseError, ValueError))


if __name__ == "__main__":
    unittest.main()
