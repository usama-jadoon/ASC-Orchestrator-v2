# Agent Lifecycle Control — AGC v1.0

## 1. PURPOSE AND SCOPE

AGC v1.0 is the deterministic agent-lifecycle runtime that operates the `agent_state` ledger over PESE, manages every agent from registration through release, tracks dependency environment state and heartbeat/checkpoint references, and emits `AGENT_*` events to the EEF execution journal. Every state mutation flows through `PESEStore.update()` with transition type `AGENT_STATUS`; AGC never bypasses PESE invariants.

AGC closes the lifecycle gap between identity (CKS), liveness (AHP), execution (AEX), and autonomous scheduling (AWS M019): without a canonical agent lifecycle, the scheduler cannot know which agents are eligible (READY), which are working (BUSY), which are blocked, and which must be quarantined or replaced after failure.

**Boundary.** AGC operates the agent lifecycle ledger over PESE `agent_state`. It does not execute agent work (AEX), schedule dispatch (EEF), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP — which records heartbeats in its own journals), or drive validation gates (VAL). AGC reads PESE state to inspect agents and writes agent records via PESE `AGENT_STATUS` transitions.

## 2. ARCHITECTURE AND BOUNDARY

AGC operates as a deterministic agent-lifecycle runtime layered on top of the existing runtimes:

```text
+-----------------------------------------------+
|   Operators / CLI / M016 recovery / M019       |
+-----------------------------------------------+
| AGC v1.0  (this contract)                      |
|   - registration → release lifecycle           |
|   - dependency environment state               |
|   - heartbeat / checkpoint references          |
|   - AGENT_* events to EEF journal             |
+-----------------------------------------------+
| PESE v1.0  (read/write: agent_state)           |
| EEF v1.0   (append: execution events)          |
| ACR v1.0   (read-only: acr_ref references)     |
+-----------------------------------------------+
```

**Key design decisions:**

1. All state mutations flow through `PESEStore.update()` with transition type `AGENT_STATUS`. AGC never writes PESE state directly; it relies on the store's legal-transition enforcement and actor authorization.
2. AGC enforces its own status state machine because `AGENT_STATUS` is not in PESE's legal-transition map (the same pattern used by RKM's `RISK_STATUS` and VAL's `VALIDATION_GATE`).
3. Dependency environment state must be `VERIFIED` before an agent may become `READY`. The `dependency_environment_state` is the canonical 4-field record defined by PESE section 4.8.
4. Actor authority: the orchestrator (`AGENT:orchestrator:local`) may manage any agent; an agent may manage itself. AGC enforces this at the engine level because PESE validates actor authority only for `ASSIGNMENT_STATUS`, `MISSION_STATUS`, and `VALIDATION_GATE` transitions.
5. The `FAILED` and `QUARANTINED` statuses trigger the PESE mandatory `FAILURE` checkpoint when the agent has an active mission (`MANDATORY_CHECKPOINTS["AGENT_STATUS"]`). AGC relies on the store's checkpoint behavior and does not attempt to force checkpoints itself.
6. Event emission is best-effort: `_emit_event` swallows exceptions to prevent journal failures from blocking agent mutations.

## 3. AGENT RECORD SCHEMA

Each agent is a 10-field record stored in `agent_state.agents` under its `agent_id` key. The canonical schema is defined by PESE v1.0 section 4.8:

```json
{
  "agent_id": "AGENT:developer:abc",
  "status": "READY",
  "mission_id": null,
  "assignment_id": null,
  "manifest_version": null,
  "last_heartbeat_at": null,
  "last_checkpoint_id": null,
  "acr_ref": "ACR:developer:specialist",
  "dependency_environment_state": {
    "status": "VERIFIED",
    "verified_at": "2026-08-05T04:00:00.000Z",
    "tool_dependencies": {"python": "3.11"},
    "environment_dependencies": {}
  },
  "interruption": null
}
```

**Agent record fields:**

| Field | Meaning |
|---|---|
| `agent_id` | Canonical agent identifier, unique across the company |
| `status` | Current lifecycle status (see vocabulary below) |
| `mission_id` | Mission the agent is currently claimed by, or `null` |
| `assignment_id` | Assignment the agent is currently working, or `null` |
| `manifest_version` | Team-manifest version the agent was assembled under, or `null` |
| `last_heartbeat_at` | UTC reference of the agent's last heartbeat, or `null` |
| `last_checkpoint_id` | ID of the agent's last checkpoint reference, or `null` |
| `acr_ref` | ACR registry reference describing the agent's capabilities |
| `dependency_environment_state` | 4-field dependency environment record (below) |
| `interruption` | Failure/quarantine interruption record, or `null` |

