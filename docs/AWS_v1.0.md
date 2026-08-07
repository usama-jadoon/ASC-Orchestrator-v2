# Autonomous Workflow Scheduler — AWS v1.0

## 1. PURPOSE AND SCOPE

AWS v1.0 is the deterministic, stdlib-only top-level orchestration runtime that evaluates full system state — consuming PESE, EEF, AGC, AHP, REC, RKM, VAL, CKS, and ETR — and produces one deterministic scheduling decision per tick. If the scheduler is ACTIVE and the decision is actionable, AWS delegates the action to the owning runtime and persists a cycle record under the `org.asc.aws` PESE extension. All state mutations flow through PESEStore.update() with transition type `SCHEDULER_STATUS`.

Today an operator has no machine-verifiable way to run a single deterministic decision loop that evaluates the entire ASC system state and produces one actionable scheduling choice. AWS closes that gap by consuming every existing runtime's state and emitting one prioritised decision per tick, persisted as a durable cycle record with full EEF event-journal provenance.

**Boundary.** AWS manages scheduler configuration and cycle records using PESE state and EEF events. It does not manage agent lifecycle (AGC), schedule dispatch (EEF/AEX), manage risks (RKM), validate gates (VAL), assemble teams (TBE), assemble missions (MSS), diagnose health (AHP), orchestrate recovery (REC), validate state (VAL), execute work (AEX), seal or open transport (ETR), or generate or rotate keys (CKS).

## 2. ARCHITECTURE AND BOUNDARY

AWS operates as a deterministic evaluation-and-delegation runtime layered on the existing runtimes:

```text
+-----------------------------------------------+
|     Operators / CLI / orchestrator / agents    |
+-----------------------------------------------+
| AWS v1.0  (this contract)                     |
|   - single-tick evaluation (priority model)   |
|   - scheduler ENABLED / DISABLED toggle       |
|   - CYCLE records persisted to PESE            |
|   - SCHEDULER_* events to EEF journal          |
+-----------------------------------------------+
| AGC v1.0  (read: agent status)                |
| AHP v1.0  (read: stalled agents)              |
| EEF v1.0  (read/write: dispatch + events)     |
| AEX v1.0  (write: assignment dispatch)        |
| REC v1.0  (write: recovery run)               |
| RKM v1.0  (read: blocking risk check)         |
| VAL v1.0  (write: gate start)                 |
| PESE v1.0 (read/write: scheduler state)       |
+-----------------------------------------------+
```

**Key design decisions:**

1. All scheduler state mutations flow through `PESEStore.update()` with transition type `SCHEDULER_STATUS`. AWS never writes PESE state directly; it relies on the store's legal-transition enforcement and actor authorization.
2. AWS enforces its own cycle counter because `SCHEDULER_STATUS` is not in PESE's legal-transition map (same pattern as AGC's `AGENT_STATUS`, RKM's `RISK_STATUS`, VAL's `VALIDATION_GATE`, REC's `RECOVERY_STATUS`, and ETR's `TRANSPORT_STATUS`).
3. Scheduler state lives under the PESE top-level key `extensions["org.asc.aws"]`, containing a `config` dict (enabled, cycle_count, last_cycle_id, last_decision_type, last_action_code) and a `cycles` dict keyed by `CYCLE:<sequence>`. The extension is optional in `_validate_state_shape()` so pre-AWS states continue to validate.
4. The decision model is deterministic: exactly one decision is selected per tick, with the highest-priority decision winning (ties broken lexicographically). The scheduler does not use randomness, timestamps, or non-deterministic input.
5. The scheduler always evaluates state (returns a decision). When ENABLED, actionable decisions are executed via the owning runtime. When DISABLED, the decision is recorded but no action is taken.
6. The `ACTOR_ORCHESTRATOR = "AGENT:orchestrator:local"` identity can execute any REC, AGC, VAL, or EEF action directly because the orchestrator is the designated state authority in the PESE transition model.
7. Lock discipline: AWS holds a per-path reentrant lock for the duration of each tick, keyed by the PESE directory path.

