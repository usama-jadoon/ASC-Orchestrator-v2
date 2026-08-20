"""Universal ASC v2.0.0 - Production Release Verifier.

Certifies that the Universal ASC v2 repository/package satisfies production release gates.
"""

from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

PRODUCTION_VERSION = "2.0.0"
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
    "asc.adapters.base",
    "asc.adapters.mock",
    "asc.adapters.shell",
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

    def failed_gates(self) -> tuple[ReleaseGate, ...]:
        return tuple(g for g in self.gates if not g.passed)


def verify(root_dir: str | Path) -> ReleaseReport:
    """Run all release verification gates against root_dir."""
    root = Path(root_dir).resolve()
    gates: list[ReleaseGate] = []

    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.exists():
        for name in (
            "version",
            "package_name",
            "dependencies",
            "console_entry_point",
            "src_layout",
        ):
            gates.append(ReleaseGate(name, False, "pyproject.toml does not exist"))
    else:
        try:
            with pyproject_path.open("rb") as fh:
                data = tomllib.load(fh)
        except Exception as exc:
            for name in (
                "version",
                "package_name",
                "dependencies",
                "console_entry_point",
                "src_layout",
            ):
                gates.append(
                    ReleaseGate(name, False, f"failed to parse pyproject.toml: {exc}")
                )
            data = {}

        if data:
            proj = data.get("project", {})

            # 1. Version gate
            ver = proj.get("version", "")
            gates.append(
                ReleaseGate(
                    "version",
                    ver == PRODUCTION_VERSION,
                    f"expected {PRODUCTION_VERSION}, got {ver}",
                )
            )

            # 2. Package name gate
            name = proj.get("name", "")
            gates.append(
                ReleaseGate(
                    "package_name",
                    name == PROJECT_NAME,
                    f"expected {PROJECT_NAME}, got {name}",
                )
            )

            # 3. Dependencies gate
            deps = proj.get("dependencies", [])
            has_pyyaml = any("pyyaml" in d.lower() for d in deps)
            gates.append(
                ReleaseGate(
                    "dependencies", has_pyyaml, f"dependencies declared: {deps}"
                )
            )

            # 4. Console entry point gate
            scripts = proj.get("scripts", {})
            ep = scripts.get("asc", "")
            gates.append(
                ReleaseGate(
                    "console_entry_point",
                    ep == CONSOLE_ENTRY_POINT,
                    f"expected {CONSOLE_ENTRY_POINT}, got {ep}",
                )
            )

            # 5. src-layout gate
            tool_st = data.get("tool", {}).get("setuptools", {})
            pkg_dir = tool_st.get("package-dir", {}).get("", "")
            gates.append(
                ReleaseGate(
                    "src_layout", pkg_dir == "src", f"expected src, got {pkg_dir}"
                )
            )

    # 6. Runtime modules importability gate
    import_failures = []
    for mod in RUNTIME_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            import_failures.append(f"{mod}: {exc}")
    gates.append(
        ReleaseGate(
            "runtime_modules", len(import_failures) == 0, ", ".join(import_failures)
        )
    )

    # 7. Universal test suite gate
    test_file = root / "tests" / "test_universal_asc.py"
    gates.append(
        ReleaseGate(
            "test_suite", test_file.exists(), f"test file present: {test_file.exists()}"
        )
    )

    return ReleaseReport(version=PRODUCTION_VERSION, gates=tuple(gates))


def render(report: ReleaseReport) -> Iterable[str]:
    """Yield lines of machine-readable release verdict report."""
    status_str = "PASS" if report.passed else "FAIL"
    yield f"release={status_str}"
    yield f"version={report.version}"
    for gate in report.gates:
        gate_status = "PASS" if gate.passed else "FAIL"
        yield f"gate.{gate.name}={gate_status}"
        if not gate.passed and gate.detail:
            yield f"gate.{gate.name}.detail={gate.detail}"