**Dependency environment state:**

| Field | Meaning |
|---|---|
| `status` | One of `VERIFIED`, `MISSING`, `MISMATCH`, `UNKNOWN` |
| `verified_at` | UTC timestamp of the last verification, or `null` |
| `tool_dependencies` | Object of verified tool dependencies |
| `environment_dependencies` | Object of verified environment dependencies |

## 4. AGENT STATUS VOCABULARY

| Status | Meaning |
|---|---|
| `INITIALIZING` | Agent record created; not yet activated |
| `REGISTERED` | Agent activated and visible to the orchestrator |
| `READY` | Agent eligible for dispatch (dependencies VERIFIED) |
| `BUSY` | Agent claimed by a mission/assignment |
| `BLOCKED` | Agent blocked on a precondition |
| `FAILED` | Agent failed; records an interruption |
| `QUARANTINED` | Agent quarantined after failure; records an interruption |
| `REPLACED` | Agent replaced by the recovery engine |
| `RELEASED` | Agent released from service (terminal) |

## 5. AGENT LIFECYCLE

Agents progress through a deterministic lifecycle:

```
INITIALIZING ──► REGISTERED ──► READY ──► BUSY
                                  │  ▲       │
                                  │  └───────┤
                                  ▼          ▼
                               BLOCKED ──► READY
                                  │
                                  ▼
             ┌───────────┬───────┴───────┐
             ▼           ▼               ▼
          FAILED      QUARANTINED     RELEASED
             │           │
             └───► REPLACED ──► RELEASED
```

**Legal transitions:**

| From | To |
|---|---|
| `INITIALIZING` | `REGISTERED` |
| `REGISTERED` | `READY` |
| `READY` | `BUSY`, `BLOCKED`, `FAILED`, `QUARANTINED`, `RELEASED` |
| `BUSY` | `READY`, `BLOCKED`, `FAILED`, `QUARANTINED`, `RELEASED` |
| `BLOCKED` | `READY`, `FAILED`, `QUARANTINED`, `RELEASED` |
| `FAILED` | `QUARANTINED`, `REPLACED`, `RELEASED` |
| `QUARANTINED` | `REPLACED`, `RELEASED` |
| `REPLACED` | `RELEASED` |

**Commands and transitions:**

| Command | From Status | To Status | Notes |
|---|---|---|---|
| `agent-register` | — (creates) | `INITIALIZING` | Records `acr_ref`, dependency `UNKNOWN` |
| `agent-activate` | `INITIALIZING` | `REGISTERED` | — |
| `agent-dependency` | any | any (unchanged) | Sets dependency environment state; no status change |
| `agent-ready` | `REGISTERED` | `READY` | Requires dependency status `VERIFIED` |
| `agent-claim` | `READY` | `BUSY` | Sets `mission_id` and `assignment_id` |
| `agent-complete` | `BUSY` | `READY` | Clears `mission_id`/`assignment_id` |
| `agent-block` | `READY`, `BUSY` | `BLOCKED` | — |
| `agent-unblock` | `BLOCKED` | `READY` | Clears `mission_id`/`assignment_id` |
| `agent-fail` | `READY`, `BUSY`, `BLOCKED` | `FAILED` | Records `interruption`; triggers FAILURE checkpoint when mission active |
| `agent-quarantine` | `READY`, `BUSY`, `BLOCKED`, `FAILED` | `QUARANTINED` | Records `interruption`; triggers FAILURE checkpoint when mission active |
| `agent-replace` | `QUARANTINED`, `FAILED` | `REPLACED` | — |
| `agent-release` | any except `RELEASED` | `RELEASED` | Clears `mission_id`/`assignment_id` |
| `agent-heartbeat` | any | any (unchanged) | Updates `last_heartbeat_at` reference |
| `agent-checkpoint` | any | any (unchanged) | Updates `last_checkpoint_id` reference |

## 6. EVENT JOURNAL

Every agent mutation emits an event to the EEF execution journal (hash-chained `execution-events.jsonl`). Events use the `AGENT_*` event types registered in the EEF `EVENT_TYPES` frozenset:

| Transition | Event Type |
|---|---|
| creation | `AGENT_REGISTERED` |
| `INITIALIZING → REGISTERED` | `AGENT_ACTIVATED` |
| `REGISTERED → READY` | `AGENT_READY` |
| `READY → BUSY` | `AGENT_BUSY` |
| `BUSY → READY` (return) | `AGENT_READY` (with `returned_from: BUSY`) |
| `READY/BUSY → BLOCKED` | `AGENT_BLOCKED` |
| `BLOCKED → READY` | `AGENT_UNBLOCKED` |
| `→ FAILED` | `AGENT_FAILED` |
| `→ QUARANTINED` | `AGENT_QUARANTINED` |
| `→ REPLACED` | `AGENT_REPLACED` |
| `→ RELEASED` | `AGENT_RELEASED` |
| dependency update | `AGENT_DEPENDENCY` |
| heartbeat reference | `AGENT_HEARTBEAT` |
| checkpoint reference | `AGENT_CHECKPOINTED` |

Event emission is best-effort: exceptions are swallowed so journal failures never block agent mutations. The journal event includes transition context (`reason`, `assignment_id`, `dep_status`, etc.) in the `detail` field.

## 7. CLI REFERENCE

All commands accept `--root <path>` (default: current directory) and emit machine-readable `key=value` output to stdout. Deterministic exit codes: 0 for success, 2 for error or precondition failure.

| Command | Description | Exit 2 on |
|---|---|---|
| `agent-register` | Register a new agent in INITIALIZING status | duplicate/empty agent_id, empty acr_ref |
| `agent-activate` | Transition INITIALIZING → REGISTERED | agent not INITIALIZING |
| `agent-dependency` | Set the agent's dependency environment state | invalid dep status, agent not found |
| `agent-ready` | Transition REGISTERED → READY | dependency not VERIFIED |
| `agent-claim` | Transition READY → BUSY | agent not READY |
| `agent-complete` | Transition BUSY → READY | agent not BUSY |
| `agent-block` | Transition READY/BUSY → BLOCKED | agent not READY/BUSY |
| `agent-unblock` | Transition BLOCKED → READY | agent not BLOCKED |
| `agent-fail` | Transition READY/BUSY/BLOCKED → FAILED | agent not READY/BUSY/BLOCKED |
| `agent-quarantine` | Transition → QUARANTINED | agent in terminal status |
| `agent-replace` | Transition QUARANTINED/FAILED → REPLACED | agent not QUARANTINED/FAILED |
| `agent-release` | Transition → RELEASED | agent already RELEASED |
| `agent-heartbeat` | Update `last_heartbeat_at` reference | agent not found |
| `agent-checkpoint` | Update `last_checkpoint_id` reference | agent not found |
| `agent-list` | List agents (optionally filtered) | — |
| `agent-status` | Read a single agent snapshot | agent not found |
| `agent-report` | Aggregated lifecycle summary | — |

**Arguments:**

- `agent-register`: `--agent` (required), `--acr-ref` (required), `--actor` (optional).
- `agent-activate`: `--agent` (required), `--actor` (optional).
- `agent-dependency`: `--agent` (required), `--dep-status` (required, one of VERIFIED/MISSING/MISMATCH/UNKNOWN), `--verified-at` (optional), `--tool` (repeatable `name=version`), `--environment` (repeatable `name=value`), `--actor` (optional).
- `agent-ready`: `--agent` (required), `--actor` (optional).
- `agent-claim`: `--agent` (required), `--mission-id` (required), `--assignment-id` (required), `--actor` (optional).
- `agent-complete`: `--agent` (required), `--actor` (optional).
- `agent-block`: `--agent` (required), `--reason` (required), `--actor` (optional).
- `agent-unblock`: `--agent` (required), `--actor` (optional).
- `agent-fail`: `--agent` (required), `--reason` (required), `--actor` (optional).
- `agent-quarantine`: `--agent` (required), `--reason` (required), `--actor` (optional).
- `agent-replace`: `--agent` (required), `--reason` (required), `--actor` (optional).
- `agent-release`: `--agent` (required), `--actor` (optional).
- `agent-heartbeat`: `--agent` (required), `--at` (optional UTC timestamp), `--actor` (optional).
- `agent-checkpoint`: `--agent` (required), `--checkpoint-id` (required), `--actor` (optional).
- `agent-list`: `--status` (optional), `--mission-id` (optional), `--actor` (optional).
- `agent-status`: `--agent` (required), `--actor` (optional).
- `agent-report`: `--actor` (optional).

