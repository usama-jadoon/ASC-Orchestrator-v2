# Specialist Handoffs

Record only distilled results and links to evidence. Do not paste private reasoning or huge logs.

## M006.5 — PESE v1.0 specification

- Canonical source: `docs/PESE_v1.0.md`.
- Compatibility: ACP audit remains logically separate; ACR remains the capability authority; TBE remains the team/recovery authority.
- Validation: JSON examples, required-topic coverage, and independent ACP/ACR/TBE compatibility review passed.
- Next: MISSION-007 implements PESE v1.0 without changing its state, checkpoint, resume, migration, locking, integrity, or recovery contracts.

## MISSION-007 - PESE Runtime v1.0

- Runtime: `src/asc_orchestrator/pese.py` implements the canonical `.project-os/PESE/` layout, immutable history, locks, audits, checkpoints, integrity checks, resume, recovery, and migrations.
- CLI: `state`, `resume`, `checkpoint`, and `validate-state` are wired through `src/asc_orchestrator/cli.py`.
- Validation: 44 unit tests, three repeated full-suite reliability runs, MyPy, Ruff, source compilation, documentation validation, Git lifecycle smoke tests, and independent QA/review passed.
- Boundary: PESE persists and validates facts; it does not implement mission, team-building, execution, or validation engines.

## M008 - Team Builder Engine Runtime v1.0

- Runtime: `src/asc_orchestrator/tbe.py` implements deterministic registry-only selection, capacity and leadership decisions, exclusive ownership, assignment-level INPUT/RESOURCE dependencies, review/validator selection, escalation routes, and canonical `TEAM.md` rendering.
- CLI: `team-build` accepts explicit mission and classification JSON, writes the canonical manifest, supports controlled timestamps, and optionally binds it to PESE.
- PESE integration: manifest binding persists builder, review, and validator assignments with their prerequisite chain; Review Matrix/Validator Assignment work is authorized from canonical TEAM.md and gate status blocks milestone completion.
- Validation: 66 unit tests, Ruff, MyPy, formatting, compilation, documentation validation, controlled manifest reproducibility, and independent QA/conformance review passed.
- Boundary: TBE assembles and persists deterministic team plans only. It does not execute agents, run autonomous workflows, or orchestrate LLMs.

## M009 - Mission Specification Standard v1.0

- Specification: `docs/MSS_v1.0.md` defines the canonical mission vocabulary, immutable intake schema, baseline capabilities, validation gates, authority scope, metadata, examples, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/mss.py` provides `MissionSpec` as a frozen `Mapping[str, Any]`, structural `MSSError` handling, semantic `MissionValidationResult` findings, canonical vocabularies, baseline-gate warnings, extension-key checks, and JSON file loading.
- CLI: `validate-mission --file <path>` validates MSS JSON relative to the configured repository root and emits findings plus deterministic PASS/FAIL exit status.
- TBE compatibility: `MissionSpec` is consumed directly by `MissionContract.from_mapping`, `derive_demands`, and `build_team`; no adapter function is required.
- Validation: 121 full-suite tests, MSS CLI smoke tests, documentation checks, MyPy, Ruff check/format, source compilation, and independent release audit passed. The audit fixed non-mapping input handling in `MissionSpec.from_mapping`.
- Boundary: MSS is intake and validation only. It does not plan, execute, orchestrate, schedule, transport, sign, or encrypt agent work.

## M010 - Execution Engine Foundation v1.0

- Specification: `docs/EEF_v1.0.md` defines the canonical execution-lifecycle contract: purpose/scope, architecture and boundary, session state machine, FIFO scheduler semantics, agent-owned transitions, checkpoint/recovery coordination, event-log schema, `org.asc.eef` extension shape, CLI reference, error handling, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/execution.py` implements immutable `ExecutionContext`, deterministic `ExecutionSession` (start, schedule, pause, resume, cancel, complete, status), `ScheduleResult`, `ExecutionStatus`, and the hash-chained `EEFEventJournal` at `.project-os/AUDIT/execution-events.jsonl`. All mutations flow through `PESEStore.update()`; resume uses the scoped `MISSION_INTERRUPT_RECOVERY` custom transition because the PESE legal map has no `INTERRUPTED → ACTIVE` edge.
- PESE/TBE integration: start fires `MISSION_START` and activates root assignments; cancel/complete fire `MISSION_FINISH`; dependency edges are consumed from the `org.asc.tbe` extension; session status persists under `org.asc.eef`.
- CLI: seven `execution-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes.
- Validation: full suite (existing PESE/TBE/MSS plus new EEF unit and CLI lifecycle suites), MyPy, Ruff check/format, compilation, documentation validation, and end-to-end lifecycle smoke tests passed; event-journal chain integrity and PESE checkpoint/validation checks verified.
- Boundary: EEF schedules and dispatches; it does not execute agents, run autonomous workflows, or orchestrate LLMs.

## M011 - Cryptographic Key Service v1.0

- Specification: `docs/CKS_v1.0.md` defines the canonical cryptographic key and audit-signing contract: architecture and boundary, key types and records, lifecycle (ACTIVE → ROTATED/REVOKED), signing and verification, signing ledger, on-disk layout, CLI reference, error handling, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/keys.py` implements the stdlib-only `KeyStore` over `.project-os/KEYS/{keys,status,signatures}/`. Key records are immutable (written once via atomic replace); status changes append to per-key JSONL journals; signatures append to a per-key hash-chained JSONL ledger with `previous_hash` linkage, fsync, and process-safe locking.
- Cryptography: HMAC-SHA256 signatures (`hmac.new(material_hex.encode(), payload, "sha256")`), SHA-256 fingerprints over the hex-encoded material, and constant-time verification via `hmac.compare_digest`. `key-validate` verifies record integrity, fingerprints, and ledger chains.
- CLI: seven `key-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes. Keys never read or mutate PESE, ACP, TBE, MSS, or EEF state.
- Validation: full 189-case suite, MyPy, Ruff check/format, compilation, documentation validation, and CLI key-lifecycle smoke tests passed; signing-ledger chain integrity and tamper detection verified.
- Boundary: CKS provides symmetric identity and audit signing only. It does not implement encrypted transport, asymmetric PKI, agent execution, or autonomous workflow scheduling.

## M012 - Agent Execution Engine v1.0

- Specification: `docs/AEX_v1.0.md` defines the canonical agent-execution contract: purpose/scope, architecture and boundary, assignment execution lifecycle, execution result record, artifact persistence, CKS attestation, EEF event integration, on-disk layout, CLI reference, error handling, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/aex.py` implements the stdlib-only `AEX` runtime over `.project-os/ARTIFACTS/`. It claims READY assignments (dispatch), completes IN_PROGRESS assignments with immutable result records plus copied artifacts, fails/block/unblocks, and reads status/results. Result records carry a canonical `entry_hash` and an optional CKS `signature`; artifact paths are validated against repository-root traversal.
- PESE/EEF integration: all transitions flow through `PESEStore.update()` with the legal ASSIGNMENT_STATUS map and actor authorization; each mutation emits an agent-owned EEF event (ASSIGNMENT_DISPATCHED, ASSIGNMENT_COMPLETED, ASSIGNMENT_FAILED, ASSIGNMENT_BLOCKED, ASSIGNMENT_ACTIVATED) to the hash-chained execution journal with the PESE revision and state hash.
- Windows compatibility: mission and assignment IDs are `%3A`-encoded in directory names (matching TBE's `team_manifest_relative_path`), so result.json and artifacts resolve on Windows filesystems.
- CLI: seven `aex-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes (`aex-complete`/`aex-result` print full record fields).
- Validation: full suite (existing PESE/TBE/MSS/EEF/CKS plus new AEX unit and CLI suites), MyPy, Ruff check/format, compilation, documentation validation, and CLI lifecycle smoke tests passed; execution-journal chain integrity and tamper detection verified; artifact + CKS signature round-trip verified.
- Boundary: AEX executes and attests local agent work. It does not schedule dispatch decisions (EEF), assemble teams (TBE), intake missions (MSS), persist general state (PESE), or manage cryptographic keys (CKS). Encrypted transport and autonomous workflow scheduling remain outside scope.

## M013 - Agent Health Protocol v1.0

- Specification: `docs/AHP_v1.0.md` defines the canonical agent-health contract: purpose/scope, architecture and boundary, heartbeat record schema, agent health model (ALIVE/STALLED/UNKNOWN), on-disk layout, integrity and validation, CLI reference, error handling, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/health.py` implements the stdlib-only `HealthStore` over `.project-os/HEALTH/agents/`. Each agent owns an append-only, hash-chained JSONL journal (`previous_heartbeat_sha256` → `heartbeat_sha256`) with process-safe locking, atomic writes, and fsync. `validate()` verifies JSON, hashes, chain linkage, and monotonic sequence. Query time is injectable for deterministic stall detection.
- Status model: ALIVE when last-heartbeat age ≤ timeout, STALLED when older, UNKNOWN when no heartbeat exists. Timeout is validated (`INVALID_TIMEOUT` for negative/non-numeric); agent ids are validated (`INVALID_AGENT`).
- PESE integration: `mission_agents` reads `assigned_agent_ids` from PESE state read-only; `health-report`/`health-check` degrade to an empty agent set for unknown missions. AHP never mutates PESE state.
- Windows compatibility: agent ids are `%3A`-encoded in journal filenames (matching TBE/AEX). The `_process_lock` from audit.py is reused for cross-process safety.
- CLI: four `health-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes (`health-check` exits 2 when any mission agent is STALLED).
- Validation: full 258-test suite, MyPy, Ruff check/format, compilation, documentation validation (now checking AHP), and CLI health-lifecycle smoke tests passed; heartbeat hash-chain validation and STALLED exit-2 path verified.
- Boundary: AHP observes and records agent liveness. It does not execute agent work (AEX), schedule dispatch decisions (EEF), assemble teams (TBE), intake missions (MSS), persist general state (PESE), or manage cryptographic keys (CKS). Heartbeats are independent of PESE state. Encrypted transport and autonomous workflow scheduling remain outside scope.

## M014 - Validation Engine v1.0

- Specification: `docs/VAL_v1.0.md` defines the canonical validation contract: purpose/scope, architecture and boundary, validation state and gates, artifact records, verification, invalidation, event journal, CLI reference, error handling, on-disk layout, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/validation.py` implements the stdlib-only `ValidationEngine` driving PESE validation gates through `PENDING → RUNNING → GREEN/RED/BLOCKED` and `GREEN → INVALIDATED`. `start`/`finish`/`invalidate` mutate exclusively through `PESEStore.update()` with transition type `VALIDATION_GATE`; `verify` compares bound artifact files against recorded SHA-256 hashes and reports per-artifact MATCH/MISMATCH/MISSING.
- Tamper policy: when tampered artifacts make PESE state unloadable (`STATE_CORRUPT`), mutations halt by design. `verify()` provides a raw-read fallback over `live.json` for per-artifact diagnostics; invalidation of tampered evidence is an operator recovery action, never a programmatic sweep. `invalidate()` enforces the binding-failure precondition per PESE spec section 5.3 and raises `BINDING_INTACT` when the binding is sound.
- EEF integration: the `EVENT_TYPES` frozenset in `src/asc_orchestrator/execution.py` is extended with GATE_STARTED, GATE_PASSED, GATE_FAILED, GATE_BLOCKED, and GATE_INVALIDATED; each verdict is appended to the hash-chained execution journal with the PESE revision and state hash. Event emission is best-effort.
- Actor resolution: mutation commands in the CLI fall back to the gate's `validator_agent_id`; read-only commands (`gates`, `report`, `verify`) skip resolution so they can diagnose corrupt state.
- CLI: six `validation-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes.
- Validation: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP plus new VAL unit and CLI suites), MyPy, Ruff check/format, compilation, documentation validation (now checking VAL), and CLI validation-lifecycle smoke tests passed; GATE_* event-journal chain integrity and tamper-detection halt path verified.
- Boundary: VAL drives gate verdicts and verifies artifacts. It does not execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), or schedule dispatch (EEF). Encrypted transport and autonomous workflow scheduling remain outside scope.

## M015 - Risk Management v1.0

- Specification: `docs/RKM_v1.0.md` defines the canonical risk-management contract: purpose/scope, architecture and boundary, risk record schema, hold mechanism (blocking evaluation), risk lifecycle, event journal, CLI reference, error handling, on-disk layout, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/risk.py` implements the stdlib-only `RiskEngine` over PESE `risk_state.risks`. All mutations flow through `PESEStore.update()` with transition type `RISK_STATUS` (RKM enforces its own state machine because `RISK_STATUS` is not in PESE's legal map — the same pattern as EEF's `MISSION_INTERRUPT_RECOVERY` and VAL's `VALIDATION_GATE`).
- Hold mechanism: `check()` evaluates per PESE section 4.7 — any HALT risk, any unresolved CRITICAL risk, or any HIGH risk with a declared block condition blocks autonomous execution. Block conditions persist under the reverse-DNS `extensions["org.asc.rkm"]` key; company-wide risks (`mission_id=None`) block all missions; mission-scoped checks include company-wide risks.
- EEF integration: the `EVENT_TYPES` frozenset in `src/asc_orchestrator/execution.py` is extended with RISK_OPENED, RISK_MITIGATED, RISK_ACCEPTED, RISK_RESOLVED, and RISK_HALTED; each transition is appended to the hash-chained execution journal with the PESE revision and state hash. Event emission is best-effort.
- CLI: nine `risk-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes; `risk-check` exits 2 when autonomous execution is blocked.
- Validation: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL plus new RKM unit and CLI suites), MyPy, Ruff check/format, compilation, documentation validation (now checking RKM), and CLI risk-lifecycle smoke tests passed; RISK_* event-journal chain integrity, hold-mechanism exit-2 paths, mission scoping, and backward compatibility verified.
- Boundary: RKM operates the risk ledger and hold mechanism. It does not execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), drive validation gates (VAL), or schedule dispatch (EEF). Encrypted transport and autonomous workflow scheduling remain outside scope.

