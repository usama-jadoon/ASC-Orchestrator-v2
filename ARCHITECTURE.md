# ASC Orchestrator v2 — Architecture

This document describes the internal architecture of ASC Orchestrator v2
(version 1.0.2). It is written for engineers who need to understand how the
runtime is organized, how state flows through it, and how the security
model is enforced.

---

## 1. System overview

ASC Orchestrator v2 is a deterministic, auditable runtime for the assembly
and operation of autonomous software-company agents. Given a mission
specification, it:

1. validates the mission (MSS),
2. assembles a registry-backed team with exclusive ownership and
   dependency graphs (TBE),
3. persists all mission, execution, validation, risk, agent, recovery, and
   transport state through one typed transactional store (PESE),
4. drives the mission through a typed lifecycle with a hash-chained event
   journal (EEF),
5. signs work and records keys in a hash-chained ledger (CKS),
6. executes agent work and persists artifacts (AEX),
7. observes liveness (AHP), validates gates (VAL), manages risk (RKM),
   controls the agent lifecycle (AGC), and recovers failed agents (REC),
8. encrypts payloads in transit (ETR),
9. makes one prioritized scheduling decision per tick (AWS), and
10. certifies the whole tree is production-ready (REL).

Design invariants:

- **Deterministic.** No randomness, no wall-clock dependence in decisions,
  no network calls. Timestamps are injected or recorded from the local
  clock at mutation time, and scheduling ties break lexicographically.
- **Standard-library only.** The runtime has zero external dependencies and
  runs on Python 3.11+.
- **Audited.** Every state mutation flows through `PESEStore.update()` and
  is recorded in a hash-chained audit stream; every contract-level event is
  appended to the hash-chained EEF execution journal.
- **Fail-closed.** Authorization is default-deny, integrity checks raise
  rather than report unverified state, and tampered inputs halt mutations.

---

## 2. Module map

All runtime code lives in `src/asc_orchestrator/`. The table maps each of
the 22 modules to the canonical contract it implements (if any).

| Module | Contract | Responsibility |
| --- | --- | --- |
| `acp.py` | ACP v1.0 | Message model, validation, serialization/parsing. |
| `audit.py` | ACP v1.0 | Append-only hash-chained ACP audit journal under `.project-os/AUDIT/`. |
| `registry.py` | ACR v1.0 | Deterministic ACR registry loading and validation. |
| `config.py` | — | TOML runtime configuration (`RuntimeConfig`, `load_config`). |
| `errors.py` | — | Shared exceptions (`ContractValidationError`, `ConfigurationError`). |
| `pese.py` | PESE v1.0 | `PESEStore`: state, checkpoints, locking, resume, recovery, migration, audits. |
| `tbe.py` | TBE v1.0 | Team assembly: `build_team`, `TeamManifest`, `bind_manifest_to_pese`. |
| `mss.py` | MSS v1.0 | `MissionSpec`, `validate_mission_spec`, `load_mission_spec`. |
| `execution.py` | EEF v1.0 | `ExecutionContext`, `ExecutionSession`, `EEFEventJournal`. |
| `keys.py` | CKS v1.0 | `KeyStore`: HMAC-SHA256 keys, signing ledger, status journals. |
| `aex.py` | AEX v1.0 | `AEX`: assignment dispatch/complete/fail/block, results, artifacts. |
| `health.py` | AHP v1.0 | `HealthStore`: heartbeat journals and ALIVE/STALLED/UNKNOWN status. |
| `validation.py` | VAL v1.0 | `ValidationEngine`: gate lifecycle, SHA-256-bound artifacts, verify. |
| `risk.py` | RKM v1.0 | `RiskEngine`: risk ledger, status state machine, hold mechanism. |
| `agent.py` | AGC v1.0 | `AgentLifecycle`: agent status machine, dependency-gated readiness. |
| `recovery.py` | REC v1.0 | `RecoveryEngine`: diagnose and run deterministic agent recovery. |
| `etr.py` | ETR v1.0 | `EncryptedTransport`: ChaCha20-Poly1305 channels and envelopes. |
| `aws.py` | AWS v1.0 | `AutonomousScheduler`: one prioritized decision per tick. |
| `release.py` | REL v1.0 | `verify`/`render`: nine-gate deterministic release verifier. |
| `cli.py` | — | `argparse` CLI dispatching to all runtimes; `main()` entry point. |
| `__init__.py` | — | Package exports (`RuntimeConfig`, `load_config`). |
| `__main__.py` | — | `python -m asc_orchestrator` entry point. |

Notable class names used across the architecture:

- `PESEStore` (`pese.py`) — `initialize`, `load`, `validate`, `update`,
  `checkpoint`, `resume`, `recover`, `migrate`, `acquire_lock`,
  `renew_lock`, `release_lock`.