## 3. SCHEDULER STATE AND CYCLE SCHEMA

### Scheduler Configuration

The scheduler config lives in `extensions["org.asc.aws"].config`:

```json
{
  "enabled": true,
  "cycle_count": 3,
  "last_cycle_id": "CYCLE:00003",
  "last_decision_type": "DISPATCH",
  "last_action_code": "ASSIGNMENT_DISPATCH",
  "last_tick_at": "2026-08-07T04:00:00.000Z"
}
```

| Field | Meaning |
|---|---|
| `enabled` | Whether the scheduler executes actionable decisions (default: `true`) |
| `cycle_count` | Total number of ticks executed since initialization |
| `last_cycle_id` | The canonical identifier of the most recent cycle |
| `last_decision_type` | The decision type of the most recent tick |
| `last_action_code` | The action code of the most recent tick |
| `last_tick_at` | UTC timestamp of the most recent tick |

**Scheduler status vocabulary:**

| Status | Meaning |
|---|---|
| `ACTIVE` | The scheduler is enabled; actionable decisions are executed |
| `DISABLED` | The scheduler is disabled; decisions are evaluated but not executed |

### Scheduling Cycle Record

Each cycle record is stored in `extensions["org.asc.aws"].cycles[cycle_id]`:

```json
{
  "cycle_id": "CYCLE:00001",
  "format": "AWS/v1.0",
  "status": "COMPLETED",
  "decision_type": "DISPATCH",
  "priority": 70,
  "reason": "assignment ASSIGNMENT:build ready for agent AGENT:developer:local",
  "action_code": "ASSIGNMENT_DISPATCH",
  "success": true,
  "created_at": "2026-08-07T04:00:00.000Z",
  "completed_at": "2026-08-07T04:00:00.000Z",
  "mission_id": "MISSION:example",
  "agent_id": "AGENT:developer:local",
  "assignment_id": "ASSIGNMENT:build",
  "detail": {"assignment_id": "ASSIGNMENT:build", "agent_id": "AGENT:developer:local"},
  "requires_ai": false,
  "enabled": true,
  "pese_revision": 5,
  "pese_state_sha256": "d822d015c80b..."
}
```

| Field | Meaning |
|---|---|
| `cycle_id` | Canonical cycle identifier (`CYCLE:<sequence>`, 1-indexed, zero-padded to 5 digits) |
| `format` | AWS format marker, always `AWS/v1.0` |
| `status` | Cycle status: `COMPLETED` (action succeeded or was a no-op) or `FAILED` (action failed) |
| `decision_type` | The decision type selected for this tick (see Decision Model) |
| `priority` | Numeric priority of the decision (higher wins; see Decision Model) |
| `reason` | Human-readable explanation of the decision |
| `action_code` | The action taken: `ASSIGNMENT_DISPATCH`, `EXECUTION_START`, `EXECUTION_COMPLETE`, `RECOVERY_RUN`, `GATE_START`, `HEALTH_CHECK`, `NONE` |
| `success` | Whether the action completed without error |
| `created_at` | UTC timestamp when the tick began |
| `completed_at` | UTC timestamp when the tick completed |
| `mission_id` | The target mission identifier, if applicable |
| `agent_id` | The target agent identifier, if applicable |
| `assignment_id` | The target assignment or gate identifier, if applicable |
| `detail` | Action-specific detail dict |
| `requires_ai` | Always `false` — AWS is fully deterministic |
| `enabled` | Whether the scheduler was enabled at tick time |
| `pese_revision` | PESE state revision after the cycle was persisted |
| `pese_state_sha256` | PESE state SHA-256 after the cycle was persisted |

**Cycle status vocabulary:**

| Status | Meaning |
|---|---|
| `COMPLETED` | The tick executed without error (including no-ops and read-only decisions) |
| `FAILED` | The tick's action failed or the cycle could not be persisted |

