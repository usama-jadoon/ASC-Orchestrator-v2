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
- Context:
- Choice:
- Reason:
- Consequences:
- Reversal path:

