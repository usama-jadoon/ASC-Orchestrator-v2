# Changelog

All notable changes to the ASC Orchestrator v2 project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [1.0.3] - 2026-08-15

Backward-compatible remediation release. Software version advances to `1.0.3`;
the PESE state schema remains `1.0.0` and no state migration is required.

### Fixed

- RC-001: historical PESE `1.0.0` persisted states created under earlier
  `1.0.x` releases legitimately omit `milestone_id` on validation gates
  (e.g. InboxShield rev52 history, revisions 2–52). The validator previously
  rejected those states because `milestone_id` was mandatory in the exact
  field-set equality. `milestone_id` is now treated as a **backward-compatible
  optional extension**: legacy gates without it remain valid when every other
  required field is present and no alien fields exist; gates that carry it are
  still validated strictly (non-empty string referencing a declared
  milestone). Current-state validation is unchanged and integrity guarantees
  stay fail-closed.
- RC-002 (`STATE_CHAIN_INVALID`): proven to be a cascade symptom of RC-001 —
  schema rejection pinned the accepted chain position at revision 1, so the
  later comparison then reported chain invalidity. RC-002 disappears once
  RC-001 is fixed; no separate chain-repair patch was introduced.
- RC-003 (audit harness defect): `audit/build_fixtures.py` regenerates the
  synthetic `v1.0.1` fixture with a correct deterministic `rev1 → rev2` SHA
  chain (`previous_state_sha256` now equals `rev1.state_sha256`). A
  chain-validation guard (`--validate-corpus`) blocks broken chains from
  entering the compatibility corpus. This is audit tooling only — it does not
  touch ASC runtime or the real InboxShield state.

### Added

- `tests/test_pese_v103_compat.py` — regression tests A–I reproducing the real
  historical gate shape and locking in the backward-compatible boundary.
- `audit/build_fixtures.py` — deterministic v1.0.1 fixture generator with a
  corpus-entry chain guard.

### Changed

- Software release version advanced to `1.0.3`; PESE `schema_version` remains
  `1.0.0` with zero state migration.
## [1.0.2] - 2026-08-12

Maintenance patch release. Software version advances to `1.0.2`; the PESE
state schema remains `1.0.0` and no state migration is required.

### Fixed

- D1: a dependent assignment (`depends_on`) stayed `PENDING` forever because
  no runtime path promoted it to `READY` when its dependencies completed.
  `AEX.complete()` now promotes dependent assignments and recomputes the
  candidate set, so the work chain drains end to end.
- D2: the AWS scheduler could start a `PENDING` validation gate (`VALIDATE`,
  priority 60) while mission assignments were still unfinished. The `VALIDATE`
  decision now requires every assignment of the mission to be `COMPLETED`
  before a gate is started.
- D3: EEF `complete()` could move an `ACTIVE` mission to `VALIDATING` while
  assignments remained unfinished. `complete()` now rejects the transition
  with `ASSIGNMENTS_INCOMPLETE` unless every assignment is `COMPLETED`.

### Added

- `tests/test_lifecycle_v102.py` — deterministic reproduction tests (A–F)
  locking in the corrected D1/D2/D3 behavior.
- PESE authorization for the EEF-owned `MILESTONE_STATUS` transition so the
  mission milestone cursor advances under mission-member authority.

### Changed

- Software release version advanced to `1.0.2`; PESE `schema_version` remains
  `1.0.0` with zero state migration.

## [1.0.1] - 2026-08-11

Maintenance bugfix release. Software version advances to `1.0.1`; the PESE
state schema remains `1.0.0` and no state migration is required.

### Fixed

- PESE `repo_state` was frozen at mission-initialization HEAD, so authorized
  Git commits made `validate-state` report `REPOSITORY_DIVERGENCE` and halted
  `resume`. A new explicit `reconcile-repository` operation records an
  authorized HEAD advance and restores state to `VALID`.
- Reconciliation is never automatic: it requires orchestrator authority,
  verifies repository identity, requires the recorded HEAD to be an ancestor
  of the observed HEAD, and rejects non-descendant or rewritten histories.
- Git errors fail closed, and an optional `--expected-revision` guard rejects
  reconciliations against a stale state revision.

### Added

- CLI command `asc-orchestrator reconcile-repository` emitting
  `outcome=RECONCILIATED` with deterministic exit codes.
- PESE transition type `REPOSITORY_RECONCILIATION` — an audited transition
  recording the old and new HEAD, preserving the state hash chain, and
  persisting a mandatory `COMMIT` checkpoint.
- `docs/PESE_v1.0.md` §5.5 documenting the repository-reconciliation contract
  as the sanctioned resolution path for `REPOSITORY_DIVERGENCE`.

### Changed

- Software release version advanced to `1.0.1`; PESE `schema_version` remains
  `1.0.0` with zero state migration.

## [1.0.0] - 2026-08-08

Initial production release of ASC Orchestrator v2 — a deterministic,
auditable, stdlib-only runtime for the assembly and operation of autonomous
software-company agents. The release ships 16 canonical v1.0 contracts, 22
runtime modules, a dependency-free `src/`-layout wheel, and a deterministic
`release` verifier that certifies the source tree before publication.

### Added

#### Foundation and core contracts (M001-M005)
- Repository skeleton with `src/` package layout, `pyproject.toml`,
  `asc-orchestrator.toml`, and the `asc-orchestrator` console entry point.
- **ACP v1.0** — Agent Communication Protocol: fixed-header messages,
  ordered string payloads, SHA-256 payload binding, semantic and UTF-8
  validation, and deterministic serialization/parsing.
- **ACR v1.0** — Agent Capability Registry: deterministic JSON registry
  loader and validator, with `investigator` and `security-auditor` seed
  entries under `.project-os/COMPANY/DEPARTMENTS/`.
- Local append-only, hash-chained ACP audit journal under
  `.project-os/AUDIT/` with process-safe locking and chain verification.
- TOML runtime configuration (`RuntimeConfig`, `load_config`) and CLI
  commands `config`, `registry`, and `acp`.

#### Persistent Execution State Engine — PESE v1.0 (M006-M007)
- Canonical persistent-state contract: state, checkpoint, locking,
  integrity, recovery, migration, and resume semantics.
- Runtime with canonical state history, hash-chained access/transition
  audits, atomic writers and audit locks, checkpointing, integrity
  validation, deterministic resume, recovery, and migration records.
- CLI commands `state`, `resume`, `checkpoint`, and `validate-state`.

#### Team Builder Engine — TBE v1.0 (M008)
- Deterministic registry-only specialist selection with capacity-aware
  membership, leadership materialization, exclusive ownership,
  assignment-level dependency/resource graphs, reviewer and validator
  interfaces, escalation routes, and canonical versioned `TEAM.md`
  manifests.
- CLI command `team-build`, including deterministic timestamp input and
  optional atomic PESE manifest binding.

#### Mission Specification Standard — MSS v1.0 (M009)
- Immutable `MissionSpec` Mapping contract with structural parsing,
  semantic validation findings, canonical vocabularies, baseline-gate
  recommendations, extension-key checks, and direct TBE consumption.
- CLI command `validate-mission` with machine-readable findings and
  deterministic exit codes.

#### Execution Engine Foundation — EEF v1.0 (M010)
- Immutable `ExecutionContext`, deterministic `ExecutionSession` lifecycle
  (start, schedule, pause, resume, cancel, complete), FIFO scheduling with
  dependency-edge cross-validation, read-only status snapshots, and a
  hash-chained append-only execution event journal.
- PESE state integration: lifecycle mutations flow exclusively through
  `PESEStore.update()`, with mandatory checkpoints and state persisted
  under the `org.asc.eef` extension key.
- CLI commands `execution-start`, `execution-status`, `execution-schedule`,
  `execution-pause`, `execution-resume`, `execution-cancel`, and
  `execution-complete`.

#### Cryptographic Key Service — CKS v1.0 (M011)
- Deterministic, stdlib-only HMAC-SHA256 key store with immutable key
  records, atomic writes, status journals, rotation and revocation,
  constant-time verification, and a hash-chained per-key signing ledger.
- CLI commands `key-create`, `key-list`, `key-sign`, `key-verify`,
  `key-rotate`, `key-revoke`, and `key-validate`. Keys persist under
  `.project-os/KEYS/` and never read or mutate PESE/ACP/TBE/MSS/EEF state.

#### Agent Execution Engine — AEX v1.0 (M012)
- Deterministic execution engine that consumes EEF-dispatched assignments,
  enforces actor authorization and PESE legal assignment transitions,
  persists immutable execution result records and copied artifacts under
  `.project-os/ARTIFACTS/`, and signs execution attestations via CKS.
