# Project State

Status: M011_CKS_COMPLETE

## Product and users

ASC Orchestrator v2 provides deterministic, auditable assembly and operation of autonomous software-company agents.

## Verified stack

Python 3.14 standard-library runtime; `unittest` test framework; `tomllib` configuration; JSON registry entries; MyPy and Ruff verification gates.

## Architecture and canonical contracts

ACP v1.0 governs messages and audit records. ACR v1.0 governs registry entries under `.project-os/COMPANY/DEPARTMENTS/`. PESE v1.0 is the canonical persistent-state contract. TBE v1.0 is the canonical deterministic team-assembly contract integrated with those foundations. MSS v1.0 is the canonical mission-intake contract consumed directly by TBE. EEF v1.0 is the canonical execution-lifecycle contract driving PESE-bound missions through start, schedule, pause, resume, cancel, and complete. CKS v1.0 is the canonical cryptographic key and audit-signing contract providing deterministic HMAC-SHA256 key lifecycle, signing/verification, and a hash-chained signing ledger.

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

## Active work

No active implementation work. M011 CKS cryptographic key and audit-signing management is complete; agent execution, transport, and autonomous workflow scheduling remain outside the current release scope.

## Incomplete capabilities

Agent execution, encrypted transport, and autonomous workflow scheduling are not yet implemented.

## Release status

M011 implements the canonical CKS v1.0 cryptographic key and audit-signing contract on top of the PESE/TBE/MSS/EEF foundations. The release is complete for intake, team-assembly, persistent-state, execution-lifecycle, and cryptographic-signing scope; agent execution, transport, and autonomous workflow scheduling remain intentionally absent.

## Last verified

2026-08-04 - MISSION-007 PESE runtime passed 44 unit tests, three repeated full-suite reliability runs, MyPy, Ruff, compilation, documentation validation, runtime Git lifecycle checks, and independent QA/conformance review.

2026-08-04 - M008 TBE runtime passed 66 unit tests, MyPy, Ruff, formatting, compilation, documentation validation, controlled byte-reproducibility, PESE integrity/authorization/gating tests, and independent QA/conformance review.

2026-08-04 - M008 release gate re-verified after fixing environmental test fixture: 69-case full suite, MyPy, Ruff check+format, source compilation, and documentation validation all passed; PESE `test_resume_plan_uses_ready_assignment_and_requires_checkpoint` now passes deterministically via `GIT_CEILING_DIRECTORIES` isolation that does not modify runtime code.

2026-08-04 - M009 MSS release gate passed: 121-case full suite, MyPy, Ruff check+format, source compilation, documentation validation, CLI smoke tests, TBE direct-consumption tests, and independent release audit passed. The audit found and fixed non-mapping input handling in `MissionSpec.from_mapping`.

2026-08-04 - M010 EEF release gate passed: full suite (existing MSS/PESE/TBE plus new EEF unit and CLI lifecycle suites), MyPy, Ruff check+format, source compilation, documentation validation, CLI lifecycle smoke tests (start → status → schedule → pause → resume → cancel → complete), PESE integrity/checkpoint checks, and event-journal chain verification.

2026-08-05 - M011 CKS release gate passed: full suite (existing PESE/TBE/MSS/EEF plus new CKS unit and CLI suites), MyPy, Ruff check+format, source compilation, documentation validation, CLI key lifecycle smoke tests (create → list → sign → verify → rotate → revoke → validate), and signing-ledger chain integrity with tamper detection.

2026-08-04 — M006.5 PESE v1.0 specification passed JSON-example, structural-topic, and independent ACP/ACR/TBE compatibility review.

2026-08-04 — 20 `unittest` cases passed; CLI config/registry smoke tests, JSON validation, source compilation, wheel build, QA, and independent code review passed.

