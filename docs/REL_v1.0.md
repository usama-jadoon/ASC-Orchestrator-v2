# Production Release — REL v1.0

## 1. PURPOSE AND SCOPE

REL v1.0 is the canonical production-release contract for ASC Orchestrator v2. It certifies that the source tree ships the complete, deterministic, dependency-free runtime stack — ACP, ACR, PESE, TBE, MSS, EEF, CKS, AEX, AHP, VAL, RKM, AGC, REC, ETR, and AWS, all at v1.0 — packaged under the production version `1.0.0` with a validated `src/` wheel layout, an installed console entry point, no undeclared runtime dependencies, every canonical contract specification present, every runtime module importable, and the full per-contract unit and CLI test suite shipped.

Today no machine-verifiable gate certifies that a checkout is a complete, packageable, production-ready release. REL closes that gap with a deterministic, stdlib-only `release` command that reads only local files and reports one gate per release invariant, exiting 0 only when every gate passes.

**Boundary.** REL verifies release readiness of the source tree. It does not publish packages, upload artifacts, manage keys (CKS), encrypt transport (ETR), schedule work (AWS), operate PESE state, or execute any other runtime. Distribution artifacts are produced by the packaging toolchain; REL certifies that the source they are built from is production-release ready.

## 2. RELEASE CRITERIA

A source tree is production-release ready when all of the following hold:

1. **Production version.** `pyproject.toml` declares `[project].version == "1.0.0"`.
2. **Package identity.** `[project].name == "asc-orchestrator"`.
3. **Dependency-free runtime.** `[project].dependencies` is the empty list — the runtime is stdlib-only by contract.
4. **Console entry point.** `[project.scripts]` maps `asc-orchestrator` to `asc_orchestrator.cli:main`.
5. **`src/` layout.** `[tool.setuptools]` declares `package-dir = { "" = "src" }` and `packages.find.where == ["src"]`.
6. **Complete contracts.** All sixteen canonical v1.0 specifications exist under `docs/` — ACP, ACR, PESE, TBE, MSS, EEF, CKS, AEX, AHP, VAL, RKM, AGC, REC, ETR, AWS, and REL.
7. **Importable runtime.** Every runtime module — including `cli` and `release` — imports cleanly from the package.
8. **Complete test suite.** The per-contract unit and CLI test suites ship in `tests/`.
9. **Ratified release contract.** `docs/REL_v1.0.md` exists and carries its terminal marker.

All criteria are checked deterministically by the `release` command; a single failing criterion fails the release.

## 3. VERSIONING

ASC Orchestrator v2 uses a single canonical version, declared only in `pyproject.toml` `[project].version`.

- The production release is `1.0.0` (REL v1.0).
- Within the `1.0.x` series the runtime contracts are stable: no contract, state encoding, CLI command, event type, or exit-code semantic changes without a new canonical contract revision and a versioned migration.
- Pre-production builds historically used `0.1.x`; the M020 production release advances the line to `1.0.0` with no state migration because PESE state carries its own revision and extension keys.

## 4. RELEASE CONTRACT SCHEMA

The `release` command emits one machine-readable gate report. The canonical JSON shape of a passing report:

```json
{
  "format": "REL/v1.0",
  "version": "1.0.0",
  "release": "PASS",
  "gates": {
    "version": "PASS",
    "package_name": "PASS",
    "no_dependencies": "PASS",
    "console_entry_point": "PASS",
    "src_layout": "PASS",
    "canonical_specs": "PASS",
    "runtime_modules": "PASS",
    "test_suites": "PASS",
    "release_spec": "PASS"
  }
}
```

The gate vocabulary is fixed: `version`, `package_name`, `no_dependencies`, `console_entry_point`, `src_layout`, `canonical_specs`, `runtime_modules`, `test_suites`, and `release_spec`. A failing gate carries a human-readable detail string naming the missing or invalid invariant.

## 5. RELEASE VERIFICATION

`verify` reads only local files: `pyproject.toml`, `docs/`, `tests/`, and the `asc_orchestrator` package itself. It never reads the network, the environment, or the wall clock, so identical checkouts produce identical reports.

- `version`, `package_name`, `no_dependencies`, `console_entry_point`, and `src_layout` parse `pyproject.toml` with `tomllib` and compare each field against the REL v1.0 constants.
- `canonical_specs` asserts every one of the sixteen v1.0 contract files exists under `docs/`.
- `runtime_modules` imports every runtime module via `importlib`; a module that fails to import fails the gate with the import error.
- `test_suites` asserts every per-contract unit and CLI test module exists under `tests/`.
- `release_spec` asserts `docs/REL_v1.0.md` exists and contains the terminal marker.

