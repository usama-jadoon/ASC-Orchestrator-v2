# Project State

Status: M014_VAL_COMPLETE

## Product and users

ASC Orchestrator v2 provides deterministic, auditable assembly and operation of autonomous software-company agents.

## Verified stack

Python 3.14 standard-library runtime; `unittest` test framework; `tomllib` configuration; JSON registry entries; MyPy and Ruff verification gates.

## Architecture and canonical contracts

ACP v1.0 governs messages and audit records. ACR v1.0 governs registry entries under `.project-os/COMPANY/DEPARTMENTS/`. PESE v1.0 is the canonical persistent-state contract. TBE v1.0 is the canonical deterministic team-assembly contract integrated with those foundations. MSS v1.0 is the canonical mission-intake contract consumed directly by TBE. EEF v1.0 is the canonical execution-lifecycle contract driving PESE-bound missions through start, schedule, pause, resume, cancel, and complete. CKS v1.0 is the canonical cryptographic key and audit-signing contract providing deterministic HMAC-SHA256 key lifecycle, signing/verification, and a hash-chained signing ledger. AEX v1.0 is the canonical agent-execution contract that claims EEF-dispatched assignments, transitions them through their lifecycle, persists work-product artifacts, and signs execution attestations via CKS. AHP v1.0 is the canonical agent-health contract that records per-agent heartbeat histories and derives ALIVE, STALLED, and UNKNOWN liveness status for stalled-agent detection. VAL v1.0 is the canonical validation contract that drives PESE validation gates through their lifecycle, registers SHA-256-bound validation artifacts, and emits gate verdicts to the EEF execution journal.

## Verified completed capabilities

