"""Production Release (REL) v1.0.

A deterministic, stdlib-only release verifier that certifies that the ASC
Orchestrator v2 source tree is production-release ready.  REL v1.0 verifies
the packaging metadata declared in ``pyproject.toml`` (production version
``1.0.1``, dependency-free wheel contract, console entry point, ``src``
layout), the presence of every canonical v1.0 contract specification, the
importability of every runtime module, and the presence of the per-contract
unit and CLI test suites.

The verifier is fully deterministic: it reads only local files and never
touches the network, the environment, or the wall clock.  Every check
produces one ``ReleaseGate``; ``verify`` aggregates them into an immutable
``ReleaseReport`` whose ``passed`` flag is True only when every gate passes.
"""

from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PRODUCTION_VERSION = "1.0.1"

PROJECT_NAME = "asc-orchestrator"
CONSOLE_ENTRY_POINT = "asc_orchestrator.cli:main"

# The 16 canonical v1.0 contracts shipped by the production release, in the
# order they were ratified.  REL v1.0 itself is the release contract.
CANONICAL_SPECS = (
    "ACP_v1.0.md",
    "ACR_v1.0.md",
    "PESE_v1.0.md",
    "TBE_v1.0.md",
    "MSS_v1.0.md",
    "EEF_v1.0.md",
    "CKS_v1.0.md",
    "AEX_v1.0.md",
    "AHP_v1.0.md",
    "VAL_v1.0.md",
    "RKM_v1.0.md",
    "AGC_v1.0.md",
    "REC_v1.0.md",
    "ETR_v1.0.md",
    "AWS_v1.0.md",
    "REL_v1.0.md",
)

# Every runtime module the production distribution must ship and import.
RUNTIME_MODULES = (
    "asc_orchestrator.acp",
    "asc_orchestrator.audit",
    "asc_orchestrator.registry",
    "asc_orchestrator.config",
    "asc_orchestrator.pese",
    "asc_orchestrator.tbe",
    "asc_orchestrator.mss",
    "asc_orchestrator.execution",
    "asc_orchestrator.keys",
    "asc_orchestrator.aex",
    "asc_orchestrator.health",
    "asc_orchestrator.validation",
    "asc_orchestrator.risk",
    "asc_orchestrator.agent",
    "asc_orchestrator.recovery",
    "asc_orchestrator.etr",
    "asc_orchestrator.aws",
    "asc_orchestrator.release",
    "asc_orchestrator.cli",
)

# The per-contract unit and CLI test suites the release gate must ship.
TEST_MODULES = (
    "test_config",
    "test_acp",
    "test_registry",
    "test_pese",
    "test_pese_cli",
    "test_tbe",
    "test_tbe_cli",
    "test_mss",
    "test_mss_cli",
    "test_execution",
    "test_execution_cli",
    "test_keys",
    "test_keys_cli",
    "test_aex",
    "test_aex_cli",
    "test_health",
    "test_health_cli",
    "test_validation",
    "test_validation_cli",
    "test_risk",
    "test_risk_cli",
    "test_agent",
    "test_agent_cli",
    "test_recovery",
    "test_recovery_cli",
    "test_etr",
    "test_etr_cli",
    "test_aws",
    "test_aws_cli",
    "test_release",
)

TERMINAL_MARKER = "**END OF SPECIFICATION"


