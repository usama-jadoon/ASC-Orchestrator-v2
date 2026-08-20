"""Universal ASC v2.0 release verifier."""

from __future__ import annotations

import importlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PRODUCTION_VERSION = "2.0.0"
PROJECT_NAME = "asc-orchestrator"
CONSOLE_SCRIPT = "asc"
CONSOLE_ENTRY_POINT = "asc.cli:main"
LEGACY_SCRIPT = "asc-orchestrator"
LEGACY_ENTRY_POINT = "asc_orchestrator.cli:main"
REQUIRED_DEPENDENCY = "pyyaml"
RUNTIME_MODULES = (
    "asc",
    "asc.cli",
    "asc.dag",
    "asc.driver",
    "asc.models",
    "asc.repo",
    "asc.spec",
    "asc.state",
    "asc.verifier",
    "asc.adapters.base",
    "asc.adapters.mock",
    "asc.adapters.shell",
)
REQUIRED_TEST_SUITES = ("test_universal_asc.py", "test_validation.py")


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    version: str
    gates: tuple[ReleaseGate, ...]

    @property
    def passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    def failed_gates(self) -> tuple[ReleaseGate, ...]:
        return tuple(gate for gate in self.gates if not gate.passed)


def _read_pyproject(repository_root: Path) -> dict:
    with (repository_root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _project(data: dict) -> dict:
    value = data.get("project")
    if not isinstance(value, dict):
        return {}
    return value


def _gate_version(repository_root: Path) -> ReleaseGate:
    version = _project(_read_pyproject(repository_root)).get("version")
    if version == PRODUCTION_VERSION:
        return ReleaseGate("version", True, PRODUCTION_VERSION)
    return ReleaseGate(
        "version", False, f"expected {PRODUCTION_VERSION}, found {version!r}"
    )


def _dependency_name(requirement: str) -> str:
    match = re.match(r"^[A-Za-z0-9_.-]+", requirement.strip())
    return match.group(0).lower() if match else ""


def _gate_dependencies(repository_root: Path) -> ReleaseGate:
    dependencies = _project(_read_pyproject(repository_root)).get("dependencies")
    if not isinstance(dependencies, list):
        return ReleaseGate("dependencies", False, "project.dependencies missing")

    names = {_dependency_name(str(dep)) for dep in dependencies}
    if REQUIRED_DEPENDENCY in names:
        return ReleaseGate("dependencies", True, f"{REQUIRED_DEPENDENCY} present")

    return ReleaseGate(
        "dependencies",
        False,
        f"expected {REQUIRED_DEPENDENCY} in dependencies {dependencies!r}",
    )


def _gate_entry_points(repository_root: Path) -> ReleaseGate:
    scripts = _project(_read_pyproject(repository_root)).get("scripts")
    if not isinstance(scripts, dict):
        return ReleaseGate("entry_points", False, "project.scripts missing")

    asc_target = scripts.get(CONSOLE_SCRIPT)
    legacy_target = scripts.get(LEGACY_SCRIPT)

    if asc_target != CONSOLE_ENTRY_POINT:
        return ReleaseGate(
            "entry_points",
            False,
            f"expected {CONSOLE_SCRIPT} -> {CONSOLE_ENTRY_POINT}, found {asc_target!r}",
        )
    if legacy_target != LEGACY_ENTRY_POINT:
        return ReleaseGate(
            "entry_points",
            False,
            f"expected {LEGACY_SCRIPT} -> {LEGACY_ENTRY_POINT}, found {legacy_target!r}",
        )

    return ReleaseGate(
        "entry_points",
        True,
        f"{CONSOLE_SCRIPT} and {LEGACY_SCRIPT} scripts configured",
    )


def _gate_runtime_modules() -> ReleaseGate:
    missing: list[str] = []
    for module in RUNTIME_MODULES:
        try:
            importlib.import_module(module)
        except ImportError as error:
            missing.append(f"{module} ({error})")
    if missing:
        return ReleaseGate("runtime_modules", False, "; ".join(missing))
    return ReleaseGate(
        "runtime_modules", True, f"{len(RUNTIME_MODULES)} modules import"
    )


def _gate_tests_present(repository_root: Path) -> ReleaseGate:
    tests_dir = repository_root / "tests"
    missing = [
        name for name in REQUIRED_TEST_SUITES if not (tests_dir / name).is_file()
    ]
    if missing:
        return ReleaseGate("test_suites", False, f"missing {', '.join(missing)}")
    return ReleaseGate("test_suites", True, "Universal ASC tests present")


def verify(repository_root: str | Path = ".") -> ReleaseReport:
    root = Path(repository_root).resolve()
    gates = (
        _gate_version(root),
        _gate_dependencies(root),
        _gate_entry_points(root),
        _gate_runtime_modules(),
        _gate_tests_present(root),
    )
    return ReleaseReport(version=PRODUCTION_VERSION, gates=gates)


def render(report: ReleaseReport) -> Iterable[str]:
    lines = [
        f"release={'PASS' if report.passed else 'FAIL'}",
        f"version={report.version}",
    ]
    for gate in report.gates:
        lines.append(f"gate.{gate.name}={'PASS' if gate.passed else 'FAIL'}")
        if not gate.passed and gate.detail:
            lines.append(f"gate.{gate.name}.detail={gate.detail}")
    return lines
