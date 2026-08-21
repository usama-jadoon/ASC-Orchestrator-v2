# ASC Orchestrator — Master Plan

**Snapshot:** 2026-08-21  
**Status:** Living project plan  
**Current baseline:** Universal ASC v2.0.0 merged to `main` at `5d08358dda89b8bb00e1c0076f37d3cfa78da709`

---

# 1. Original problem

The project started from a practical problem: a coding AI can write code, but a long autonomous software project needs more than a single coding loop.

A real autonomous software-company system needs to know:

- what the goal is,
- how the goal is broken into assignments,
- which assignment is ready,
- what depends on what,
- who/what is allowed to perform work,
- whether the work actually passed verification,
- whether the repository changed safely,
- whether risks block execution,
- whether an agent failed or stalled,
- whether work can be retried,
- whether validation may begin,
- whether the mission is actually complete,
- and how to resume later without losing truth.

The long-term objective became:

> Build a reusable operating/control system for autonomous software development, not merely another code-generation agent.

---

# 2. Permanent product definition

ASC should become the **mission/control plane** of an autonomous software company.

Its intended responsibility is:

```text
Goal / Mission
    ↓
Mission specification
    ↓
Task / assignment graph
    ↓
Readiness + dependency evaluation
    ↓
Execution delegation
    ↓
Evidence / result intake
    ↓
Verification
    ↓
Risk / recovery / retry decisions
    ↓
Lifecycle progression
    ↓
Verified completion
```

ASC should **not** become the model provider itself.

ASC should **not** duplicate the coding loop already provided by OMP.

ASC should **not** make OmniRoute’s provider-routing decisions.

---

# 3. Target system roles

## 3.1 ASC — brain / control plane

ASC owns:

- authoritative mission state,
- assignment/task state,
- dependency progression,
- validation eligibility,
- milestone progression,
- risk holds,
- recovery eligibility,
- completion eligibility,
- audit/history,
- deterministic resume,
- final acceptance.

## 3.2 OMP — hands / execution plane

OMP is intended to own task-level coding autonomy:

- inspect repository,
- understand task context,
- plan implementation,
- edit files,
- run commands,
- run tests,
- debug,
- repair,
- retry within bounded limits,
- review its own task-level work,
- return structured execution results.

## 3.3 OmniRoute — model/network routing plane

OmniRoute is intended to own:

- model/provider routing,
- free-provider selection,
- quotas,
- provider health,
- failover,
- local/cloud model routing,
- provider-specific failures.

## 3.4 Integration layer / DevOS concept

The integration layer should translate between:

```text
ASC lifecycle/state
        ↔
OMP execution sessions
        ↔
OmniRoute model routing
```

It must not duplicate authoritative mission state.

---

# 4. Why two generations of ASC exist

## 4.1 First generation: contract-heavy deterministic control plane

The original `src/asc_orchestrator/` engine grew into a highly structured local deterministic runtime with formal contracts, state, audit and governance.

It implemented:

- ACP — agent communication protocol,
- ACR — capability registry,
- PESE — persistent execution state engine,
- TBE — team builder engine,
- MSS — mission specification standard,
- EEF — execution engine foundation,
- CKS — cryptographic key service,
- AEX — agent execution/assignment lifecycle,
- AHP — agent health,
- VAL — validation,
- RKM — risk management,
- AGC — agent lifecycle,
- REC — recovery,
- ETR — encrypted transport,
- AWS — autonomous workflow scheduler,
- REL — release verification.

This produced a strong control-plane foundation, but also substantial complexity.

## 4.2 Second generation: Universal ASC v2 compact core

Universal ASC v2 was introduced as a smaller, reusable runtime under:

```text
src/asc/
```

The intention is to preserve useful deterministic concepts while exposing a simpler mission-driven core suitable for integration with real external executors such as OMP.

Current Universal ASC v2 components:

