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

## M016 - Agent Lifecycle Control v1.0

- Specification: `docs/AGC_v1.0.md` defines the canonical agent-lifecycle contract: purpose/scope, architecture and boundary, agent record schema, agent status vocabulary, agent lifecycle (legal transitions), event journal, CLI reference, error handling, on-disk layout, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/agent.py` implements the stdlib-only `AgentLifecycle` over PESE `agent_state.agents`. All mutations flow through `PESEStore.update()` with transition type `AGENT_STATUS` (AGC enforces its own state machine because `AGENT_STATUS` is not in PESE's legal map — the same pattern as RKM's `RISK_STATUS` and VAL's `VALIDATION_GATE`).
- Lifecycle: the deterministic state machine runs INITIALIZING → REGISTERED → READY → BUSY with BLOCKED/FAILED/QUARANTINED/REPLACED/RELEASED branches; `agent-ready` requires the 4-field dependency environment state to be `VERIFIED`; `agent-claim`/`agent-complete` bind and release mission/assignment; `agent-fail`/`agent-quarantine` record interruption state and trigger the PESE mandatory FAILURE checkpoint when an active mission exists.
- Authority: actor authority requires the orchestrator (`AGENT:orchestrator:local`) or the target agent itself, enforced at the engine level because PESE validates actor authority only for ASSIGNMENT_STATUS, MISSION_STATUS, and VALIDATION_GATE transitions.
- EEF integration: the `EVENT_TYPES` frozenset in `src/asc_orchestrator/execution.py` is extended with thirteen AGENT_* event types (AGENT_REGISTERED, AGENT_ACTIVATED, AGENT_READY, AGENT_BUSY, AGENT_BLOCKED, AGENT_UNBLOCKED, AGENT_FAILED, AGENT_QUARANTINED, AGENT_REPLACED, AGENT_RELEASED, AGENT_DEPENDENCY, AGENT_HEARTBEAT, AGENT_CHECKPOINTED); each mutation is appended to the hash-chained execution journal with the PESE revision and state hash. Event emission is best-effort.
- CLI: seventeen `agent-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes; precondition failures (e.g. ready without VERIFIED dependencies, activate from the wrong status) exit 2.
- Validation: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL/RKM plus new AGC unit and CLI suites), MyPy, Ruff check/format, compilation, documentation validation (now checking AGC), and CLI agent-lifecycle smoke tests passed; AGENT_* event-journal chain integrity, dependency-gated ready, authority checks, and backward compatibility verified.
- Boundary: AGC operates the agent lifecycle ledger. It does not execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), drive validation gates (VAL), operate the risk ledger (RKM), or schedule dispatch (EEF). Encrypted transport and autonomous workflow scheduling remain outside scope.

## M017 - Recovery Engine v1.0