## 4. DECISION MODEL

AWS evaluates state once per tick and returns exactly one decision, selected by deterministic priority (highest wins; ties broken by evaluation order).

**Decision types and priorities:**

| Decision | Priority | When |
|---|---|---|
| `HOLD` | 100 | RKM reports a blocking risk (HALT, unresolved CRITICAL, or HIGH with block condition) |
| `RECOVER` | 90 | A FAILED or QUARANTINED agent exists (sorted deterministically), or AHP reports a STALLED agent |
| `START_MISSION` | 80 | No active mission and at least one PLANNED mission exists |
| `DISPATCH` | 70 | An active mission has a READY assignment (via EEF FIFO schedule) |
| `VALIDATE` | 60 | An active mission has a PENDING validation gate |
| `COMPLETE_MISSION` | 50 | All assignments in the active mission are COMPLETED |
| `MONITOR_HEALTH` | 40 | An active mission exists but no higher-priority decision applies |
| `IDLE` | 0 | No planned missions, no active mission, no actionable work |

**Action mapping (when enabled):**

| Decision | Action | Owning Runtime |
|---|---|---|
| `HOLD` | `NONE` (no-op; risk blocks execution) | — |
| `RECOVER` | `RECOVERY_RUN` | REC v1.0 |
| `START_MISSION` | `EXECUTION_START` | EEF v1.0 |
| `DISPATCH` | `ASSIGNMENT_DISPATCH` | AEX v1.0 |
| `VALIDATE` | `GATE_START` | VAL v1.0 |
| `COMPLETE_MISSION` | `EXECUTION_COMPLETE` | EEF v1.0 |
| `MONITOR_HEALTH` | `HEALTH_CHECK` | AHP v1.0 (read-only) |
| `IDLE` | `NONE` (no-op) | — |

**Read-only decisions** (`HOLD`, `MONITOR_HEALTH`, `IDLE`) are always evaluated and recorded, regardless of whether the scheduler is ENABLED or DISABLED. Only actionable decisions (`RECOVER`, `START_MISSION`, `DISPATCH`, `VALIDATE`, `COMPLETE_MISSION`) are executed when enabled, and recorded as no-ops when disabled.

## 5. LIFECYCLE

### Scheduler Toggle

```text
DISABLED ──► ACTIVE ──► DISABLED
```

1. `enable(actor)` — if already ACTIVE, returns `NO_CHANGE`; otherwise transitions ENABLED config to `true`, persists via PESE, emits `SCHEDULER_ENABLED`.
2. `disable(actor)` — if already DISABLED, returns `NO_CHANGE`; otherwise transitions ENABLED config to `false`, persists via PESE, emits `SCHEDULER_DISABLED`.

### Tick

```text
evaluate ──► [execute if enabled] ──► persist cycle record ──► emit event
```

1. `tick(actor)` — loads PESE state, evaluates the decision model, executes the action if the scheduler is ENABLED and the decision is actionable, persists a CYCLE record, and emits `SCHEDULER_CYCLE_COMPLETED`.
2. If the cycle record cannot be persisted (PESE update returns non-UPDATED), a FAILED cycle is returned but no event is emitted.

### Evaluation (read-only)

```text
evaluate ──► SchedulingDecision
```

1. `evaluate(actor)` — loads PESE state, evaluates the decision model, and returns a read-only `SchedulingDecision` without persisting anything or emitting events.

## 6. EVENT JOURNAL

Every tick and scheduler toggle emits an event to the EEF execution journal (hash-chained `execution-events.jsonl`). Events use the `SCHEDULER_*` event types registered in the EEF `EVENT_TYPES` frozenset:

| Transition | Event Type |
|---|---|
| Scheduler enabled | `SCHEDULER_ENABLED` |
| Scheduler disabled | `SCHEDULER_DISABLED` |
| Cycle completed (tick) | `SCHEDULER_CYCLE_COMPLETED` |

