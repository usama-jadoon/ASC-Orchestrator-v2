# EXECUTION ENGINE FOUNDATION (EEF v1.0) SPECIFICATION

## Canonical Execution-Lifecycle Contract for ASC Orchestrator v2

---

## 1. PURPOSE, SCOPE, AND NORMATIVE CONVENTIONS

### 1.1 Purpose

Execution Engine Foundation (EEF) v1.0 defines the deterministic execution lifecycle that drives a planned, team-assigned mission through its operational states: start, schedule/dispatch, pause, resume, cancel, and complete. EEF consumes three canonical contracts already ratified by this project — the Mission Specification Standard (MSS v1.0) as intake, the Team Builder Engine (TBE v1.0) as the team/assignment authority, and the Persistent Execution State Engine (PESE v1.0) as the state, audit, and recovery authority — and adds the missing operational layer that moves mission and assignment state through PESE's legal transitions.

EEF SHALL be deterministic and append-only: two conforming implementations given the same PESE state and the same sequence of lifecycle commands SHALL produce the same transitions, the same event journal entries, and the same final state.

### 1.2 Principles

1. **PESE is the only state authority.** Every EEF state mutation SHALL flow through the public `PESEStore.update()` API. EEF SHALL NEVER write PESE files directly, bypass `_validate_transition` invariants, or redefine state shapes.
2. **TBE is the only team authority.** EEF SHALL consume the assignments, milestones, dependency edges, and agent facts that TBE bound into PESE. EEF SHALL NOT recruit, select, or re-assign agents.
3. **MSS is the only intake authority.** EEF SHALL consume the mission contract facts (mission type, demands, validation gates) exactly as MSS parsed them and TBE projected them into assignments.
4. **Deterministic scheduling.** Given identical state, the scheduler SHALL return the identical dispatch decision. Scheduling SHALL NOT consult wall-clock order beyond PESE's persisted sequence and SHALL NOT read external state.
5. **Append-only evidence.** Every lifecycle event SHALL be recorded in the hash-chained EEF event journal. Events are immutable once appended.
6. **Session is derived, not invented.** The EEF session status is persisted under the `org.asc.eef` extension key and SHALL be consistent with the PESE mission status.
7. **No agent execution.** EEF schedules and dispatches assignments; it does not execute agent work, run autonomous workflows, or orchestrate LLMs.

### 1.3 Non-goals and boundaries

EEF v1.0 (this specification) SHALL NOT:

- persist mission, assignment, milestone, or agent state directly (PESE responsibility);
- select or assemble teams, derive demands, or decide ownership (TBE responsibility);
- validate mission intake or mission vocabulary (MSS responsibility);
- parse or transport ACP messages or define agent identity (ACP/ACR responsibility);
- run agents, LLMs, external processes, network services, or distributed coordination.

EEF v1.0 is a thin, deterministic driver layer on top of PESE/TBE/MSS. It adds the execution lifecycle that those contracts do not cover.

### 1.4 Normative language

The terms **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative. A `mission_id` is an ASCII string matching the MSS pattern. All times are UTC RFC 3339 timestamps with millisecond precision (`YYYY-MM-DDTHH:mm:ss.sssZ`). An "execution session" is the EEF-observed lifecycle of a single mission from start to a terminal session status.

---

## 2. ARCHITECTURE AND BOUNDARY

### 2.1 Layering

```
+-----------------------------------------------+
| Operators / Agents (CLI, future drivers)       |
+-----------------------------------------------+
| EEF v1.0  ExecutionSession (this contract)     |
|   - lifecycle transitions                      |
|   - deterministic FIFO scheduling              |
|   - event journal                              |
+-----------------------------------------------+
| PESE v1.0  PESEStore.update() / resume()       |
|   - legal transitions, actors, checkpoints     |
|   - immutable history, audits, locks, recovery |
+-----------------------------------------------+
| TBE v1.0  bound assignments, milestones, edges |
| MSS v1.0  mission contract facts               |
+-----------------------------------------------+
```

EEF sits between operators/agents and PESE. Every command is validated by PESE before any state changes; EEF only decides *which* legal transition to request and records the event afterward.