- Specification: `docs/REC_v1.0.md` defines the canonical recovery contract: purpose/scope, architecture and boundary, recovery record schema, trigger model, recovery lifecycle (legal transitions), event journal, CLI reference, error handling, on-disk layout, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/recovery.py` implements the stdlib-only `RecoveryEngine` over PESE `recovery_state.recoveries`. All mutations flow through `PESEStore.update()` with transition type `RECOVERY_STATUS` (REC enforces its own state machine because `RECOVERY_STATUS` is not in PESE's legal map — the same pattern as RKM's `RISK_STATUS`, VAL's `VALIDATION_GATE`, and AGC's `AGENT_STATUS`). It consumes `AgentLifecycle` for recovery steps and `HealthStore` (read-only) for liveness.
- Trigger model: `diagnose` derives FAILED/QUARANTINED from AGC agent status, and STALLED when the AGC status is READY/BUSY/BLOCKED and AHP reports STALLED; RELEASED/REPLACED/INITIALIZING/REGISTERED and healthy agents are reported not recoverable with a reason. `run` raises `NOT_RECOVERABLE` when no trigger resolves.
- Recovery sequence: `run` orchestrates quarantine → release → register replacement → activate → dependency VERIFIED → ready → claim (claim skipped when `assignment_id` is absent, leaving the replacement READY); the replacement ID defaults to `{agent_id}:recovery:{N}` and copies the original agent's tool/environment dependencies. Each step is an individually-atomic PESE transition; any non-UPDATED step transitions the record to FAILED with the error detail (a mandatory FAILURE checkpoint fires only on that FAILED transition).
- EEF integration: the `EVENT_TYPES` frozenset in `src/asc_orchestrator/execution.py` is extended with RECOVERY_STARTED, RECOVERY_COMPLETED, and RECOVERY_FAILED; each transition is appended to the hash-chained execution journal with the PESE revision and state hash. Event emission is best-effort.
- CLI: five `recovery-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes; agent-not-found, not-recoverable, and step-failure paths exit 2 with `status=FAILED` and the error detail.
- Validation: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL/RKM/AGC plus new REC unit and CLI suites), MyPy, Ruff check/format, compilation, documentation validation (now checking REC), and CLI recovery-lifecycle smoke tests passed; RECOVERY_* event-journal chain integrity, FAILED/STALLED triggers, replacement provisioning, step-failure exit-2 paths, and backward compatibility verified.
- Boundary: REC orchestrates recovery by calling AGC lifecycle transitions and reading AHP liveness; it does not define new lifecycle states (AGC owns those), execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), drive validation gates (VAL), operate the risk ledger (RKM), or schedule dispatch (EEF). Encrypted transport and autonomous workflow scheduling remain outside scope.

## M018 - Encrypted Transport v1.0

- Specification: `docs/ETR_v1.0.md` defines the canonical encrypted-transport contract: architecture/boundary, channel and envelope schema, AEAD envelope format, lifecycle, CLI reference, error handling, and implementation gates.
- Runtime: `src/asc_orchestrator/etr.py` implements the stdlib-only `ETR` runtime using RFC 8439 ChaCha20-Poly1305 AEAD. Channels bind a named channel to a CKS key id; envelopes seal plaintext with a fresh per-envelope 96-bit nonce (chunk counter + random) plus the derived Poly1305 tag, and open verifies the tag before decrypting so tampering raises `AUTH_FAILED` before any plaintext is released.
- Key derivation: a seal key and an integrity key are derived from the CKS channel key material using HKDF-style SHA-256 expansion with channel-scoped info; the PESE mission binding is not required for channel use.
- EEF integration: the `EVENT_TYPES` frozenset in `src/asc_orchestrator/execution.py` is extended with ETR_CHANNEL_BOUND, ETR_CHANNEL_REVOKED, ETR_ENVELOPE_SEALED, and ETR_ENVELOPE_OPENED; each mutation is appended to the hash-chained execution journal with the PESE revision and state hash. Event emission is best-effort.
- CLI: eight `etr-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes; channel-not-found, AUTH_FAILED, and unknown-envelope paths exit 2.
- Validation: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL/RKM/AGC/REC plus new ETR unit and CLI suites), MyPy, Ruff check/format, compilation, documentation validation (now checking ETR), and CLI encrypted-transport smoke tests passed; ETR_* event-journal chain integrity, AUTH_FAILED tamper detection, channel revoke, and backward compatibility verified.
- Boundary: ETR encrypts transport envelopes only. It does not execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), drive validation gates (VAL), operate the risk ledger (RKM), operate the agent lifecycle (AGC), or recover agents (REC). Autonomous workflow scheduling and production-release verification remain outside scope.

## M019 - Autonomous Workflow Scheduler v1.0

- Specification: `docs/AWS_v1.0.md` defines the canonical autonomous-workflow-scheduler contract: purpose/scope, architecture and boundary, scheduler state and cycle schema, decision model, lifecycle, event journal, CLI reference, error handling, on-disk layout, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/aws.py` implements the stdlib-only `AWSScheduler` over PESE `scheduler_state` (config and cycles). All mutations flow through `PESEStore.update()` with transition type `SCHEDULER_STATUS` (AWS enforces its own state machine because `SCHEDULER_STATUS` is not in PESE's legal map — the same pattern as RKM's `RISK_STATUS`, VAL's `VALIDATION_GATE`, AGC's `AGENT_STATUS`, REC's `RECOVERY_STATUS`, and ETR's `TRANSPORT_STATUS`). The `org.asc.aws` extension key is optional in PESE state-shape validation.
- Decision model: one deterministic decision per tick with eight prioritized decision types (HOLD=100, RECOVER=90, START_MISSION=80, DISPATCH=70, VALIDATE=60, COMPLETE_MISSION=50, MONITOR_HEALTH=40, IDLE=0). `tick` consumes PESE, EEF, AGC, AHP, REC, RKM, VAL, CKS, and ETR state and returns the highest-priority decision; when enabled, actionable decisions are delegated to the owning runtime (REC for RECOVER, EEF for START_MISSION and COMPLETE_MISSION, AEX for DISPATCH, VAL for VALIDATE, AHP for MONITOR_HEALTH); when disabled, decisions are evaluated but not executed (`action_code=NONE`).
- EEF integration: the `EVENT_TYPES` frozenset in `src/asc_orchestrator/execution.py` is extended with SCHEDULER_TICK, SCHEDULER_ENABLED, and SCHEDULER_DISABLED; each tick and toggle is appended to the hash-chained execution journal with the PESE revision and state hash. Event emission is best-effort.
- CLI: seven `scheduler-*` commands wired through `src/asc_orchestrator/cli.py` with machine-readable outcomes and deterministic exit codes; cycle-not-found and missing-agent paths exit 2.
- Validation: full suite (573 tests, existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL/RKM/AGC/REC/ETR plus new AWS unit and CLI suites), MyPy, Ruff check/format, compilation, documentation validation (now checking AWS), decision-model coverage for all eight decision types (crafted + real fixtures), and CLI scheduler-lifecycle smoke tests passed; SCHEDULER_* event-journal chain integrity and backward compatibility verified.
- Boundary: AWS orchestrates by delegating decisions to the owning runtime; it does not execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), drive validation gates (VAL), operate the risk ledger (RKM), operate the agent lifecycle (AGC), recover agents (REC), or encrypt transport (ETR). Production-release verification remains outside scope.