No gate raises: every failure is encoded in the gate's `detail`. The report's `passed` flag is True only when all gates pass.

## 6. RELEASE GATES

The release gate is the composition of the deterministic static verification above with the executable quality gates the repository already documents:

1. `release` command report — `release=PASS` (this contract).
2. Full unit and CLI suite — `python -m unittest discover -s tests -t .` passes.
3. Static typing — `python -m mypy` passes.
4. Lint — `python -m ruff check src tests scripts` passes.
5. Formatting — `python -m ruff format --check src tests scripts` passes.
6. Documentation — `python scripts/validate_docs.py` passes (now also validating REL v1.0).
7. Distribution — a dependency-free wheel build produces `asc_orchestrator-1.0.0-py3-none-any.whl`, installs cleanly, and the `asc-orchestrator` console entry point runs.

## 7. CLI REFERENCE

### `release`

Verifies production-release readiness of the source tree.

```text
asc-orchestrator [--root <repo-root>] release
```

Behavior:

1. Resolves the repository root from `--root` (default current directory).
2. Runs the deterministic `verify` report over that root.
3. Prints `release=PASS` (or `FAIL`) followed by `version=1.0.0` and one `gate.<name>=PASS|FAIL` line per gate; failing gates additionally print `gate.<name>.detail=<reason>`.
4. Exits 0 when every gate passes, 2 otherwise.

Example:

```text
release=PASS
version=1.0.0
gate.version=PASS
gate.package_name=PASS
gate.no_dependencies=PASS
gate.console_entry_point=PASS
gate.src_layout=PASS
gate.canonical_specs=PASS
gate.runtime_modules=PASS
gate.test_suites=PASS
gate.release_spec=PASS
```

## 8. ERROR HANDLING

- A missing or malformed `pyproject.toml` fails the packaging gates with `PROJECT_METADATA_MISSING` / `PROJECT_METADATA_INVALID` details.
- A missing contract spec, test module, or runtime module fails the corresponding gate with the missing name.
- An unimportable runtime module fails `runtime_modules` with the import error text.
- The `release` command returns exit code 2 whenever `report.passed` is False; it never raises for a non-ready tree.
- Invalid `--root` (a directory without `asc-orchestrator.toml`) raises `ConfigurationError` like every other command and exits 2.

## 9. DISTRIBUTION

The production distribution is a dependency-free wheel `asc_orchestrator-1.0.0-py3-none-any.whl` built from the `src/` layout, plus the corresponding source distribution. Installation registers the `asc-orchestrator` console entry point (`asc_orchestrator.cli:main`) and the `python -m asc_orchestrator` module entry point. No third-party runtime dependency is declared or installed; the runtime is stdlib-only by contract and by verification.

## 10. COMPATIBILITY

- REL v1.0 is backward compatible with all fifteen prior v1.0 contracts: it verifies their presence and shipping state without modifying them.
- The `release` command is read-only; it never mutates PESE state, the audit journal, keys, health journals, artifacts, or the event journal.
- PESE state created before M020 validates unchanged; version advancement to `1.0.0` does not alter any state encoding or extension key.

## 11. IMPLEMENTATION REQUIREMENTS

1. The verifier is stdlib-only: `tomllib` for `pyproject.toml`, `importlib` for module importability, and `dataclasses` for the report.
2. Every check is deterministic and encoded as a gate; no exception escapes `verify`.
3. `ReleaseReport.passed` is the logical AND of all gates; `failed_gates` enumerates the failures in declaration order.
4. The canonical constants (`PRODUCTION_VERSION = "1.0.0"`, the sixteen `CANONICAL_SPECS`, `RUNTIME_MODULES`, and `TEST_MODULES`) are the single source of truth for the release vocabulary.
5. The `release` CLI command prints machine-readable `key=value` lines and returns exit code 0 (ready) or 2 (not ready).

## 12. IMPLEMENTATION GATES

M020 is complete when:

1. `src/asc_orchestrator/release.py` implements `verify`, `render`, `ReleaseGate`, `ReleaseReport`, and the nine fixed gates.
2. `release` is registered and dispatched in `src/asc_orchestrator/cli.py` with exit code 0 on `release=PASS` and 2 on `release=FAIL`.
3. `pyproject.toml` declares version `1.0.0` with a dependency-free `asc-orchestrator` console entry point and the `src/` layout.
4. `tests/test_release.py` covers the passing tree and tampered-tree FAIL paths.
5. `scripts/validate_docs.py` validates this specification (required headings, JSON example, terminal marker, `release` command documentation).
6. All release gates in section 6 pass: full suite, MyPy, Ruff check+format, documentation validation, `release=PASS`, and the `1.0.0` wheel build/install smoke.

**END OF SPECIFICATION**