### 2.2 Execution context

`ExecutionContext` is an immutable, frozen bundle created once per command from current PESE state plus runtime configuration. It carries:

- `mission_id` — the canonical mission identifier;
- `root` — the repository root;
- `store` — the `PESEStore` instance;
- `manifest_path` — the canonical TBE `TEAM.md` filesystem path;
- `manifest_version` — the bound manifest revision;
- `dependency_edges` — assignment-level INPUT/RESOURCE edges parsed from the TBE `org.asc.tbe` extension;
- `assignments`, `milestones`, `agent_ids` — snapshots used for validation and scheduling.

`ExecutionContext` has no side effects. Construction reads PESE state and returns a structured `MISSION_NOT_FOUND` error when the mission does not exist.

### 2.3 Execution session

`ExecutionSession` is a fresh, non-persisted driver. It persists everything through `PESEStore.update()` plus the event journal and holds no durable state of its own. Re-construction from PESE state at any point yields an identical session view, which is what makes recovery (Section 7) deterministic.

---

## 3. SESSION STATE MACHINE

### 3.1 Session status vocabulary

The EEF session status is persisted in `state["extensions"]["org.asc.eef"][mission_id]["session_status"]` and SHALL be exactly one of:

| Session status | Meaning |
| --- | --- |
| `CREATED` | Mission is planned and bound; no lifecycle command has started it. |
| `RUNNING` | Mission is `ACTIVE` and dispatchable; root assignments are `READY`. |
| `PAUSED` | Mission is `INTERRUPTED`; non-terminal assignments were interrupted. |
| `CANCELLED` | Mission reached a terminal `CANCELLED` state. |
| `COMPLETED` | Mission advanced to `VALIDATING`; session work is done. |

### 3.2 Session transitions

The session status SHALL follow PESE mission status exactly:

```
PLANNED ──start()──▶ ACTIVE ──pause()──▶ INTERRUPTED ──resume()──▶ ACTIVE
   ▲                    │                                                │
   │                    ├──cancel()────────────────────────────────────▶ CANCELLED
   │                    │
   │                    └──complete()──▶ VALIDATING (session COMPLETED)
```

Session derivation:

| Mission status | Session status |
| --- | --- |
| `PLANNED` | `CREATED` |
| `ACTIVE` | `RUNNING` |
| `INTERRUPTED` | `PAUSED` |
| `CANCELLED` | `CANCELLED` |
| `VALIDATING` / `COMPLETED` | `COMPLETED` |

### 3.3 Mandatory checkpoints

EEF relies on PESE's mandatory checkpoint rules:

- `MISSION_STATUS → ACTIVE` (start, resume) fires the `MISSION_START` checkpoint.
- Terminal mission transitions (`ACTIVE → CANCELLED`, `ACTIVE → VALIDATING`) fire the `MISSION_FINISH` checkpoint.

PESE `resume()` requires the latest mission checkpoint, so `start()` MUST precede any scheduling or recovery on a mission.

---

## 4. LIFECYCLE OPERATIONS

### 4.1 start()

`start()` activates a planned mission:

1. Reads current PESE state; requires mission status `PLANNED` (else `INVALID_TRANSITION`).
2. Requests `MISSION_STATUS` `PLANNED → ACTIVE`, which fires the `MISSION_START` checkpoint.
3. In the same audited update, sets `dependency_environment_state.status = VERIFIED` for the mission's assigned agents.
4. Activates root assignments: every assignment with an empty `depends_on` set transitions `PENDING → READY`.
5. Recomputes `next_task_candidates` from READY assignments.
6. Persists `extensions["org.asc.eef"][mission_id] = {session_status: RUNNING, started_at, last_event_sequence, resume_count: 0, pause_count: 0}`.
7. Appends `SESSION_STARTED` and, per root assignment, `ASSIGNMENT_ACTIVATED` events.

Outcome codes: `UPDATED` on success.

### 4.2 schedule()

`schedule()` computes the deterministic dispatch decision without transitioning any assignment:

1. Calls `PESEStore.resume()`, which returns a `RESUME_PLAN` with `next_assignment_id` chosen by (priority, milestone order, assignment_id).
2. Cross-validates the candidate against `dependency_edges`: all INPUT/RESOURCE edges of the candidate MUST be satisfied (dependency completed). Unsatisfied edges return a `NO_WORK`-style outcome.
3. Returns `ScheduleResult` with `assignment_id`, `agent_id`, `milestone_id`, and `pese_revision`.
4. Appends a `SCHEDULE_RESULT` event.

**The scheduler does not transition the assignment.** Dispatch ownership belongs to the assigned agent, who claims work via the `ASSIGNMENT_STATUS` `READY → IN_PROGRESS` transition (Section 6). Scheduling against a non-active mission returns `NO_ACTIVE_MISSION`; scheduling with nothing dispatchable returns `NO_WORK`.

### 4.3 pause()

`pause()` interrupts an active mission:

1. Requires mission status `ACTIVE` (else `INVALID_TRANSITION`).
2. Requests `MISSION_STATUS` `ACTIVE → INTERRUPTED`.
3. In the same update, cascades every non-terminal assignment (`PENDING`, `READY`, `IN_PROGRESS`, `BLOCKED`) to `INTERRUPTED`.
4. Sets `session_status = PAUSED` and increments `pause_count`.
5. Appends a `SESSION_PAUSED` event listing the interrupted assignments.

### 4.4 resume()

`resume()` recovers an interrupted mission to `ACTIVE`:

1. Requires mission status `INTERRUPTED` (else `INVALID_TRANSITION`).
2. Uses the custom transition type `MISSION_INTERRUPT_RECOVERY`. This kind SHALL skip the legal-map and actor-ACR checks because the PESE legal map has no `INTERRUPTED → ACTIVE` MISSION_STATUS edge; the mutate function directly sets mission status, the same pattern PESE uses for its own `SCHEMA_VERSION` migrations.
3. In the same update, cascades every `INTERRUPTED` assignment back to `READY`, recomputes `next_task_candidates`, sets `session_status = RUNNING`, and increments `resume_count`.
4. Appends a `SESSION_RESUMED` event listing the reactivated assignments.

### 4.5 cancel()

`cancel()` terminates an active or interrupted mission:

1. Requires mission status `ACTIVE` or `INTERRUPTED` (else `INVALID_TRANSITION`).
2. Requests `MISSION_STATUS` `ACTIVE|INTERRUPTED → CANCELLED`, which fires the `MISSION_FINISH` checkpoint.
3. In the same update, cascades every non-terminal assignment to `CANCELLED`.
4. Sets `session_status = CANCELLED`.
5. Appends a `SESSION_CANCELLED` event listing the cancelled assignments.

### 4.6 complete()

`complete()` advances an active mission to validation:

1. Requires mission status `ACTIVE` (else `INVALID_TRANSITION`).
2. Requests `MISSION_STATUS` `ACTIVE → VALIDATING`, which fires the `MISSION_FINISH` checkpoint.
3. Sets `session_status = COMPLETED`.
4. Appends a `SESSION_COMPLETED` event.

Gate validation remains PESE-owned; EEF does not evaluate validation gates.

### 4.7 status()

`status()` is read-only and returns an `ExecutionStatus` snapshot:

- `mission_id`, `mission_status`, `session_status`;
- `current_milestone_id`;
- counts of `active_assignments` (`READY`/`IN_PROGRESS`), `completed_assignments`, and `blocked_assignments` (`BLOCKED`/`FAILED`);
- `next_task_candidates`;
- `last_event_sequence`.

---

## 5. FIFO SCHEDULER SEMANTICS

### 5.1 Deterministic order

`schedule()` selects exactly one next assignment per call, deterministically, from PESE's `resume()` plan. The ordering is:

1. **Priority** — higher-priority assignments first;
2. **Milestone order** — assignments within earlier milestones first;
3. **Assignment identifier** — lexicographic `assignment_id` tie-break.

### 5.2 Dependency gating

A candidate is dispatchable only when every assignment it `depends_on` (INPUT or RESOURCE edges from `extensions["org.asc.tbe"][mission_id].dependency_edges`) has reached a completed/terminal state. PESE keeps dependent assignments `PENDING` (not `READY`) until their dependencies complete; EEF re-checks the edges when the scheduler runs and refuses to dispatch a candidate whose edges are unsatisfied.

