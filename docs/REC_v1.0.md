# Recovery Engine — REC v1.0

## 1. PURPOSE AND SCOPE

REC v1.0 is the deterministic agent-recovery runtime that automates the multi-step recovery sequence when an agent fails or stalls. REC bridges the gap between AHP's liveness detection and AGC's lifecycle: when AHP reports a STALLED agent or AGC reports a FAILED / QUARANTINED agent, REC orchestrates quarantine → release → register replacement → activate → dependency VERIFIED → ready → claim, persists a recovery ledger over PESE `recovery_state`, and emits `RECOVERY_*` events to the EEF execution journal.

Today an operator must run 7+ manual AGC commands to recover a failing agent. REC reduces that to one deterministic `recovery-run` invocation while preserving a durable audit trail of every recovery attempt. It closes the loop between AHP's stall detection and AGC's lifecycle the same way AHP's `health-check` signaled M017's need.

**Boundary.** REC orchestrates recovery by calling AGC's `AgentLifecycle` and (read-only) AHP's `HealthStore`. It does not define new agent lifecycle transitions (AGC owns those), schedule dispatch (EEF), execute work (AEX), manage risks (RKM), validate gates (VAL), assemble teams (TBE), or manage keys (CKS). Encrypted transport and autonomous workflow scheduling remain outside scope.

## 2. ARCHITECTURE AND BOUNDARY

REC operates as a deterministic orchestration runtime layered on top of the existing runtimes:

```text
+-----------------------------------------------+
|     Operators / CLI / M019 scheduler / AEX    |
+-----------------------------------------------+
| REC v1.0  (this contract)                     |
|   - diagnose, orchestrated recovery, ledger   |
|   - RECOVERY_* events to EEF journal          |
+-----------------------------------------------+
| AGC v1.0  (lifecycle transitions)             |
| AHP v1.0  (read-only: liveness)               |
| PESE v1.0 (read/write: recovery_state)        |
| EEF v1.0  (append: execution events)          |
+-----------------------------------------------+
```

**Key design decisions:**

1. All recovery-ledger mutations flow through `PESEStore.update()` with transition type `RECOVERY_STATUS`. REC never writes PESE state directly; it relies on the store's legal-transition enforcement and actor authorization.
2. REC enforces its own status state machine (`IN_PROGRESS → {COMPLETED, FAILED}`) because `RECOVERY_STATUS` is not in PESE's legal-transition map (the same pattern used by AGC's `AGENT_STATUS`, RKM's `RISK_STATUS`, and VAL's `VALIDATION_GATE`).
3. The recovery ledger lives under a new top-level PESE key `recovery_state.recoveries`. PESE's `default_state()` includes it and `_validate_state_shape()` permits it; the key is optional so states initialized before REC v1.0 continue to validate.
4. A PESE mandatory checkpoint (`FAILURE`) is recorded only when a recovery record transitions to `FAILED`. Successful recovery (IN_PROGRESS → COMPLETED) does not mark the mission failed.
5. The recovery sequence calls AGC lifecycle methods one step at a time; each step is an individually-atomic PESE transition, and the recovery record is the audit trail. If any step does not return `UPDATED`, the record transitions to `FAILED` with the error detail.
6. Event emission is best-effort: `_emit_event` swallows exceptions to prevent journal failures from blocking recovery mutations.
7. Lock discipline: REC holds a per-path reentrant lock for the duration of a `run` so concurrent recovery attempts cannot collide on recovery-id allocation, while AGC steps (which use their own lock registry) are called without a cross-engine deadlock.

## 3. RECOVERY RECORD SCHEMA

Each recovery is a record stored in `recovery_state.recoveries` under its `recovery_id` key:

```json
{
  "recovery_id": "RECOVERY:0001",
  "format": "REC/v1.0",
  "agent_id": "AGENT:developer:local",
  "trigger": "FAILED",
  "mission_id": "MISSION:example",
  "assignment_id": "ASSIGNMENT:build",
  "acr_ref": "ACR:developer:specialist",
  "replacement_agent_id": "AGENT:developer:local:recovery:1",
  "status": "COMPLETED",
  "actions": ["QUARANTINED", "RELEASED", "REGISTERED", "ACTIVATED", "DEPENDENCY_VERIFIED", "READY", "CLAIMED"],
  "created_at": "2026-08-06T04:00:00.000Z",
  "updated_at": "2026-08-06T04:00:01.000Z",
  "completed_at": "2026-08-06T04:00:01.000Z",
  "error": null
}
```

**Recovery record fields:**

| Field | Meaning |
|---|---|
| `recovery_id` | Canonical recovery identifier, unique across all recoveries (`RECOVERY:NNNN`) |
| `format` | REC format marker, always `REC/v1.0` |
| `agent_id` | The original (failing) agent that was recovered |
| `trigger` | Recovery trigger (`FAILED`, `QUARANTINED`, or `STALLED`) |
| `mission_id` | Owning mission identifier, or `null` |
| `assignment_id` | Owning assignment identifier, or `null` |
| `acr_ref` | ACR reference copied from the original agent to the replacement |
| `replacement_agent_id` | The newly-registered replacement agent |
| `status` | Current recovery status (see state machine below) |
| `actions` | Ordered list of AGC actions successfully applied |
| `created_at` | UTC timestamp when the record was created |
| `updated_at` | UTC timestamp of the last update, or `null` |
| `completed_at` | UTC timestamp of completion/failure, or `null` |
| `error` | Error detail when `status == FAILED`, else `null` |

**Recovery status vocabulary:**

| Status | Meaning |
|---|---|
| `IN_PROGRESS` | Recovery sequence is running (or was interrupted mid-sequence) |
| `COMPLETED` | All required AGC actions applied successfully |
| `FAILED` | An AGC step did not return `UPDATED`; the record retains partial `actions` |

**Legal transitions (REC-enforced):**

| From | To |
|---|---|
| `IN_PROGRESS` | `COMPLETED`, `FAILED` |

There are no reverse transitions.

## 4. TRIGGER MODEL

REC derives a recovery trigger from AGC agent status and AHP liveness:

| AGC Status | AHP Health | Trigger |
|---|---|---|
| `FAILED` | any | `FAILED` |
| `QUARANTINED` | any | `QUARANTINED` |
| `READY`, `BUSY`, `BLOCKED` | `STALLED` | `STALLED` |
| `READY`, `BUSY`, `BLOCKED` | `ALIVE`/`UNKNOWN` | none (not recoverable) |
| `RELEASED`, `REPLACED`, `INITIALIZING`, `REGISTERED` | any | none (not recoverable) |

**Not recoverable reasons:**

- `RELEASED` / `REPLACED`: the agent has exited the lifecycle and is not a recovery candidate.
- `INITIALIZING` / `REGISTERED`: the agent has not reached lifecycle activation.
- Healthy `READY` / `BUSY` / `BLOCKED`: heartbeat is fresh; the agent is alive.
- AHP reports `STALLED` but AGC status is outside the recoverable set.

`diagnose` returns a `RecoveryDiagnosis` (read-only) with `recoverable=True/False`, the trigger, mission/assignment/acr_ref from the agent record, and a suggested replacement ID. `run` raises `RecoveryError("NOT_RECOVERABLE")` when the agent cannot be recovered.

## 5. RECOVERY LIFECYCLE

A recovery progresses through a deterministic lifecycle:

```text
                 ┌────────────────────────────┐
                 ▼                            │
diagnose ──► IN_PROGRESS ──► COMPLETED        │
                     │                        │
                     └──► FAILED ─────────────┘
```

**Recovery sequence (each step must return `UPDATED`):**

| Step | AGC call | Appended action |
|---|---|---|
| 1 | `quarantine(agent_id, actor, "RECOVERY")` | `QUARANTINED` |
| 2 | `release(agent_id, actor)` | `RELEASED` |
| 3 | `register(replacement_id, acr_ref, actor)` | `REGISTERED` |
| 4 | `activate(replacement_id, actor)` | `ACTIVATED` |
| 5 | `set_dependency(replacement_id, "VERIFIED", actor, tool_dependencies, environment_dependencies)` | `DEPENDENCY_VERIFIED` |
| 6 | `ready(replacement_id, actor)` | `READY` |
| 7 | `claim(replacement_id, mission_id, assignment_id, actor)` — only when both mission and assignment are present | `CLAIMED` |

