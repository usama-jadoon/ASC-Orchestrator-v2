# ASC Orchestrator v2 — Developer Guide

This guide explains how to set up a development environment, run the
verification gates, build the package, and extend the runtime with a new
contract or module. It assumes a checkout of
`D:\Usama Data\All Software\ASC-Orchestrator-v2` (or any clone of the
repository).

---

## 1. Prerequisites

- **Python 3.11 or later.** The runtime is standard-library only, but the
  toolchain (mypy, ruff, build) is installed separately. The verified
  development stack is Python 3.14; CI runs 3.11, 3.12, and 3.13.
- **Git.**
- Optional, for the release gate and CI parity:
  `python -m pip install mypy ruff build` — these are development-only
  tools, never runtime dependencies.

Verify the base toolchain:

```powershell
python --version                 # 3.11+
python -m mypy --version
python -m ruff --version
python -m build --version
```

---

## 2. Repository layout

```text
asc-orchestrator.toml       canonical local runtime configuration
pyproject.toml              packaging metadata (version, entry point, tool config)
src/asc_orchestrator/       22 runtime modules (see ARCHITECTURE.md module map)
tests/                      unittest suites: test_<contract>.py + test_<contract>_cli.py
docs/                       16 canonical v1.0 contract specifications (ACP..REL)
scripts/validate_docs.py    documentation invariant checker
.project-os/                runtime state (git-ignored: KEYS/, PESE/, AUDIT/)
.github/                    CI workflow and community files
CHANGELOG.md, RELEASE_NOTES.md, ARCHITECTURE.md, DEVELOPER_GUIDE.md
```

Runtime state is generated, never committed: `.project-os/KEYS/`,
`.project-os/PESE/`, and `.project-os/AUDIT/` are excluded by `.gitignore`.

---

## 3. Running tests

The project uses the standard-library `unittest` framework. There are no
pytest dependencies.

```powershell
# Full suite (verbose)
python -m unittest discover -s tests -t . -v

# Full suite (summary)
python -m unittest discover -s tests -t .
```

> Note: `pytest` will also run the suite (the CI workflow uses it), but
> `unittest` is the canonical runner.

Run one suite:

```powershell
python -m unittest tests.test_pese -v
python -m unittest tests.test_aws tests.test_aws_cli -v
```

The release gate requires the per-contract suites named in
`asc_orchestrator/release.py::TEST_MODULES` (e.g. `test_execution`,
`test_execution_cli`, ..., `test_release`) to exist.

---

## 4. Type checking (mypy)

```powershell
python -m mypy src
```

`[tool.mypy]` in `pyproject.toml` configures `python_version = "3.11"`,
`files = ["src"]`, `check_untyped_defs = true`,
`warn_redundant_casts = true`, and `warn_unused_ignores = true`. The
expected result is `Success: no issues found in 22 source files`.

---

## 5. Linting and formatting (ruff)

```powershell
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m ruff format src tests scripts     # apply formatting
```

Ruff targets Python 3.11 and selects rules `E`, `F`, and `I`
(imports are sorted by the formatter).

---

## 6. Documentation validation

The canonical contract specifications in `docs/` are validated for
required headings, terminal markers, JSON examples, and that the README
documents every CLI command:

```powershell
python scripts/validate_docs.py
```

A passing run prints `documentation=PASS` and exits 0. **If you add a new
CLI command or contract, update `README.md` and `validate_docs.py`
accordingly** — the checker asserts that every registered command name
appears in the README and that each contract spec has its required
sections.

---

## 7. Building packages

Build the wheel and sdist with the `build` frontend:

```powershell
python -m pip install build      # development tool only
python -m build
```

The wheel is dependency-free by contract (`dependencies = []`), uses the
`src/` layout, and exposes the `asc-orchestrator` console entry point.
Inspect the artifact:

```powershell
python -m pip install dist/asc_orchestrator-1.0.2-py3-none-any.whl
asc-orchestrator --root <checkout> release
```

The `release` command verifies the source tree against the nine REL gates
and exits 0 only when every gate passes.

---