### 5.3 Dispatch vs. claim

The scheduler produces a decision; it does not change assignment status. The assigned agent claims the work with the `ASSIGNMENT_STATUS` `READY → IN_PROGRESS` transition. This separation keeps scheduling deterministic and read-only while agent ownership is enforced by PESE's actor checks.

---

## 6. AGENT-OWNED ASSIGNMENT TRANSITIONS

Assignment transitions are owned by the assigned agent and are enforced by PESE's legal map and actor checks:

| From | To |
| --- | --- |
| `PENDING` | `READY` (EEF start) |
| `READY` | `IN_PROGRESS`, `BLOCKED`, `INTERRUPTED`, `FAILED`, `CANCELLED` |
| `IN_PROGRESS` | `COMPLETED`, `FAILED`, `BLOCKED`, `INTERRUPTED`, `CANCELLED` |
| `BLOCKED` | `READY` |
| `INTERRUPTED` | `READY` (EEF resume) |

The EEF event journal schema (Section 8) defines `ASSIGNMENT_DISPATCHED`, `ASSIGNMENT_COMPLETED`, `ASSIGNMENT_FAILED`, and `ASSIGNMENT_BLOCKED` record types. The M010 library appends `SESSION_*`, `SCHEDULE_RESULT`, and `ASSIGNMENT_ACTIVATED` events; agent-owned transitions and milestone advancement emit their event types through the same journal as the agents and gates progress. EEF API surface exposes the journal so downstream runtime layers append agent-owned events.

---

## 7. CHECKPOINT AND RECOVERY COORDINATION

### 7.1 Checkpoint coverage

`start()` guarantees the `MISSION_START` checkpoint; `cancel()` and `complete()` guarantee the `MISSION_FINISH` checkpoint. These are PESE `MANDATORY_CHECKPOINTS` and are produced by the underlying `PESEStore.update()` calls, not by EEF-specific checkpoint code.

### 7.2 Recovery

Because `ExecutionSession` persists nothing and `schedule()` is read-only, any interrupted process may reconstruct a session from PESE state and continue. `resume()` is the explicit recovery path from `INTERRUPTED`. PESE's own `resume()` requires a mission checkpoint; the EEF `start()` ordering (Section 3.3) ensures one exists.

### 7.3 Integrity

EEF reads and writes exclusively through `PESEStore`, so `PESEStore.validate()` (including repository fingerprinting and hash-chain verification) continues to cover all state EEF mutates. The EEF event journal has its own independent chain verification (Section 8.3).

---

## 8. EVENT LOG SCHEMA

### 8.1 Journal location and format

EEF events are appended to the hash-chained JSON-lines journal at:

```
.project-os/AUDIT/execution-events.jsonl
```

The journal is append-only, one JSON object per line, canonical compact JSON (`sort_keys=True`, `separators=(",", ":")`), UTF-8, and process-safe under a per-log file lock mirroring the ACP audit journal. It lives under `AUDIT/` but is a separate file from ACP audit records and does not interfere with PESE audit validation (which scans only the `access/` and `transitions/` subdirectories).

### 8.2 Record fields

Each record contains:

| Field | Type | Meaning |
| --- | --- | --- |
| `format` | string | `"EEF/v1.0"` |
| `kind` | string | `"execution-event"` |
| `sequence` | integer | monotonic per log |
| `event_type` | string | one of the event vocabulary below |
| `mission_id` | string | canonical mission identifier |
| `assignment_id` | string \| null | related assignment, when applicable |
| `actor_agent_id` | string | the agent (or orchestrator) that produced the event |
| `occurred_at` | string | UTC RFC 3339 timestamp |
| `pese_revision` | integer \| null | PESE state revision after the transition |
| `pese_state_sha256` | string \| null | SHA-256 of the canonical PESE state envelope |
| `previous_event_sha256` | string \| null | chain anchor to the prior record |
| `event_sha256` | string | SHA-256 of the record excluding this field |
| `detail` | object | event-specific structured detail |

