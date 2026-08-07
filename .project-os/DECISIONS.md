# Decisions

### Decision
- Context: ACP, ACR, and TBE require persistent state but did not previously define the authoritative PESE contract.
- Choice: Ratify `docs/PESE_v1.0.md` as the single canonical PESE v1.0 source of truth.
- Reason: It supplies deterministic state, checkpoint, resume, locking, integrity, migration, and recovery rules while preserving ACP, ACR, and TBE ownership boundaries.
- Consequences: MISSION-007 implements this contract; it must not invent alternate state encodings or recovery semantics.
- Reversal path: A versioned constitutional amendment and PESE migration under its Version Manager rules.

### Decision
- Context: No runtime, package format, registry serialization, or test framework existed; ACP and ACR require machine-readable, deterministic contracts.
- Choice: Use Python 3.14 standard library, TOML configuration, JSON ACR entries, and `unittest`.
- Reason: Python is installed; these formats/runtime require no undeclared third-party dependency and preserve deterministic validation.
- Consequences: YAML registry support, network transport, cryptographic signing, and the TBE engine remain out of scope for M006.
- Reversal path: Add a versioned adapter or migration after a separately approved format/runtime decision.

### Decision
- Context: The ASC stack had no top-level orchestration runtime that evaluates full system state and produces a single deterministic scheduling decision per tick.
- Choice: Implement AWS v1.0 as a deterministic, stdlib-only scheduler that evaluates PESE, EEF, AGC, AHP, REC, RKM, VAL, CKS, and ETR state and produces one prioritized decision (HOLD, RECOVER, START_MISSION, DISPATCH, VALIDATE, COMPLETE_MISSION, MONITOR_HEALTH, IDLE) per tick.
- Reason: Operators needed a machine-verifiable way to run a single deterministic decision loop that covers the entire ASC system state; the existing runtimes (AGC, EEF, AEX, VAL, RKM, REC, ETR) each owned their domain but no single entity orchestrated across them.
- Consequences: AWS adds scheduler config and cycle records to existing PESE state without modifying any prior contract; the SCHEDULER_STATUS transition type passes PESE's legal-transition validation as an unknown kind (same pattern as AGC's AGENT_STATUS, RKM's RISK_STATUS, VAL's VALIDATION_GATE, REC's RECOVERY_STATUS, and ETR's TRANSPORT_STATUS); the org.asc.aws extension key is optional in PESE state-shape validation.
- Reversal path: Remove the org.asc.aws extension key and SCHEDULER_* events; revert aws.py, the seven scheduler-* CLI subcommands, the EVENT_TYPES registration, validate_docs.py, and README.md changes.

### Decision
- Context: The roadmap's final milestone required certifying that the whole ASC Orchestrator v2 stack ships as a single production release with one version and no external dependencies.
- Choice: Ratify `docs/REL_v1.0.md` as the canonical REL v1.0 contract and implement a deterministic, stdlib-only release verifier that bumps the project to `version = "1.0.0"` and checks nine release gates (version, package_name, no_dependencies, console_entry_point, src_layout, canonical_specs, runtime_modules, test_suites, release_spec).
- Reason: A production release needs a machine-verifiable, local-only check that the source tree and its packaged wheel both report the same identity, ship all sixteen canonical v1.0 specs, import all runtime modules, and carry the full test suite — without introducing any third-party dependency.
- Consequences: `release` exits 0 with `release=PASS` only when every gate passes and exits 2 otherwise; the release contract is checked at runtime (`python -m asc_orchestrator --root . release`) and after installation (the wheel's console script), and REL is the final milestone of the roadmap.
- Reversal path: Bump `PRODUCTION_VERSION` and pyproject.toml together, or remove the `release` subcommand and `docs/REL_v1.0.md`; this decision closes the roadmap at M020.