class ReleaseError(ValueError):
    """Raised when a release verification precondition is invalid."""


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    """One deterministic release-verification check."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    """Immutable aggregate of the release-verification gates."""

    version: str
    gates: tuple[ReleaseGate, ...]

    @property
    def passed(self) -> bool:
        """True only when every gate passes."""
        return all(gate.passed for gate in self.gates)

    @property
    def passed_count(self) -> int:
        """Number of passing gates."""
        return sum(1 for gate in self.gates if gate.passed)

    def failed_gates(self) -> tuple[ReleaseGate, ...]:
        """The gates that did not pass, in declaration order."""
        return tuple(gate for gate in self.gates if not gate.passed)


def _read_pyproject(repository_root: Path) -> dict:
    """Load pyproject.toml as a mapping; raise ReleaseError when absent."""
    path = repository_root / "pyproject.toml"
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        raise ReleaseError(f"PROJECT_METADATA_MISSING: {path}") from None
    except tomllib.TOMLDecodeError as error:
        raise ReleaseError(f"PROJECT_METADATA_INVALID: {error}") from None
    return data


def _project(data: dict) -> dict:
    value = data.get("project")
    if not isinstance(value, dict):
        raise ReleaseError("PROJECT_METADATA_MISSING: [project] table")
    return value


def _gate_version(repository_root: Path) -> ReleaseGate:
    try:
        project = _project(_read_pyproject(repository_root))
        version = project.get("version")
        if version == PRODUCTION_VERSION:
            return ReleaseGate("version", True, PRODUCTION_VERSION)
        return ReleaseGate(
            "version", False, f"expected {PRODUCTION_VERSION}, found {version!r}"
        )
    except ReleaseError as error:
        return ReleaseGate("version", False, str(error))


def _gate_package_name(repository_root: Path) -> ReleaseGate:
    try:
        project = _project(_read_pyproject(repository_root))
        name = project.get("name")
        if name == PROJECT_NAME:
            return ReleaseGate("package_name", True, PROJECT_NAME)
        return ReleaseGate(
            "package_name", False, f"expected {PROJECT_NAME}, found {name!r}"
        )
    except ReleaseError as error:
        return ReleaseGate("package_name", False, str(error))


def _gate_no_dependencies(repository_root: Path) -> ReleaseGate:
    try:
        project = _project(_read_pyproject(repository_root))
        dependencies = project.get("dependencies")
        if dependencies == []:
            return ReleaseGate("no_dependencies", True, "dependency-free")
        return ReleaseGate(
            "no_dependencies", False, f"unexpected dependencies {dependencies!r}"
        )
    except ReleaseError as error:
        return ReleaseGate("no_dependencies", False, str(error))


def _gate_console_entry_point(repository_root: Path) -> ReleaseGate:
    try:
        data = _read_pyproject(repository_root)
        scripts = data.get("project", {}).get("scripts")
        if not isinstance(scripts, dict):
            return ReleaseGate(
                "console_entry_point", False, "[project.scripts] table missing"
            )
        target = scripts.get(PROJECT_NAME)
        if target == CONSOLE_ENTRY_POINT:
            return ReleaseGate(
                "console_entry_point", True, f"{PROJECT_NAME} -> {CONSOLE_ENTRY_POINT}"
            )
        return ReleaseGate(
            "console_entry_point",
            False,
            f"expected {CONSOLE_ENTRY_POINT}, found {target!r}",
        )
    except ReleaseError as error:
        return ReleaseGate("console_entry_point", False, str(error))


def _gate_src_layout(repository_root: Path) -> ReleaseGate:
    try:
        data = _read_pyproject(repository_root)
        setuptools = data.get("tool", {}).get("setuptools")
        if not isinstance(setuptools, dict):
            return ReleaseGate("src_layout", False, "[tool.setuptools] table missing")
        package_dir = setuptools.get("package-dir")
        where = setuptools.get("packages", {}).get("find", {}).get("where")
        if package_dir == {"": "src"} and where == ["src"]:
            return ReleaseGate("src_layout", True, "src/ package layout")
        return ReleaseGate(
            "src_layout", False, f"package-dir={package_dir!r}, find.where={where!r}"
        )
    except ReleaseError as error:
        return ReleaseGate("src_layout", False, str(error))


def _gate_canonical_specs(repository_root: Path) -> ReleaseGate:
    docs = repository_root / "docs"
    missing = [name for name in CANONICAL_SPECS if not (docs / name).is_file()]
    if missing:
        return ReleaseGate("canonical_specs", False, f"missing {', '.join(missing)}")
    return ReleaseGate(
        "canonical_specs", True, f"{len(CANONICAL_SPECS)} v1.0 contracts"
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


def _gate_test_suites(repository_root: Path) -> ReleaseGate:
    tests = repository_root / "tests"
    missing = [name for name in TEST_MODULES if not (tests / f"{name}.py").is_file()]
    if missing:
        return ReleaseGate("test_suites", False, f"missing {', '.join(missing)}")
    return ReleaseGate("test_suites", True, f"{len(TEST_MODULES)} suites present")


def _gate_release_spec(repository_root: Path) -> ReleaseGate:
    spec = repository_root / "docs" / "REL_v1.0.md"
    try:
        text = spec.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ReleaseGate("release_spec", False, "docs/REL_v1.0.md missing")
    if TERMINAL_MARKER not in text:
        return ReleaseGate("release_spec", False, "terminal marker absent")
    return ReleaseGate("release_spec", True, "docs/REL_v1.0.md ratified")


def verify(repository_root: str | Path = ".") -> ReleaseReport:
    """Deterministically verify production-release readiness of a source tree.

    Reads only local files.  Every check is encoded as a ``ReleaseGate`` and
    the report's ``passed`` flag is True only when all gates pass.  No gate
    raises; failures are reported in ``detail``.
    """
    root = Path(repository_root).resolve()
    gates: tuple[ReleaseGate, ...] = (
        _gate_version(root),
        _gate_package_name(root),
        _gate_no_dependencies(root),
        _gate_console_entry_point(root),
        _gate_src_layout(root),
        _gate_canonical_specs(root),
        _gate_runtime_modules(),
        _gate_test_suites(root),
        _gate_release_spec(root),
    )
    return ReleaseReport(version=PRODUCTION_VERSION, gates=gates)


def render(report: ReleaseReport) -> Iterable[str]:
    """Render a ReleaseReport as machine-readable key=value lines."""
    lines = [f"release={'PASS' if report.passed else 'FAIL'}"]
    lines.append(f"version={report.version}")
    for gate in report.gates:
        lines.append(f"gate.{gate.name}={'PASS' if gate.passed else 'FAIL'}")
        if not gate.passed and gate.detail:
            lines.append(f"gate.{gate.name}.detail={gate.detail}")
    return lines