- `ExecutionSession` (`execution.py`) — `start`, `schedule`, `pause`,
  `resume_session`, `cancel`, `complete`, `status`.
- `KeyStore` (`keys.py`) — `create_key`, `sign`, `verify`, `rotate`,
  `revoke`, `validate`.
- `AutonomousScheduler` (`aws.py`) — `enable`, `disable`, `evaluate`,
  `tick`, `status`, `cycle`, `list_cycles`, `report`.
- `AgentLifecycle` (`agent.py`), `RecoveryEngine` (`recovery.py`),
  `ValidationEngine` (`validation.py`), `RiskEngine` (`risk.py`),
  `EncryptedTransport` (`etr.py`), `AEX` (`aex.py`), `HealthStore`
  (`health.py`).

---

## 3. State persistence model

### 3.1 PESE state store

All persistent runtime state is owned by `PESEStore`, rooted at
`.project-os/PESE/` under the repository root. The canonical layout
(`REQUIRED_DIRS`) is:

```text
.project-os/PESE/
|-- state/
|   |-- live.json                 # current envelope (state + sha256 + revision)
|   `-- history/
|       `-- 1.json                # immutable revision history
|-- checkpoints/                  # CP-<id>-<ts>-<seq>.json checkpoints
|-- locks/
|   `-- state.lock.json           # single-writer lease lock
|-- migrations/                   # schema migration records
|-- audit/
|   |-- access/                   # access-audit stream (hash-chained)
|   `-- transitions/              # transition-audit stream (hash-chained)
`-- recovery/                     # recovery records
```

The top-level state shape (`PESEStore.default_state`) is:

```text
schema_version        "1.0.0"
company_state         company_id, status, protocol refs, timestamps
repo_state            observed repository head observation
mission_state         active_mission_id, missions{}
execution_state       current_milestone_id, milestones[], assignments{},
                      next_task_candidates[]
validation_state      gates{}, artifacts{}
risk_state            risks{}
agent_state           agents{}
recovery_state        recoveries{}
transport_state       channels{}, envelopes{}
extensions            reverse-DNS extension keys (org.asc.*)
```

Every mutation goes through the keyword-only
`PESEStore.update(expected_revision, actor, transition_type, subject,
from_value, to_value, mutate)`:

1. acquire the writer lease lock,
2. validate the requested transition (legal status map + authorization),
3. call the `mutate` callback on the state copy,
4. recompute `state_sha256`, increment `revision`,
5. append a transition-audit record and emit a PESE outcome.

Mandatory checkpoints fire on specific transitions (`MANDATORY_CHECKPOINTS`):
mission `ACTIVE`/`COMPLETED`/`CANCELLED`/`FAILED`, any gate verdict, agent
`FAILED`/`QUARANTINED`, recovery `FAILED`, and repository-head changes.

### 3.2 Contract-owned runtime state

Several runtimes own state keys or files outside the PESE envelope:

| Runtime | Location | Contents |
| --- | --- | --- |
| EEF | `.project-os/AUDIT/execution-events.jsonl` | Hash-chained event journal; all `*_` events from every runtime. |
| CKS | `.project-os/KEYS/` | Immutable key records, status journals, per-key signing ledgers. |
| AEX | `.project-os/ARTIFACTS/<mission>/<assignment>/` | `result.json` and copied artifacts; IDs percent-encoded (`%3A`). |
| AHP | `.project-os/HEALTH/agents/` | Per-agent append-only hash-chained heartbeat journals. |
| TBE | `.project-os/COMPANY/TEAMS/<team-id%3A-encoded>/TEAM.md` | Canonical `TEAM.md` manifests (`:` encoded as `%3A`). |
| ACR | `.project-os/COMPANY/DEPARTMENTS/` | JSON registry entries. |

### 3.3 Hash-chained journals

Four journal families are append-only and hash-chained:

- **ACP audit** (`audit.py`) — `AuditJournal.append` writes JSONL records
  where each entry stores the previous entry hash; `verify_chain()` checks
  the whole chain.
- **EEF execution events** (`execution.py`) — `EEFEventJournal.append`
  writes JSONL events to `.project-os/AUDIT/execution-events.jsonl`; every
  runtime emits its namespaced events here.
- **CKS signing ledger** (`keys.py`) — per-key JSONL ledger with
  entry-hash chaining; `verify_chain()` checks both the signing ledger and
  the status journal.
- **AHP heartbeats** (`health.py`) — per-agent JSONL journals with
  `previous_heartbeat_sha256` chaining; `agent_health()` verifies the full
  chain before deriving liveness.

---

## 4. Authorization model

Authorization is enforced centrally in `PESEStore._validate_transition`
and per-engine. The model is **default-deny**: an unknown transition kind
requires orchestrator authority.

The orchestrator identity is the constant `AGENT:orchestrator:local`.
Per-kind rules:

| Transition kind | Who may mutate |
| --- | --- |
| `MISSION_STATUS` | A member of the mission's `assigned_agent_ids`. |
| `ASSIGNMENT_STATUS` | The assigned agent (assignment ownership must match the manifest). |
| `VALIDATION_GATE` | The gate's designated validator. |
| `AGENT_STATUS` | The orchestrator or the target agent itself (engine-enforced `_require_authority`). |
| `RISK_STATUS` | The risk owner or an orchestrator-role actor. |
| `TRANSPORT_STATUS` | Channel bind: sender or orchestrator; channel revoke / envelope open: an endpoint or orchestrator. |
| `MISSION_INTERRUPT_RECOVERY` | Orchestrator (resume path). |
| `SCHEDULER_STATUS` | Orchestrator. |
| Unknown kind | Denied unless the actor holds orchestrator authority. |

Engine-level additions:

- AEX `_require_actor` — only the assignment's `assigned_agent_id` may
  transition it.
- AGC `_require_authority` — only the orchestrator or the target agent.
- VAL `_require_validator` — only the gate's designated validator.
- RKM transition checks — risk owner or orchestrator-role actor.
- REC recovery mutations resolve to the orchestrator acting for the agent.
- TBE `bind_manifest_to_pese` requires orchestrator authority.

---

## 5. Data flow

### 5.1 Agent lifecycle (AGC) and recovery (REC)

```text
                        AGC (agent.py)                    AHP (health.py)
  orchestrator    +---------------------------+      +---------------------+
      |           | register -> INITIALIZING   |      | heartbeat (self)    |
      |           | activate -> REGISTERED     |      |   append + chain    |
      |           | dependency VERIFIED        |      +----------+----------+
      |           | ready -> READY             |                 |
      |           | claim -> BUSY (mission)    |                 v
      |           | complete -> READY          |        liveness ALIVE/STALLED
      |           | fail/quarantine/replace/   |                 |
      |           |   release (terminal)       |                 |
      +-----------+---------------------------+                 |
                                |  PESEStore.update(AGENT_STATUS) |
                                v                                |
                     +----------------------+                    |
                     | PESE agent_state     |                    |
                     | (agents ledger)      | <------------------+
                     +----------------------+
                                |
                                v  EEF journal: AGENT_* events
                     +---------------------------------------+
                     | .project-os/AUDIT/execution-events.jsonl |
                     +---------------------------------------+
                                ^
                                |
  REC (recovery.py): diagnose -> run -> quarantine -> release ->
  register replacement -> activate -> dependency VERIFIED -> ready ->
  claim   (claims only when an assignment exists; otherwise READY)
  every mutation: PESEStore.update(RECOVERY_STATUS) + RECOVERY_* events
