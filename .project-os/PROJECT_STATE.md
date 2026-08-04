# Project State

Status: M009_MSS_RUNTIME_COMPLETE

## Product and users

ASC Orchestrator v2 provides deterministic, auditable assembly and operation of autonomous software-company agents.

## Verified stack

Python 3.14 standard-library runtime; `unittest` test framework; `tomllib` configuration; JSON registry entries; MyPy and Ruff verification gates.

## Architecture and canonical contracts

ACP v1.0 governs messages and audit records. ACR v1.0 governs registry entries under `.project-os/COMPANY/DEPARTMENTS/`. PESE v1.0 is the canonical persistent-state contract. TBE v1.0 is the canonical deterministic team-assembly contract integrated with those foundations. MSS v1.0 is the canonical mission-intake contract consumed directly by TBE.

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

## Active work

No active implementation work. M009 MSS intake is complete; agent execution, transport, identity, and cryptographic production capabilities remain outside the current release scope.

## Incomplete capabilities

Agent execution, crypto key management, production audit signing, encrypted transport, and autonomous workflow scheduling are not yet implemented.

## Release status

M009 implements the canonical MSS mission-intake contract and runtime validation on top of the PESE/TBE foundations. The release is complete for intake and validation scope; execution, transport, identity, and cryptographic capabilities remain intentionally absent.

## Last verified

2026-08-04 - MISSION-007 PESE runtime passed 44 unit tests, three repeated full-suite reliability runs, MyPy, Ruff, compilation, documentation validation, runtime Git lifecycle checks, and independent QA/conformance review.

2026-08-04 - M008 TBE runtime passed 66 unit tests, MyPy, Ruff, formatting, compilation, documentation validation, controlled byte-reproducibility, PESE integrity/authorization/gating tests, and independent QA/conformance review.

2026-08-04 - M008 release gate re-verified after fixing environmental test fixture: 69-case full suite, MyPy, Ruff check+format, source compilation, and documentation validation all passed; PESE `test_resume_plan_uses_ready_assignment_and_requires_checkpoint` now passes deterministically via `GIT_CEILING_DIRECTORIES` isolation that does not modify runtime code.

2026-08-04 - M009 MSS release gate passed: 121-case full suite, MyPy, Ruff check+format, source compilation, documentation validation, CLI smoke tests, TBE direct-consumption tests, and independent release audit passed. The audit found and fixed non-mapping input handling in `MissionSpec.from_mapping`.

2026-08-04 — M006.5 PESE v1.0 specification passed JSON-example, structural-topic, and independent ACP/ACR/TBE compatibility review.

2026-08-04 — 20 `unittest` cases passed; CLI config/registry smoke tests, JSON validation, source compilation, wheel build, QA, and independent code review passed.