- Python package skeleton and CLI (`config`, `registry`, `acp` validation).
- ACP v1.0 fixed-header, ordered-payload, integrity, semantic, and UTF-8 validation.
- Local append-only, hash-chained ACP audit journal with process-safe local locking.
- ACR v1.0 deterministic JSON registry loader/validator and the investigator/security-auditor seed entries.
- TOML runtime configuration and source-compatible `unittest` suite.
- Canonical PESE v1.0 specification, including the state, checkpoint, locking, integrity, recovery, migration, and resume contracts required by MISSION-007.
- PESE v1.0 runtime with canonical state history, hash-chained access/transition audits, atomic writer and audit locks, checkpointing, integrity validation, deterministic resume, recovery, and migration records.
- PESE CLI commands: `state`, `resume`, `checkpoint`, and `validate-state`.
- TBE v1.0 runtime: deterministic registry-only specialist selection, capacity-aware membership, leadership materialization, exclusive ownership, assignment-level dependency/resource graphs, reviewer and validator interfaces, escalation routes, and canonical versioned `TEAM.md` manifests.
- TBE CLI command: `team-build`, including deterministic timestamp input and optional atomic PESE manifest binding.
- PESE/TBE compatibility: PESE authorizes canonical Review Matrix and Validator Assignment work, keeps milestones pending until relevant gates are GREEN, and persists TBE metadata under a reverse-DNS extension key.
- MSS v1.0 runtime: immutable `MissionSpec` Mapping contract, structural parsing, semantic validation findings, canonical vocabularies, baseline-gate recommendations, extension-key checks, file loading, and direct TBE consumption.
- MSS CLI command: `validate-mission` validates a mission JSON file and emits machine-readable findings with deterministic exit codes.
- EEF v1.0 runtime: immutable `ExecutionContext`, deterministic `ExecutionSession` lifecycle (start, schedule, pause, resume, cancel, complete), FIFO scheduling with dependency-edge cross-validation, read-only status snapshots, and a hash-chained append-only execution event journal.
- EEF v1.0 state integration: lifecycle mutations flow exclusively through `PESEStore.update()`; resume uses the scoped `MISSION_INTERRUPT_RECOVERY` custom transition; start/cancel/complete fire PESE mandatory checkpoints; session status persists under the `org.asc.eef` extension key.
- EEF CLI commands: `execution-start`, `execution-status`, `execution-schedule`, `execution-pause`, `execution-resume`, `execution-cancel`, and `execution-complete` with machine-readable outcomes and deterministic exit codes.
- CKS v1.0 runtime: deterministic, stdlib-only HMAC-SHA256 key store with immutable key records, atomic writes, status journals, rotation and revocation, constant-time verification, and a hash-chained per-key signing ledger.
- CKS CLI commands: `key-create`, `key-list`, `key-sign`, `key-verify`, `key-rotate`, `key-revoke`, and `key-validate` with machine-readable outcomes and deterministic exit codes; keys persist under `.project-os/KEYS/` and never read or mutate PESE/ACP/TBE/MSS/EEF state.
- AEX v1.0 runtime: deterministic, stdlib-only agent execution engine that consumes EEF-dispatched assignments, enforces actor authorization and PESE legal assignment transitions, persists immutable execution result records and copied artifacts under `.project-os/ARTIFACTS/`, and signs execution attestations via CKS.
- AEX v1.0 EEF/CKS integration: every transition flows through `PESEStore.update()` with the legal ASSIGNMENT_STATUS map; each mutation emits an agent-owned EEF event (ASSIGNMENT_DISPATCHED, ASSIGNMENT_COMPLETED, ASSIGNMENT_FAILED, ASSIGNMENT_BLOCKED, ASSIGNMENT_ACTIVATED) to the hash-chained execution journal; result records are atomically written, entry-hash canonical, and optionally CKS-signed.
- AEX CLI commands: `aex-dispatch`, `aex-complete`, `aex-fail`, `aex-block`, `aex-unblock`, `aex-status`, and `aex-result` with machine-readable outcomes, deterministic exit codes, Windows-safe `%3A`-encoded artifact layout, and path-traversal rejection.
- AHP v1.0 runtime: deterministic, stdlib-only agent health store recording append-only, hash-chained per-agent heartbeat journals under `.project-os/HEALTH/agents/`, with process-safe locking, atomic writes, injectable query time, and read-only chain/sequence/hash validation.
- AHP v1.0 status model: ALIVE/STALLED/UNKNOWN derived at query time from last-heartbeat age against a configurable timeout; `health-report` and `health-check` read mission `assigned_agent_ids` from PESE state (read-only) and never mutate PESE.
- AHP CLI commands: `health-heartbeat`, `health-status`, `health-report`, and `health-check` with machine-readable outcomes and deterministic exit codes; `health-check` exits 2 when any mission agent is STALLED.
- VAL v1.0 runtime: deterministic, stdlib-only validation engine that drives PESE validation gates through their lifecycle (`PENDING → RUNNING → GREEN/RED/BLOCKED`), registers SHA-256-bound validation artifacts, verifies bound artifact files against recorded hashes, and revokes GREEN verdicts when the artifact/repository binding fails.
- VAL v1.0 PESE/EEF integration: every gate transition flows through `PESEStore.update()` with transition type `VALIDATION_GATE`; each verdict emits a `GATE_*` event (GATE_STARTED, GATE_PASSED, GATE_FAILED, GATE_BLOCKED, GATE_INVALIDATED) to the EEF execution journal; `verify()` provides raw-read per-artifact diagnostics when tampered artifacts make PESE state unloadable.
- VAL v1.0 tamper policy: tampered artifacts are a secure halt for mutations; invalidation of tampered evidence is an operator recovery action, never a programmatic sweep under the rug; `invalidate()` enforces the binding-failure precondition per PESE spec section 5.3 and raises `BINDING_INTACT` when the binding is sound.
- VAL CLI commands: `validation-gates`, `validation-start`, `validation-finish`, `validation-verify`, `validation-invalidate`, and `validation-report` with machine-readable outcomes and deterministic exit codes; mutation commands resolve the actor to the gate's designated validator.