### 8.3 Chain verification

`verify_chain()` recomputes each record's `event_sha256` from its canonical encoding and confirms every record's `previous_event_sha256` equals its predecessor's hash. Any out-of-order, missing, or modified record fails verification. Appends are serialized by a process lock, so concurrent writers cannot interleave.

### 8.4 Event vocabulary

| Event type | Emitted by |
| --- | --- |
| `SESSION_STARTED` | `start()` |
| `ASSIGNMENT_ACTIVATED` | `start()` per root assignment |
| `SCHEDULE_RESULT` | `schedule()` |
| `SESSION_PAUSED` | `pause()` |
| `SESSION_RESUMED` | `resume()` |
| `SESSION_CANCELLED` | `cancel()` |
| `SESSION_COMPLETED` | `complete()` |
| `ASSIGNMENT_DISPATCHED` | agent-owned dispatch (schema reserved) |
| `ASSIGNMENT_COMPLETED` | agent-owned completion (schema reserved) |
| `ASSIGNMENT_FAILED` | agent-owned failure (schema reserved) |
| `ASSIGNMENT_BLOCKED` | agent-owned block (schema reserved) |
| `MILESTONE_ADVANCED` | gate-driven milestone advancement (schema reserved) |

`MILESTONE_ADVANCED` is emitted only when PESE's computed milestone differs from the persisted `execution_state.current_milestone_id`; EEF updates it via the typed `MILESTONE_STATUS` transition and does not duplicate milestone logic.

---

## 9. `org.asc.eef` EXTENSION SHAPE

EEF persists its session extension under the reverse-DNS key `org.asc.eef`, keyed by `mission_id`:

```json
{
  "org.asc.eef": {
    "MISSION:cli": {
      "session_status": "RUNNING",
      "started_at": "2026-08-04T00:00:00.000Z",
      "last_event_sequence": 3,
      "resume_count": 0,
      "pause_count": 0
    }
  }
}
```

- `session_status` SHALL be one of `CREATED`, `RUNNING`, `PAUSED`, `CANCELLED`, `COMPLETED` (Section 3.1).
- `started_at` SHALL be set by `start()` and SHALL NOT be rewritten by resume.
- `last_event_sequence` SHALL be the `sequence` of the most recently appended event for the mission.
- `resume_count` / `pause_count` SHALL increment monotonically on each resume/pause and SHALL NOT be reset.

---

## 10. CLI REFERENCE

All EEF commands accept `--root <dir>` (default `.`) and emit the same machine-readable `key=value` style as the PESE and TBE commands. Each lifecycle command requires `--mission-id` and accepts `--actor` (default `AGENT:orchestrator:local`). When the actor is not a mission member, PESE authorization resolves the session actor to the first assigned agent.

| Command | Operation | Example output |
| --- | --- | --- |
| `execution-start` | `PLANNED → ACTIVE`, activate root assignments | `outcome=UPDATED` |
| `execution-status` | read-only lifecycle snapshot | `mission_status=ACTIVE` |
| `execution-schedule` | deterministic dispatch decision | `outcome=READY` |
| `execution-pause` | `ACTIVE → INTERRUPTED` | `outcome=UPDATED` |
| `execution-resume` | `INTERRUPTED → ACTIVE` (custom transition) | `outcome=UPDATED` |
| `execution-cancel` | `ACTIVE\|INTERRUPTED → CANCELLED` | `outcome=UPDATED` |
| `execution-complete` | `ACTIVE → VALIDATING` | `outcome=UPDATED` |

### 10.1 Example

```powershell
python -m asc_orchestrator --root . state --initialize
python -m asc_orchestrator --root . team-build --mission mission.json --classification classification.json --bind-state
python -m asc_orchestrator --root . execution-start --mission-id MISSION:cli
python -m asc_orchestrator --root . execution-status --mission-id MISSION:cli
python -m asc_orchestrator --root . execution-schedule --mission-id MISSION:cli
python -m asc_orchestrator --root . execution-pause --mission-id MISSION:cli
python -m asc_orchestrator --root . execution-resume --mission-id MISSION:cli
python -m asc_orchestrator --root . execution-cancel --mission-id MISSION:cli
```