```text
models.py
spec.py
dag.py
state.py
verifier.py
repo.py
driver.py
cli.py
release.py
adapters/
```

Both generations currently coexist.

---

# 5. What has already been built

## 5.1 Legacy/control-plane capabilities — built

The frozen `asc_orchestrator` engine already contains:

- typed persistent state,
- hash-chained history/audits,
- mission lifecycle,
- assignment lifecycle,
- dependency progression,
- validation gates,
- risk management,
- agent lifecycle,
- health monitoring,
- recovery,
- cryptographic signing,
- encrypted transport,
- deterministic scheduling,
- release verification,
- CLI tooling,
- repository reconciliation,
- checkpoint/resume behavior.

These capabilities are not to be casually rewritten.

## 5.2 Universal ASC v2 capabilities — built

The `asc` engine currently provides:

### Mission specification
- YAML/JSON parsing,
- mission ID,
- goal,
- task list,
- dependencies,
- one verification command per task.

### DAG evaluation
- task readiness,
- runnable-task discovery,
- `RUNNABLE`,
- `COMPLETE`,
- `BLOCKED`.

### State
SQLite persistence for missions, tasks, attempts and events.

### CLI
Commands:
- `init`
- `validate`
- `run`
- `status`
- `resume`
- `doctor`

### Verification
- command execution,
- stdout,
- stderr,
- exit code,
- timeout handling.

### Repository helper
- Git repository detection,
- HEAD,
- branch,
- dirty-state detection,
- commit support.

### Adapter foundation
- base adapter contract,
- mock adapter,
- shell adapter.

### Release verification
- packaging/version checks,
- dependency check,
- entry point check,
- src-layout check,
- runtime-module importability,
- test-suite presence.

### CI
- Ruff,
- formatting,
- MyPy,
- Python 3.11,
- Python 3.12,
- Python 3.13,
- docs,
- post-merge Release Gate.

---

# 6. Current gaps & architectural status

Universal ASC v2.1 has closed the critical execution/runtime gaps in the sandbox environment:

- [x] **Execute → Verify ordering**: Adapter execution runs first; deterministic verification runs second.
- [x] **Real OMP adapter**: `src/asc/adapters/omp.py` discovers installed `omp.exe` and uses `-p --auto-approve --cwd <dir> [--model <model>]` syntax with safe stdio isolation.
- [x] **Bounded retries & persistence**: `max_attempts` enforced; attempts and events recorded in SQLite; DB-level atomic `increment_attempt_count`.
- [x] **Model configuration**: Optional `model` parameter supported across `defaults`, `spec`, and `task` levels and passed to OMP adapter without hardcoding defaults.
- [x] **Target working directory**: End-to-end propagation for target repo, OMP execution, and verification commands with full Windows spaced paths support.
- [x] **Git commit safety**: Commits created only after verification PASS; no commits on execution/verification failure; strictly no autonomous push/merge/tag/release.
- [x] **Single-driver scheduler**: Deterministic single-threaded mission scheduling in v2.1.

### Future architectural scope (post-v2.1):
1. **Real-project pilot**: Bounded execution against real-world repositories with pre-existing user code.
2. **Task-scoped Git staging isolation**: Finer-grained index staging to completely isolate pre-existing dirty files from task commits.
3. **Multi-command verification sequencing**: Definitive ordered sequence semantics with fail-fast / report-all options.
4. **State convergence**: Formal reconciliation between legacy PESE (`.project-os/`) and Universal SQLite (`.asc/asc.db`) stores.

---

# 7. Milestone v2.1 — Real OMP Executor Bridge (COMPLETED & VERIFIED)

**Status:** Completed & Verified (2026-08-21)