## 8. ERROR HANDLING

| Error Code | When |
|---|---|
| `INVALID_AGENT` | Empty agent_id string |
| `INVALID_ACR_REF` | Empty acr_ref string |
| `DUPLICATE_AGENT` | agent_id already exists in agent_state |
| `AGENT_NOT_FOUND` | Requested agent_id does not exist |
| `INVALID_TRANSITION` | The requested status change is not legal from the current status |
| `DEPENDENCY_UNVERIFIED` | agent-ready requires dependency status VERIFIED |
| `INVALID_DEP_STATUS` | Dependency status not in {VERIFIED, MISSING, MISMATCH, UNKNOWN} |
| `UNAUTHORIZED` | Actor is neither the orchestrator nor the target agent |
| `STATE_LOAD_FAILED` | PESE state could not be loaded or is missing revision/sha256 |

## 9. ON-DISK LAYOUT

AGC state is persisted within PESE's canonical layout:

```
.project-os/
├── PESE/
│   ├── live.json          ← agent_state.agents
│   └── ...
└── AUDIT/
    └── execution-events.jsonl   ← AGENT_* events appended here
```

Agent records live in `state.agent_state.agents[agent_id]`. Heartbeats recorded via `health-heartbeat` live in `.project-os/HEALTH/agents/` (AHP owns those journals; AGC records only the `last_heartbeat_at` state reference).

## 10. COMPATIBILITY

AGC v1.0 is additive — it adds agent records to existing PESE state without modifying any prior contract. Existing PESE, TBE, MSS, EEF, CKS, AEX, AHP, VAL, and RKM commands continue to work unchanged.

The `AGENT_STATUS` transition type is not in PESE's legal-transition map; AGC enforces its own state machine (same pattern as RKM's `RISK_STATUS` and VAL's `VALIDATION_GATE`). PESE's `MANDATORY_CHECKPOINTS` mapping already recognizes `AGENT_STATUS → FAILED/QUARANTINED` as a `FAILURE` checkpoint trigger when an active mission exists.

## 11. IMPLEMENTATION REQUIREMENTS

1. `src/asc_orchestrator/agent.py` must implement `AgentLifecycle`, `AGCError`, `AgentRecord`, and `AgentReport` using only stdlib.
2. All state mutations must flow through `PESEStore.update()` with `transition_type="AGENT_STATUS"`.
3. The lifecycle must enforce the legal state machine from section 5, including the `VERIFIED` dependency requirement for READY.
4. Actor authority must require the orchestrator or the target agent itself.
5. Event emission must use `EEFEventJournal.append()` with the thirteen `AGENT_*` event types.
6. Dependency environment state must be updated in place on the agent record (no status change).

## 12. IMPLEMENTATION GATES

AGC v1.0 is complete when:

1. `docs/AGC_v1.0.md` is ratified with all required sections (purpose, architecture, schema, lifecycle, events, CLI reference, error handling, layout, compatibility, requirements, implementation gates, and terminal marker).
2. `src/asc_orchestrator/agent.py` implements `AgentLifecycle`, `AGCError`, `AgentRecord`, and `AgentReport` using only stdlib.
3. Agent mutations flow through `PESEStore.update()` with `transition_type="AGENT_STATUS"`.
4. The lifecycle enforces the legal state machine and the `VERIFIED` dependency requirement for READY.
5. Thirteen `AGENT_*` event types are registered in EEF's `EVENT_TYPES` frozenset.
6. Seventeen `agent-*` CLI subcommands emit machine-readable outcomes and deterministic exit codes.
7. `tests/test_agent.py` exercises all transitions, dependency gating, authority checks, event journal integrity, and backward compatibility.
8. `tests/test_agent_cli.py` exercises the full CLI lifecycle including status/authority exit codes.
9. `python -m mypy` passes on `src`.
10. `python -m ruff check src tests scripts` and `ruff format --check` pass.
11. `python scripts/validate_docs.py` passes with AGC spec coverage.
12. `python -m unittest discover -s tests -t . -v` passes (existing + new AGC tests).

**END OF SPECIFICATION — AGC v1.0**