Event emission is best-effort: exceptions are swallowed so journal failures never block scheduler state mutations. The journal event includes `decision_type`, `action_code`, and `success` in the `detail` field for cycle events.

## 7. CLI REFERENCE

All commands accept `--root <path>` (default: current directory) and emit machine-readable `key=value` output to stdout. Deterministic exit codes: 0 for success, 2 for error/failure.

| Command | Description | Exit 2 on |
|---|---|---|
| `scheduler-tick` | Execute one deterministic AWS v1.0 scheduling cycle | tick action failed |
| `scheduler-enable` | Enable autonomous scheduling | PESE persistence failed |
| `scheduler-disable` | Disable autonomous scheduling | PESE persistence failed |
| `scheduler-status` | Read the current scheduler snapshot | — |
| `scheduler-cycle` | Read a single scheduling cycle record | cycle not found |
| `scheduler-list` | List all scheduling cycle records | — |
| `scheduler-report` | Aggregated scheduler summary | — |

**Arguments:**

- `scheduler-tick`: `--actor` (optional).
- `scheduler-enable`: `--actor` (optional).
- `scheduler-disable`: `--actor` (optional).
- `scheduler-status`: `--actor` (optional).
- `scheduler-cycle`: `--cycle-id` (required), `--actor` (optional).
- `scheduler-list`: `--actor` (optional).
- `scheduler-report`: `--actor` (optional).

**Output examples:**

`scheduler-tick`:
```text
cycle_id=CYCLE:00001
status=COMPLETED
decision_type=IDLE
priority=0
reason=no missions and no actionable work
action_code=NONE
success=true
mission_id=
agent_id=
assignment_id=
detail={"disabled": false}
```

`scheduler-status`:
```text
enabled=true
active_mission_id=MISSION:example
cycle_count=3
last_cycle_id=CYCLE:00003
last_decision_type=DISPATCH
last_action_code=ASSIGNMENT_DISPATCH
reason=
```

`scheduler-report`:
```text
enabled=true
total_cycles=3
completed_cycles=3
failed_cycles=0
decision_counts={"DISPATCH": 2, "IDLE": 1}
action_counts={"ASSIGNMENT_DISPATCH": 2, "NONE": 1}
last_cycle_id=CYCLE:00003
```

## 8. ERROR HANDLING

| Error Code | When |
|---|---|
| `STATE_LOAD_FAILED` | PESE load returned a non-STATE_LOADED outcome or state was missing revision/sha256 |
| `CYCLE_NOT_FOUND` | Requested `cycle_id` does not exist in `extensions["org.asc.aws"].cycles` |
| `RECOVERY_SKIP` | RECOVER decision targeted an agent with no agent_id |
| `EXECUTION_SKIP` | START_MISSION or COMPLETE_MISSION decision targeted no mission |
| `ASSIGNMENT_SKIP` | DISPATCH decision had missing mission/assignment/agent identifiers |
| `GATE_SKIP` | VALIDATE decision had missing mission or gate identifiers |

Execution errors within delegate runtimes (REC, EEF, AEX, VAL) are caught per-action and recorded in the cycle's `detail` dict as `{"error": "..."}` with `success=false`, never propagated as AWS exceptions.

## 9. ON-DISK LAYOUT

AWS state is persisted within PESE's canonical layout:

```text
.project-os/
├── PESE/
│   ├── live.json          ← extensions["org.asc.aws"].config, extensions["org.asc.aws"].cycles
│   └── ...
└── AUDIT/
    └── execution-events.jsonl   ← SCHEDULER_* events appended here
```

Scheduler config and cycle records live in `state["extensions"]["org.asc.aws"]["config"]` and `state["extensions"]["org.asc.aws"]["cycles"][cycle_id]` respectively. These keys are created lazily by `state.setdefault("extensions", {}).setdefault("org.asc.aws", {})` and are not present in fresh `default_state()` — the first tick or enable/disable operation creates them.

## 10. COMPATIBILITY

