"""Universal ASC v2.3.0 - Production Release Verifier.

Certifies that the Universal ASC v2 repository/package satisfies production release gates.
"""

from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

PRODUCTION_VERSION = "2.3.0"
PROJECT_NAME = "asc-orchestrator"
CONSOLE_ENTRY_POINT = "asc.cli:main"

RUNTIME_MODULES = (
    "asc.models",
    "asc.spec",
    "asc.dag",
    "asc.state",
    "asc.verifier",
    "asc.repo",
    "asc.driver",
    "asc.cli",
    "asc.events",
    "asc.lock",
    "asc.console",
    "asc.adapters.base",
    "asc.adapters.mock",
    "asc.adapters.shell",
    "asc.adapters.omp",
)


class ReleaseError(ValueError):
    """Raised when the release verification inputs are structurally invalid."""


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    """An individual gate evaluated by the release verifier."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    """Aggregate verdict produced by the release verifier."""

    version: str
    gates: Sequence[ReleaseGate]

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def passed_count(self) -> int:
        return sum(1 for g in self.gates if g.passed)

    def failed_gates(self) -> Sequence[ReleaseGate]:
        return tuple(g for g in self.gates if not g.passed)


class ReleaseVerifier:
    """Verifies that the codebase satisfies release requirements for v2.3.0."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (
            repo_root if repo_root is not None else Path(__file__).resolve().parents[2]
        )

    def verify_version(self) -> ReleaseGate:
        """Gate 1: Version declaration is canonical 2.3.0 across pyproject.toml."""
        pyproject_path = self.repo_root / "pyproject.toml"
        if not pyproject_path.exists():
            return ReleaseGate(
                name="version",
                passed=False,
                detail="pyproject.toml not found",
            )
        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            version = data.get("project", {}).get("version")
            if version == PRODUCTION_VERSION:
                return ReleaseGate(
                    name="version",
                    passed=True,
                    detail=f"pyproject.toml version {version} == {PRODUCTION_VERSION}",
                )
            return ReleaseGate(
                name="version",
                passed=False,
                detail=f"pyproject.toml version {version!r} != {PRODUCTION_VERSION!r}",
            )
        except Exception as exc:
            return ReleaseGate(name="version", passed=False, detail=str(exc))

    def verify_package_entry_points(self) -> ReleaseGate:
        """Gate 2: Verify asc console script entry point exists in pyproject.toml."""
        pyproject_path = self.repo_root / "pyproject.toml"
        if not pyproject_path.exists():
            return ReleaseGate(
                name="entry_points",
                passed=False,
                detail="pyproject.toml not found",
            )
        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            scripts = data.get("project", {}).get("scripts", {})
            asc_script = scripts.get("asc")
            if asc_script == CONSOLE_ENTRY_POINT:
                return ReleaseGate(
                    name="entry_points",
                    passed=True,
                    detail=f"scripts.asc == {CONSOLE_ENTRY_POINT}",
                )
            return ReleaseGate(
                name="entry_points",
                passed=False,
                detail=f"scripts.asc is {asc_script!r}, expected {CONSOLE_ENTRY_POINT!r}",
            )
        except Exception as exc:
            return ReleaseGate(name="entry_points", passed=False, detail=str(exc))

    def verify_runtime_modules(
        self, modules: Iterable[str] = RUNTIME_MODULES
    ) -> ReleaseGate:
        """Gate 3: All runtime modules import cleanly without circular dependencies."""
        failed: list[str] = []
        for mod in modules:
            try:
                importlib.import_module(mod)
            except Exception as exc:
                failed.append(f"{mod}: {exc}")
        if not failed:
            return ReleaseGate(
                name="runtime_modules",
                passed=True,
                detail=f"All {len(list(modules))} runtime modules imported successfully",
            )
        return ReleaseGate(
            name="runtime_modules",
            passed=False,
            detail=f"Failed importing: {'; '.join(failed)}",
        )

    def run_all_gates(self) -> ReleaseReport:
        """Run all release verification gates and produce comprehensive report."""
        gates = [
            self.verify_version(),
            self.verify_package_entry_points(),
            self.verify_runtime_modules(),
        ]
        return ReleaseReport(version=PRODUCTION_VERSION, gates=gates)


def verify(repo_root: Path | None = None) -> ReleaseReport:
    """Run all release gates."""
    verifier = ReleaseVerifier(repo_root)
    return verifier.run_all_gates()


def render(report: ReleaseReport) -> Iterator[str]:
    """Render release report lines."""
    yield f"release={'PASS' if report.passed else 'FAIL'}"
    yield f"version={report.version}"
    for g in report.gates:
        yield f"gate.{g.name}={'PASS' if g.passed else 'FAIL'}"