### 10.2 Exit codes

- `execution-status` returns 0 on success and 2 when the mission is unknown or state cannot be loaded.
- All mutating lifecycle commands return 0 on `UPDATED`.
- `execution-schedule` returns 0 on `READY` and `NO_WORK`, 2 on `NO_ACTIVE_MISSION`, `RECOVERY_REQUIRED`, `HALTED`, or a store error.
- A missing mission returns `outcome=MISSION_NOT_FOUND` with exit code 2.

---

## 11. ERROR HANDLING

| Outcome code | Cause |
| --- | --- |
| `MISSION_NOT_FOUND` | The mission identifier is absent from PESE state. |
| `INVALID_TRANSITION` | The requested lifecycle transition is illegal for the current mission or assignment status. |
| `NO_ACTIVE_MISSION` | `schedule()` found no mission currently `ACTIVE`. |
| `NO_WORK` | `schedule()` found no dispatchable assignment with satisfied dependencies. |
| `RECOVERY_REQUIRED` | PESE requires checkpoint recovery before further work. |
| `HALTED` | PESE `resume()` reported a blocked or unrecoverable state. |
| `INVALID_EVENT_TYPE` | A journal append used a type outside the event vocabulary. |

All structured failures are raised as `EEFError` or returned as `PESEOutcome` objects and printed as `error: <code>: <detail>` with exit code 2. No lifecycle command SHALL mutate state when its outcome is not `UPDATED`.

---

## 12. COMPATIBILITY

- **ACP/ACR**: EEF does not define message or registry contracts. Assignment actors must exist in the ACR registry with an `acr_ref` because PESE actor authorization consults it; agent-owned transitions remain ACR-governed.
- **PESE**: EEF consumes `PESEStore.load()`, `update()`, and `resume()` read-only/write-through. It never bypasses `_validate_transition`, never defines state shapes, and never writes files under `.project-os/PESE/` directly.
- **TBE**: EEF consumes `extensions["org.asc.tbe"][mission_id].dependency_edges`, bound assignments, milestones, and agent facts. It never re-derives teams or ownership.
- **MSS**: EEF treats mission facts as already-validated intake and never re-validates mission vocabulary.

---

## 13. IMPLEMENTATION GATES

The EEF v1.0 runtime is complete when:

| # | Gate |
| --- | --- |
| **G-1** | `src/asc_orchestrator/execution.py` implements `ExecutionContext`, `ExecutionSession`, `ScheduleResult`, `ExecutionStatus`, and `EEFEventJournal` using only the standard library plus `pese`, `tbe`, and `audit` imports. |
| **G-2** | All lifecycle mutations flow through `PESEStore.update()`; the custom `MISSION_INTERRUPT_RECOVERY` transition is the only non-legal-kind transition and it is scoped strictly to resume. |
| **G-3** | `start()` fires `MISSION_START`, marks agents `VERIFIED`, activates root assignments, and appends `SESSION_STARTED` plus `ASSIGNMENT_ACTIVATED` events. |
| **G-4** | `schedule()` returns a deterministic decision without transitioning assignments and rejects candidates with unsatisfied dependency edges. |
| **G-5** | `pause()`, `resume()`, `cancel()`, and `complete()` cascade assignments and append their session events; terminal transitions fire `MISSION_FINISH`. |
| **G-6** | `status()` is read-only and derives session status from mission status. |
| **G-7** | The event journal is hash-chained JSONL under `.project-os/AUDIT/execution-events.jsonl`, process-safe, and `verify_chain()` detects any tampering. |
| **G-8** | The six CLI lifecycle commands plus `execution-status` are wired through `src/asc_orchestrator/cli.py` and emit machine-readable outcomes with deterministic exit codes. |
| **G-9** | `python -m unittest discover -s tests -t . -v` passes the full suite including `test_execution.py` and `test_execution_cli.py`. |
| **G-10** | `python -m mypy`, `python -m ruff check src tests scripts`, `python -m ruff format --check src tests scripts`, `python -m compileall -q src`, and `python scripts/validate_docs.py` all pass. |

---

**END OF SPECIFICATION — EEF v1.0**