**Details:**

- The replacement ID defaults to `{agent_id}:recovery:{N}` (first unused counter). Tool and environment dependencies are copied from the original agent's `dependency_environment_state` so the replacement is provisioned identically.
- Claim is skipped (replacement left `READY`, `CLAIMED` absent) when `assignment_id` is absent — e.g. the original agent was READY-assigned but never BUSY.
- When the sequence completes, the record transitions to `COMPLETED` (`RECOVERY_COMPLETED` event). When any step fails, the record transitions to `FAILED` with the error detail (`RECOVERY_FAILED` event).
- A PESE mandatory `FAILURE` checkpoint is written only on the `FAILED` transition.

## 6. EVENT JOURNAL

Every recovery mutation emits an event to the EEF execution journal (hash-chained `execution-events.jsonl`). Events use the `RECOVERY_*` event types registered in the EEF `EVENT_TYPES` frozenset:

| Transition | Event Type |
|---|---|
| Record created (`IN_PROGRESS`) | `RECOVERY_STARTED` |
| Record → `COMPLETED` | `RECOVERY_COMPLETED` |
| Record → `FAILED` | `RECOVERY_FAILED` |

Event emission is best-effort: exceptions are swallowed so journal failures never block recovery mutations. The journal event includes `agent_id`, `trigger`, and `replacement_agent_id` (started), and `replacement_agent_id` + `actions` (completed) or `error` + `actions_completed` (failed) in the `detail` field.

## 7. CLI REFERENCE

All commands accept `--root <path>` (default: current directory) and emit machine-readable `key=value` output to stdout. Deterministic exit codes: 0 for success, 2 for error/failure.

| Command | Description | Exit 2 on |
|---|---|---|
| `recovery-diagnose` | Pre-flight assessment of a potentially failing agent | agent not found |
| `recovery-run` | Execute the full recovery sequence | agent not recoverable, trigger unknown, any AGC step failure |
| `recovery-status` | Read a single recovery record | recovery not found |
| `recovery-list` | List recovery records (optionally filtered) | — |
| `recovery-report` | Aggregated recovery summary | — |

**Arguments:**

- `recovery-diagnose`: `--agent` (required), `--actor` (optional).
- `recovery-run`: `--agent` (required), `--trigger` (optional, override), `--replacement` (optional, override), `--mission-id` (optional, override), `--assignment-id` (optional, override), `--actor` (optional).
- `recovery-status`: `--recovery-id` (required), `--actor` (optional).
- `recovery-list`: `--mission-id` (optional), `--agent-id` (optional), `--status` (optional), `--actor` (optional).
- `recovery-report`: `--actor` (optional).

**Output examples:**

`recovery-run` on a FAILED agent:
```text
recovery_id=RECOVERY:0001
status=COMPLETED
replacement_agent_id=AGENT:developer:local:recovery:1
actions=QUARANTINED,RELEASED,REGISTERED,ACTIVATED,DEPENDENCY_VERIFIED,READY,CLAIMED
mission_id=MISSION:example
assignment_id=ASSIGNMENT:build
error=
```

`recovery-report`:
```text
total=1
in_progress_count=0
completed_count=1
failed_count=0
```

## 8. ERROR HANDLING

| Error Code | When |
|---|---|
| `AGENT_NOT_FOUND` | Requested agent does not exist in agent_state (from AGC, surfaced as RecoveryError) |
| `RECOVERY_NOT_FOUND` | Requested recovery_id does not exist in recovery_state |
| `NOT_RECOVERABLE` | The agent's status/health combination has no valid trigger |
| `TRIGGER_UNKNOWN` | No trigger could be resolved for `recovery-run` |
| `STATE_LOAD_FAILED` | PESE state could not be loaded or is missing revision/sha256 |
| `INVALID_TRANSITION` | A recovery record transition violates the REC state machine |