## 8. Contributing guidelines

1. Fork the repository and create a feature branch.
2. Keep changes deterministic and stdlib-only — no new runtime
   dependencies.
3. Add a `test_<area>.py` (and `test_<area>_cli.py` when you add CLI
   commands) to `tests/`.
4. Run every gate before submitting:
   ```powershell
   python -m unittest discover -s tests -t .
   python -m mypy src
   python -m ruff check src tests scripts
   python -m ruff format --check src tests scripts
   python scripts/validate_docs.py
   python -m asc_orchestrator --root . release
   ```
5. Update the contract specification in `docs/` if you change a contract,
   and update `README.md` for any new CLI command.
6. Open a pull request. CI runs lint, type-check, tests on 3.11/3.12/3.13,
   docs validation, and the release gate.

See `.github/CONTRIBUTING.md` for the contribution process and
`.github/PULL_REQUEST_TEMPLATE` for the PR template.

---

## 9. Code structure overview

Each contract runtime follows the same pattern:

- A module in `src/asc_orchestrator/` owning one engine class
  (e.g. `RiskEngine`, `AgentLifecycle`, `EncryptedTransport`).
- All mutations call `PESEStore.update(actor, kind, subject, mutate)` with
  a contract-specific transition kind (`RISK_STATUS`, `AGENT_STATUS`,
  `TRANSPORT_STATUS`, `SCHEDULER_STATUS`, `VALIDATION_GATE`, ...) — kinds
  not in PESE's legal map are enforced by the owning engine.
- Every mutation appends a namespaced event to the EEF event journal
  (`GATE_*`, `RISK_*`, `AGENT_*`, `RECOVERY_*`, `ETR_*`, `SCHEDULER_*`).
- A CLI section in `cli.py` registers `argparse` subcommands, resolves the
  actor, calls the engine, prints machine-readable key=value outcomes, and
  returns deterministic exit codes (0 success, 2 precondition/integrity
  failure).

Key engine classes and their entry points are tabulated in
[ARCHITECTURE.md](./ARCHITECTURE.md), section 2.

---

## 10. Adding a new contract/module

To add a new contract (say `XYZ v1.0`) to the runtime:

1. **Ratify the specification.** Add `docs/XYZ_v1.0.md` with the required
   headings, a JSON example, the terminal marker
   `**END OF SPECIFICATION`, and the CLI reference. Register the required
   headings and JSON-example checks in `scripts/validate_docs.py`.

2. **Create the runtime module.** Add `src/asc_orchestrator/xyz.py` with:
   - a deterministic, stdlib-only engine class,
   - an error type `XYZError(RuntimeError)` carrying `code` and `detail`,
   - mutations routed through `PESEStore.update()` with a dedicated
     transition kind, and
   - namespaced `XYZ_*` events appended to the EEF event journal
     (`asc_orchestrator.execution.EEFEventJournal`).

3. **Add tests.** Create `tests/test_xyz.py` and `tests/test_xyz_cli.py`,
   covering the lifecycle, error paths (exit 2), and journal chain
   verification. Add both names to `TEST_MODULES` in
   `src/asc_orchestrator/release.py`.

4. **Wire the CLI.** Register the `xyz-*` subcommands in
   `cli.py::_parser`, dispatch to the engine in `main`, and document every
   command in `README.md` (the docs validator enforces this).

5. **Register the extension key (if the contract owns PESE state).**
   Persist contract state under a reverse-DNS key in the PESE `extensions`
   mapping (e.g. `org.asc.xyz`), mirroring `org.asc.eef`, `org.asc.rkm`,
   and `org.asc.aws`. The owning engine validates its own extension schema.

6. **Update release metadata.** Add the spec to `CANONICAL_SPECS` and the
   module to `RUNTIME_MODULES` in `asc_orchestrator/release.py`, then bump
   the milestone docs and `CHANGELOG.md`.

7. **Run all gates** (section 8) and confirm `release=PASS` with all nine
   gates green.

> The order of contracts in `CANONICAL_SPECS` is the ratification order;
> keep new specs appended after `REL_v1.0.md`.