## Active work

No active implementation work. M014 VAL validation gates and artifact verification is complete; encrypted transport and autonomous workflow scheduling remain outside the current release scope.

## Incomplete capabilities

Encrypted transport and autonomous workflow scheduling are not yet implemented.

## Release status

M014 implements the canonical VAL v1.0 validation contract on top of the PESE/TBE/MSS/EEF/CKS/AEX/AHP foundations, closing the mission-lifecycle gap: intake (MSS), assembly (TBE), state (PESE), lifecycle (EEF), identity (CKS), execution (AEX), liveness (AHP), and validation (VAL). VAL drives gate verdicts and verifies artifacts, supplying the validation runtime the M017 recovery engine and M019 autonomous scheduler consume to gate mission completion. The release is complete for intake, team-assembly, persistent-state, execution-lifecycle, cryptographic-signing, agent-execution, agent-health, and validation scope; encrypted transport and autonomous workflow scheduling remain intentionally absent.

## Last verified

2026-08-05 - M014 VAL release gate passed: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP plus new VAL unit and CLI suites), MyPy, Ruff check+format, source compilation, documentation validation (now checking VAL), CLI validation lifecycle smoke tests (gates → start → finish GREEN/RED → verify → invalidate → report), EEF event-journal chain verification with GATE_* events, and tamper-detection halt path.

2026-08-05 - M012 AEX release gate passed: full suite (existing PESE/TBE/MSS/EEF/CKS plus new AEX unit and CLI suites), MyPy, Ruff check+format, source compilation, documentation validation (now checking AEX), CLI execution lifecycle smoke tests (start → dispatch → complete/result with artifact + CKS signature, fail, block/unblock), and EEF event-journal chain verification.

2026-08-04 - MISSION-007 PESE runtime passed 44 unit tests, three repeated full-suite reliability runs, MyPy, Ruff, compilation, documentation validation, runtime Git lifecycle checks, and independent QA/conformance review.

2026-08-04 - M008 TBE runtime passed 66 unit tests, MyPy, Ruff, formatting, compilation, documentation validation, controlled byte-reproducibility, PESE integrity/authorization/gating tests, and independent QA/conformance review.

2026-08-04 - M008 release gate re-verified after fixing environmental test fixture: 69-case full suite, MyPy, Ruff check+format, source compilation, and documentation validation all passed; PESE `test_resume_plan_uses_ready_assignment_and_requires_checkpoint` now passes deterministically via `GIT_CEILING_DIRECTORIES` isolation that does not modify runtime code.

2026-08-04 - M009 MSS release gate passed: 121-case full suite, MyPy, Ruff check+format, source compilation, documentation validation, CLI smoke tests, TBE direct-consumption tests, and independent release audit passed. The audit found and fixed non-mapping input handling in `MissionSpec.from_mapping`.

2026-08-04 - M010 EEF release gate passed: full suite (existing MSS/PESE/TBE plus new EEF unit and CLI lifecycle suites), MyPy, Ruff check+format, source compilation, documentation validation, CLI lifecycle smoke tests (start → status → schedule → pause → resume → cancel → complete), PESE integrity/checkpoint checks, and event-journal chain verification.

2026-08-05 - M011 CKS release gate passed: full suite (existing PESE/TBE/MSS/EEF plus new CKS unit and CLI suites), MyPy, Ruff check+format, source compilation, documentation validation, CLI key lifecycle smoke tests (create → list → sign → verify → rotate → revoke → validate), and signing-ledger chain integrity with tamper detection.

2026-08-04 — M006.5 PESE v1.0 specification passed JSON-example, structural-topic, and independent ACP/ACR/TBE compatibility review.

2026-08-04 — 20 `unittest` cases passed; CLI config/registry smoke tests, JSON validation, source compilation, wheel build, QA, and independent code review passed.