```

### 5.2 Mission execution (MSS -> TBE -> EEF -> AEX)

```text
 mission.json          classifications.json
     |                        |
     v                        v
  MSS validate_mission   TBE build_team (registry-only selection)
     |                        |
     |                        v
     |              TEAM.md manifest (ownership, deps, reviewers)
     |                        |
     +-----------> PESEStore.update (planned mission + manifest binding)
                        |
                        v
             EEF ExecutionSession.start -> ACTIVE
                        |
                        v
             EEF schedule -> FIFO dispatch decision
                        |
                        v
             AEX dispatch -> IN_PROGRESS (actor = assigned agent)
                        |
                        v
             AEX complete -> result.json + artifacts + optional CKS sign
                        |
                        v
             EEF complete -> VALIDATING -> validation gates
                        |
                        v
             EEF event journal: SESSION_*/ASSIGNMENT_*/MILESTONE_*
```

### 5.3 Validation (VAL)

```text
  validation-start            validation-finish
  (PENDING -> RUNNING)        (RUNNING -> GREEN/RED/BLOCKED)
        |                              |
        v                              v
  PESEStore.update(VALIDATION_GATE)  + bind artifact SHA-256 on GREEN
        |                              |
        v                              v
  EEF journal GATE_STARTED        EEF journal GATE_PASSED/GATE_FAILED/
                                   GATE_BLOCKED
                                          |
                                          v
  validation-verify -> compare artifact file hash to recorded SHA-256
        |  tampered -> secure halt (no mutation) ; BINDING_INTACT -> keep
        v
  validation-invalidate -> GREEN -> INVALIDATED (operator recovery action,
        only when the binding precondition failed)