Any AGC step that raises or returns a non-`UPDATED` outcome does not abort the command with exit 2; instead the recovery record transitions to `FAILED` and the command exits 2 with `status=FAILED` and the error detail.

## 9. ON-DISK LAYOUT

REC state is persisted within PESE's canonical layout:

```text
.project-os/
├── PESE/
│   ├── live.json          ← recovery_state.recoveries
│   ├── checkpoints/       ← FAILURE checkpoint only on recovery FAILED
│   └── ...
└── AUDIT/
    └── execution-events.jsonl   ← RECOVERY_* events appended here
```

Recovery records live in `state.recovery_state.recoveries[recovery_id]`. The key is created lazily by `state.setdefault("recovery_state", {})` and is present in fresh `default_state()`.

## 10. COMPATIBILITY

REC v1.0 is additive — it adds a recovery ledger to existing PESE state without modifying any prior contract. Existing PESE, TBE, MSS, EEF, CKS, AEX, AHP, VAL, RKM, and AGC commands continue to work unchanged.

The `RECOVERY_STATUS` transition type is not in PESE's legal-transition map; REC enforces its own state machine (same pattern as AGC's `AGENT_STATUS`, RKM's `RISK_STATUS`, and VAL's `VALIDATION_GATE`). The recovery ledger key `recovery_state` is optional in PESE's state-shape validation so states initialized before REC v1.0 remain valid.

## 11. IMPLEMENTATION REQUIREMENTS

1. `src/asc_orchestrator/recovery.py` must implement `RecoveryEngine`, `RecoveryError`, `RecoveryDiagnosis`, `RecoveryRecord`, `RecoveryOutcome`, and `RecoveryReport` using only stdlib.
2. All recovery-ledger mutations must flow through `PESEStore.update()` with `transition_type="RECOVERY_STATUS"`.
3. The recovery sequence must call AGC lifecycle methods in order and copy the original agent's tool/environment dependencies to the replacement.
4. Trigger derivation must implement the trigger model from section 4 (AGC FAILED/QUARANTINED, or READY/BUSY/BLOCKED + AHP STALLED).
5. Claim must be skipped when `assignment_id` is absent, leaving the replacement `READY`.
6. Event emission must use `EEFEventJournal.append()` with the three `RECOVERY_*` event types.
7. PESE must register the `recovery_state` top-level key in `default_state()` and permit it in `_validate_state_shape()` (optional).
8. PESE's `MANDATORY_CHECKPOINTS["RECOVERY_STATUS"]` must map only `FAILED → FAILURE` so successful recovery does not mark the mission failed.

## 12. IMPLEMENTATION GATES

REC v1.0 is complete when:

1. `docs/REC_v1.0.md` is ratified with all required sections (purpose, architecture, record schema, trigger model, lifecycle, events, CLI reference, error handling, layout, compatibility, requirements, implementation gates, and terminal marker).
2. `src/asc_orchestrator/recovery.py` implements `RecoveryEngine`, `RecoveryError`, `RecoveryDiagnosis`, `RecoveryRecord`, `RecoveryOutcome`, and `RecoveryReport` using only stdlib.
3. Recovery-ledger mutations flow through `PESEStore.update()` with `transition_type="RECOVERY_STATUS"`.
4. Three `RECOVERY_*` event types are registered in EEF's `EVENT_TYPES` frozenset.
5. Five `recovery-*` CLI subcommands emit machine-readable outcomes and deterministic exit codes.
6. `tests/test_recovery.py` exercises diagnose (FAILED/STALLED/not-recoverable), run (COMPLETED with and without claim, FAILED on step failure), status/list/report, event journal integrity, and backward compatibility.
7. `tests/test_recovery_cli.py` exercises the full CLI lifecycle including exit codes.
8. `python -m mypy` passes on `src`.
9. `python -m ruff check src tests scripts` and `ruff format --check` pass.
10. `python scripts/validate_docs.py` passes with REC spec coverage.
11. `python -m unittest discover -s tests -t .` passes (existing + new REC tests).

**END OF SPECIFICATION — REC v1.0**