AWS v1.0 is additive — it adds scheduler config and cycle records to existing PESE state without modifying any prior contract. Existing PESE, TBE, MSS, EEF, CKS, AEX, AHP, VAL, RKM, AGC, REC, and ETR commands continue to work unchanged.

The `SCHEDULER_STATUS` transition type is not in PESE's legal-transition map; AWS enforces its own cycle counter (same pattern as AGC's `AGENT_STATUS`, RKM's `RISK_STATUS`, VAL's `VALIDATION_GATE`, REC's `RECOVERY_STATUS`, and ETR's `TRANSPORT_STATUS`). The `org.asc.aws` extension key is optional in PESE's state-shape validation so states initialized before AWS v1.0 remain valid.

The scheduler defaults to ENABLED on first use (when `config.enabled` is absent from the extension). The `ACTOR_ORCHESTRATOR` identity (`AGENT:orchestrator:local`) can execute any delegate action because the orchestrator is the designated state authority in the PESE transition model.

## 11. IMPLEMENTATION REQUIREMENTS

1. `src/asc_orchestrator/aws.py` must implement `AutonomousScheduler`, `AwsError`, `SchedulingDecision`, `SchedulingAction`, `SchedulingCycle`, `SchedulerStatus`, and `SchedulerReport` using only stdlib.
2. The decision model must evaluate eight decision types (HOLD, RECOVER, START_MISSION, DISPATCH, VALIDATE, COMPLETE_MISSION, MONITOR_HEALTH, IDLE) in deterministic priority order with no randomness.
3. All scheduler state mutations must flow through `PESEStore.update()` with `transition_type="SCHEDULER_STATUS"`.
4. The scheduler must read AGC, AHP, RKM, VAL, and EEF state and delegate RECOVER, START_MISSION, DISPATCH, VALIDATE, and COMPLETE_MISSION actions to the owning runtime.
5. Event emission must use `EEFEventJournal.append()` with the three `SCHEDULER_*` event types.
6. PESE must permit `SCHEDULER_STATUS` as a transition type (passes `_validate_transition` as an unknown kind).
7. The `org.asc.aws` extension key must be optional in PESE's `_validate_state_shape()` so pre-AWS states continue to validate.
8. Seven `scheduler-*` CLI subcommands must emit machine-readable `key=value` output and deterministic exit codes.
9. `SCHEDULER_*` event types must be registered in EEF's `EVENT_TYPES` frozenset.

## 12. IMPLEMENTATION GATES

AWS v1.0 is complete when:

1. `docs/AWS_v1.0.md` is ratified with all required sections (purpose, architecture, schema, decision model, lifecycle, events, CLI reference, error handling, layout, compatibility, requirements, implementation gates, and terminal marker).
2. `src/asc_orchestrator/aws.py` implements `AutonomousScheduler`, `AwsError`, `SchedulingDecision`, `SchedulingAction`, `SchedulingCycle`, `SchedulerStatus`, and `SchedulerReport` using only stdlib.
3. Scheduler state mutations flow through `PESEStore.update()` with `transition_type="SCHEDULER_STATUS"`.
4. Three `SCHEDULER_*` event types are registered in EEF's `EVENT_TYPES` frozenset.
5. Seven `scheduler-*` CLI subcommands emit machine-readable outcomes and deterministic exit codes.
6. `tests/test_aws.py` exercises the decision model (all eight decisions), enable/disable toggle, tick persistence, cycle records, report, and event journal.
7. `tests/test_aws_cli.py` exercises the full CLI lifecycle including exit codes, scheduler toggle, tick output, cycle lookup, list, report, and event journal integrity.
8. `python -m mypy` passes on `src/asc_orchestrator/aws.py` and `src/asc_orchestrator/cli.py`.
9. `python -m ruff check src tests` and `ruff format --check` pass.
10. `python -m pytest tests/ -q` passes (existing + new AWS tests).

**END OF SPECIFICATION — AWS v1.0**