```

### 5.4 Risk hold mechanism (RKM) and scheduler (AWS)

```text
  risk-open/risk-mitigate/risk-accept/risk-resolve/risk-halt
        |
        v
  PESEStore.update(RISK_STATUS) + RISK_* events
        |
        v
  risk-check (mission-scoped + company-wide)
        |
        +--> HALT risk, unresolved CRITICAL, or HIGH with declared
        |     block condition  ->  exit 2 (autonomous execution blocked)
        +--> otherwise         ->  exit 0

  scheduler-tick
        |
        v
  AWS evaluate() reads PESE + AGC + AHP + REC + RKM + VAL + CKS + ETR
        |
        v
  exactly one decision: HOLD(100) RECOVER(90) START_MISSION(80)
                        DISPATCH(70) VALIDATE(60) COMPLETE_MISSION(50)
                        MONITOR_HEALTH(40) IDLE(0)
        |
        v
  if enabled and actionable -> delegate to owning runtime
        |
        v
  persist cycle record under extensions["org.asc.aws"] + SCHEDULER_* event
```

---

## 6. Security architecture

The security posture is fail-closed: unverifiable state is treated as a
block, unauthorized actors are denied, and tampered inputs halt mutations.

### 6.1 Release-blocker remediation (RB-1..12)

The RB fixes closed twelve release blockers before publication:

| RB | Area | Remediation |
| --- | --- | --- |
| RB-1 | PESE | `_validate_transition` enumerates per-kind authorization and defaults to deny for unknown kinds. |
| RB-2 | RKM | Risk mutations require the risk owner or an orchestrator-role actor. |
| RB-3 | ETR | Channel bind requires the sender or orchestrator. |
| RB-4 | ETR | Channel revoke and envelope open require an endpoint or orchestrator. |
| RB-5 | AHP | `heartbeat()` rejects third-party reporting; `_safe_id` percent-encodes every character outside `[A-Za-z0-9._-]` and encodes a leading dot. |
| RB-6 | TBE | `bind_manifest_to_pese` requires orchestrator authority. |
| RB-7 | AHP | `agent_health()` verifies the full heartbeat chain before deriving liveness; corrupted journal raises `JOURNAL_CORRUPT`. |
| RB-8 | VAL | `verify()` forces `all_match=False` on `STATE_CORRUPT`; unverified state is never authoritative. |
| RB-9 | CKS | `key_id` is validated (rejects `..`, `/`, `\`, NUL) before any path construction; `KEY_ID_INVALID`. |
| RB-10 | AWS | `_blocking_risk_check` fails closed — risk evaluation errors force HOLD. |
| RB-11 | CKS | Status journals fail closed — missing/corrupt/broken-chain raise `LEDGER_BROKEN`; `verify()` returns False on broken status. |
| RB-12 | AGC | `register` restricted to orchestrator authority; heartbeat and checkpoint enforce actor authority. |

### 6.2 Cryptographic primitives

- **CKS** — HMAC-SHA256 signing with constant-time verification and a
  hash-chained per-key signing ledger.
- **ETR** — RFC 8439 ChaCha20-Poly1305 AEAD (pure-Python, stdlib-only)
  with the envelope header bound as authenticated data.
- **Integrity** — SHA-256 state hashes (`state_sha256`), per-record
  entry hashes, and hash-chained journals throughout.

### 6.3 Threat posture summary

| Threat | Defense |
| --- | --- |
| Unauthorized state mutation | Default-deny per-kind authorization, orchestrator authority, agent self-authority. |
| Journal tampering | Hash-chained append-only journals verified on read. |
| Tampered validation artifacts | SHA-256 binding; `verify()` detects tampering/deletion; mutations halt. |
| Path traversal via IDs | `_safe_id` percent-encoding and key-id validation before path construction. |
| Ciphertext tampering | Poly1305 tag verification; `AUTH_FAILED` and exit 2. |
| Unverifiable release tree | REL nine-gate deterministic verification before packaging. |

---

## 7. Extension model

PESE state carries a top-level `extensions` mapping keyed by reverse-DNS
extension keys (`EXTENSION_KEY_RE`). Contract-specific runtimes store their
private state there and are responsible for its schema:

| Extension key | Owner | Contents |
| --- | --- | --- |
| `org.asc.tbe` | TBE | Planned-mission manifest binding produced by `bind_manifest_to_pese`. |
| `org.asc.eef` | EEF | Session status and lifecycle state. |
| `org.asc.rkm` | RKM | HIGH-risk block conditions per risk id. |
| `org.asc.aws` | AWS | Scheduler config and durable cycle records. |

Note: `asc_orchestrator/keys.py` defines an unused `KEYS_EXTENSION_KEY`
constant (`org.asc.cks`), but CKS never reads or mutates PESE state — keys,
status journals, and signing ledgers live entirely under `.project-os/KEYS/`.

PESE enforces extension-key shape but does not interpret extension payloads:
each owning runtime reads and writes its own extension and remains
responsible for its validation. This is the primary extension point for new
contracts — see [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) for how to add a
new contract and extension.