## M020 - Production Release v1.0

- Specification: `docs/REL_v1.0.md` defines the canonical production-release contract: purpose/scope, release criteria, versioning, release contract schema, release verification, release gates, CLI reference, error handling, distribution, compatibility, and implementation gates.
- Runtime: `src/asc_orchestrator/release.py` implements the stdlib-only `ReleaseVerifier`. `verify()` reads only local files and checks nine deterministic release gates: version (pyproject.toml must be 1.0.0), package_name (asc-orchestrator), no_dependencies (dependency-free), console_entry_point (asc_orchestrator.cli:main), src_layout (packages under src/), canonical_specs (all sixteen v1.0 docs present), runtime_modules (all nineteen runtime modules importable), test_suites (all thirty test modules present), and release_spec (docs/REL_v1.0.md with the terminal marker). `render()` emits `release=PASS` plus one `gate.*=PASS` line per gate; `verify()` never raises — failures are encoded as FAIL gates with detail.
- Packaging: `pyproject.toml` is bumped to `version = "1.0.0"`; the wheel builds as `asc_orchestrator-1.0.0-py3-none-any.whl` with no third-party dependencies, installs cleanly, and its console script `asc-orchestrator --root . release` reports `release=PASS` exit 0 against the checked-out tree.
- CLI: the `release` subcommand wired through `src/asc_orchestrator/cli.py` returns 0 on PASS and 2 on FAIL, with `gate.*` detail lines for operators.
- Validation: full 596-test suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL/RKM/AGC/REC/ETR/AWS plus new REL unit tests), MyPy, Ruff check/format, compilation, documentation validation (now checking REL: 10 required headings, 1 JSON example, terminal marker), all nine release gates PASS, wheel build + install smoke, and installed console-script smoke passed.
- Boundary: REL verifies production-release readiness only; it does not execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), drive validation gates (VAL), operate the risk ledger (RKM), operate the agent lifecycle (AGC), recover agents (REC), encrypt transport (ETR), or schedule workflows (AWS). This is the final milestone of the roadmap.