## Achieved Vertical Slice:
```text
Mission submitted
      ↓
ASC loads state (SQLite)
      ↓
ASC determines READY task (DAG)
      ↓
OMP adapter executes task via real omp.exe
      ↓
OMP modifies code in target repository
      ↓
ASC runs deterministic verification
      ↓
FAIL → bounded retry/repair (max_attempts enforced)
PASS → safe Git commit (feat(<task_id>): <title>)
      ↓
ASC advances DAG to next dependent task
      ↓
Mission reaches terminal COMPLETE (clean working tree)
```

## Evidence Summary:
- **Focused OMP suite**: 28/28 PASS
- **Universal + OMP suite**: 54/54 PASS
- **Full repository suite**: 715 passed, 6 skipped, 4 subtests passed
- **Real Sandbox E2E**: 2-task pipeline (`fix-alpha` -> commit `714c192`, `fix-beta` -> commit `5311597`, status `COMPLETE`)
- **Quality Gates**: Ruff check & format (72 files), MyPy (36 files), git diff --check clean.

---

# 8. Next milestone — Real Project Pilot (Planned)

After the disposable sandbox vertical slice success:

1. choose one small, bounded real-project change,
2. update all master docs before implementation,
3. create one mission,
4. allow ASC to select work,
5. allow OMP to execute,
6. verify,
7. commit,
8. inspect evidence,
9. stop after acceptance.

The first real project pilot must not be a full multi-week autonomous rewrite.

---

# 9. Long-term product architecture

Long-term target:

```text
Human / API / UI
        ↓
Mission Intake
        ↓
ASC Mission Control
        ↓
DAG + State + Risk + Validation + Recovery
        ↓
Executor Adapter Layer
        ├── OMP
        ├── future coding agents
        └── deterministic shell/tool adapters
        ↓
Model Routing Layer
        └── OmniRoute
              ├── free cloud providers
              ├── local models
              └── fallback / provider health
        ↓
Target Git Repository
        ↓
Verification Evidence
        ↓
ASC Final Acceptance
```

---

# 10. Prime-style supervision rule

A separate “Prime” supervisor must **not** become a third independent authoritative state machine.

Prime-style behavior should map onto ASC concepts:

```text
RECEIVED
PLANNING
EXECUTING
TESTING
VALIDATING
REPAIRING
COMPLETED
FAILED
BLOCKED
```

Where ASC already has equivalent lifecycle states, reuse them.

UI-only or executor-only state may live in integration metadata, but mission truth remains in ASC.

---

# 11. State ownership rule

Historical integration design defined `.project-os/` as authoritative ASC mission/control-plane state.

Integration/runtime metadata may use `.asc/` for things such as executor session IDs, gateway/model observations, command summaries and integration diagnostics.

Do not create another authoritative lifecycle database merely because an integration layer needs caching.

---

# 12. Failure ownership

## OmniRoute
Owns provider routing, quota/fallback, provider health and provider errors.

## OMP
Owns coding-session execution, tool use, task-level reasoning/context and task-level repair attempts.

## ASC
Owns mission truth, task/assignment truth, dependencies, validation eligibility, risk/recovery policy and final completion.

## Integration layer
Owns process/transport failures between components, translation of structured results and diagnostics.

Do not fix the same failure independently in multiple layers without evidence.

---

# 13. Non-goals

Do not:

- rebuild OmniRoute inside ASC,
- rebuild OMP’s internal coding loop,
- create infinite verification loops,
- create multiple sources of mission truth,
- auto-merge code,
- claim production readiness because tests merely exist,
- silently change historical evidence,
- rewrite the frozen legacy engine for cosmetic reasons,
- add large features before the master docs are updated.

---

# 14. Definition of project completion

ASC should eventually be considered a complete autonomous-development control system only when it can repeatedly prove:

```text
goal
→ plan
→ task graph
→ correct readiness
→ real executor
→ code change
→ verification
→ bounded self-repair
→ safe commit
→ dependency progression
→ validation
→ risk/recovery handling
→ deterministic resume
→ terminal truthful completion
```

across disposable fixtures and real projects without corrupting state or user work.

That is the long-term destination.
