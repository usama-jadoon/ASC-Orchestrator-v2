# Project State

Status: M017_REC_COMPLETE

## Product and users

ASC Orchestrator v2 provides deterministic, auditable assembly and operation of autonomous software-company agents.

## Verified stack

Python 3.14 standard-library runtime; `unittest` test framework; `tomllib` configuration; JSON registry entries; MyPy and Ruff verification gates.

## Architecture and canonical contracts

ACP v1.0 governs messages and audit records. ACR v1.0 governs registry entries under `.project-os/COMPANY/DEPARTMENTS/`. PESE v1.0 is the canonical persistent-state contract. TBE v1.0 is the canonical deterministic team-assembly contract integrated with those foundations. MSS v1.0 is the canonical mission-intake contract consumed directly by TBE. EEF v1.0 is the canonical execution-lifecycle contract driving PESE-bound missions through start, schedule, pause, resume, cancel, and complete. CKS v1.0 is the canonical cryptographic key and audit-signing contract providing deterministic HMAC-SHA256 key lifecycle, signing/verification, and a hash-chained signing ledger. AEX v1.0 is the canonical agent-execution contract that claims EEF-dispatched assignments, transitions them through their lifecycle, persists work-product artifacts, and signs execution attestations via CKS. AHP v1.0 is the canonical agent-health contract that records per-agent heartbeat histories and derives ALIVE, STALLED, and UNKNOWN liveness status for stalled-agent detection. VAL v1.0 is the canonical validation contract that drives PESE validation gates through their lifecycle, registers SHA-256-bound validation artifacts, and emits gate verdicts to the EEF execution journal. RKM v1.0 is the canonical risk-management contract that operates the PESE risk ledger, enforces the risk status state machine, and implements the hold mechanism that blocks autonomous execution on HALT / unresolved CRITICAL / declared HIGH block conditions. AGC v1.0 is the canonical agent-lifecycle contract that operates the PESE agent ledger, enforces the agent status state machine, verifies dependency environments before READY, and tracks every agent from registration through release with `AGENT_*` events to the EEF execution journal. REC v1.0 is the canonical recovery contract that automates the deterministic agent-recovery sequence — quarantine → release → register replacement → activate → dependency VERIFIED → ready → claim — when an agent fails or stalls, persisting a durable recovery ledger over PESE `recovery_state` with `RECOVERY_*` events to the EEF execution journal.

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
- RKM v1.0 runtime: deterministic, stdlib-only risk-management engine that operates the PESE `risk_state.risks` ledger, enforces the RKM status state machine (`OPEN → MITIGATING/ACCEPTED/RESOLVED/HALT`, `MITIGATING → RESOLVED`), and evaluates the hold mechanism per PESE section 4.7 (HALT risk, unresolved CRITICAL, or HIGH risk with a declared block condition blocks autonomous execution).
- RKM v1.0 PESE/EEF integration: every risk mutation flows through `PESEStore.update()` with transition type `RISK_STATUS` (RKM enforces its own state machine because `RISK_STATUS` is not in PESE's legal map, the same pattern as EEF's `MISSION_INTERRUPT_RECOVERY` and VAL's `VALIDATION_GATE`); each transition emits a `RISK_*` event (RISK_OPENED, RISK_MITIGATED, RISK_ACCEPTED, RISK_RESOLVED, RISK_HALTED) to the EEF execution journal; block conditions for HIGH risks persist under the reverse-DNS `extensions["org.asc.rkm"]` key.
- RKM hold mechanism: mission-scoped checks include company-wide risks (`mission_id=None`), which block all missions; HIGH risks block only when a block condition is declared in the `org.asc.rkm` extension; CRITICAL risks always block while open unless ACCEPTED or RESOLVED.
- RKM CLI commands: `risk-open`, `risk-list`, `risk-status`, `risk-mitigate`, `risk-accept`, `risk-resolve`, `risk-halt`, `risk-check`, and `risk-report` with machine-readable outcomes and deterministic exit codes; `risk-check` exits 2 when autonomous execution is blocked.
- AGC v1.0 runtime: deterministic, stdlib-only agent-lifecycle engine that operates the PESE `agent_state.agents` ledger, enforces the AGC status state machine (INITIALIZING → REGISTERED → READY → BUSY with BLOCKED/FAILED/QUARANTINED/REPLACED/RELEASED branches), and requires the 4-field dependency environment state to be `VERIFIED` before an agent becomes READY.
- AGC v1.0 PESE/EEF integration: every agent mutation flows through `PESEStore.update()` with transition type `AGENT_STATUS` (AGC enforces its own state machine because `AGENT_STATUS` is not in PESE's legal map, the same pattern as RKM's `RISK_STATUS` and VAL's `VALIDATION_GATE`); each transition emits one of thirteen `AGENT_*` events (AGENT_REGISTERED, AGENT_ACTIVATED, AGENT_READY, AGENT_BUSY, AGENT_BLOCKED, AGENT_UNBLOCKED, AGENT_FAILED, AGENT_QUARANTINED, AGENT_REPLACED, AGENT_RELEASED, AGENT_DEPENDENCY, AGENT_HEARTBEAT, AGENT_CHECKPOINTED) to the EEF execution journal; `FAILED`/`QUARANTINED` with an active mission trigger the PESE mandatory FAILURE checkpoint.
- AGC v1.0 actor authority: only the orchestrator (`AGENT:orchestrator:local`) or the target agent itself may manage an agent, enforced at the engine level; agent records carry heartbeat/checkpoint references and a canonical interruption record.
- AGC CLI commands: `agent-register`, `agent-activate`, `agent-dependency`, `agent-ready`, `agent-claim`, `agent-complete`, `agent-block`, `agent-unblock`, `agent-fail`, `agent-quarantine`, `agent-replace`, `agent-release`, `agent-heartbeat`, `agent-checkpoint`, `agent-list`, `agent-status`, and `agent-report` with machine-readable outcomes and deterministic exit codes; precondition failures (missing agent, wrong-status activation, ready without VERIFIED dependency, double-release) exit 2.
- REC v1.0 runtime: deterministic, stdlib-only recovery engine that operates the PESE `recovery_state.recoveries` ledger, derives the recovery trigger from AGC agent status and AHP liveness (FAILED / QUARANTINED from AGC, STALLED from AHP when the AGC status is READY/BUSY/BLOCKED), and enforces the REC status state machine (`IN_PROGRESS → COMPLETED/FAILED`).
- REC v1.0 recovery sequence: `run` orchestrates quarantine → release → register replacement → activate → dependency VERIFIED → ready → claim (claim skipped when no assignment exists, leaving the replacement READY), copies the original agent's tool/environment dependencies, and defaults the replacement ID to `{agent_id}:recovery:{N}`.
- REC v1.0 PESE/EEF integration: every recovery-ledger mutation flows through `PESEStore.update()` with transition type `RECOVERY_STATUS` (REC enforces its own state machine because `RECOVERY_STATUS` is not in PESE's legal map, the same pattern as RKM's `RISK_STATUS`, VAL's `VALIDATION_GATE`, and AGC's `AGENT_STATUS`); each transition emits a `RECOVERY_*` event (RECOVERY_STARTED, RECOVERY_COMPLETED, RECOVERY_FAILED) to the EEF execution journal; a PESE mandatory FAILURE checkpoint is recorded only when a recovery transitions to FAILED so successful recovery does not mark the mission failed.
- REC v1.0 read-only pre-flight: `diagnose` returns a `RecoveryDiagnosis` (recoverable/not-recoverable, trigger, mission/assignment/acr_ref, and a suggested replacement ID) without mutating state; RELEASED/REPLACED/INITIALIZING/REGISTERED agents and healthy READY/BUSY/BLOCKED agents are reported not recoverable.
- REC CLI commands: `recovery-diagnose`, `recovery-run`, `recovery-status`, `recovery-list`, and `recovery-report` with machine-readable outcomes and deterministic exit codes; agent not found, not recoverable, and step-failure paths exit 2 with `status=FAILED` and the error detail.

## Active work

No active implementation work. M017 REC agent recovery is complete; encrypted transport and autonomous workflow scheduling remain outside the current release scope.

## Incomplete capabilities

Encrypted transport and autonomous workflow scheduling are not yet implemented.

## Release status

M017 implements the canonical REC v1.0 recovery contract on top of the PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL/RKM/AGC foundations, closing the recovery loop: when AHP detects a STALLED agent or AGC reports a FAILED/QUARANTINED agent, REC reduces the 7+ manual AGC recovery commands to one deterministic `recovery-run` that orchestrates quarantine → release → register replacement → activate → dependency VERIFIED → ready → claim, persists a durable recovery ledger over PESE `recovery_state`, and emits `RECOVERY_*` events to the EEF execution journal. REC derives its trigger from AGC agent status and AHP liveness (read-only), enforces its own `IN_PROGRESS → COMPLETED/FAILED` state machine through `RECOVERY_STATUS` transitions, records a mandatory FAILURE checkpoint only on failed recovery, and leaves successful recovery free of mission-failure marking. The release is complete for intake, team-assembly, persistent-state, execution-lifecycle, cryptographic-signing, agent-execution, agent-health, validation, risk-management, agent-lifecycle, and recovery scope; encrypted transport and autonomous workflow scheduling remain intentionally absent.

## Last verified

2026-08-06 - M017 REC release gate passed: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL/RKM/AGC plus new REC unit and CLI suites), MyPy, Ruff check+format, source compilation, documentation validation (now checking REC), CLI recovery lifecycle smoke tests (fail an agent → diagnose → run → status → list → report, STALLED trigger via stale heartbeat, run without assignment → replacement READY, non-recoverable/step-failure/missing-agent exit paths), EEF event-journal chain verification with RECOVERY_* events, replacement agent BUSY/READY verification, and backward-compatibility smoke.

2026-08-06 - M016 AGC release gate passed: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL/RKM plus new AGC unit and CLI suites), MyPy, Ruff check+format, source compilation, documentation validation (now checking AGC), CLI agent lifecycle smoke tests (register → activate → dependency → ready → claim → complete → release, block/unblock, fail/quarantine/replace, list/report, error paths), EEF event-journal chain verification with AGENT_* events, dependency-gated ready, authority checks, and backward-compatibility smoke.

2026-08-05 - M015 RKM release gate passed: full suite (existing PESE/TBE/MSS/EEF/CKS/AEX/AHP/VAL plus new RKM unit and CLI suites), MyPy, Ruff check+format, source compilation, documentation validation (now checking RKM), CLI risk lifecycle smoke tests (open → list → status → mitigate → resolve, halt → check exit 2, CRITICAL → check exit 2, resolve/accept CRITICAL → check exit 0, HIGH with block condition → check exit 2, mission-scoped check, report), EEF event-journal chain verification with RISK_* events, and backward-compatibility smoke.

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