- CLI commands `aex-dispatch`, `aex-complete`, `aex-fail`, `aex-block`,
  `aex-unblock`, `aex-status`, and `aex-result`, with Windows-safe
  `%3A`-encoded artifact layout and path-traversal rejection.

#### Agent Health Protocol — AHP v1.0 (M013)
- Deterministic agent health store recording append-only, hash-chained
  per-agent heartbeat journals under `.project-os/HEALTH/agents/`, with
  process-safe locking, atomic writes, injectable query time, and read-only
  chain/sequence/hash validation.
- ALIVE / STALLED / UNKNOWN status model derived at query time from
  last-heartbeat age against a configurable timeout.
- CLI commands `health-heartbeat`, `health-status`, `health-report`, and
  `health-check` (exits 2 when any mission agent is STALLED).

#### Validation Engine — VAL v1.0 (M014)
- Deterministic validation engine driving PESE validation gates through
  their lifecycle (`PENDING → RUNNING → GREEN/RED/BLOCKED`), registering
  SHA-256-bound validation artifacts, verifying bound artifact files, and
  revoking GREEN verdicts when the artifact/repository binding fails.
- Tamper policy: tampered artifacts are a secure halt for mutations;
  invalidation is an operator recovery action that enforces the
  binding-failure precondition.
- CLI commands `validation-gates`, `validation-start`, `validation-finish`,
  `validation-verify`, `validation-invalidate`, and `validation-report`.

#### Risk Management — RKM v1.0 (M015)
- Deterministic risk-management engine operating the PESE `risk_state`
  ledger and enforcing the risk status state machine
  (`OPEN → MITIGATING/ACCEPTED/RESOLVED/HALT`).
- Hold mechanism: HALT risks, unresolved CRITICAL risks, and HIGH risks
  with a declared block condition block autonomous execution.
- CLI commands `risk-open`, `risk-list`, `risk-status`, `risk-mitigate`,
  `risk-accept`, `risk-resolve`, `risk-halt`, `risk-check` (exits 2 when
  autonomous execution is blocked), and `risk-report`.

#### Agent Lifecycle Control — AGC v1.0 (M016)
- Deterministic agent-lifecycle engine operating the PESE `agent_state`
  ledger and enforcing the AGC status state machine
  (`INITIALIZING → REGISTERED → READY → BUSY` with
  BLOCKED/FAILED/QUARANTINED/REPLACED/RELEASED branches), requiring the
  4-field dependency environment state to be `VERIFIED` before READY.
- Actor authority: only the orchestrator or the target agent itself may
  manage an agent.
- CLI commands `agent-register`, `agent-activate`, `agent-dependency`,
  `agent-ready`, `agent-claim`, `agent-complete`, `agent-block`,
  `agent-unblock`, `agent-fail`, `agent-quarantine`, `agent-replace`,
  `agent-release`, `agent-heartbeat`, `agent-checkpoint`, `agent-list`,
  `agent-status`, and `agent-report`.

#### Recovery Engine — REC v1.0 (M017)
- Deterministic recovery engine operating the PESE `recovery_state` ledger,
  deriving the recovery trigger from AGC agent status and AHP liveness
  (FAILED / QUARANTINED from AGC, STALLED from AHP), and enforcing the REC
  status state machine (`IN_PROGRESS → COMPLETED/FAILED`).
- Single `recovery-run` orchestrating quarantine → release → register
  replacement → activate → dependency VERIFIED → ready → claim, with a
  read-only `recovery-diagnose` pre-flight assessment.
- CLI commands `recovery-diagnose`, `recovery-run`, `recovery-status`,
  `recovery-list`, and `recovery-report`.

#### Encrypted Transport — ETR v1.0 (M018)
- Deterministic encrypted-transport engine providing RFC 8439
  ChaCha20-Poly1305 AEAD symmetric authenticated encryption for ACP
  payloads and artifact files, operating over PESE `transport_state` with
  CKS key binding.
- Channel-based sender/recipient binding with ACTIVE/REVOKED status;
  `etr-seal` encrypts into tamper-evident `.etr` JSON envelopes and
  `etr-open` authenticates with Poly1305 tag verification.
- CLI commands `etr-bind-channel`, `etr-revoke-channel`, `etr-channel`,
  `etr-list-channels`, `etr-seal`, `etr-open`, `etr-list-envelopes`, and
  `etr-report`.

#### Autonomous Workflow Scheduler — AWS v1.0 (M019)
- Deterministic top-level orchestration runtime evaluating full system
  state once per tick and producing exactly one prioritized scheduling
  decision, delegating actionable decisions to the owning runtime.
- Eight decision types with deterministic priority ordering: HOLD (100),
  RECOVER (90), START_MISSION (80), DISPATCH (70), VALIDATE (60),
  COMPLETE_MISSION (50), MONITOR_HEALTH (40), IDLE (0).
- CLI commands `scheduler-tick`, `scheduler-enable`, `scheduler-disable`,
  `scheduler-status`, `scheduler-cycle`, `scheduler-list`, and
  `scheduler-report`.

#### Production Release — REL v1.0 (M020)
- Deterministic, stdlib-only release verifier certifying packaging metadata
  (version 1.0.0, dependency-free wheel, `src/` layout, console entry
  point), canonical contract coverage, runtime module importability, and
  per-contract test suite presence.
- Nine release gates: `version`, `package_name`, `no_dependencies`,
  `console_entry_point`, `src_layout`, `canonical_specs`,
  `runtime_modules`, `test_suites`, `release_spec`.
- CLI command `release` emitting `release=PASS` (exit 0) only when all
  nine gates pass.

### Changed

- All runtime state changes flow exclusively through
  `PESEStore.update()` with typed, audited transition records; no runtime
  mutates PESE state out-of-band.
- Every contract-specific mutation emits a namespaced event to the
  hash-chained EEF execution journal at `.project-os/AUDIT/execution-events.jsonl`.
- The documented Python floor is 3.11 (`requires-python = ">=3.11"`); the
  runtime is standard-library-only with zero external dependencies.
- Milestones beyond PESE/TBE/MSS (AHP, VAL, RKM, AGC, REC, ETR, AWS, REL)
  were ratified as canonical contracts after the M006/M008/M009 foundations.

### Fixed

- Resolved release blockers RB-10 and RB-11: AWS `_blocking_risk_check`
  now fails closed (risk evaluation errors force HOLD) and CKS status
  journals fail closed (missing, corrupt, or broken-chain journals raise
  `LEDGER_BROKEN` instead of defaulting to ACTIVE). AGC `register` was
  restricted to orchestrator authority and heartbeat/checkpoint now enforce
  actor authority.
- M021: enforced RB-1..6 transition authorization with default-deny —
  `PESEStore._validate_transition` now enumerates `ASSIGNMENT_STATUS`,
  `MISSION_STATUS`, `VALIDATION_GATE`, `AGENT_STATUS`, `RISK_STATUS`,
  `TRANSPORT_STATUS`, `MISSION_INTERRUPT_RECOVERY`, and `SCHEDULER_STATUS`
  with per-kind authorization checks, then denies any unknown kind unless
  the actor holds orchestrator authority; RKM risk transitions require the
  risk owner or an orchestrator-role actor; ETR channel binds require the
  sender or orchestrator, and revokes/opens require an endpoint or
  orchestrator; TBE `bind_manifest_to_pese` requires orchestrator authority.
- M022: fail-closed defense-in-depth for RB-5/7/8/9/12 — AHP `heartbeat`
  rejects third-party reporting and `_safe_id` percent-encodes traversal
  names; AHP `agent_health` verifies the full heartbeat journal hash chain
  before deriving liveness (fail-closed `JOURNAL_CORRUPT`); VAL `verify`
  forces `all_match=False` on corrupt state; CKS validates `key_id` before
  any path construction.

### Security

- Fail-closed authorization: all PESE transitions are default-deny with
  per-kind actor checks (RB-1..6, RB-10, RB-11).
- Fail-closed integrity: health, status, and key journals verify their
  hash chains before reporting; corrupted journals raise instead of
  serving unverified state (RB-7, RB-9, RB-11).
- Input containment: agent IDs and key IDs are validated and
  percent-encoded before path construction to reject traversal names
  (RB-5, RB-9).
- Tamper-evident audit trail: ACP audit journals, EEF execution journals,
  CKS signing ledgers, and AHP heartbeat journals are all append-only and
  hash-chained.
- Transport security: RFC 8439 ChaCha20-Poly1305 AEAD envelopes bind the
  envelope header as authenticated data; any metadata or ciphertext
  tampering fails at open time.
- Release security: the REL v1.0 verifier is deterministic, reads only
  local files, and certifies the dependency-free wheel contract.
