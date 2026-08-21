# ASC Orchestrator — Master Architecture

**Status:** Consolidated architecture guide  
**Snapshot:** 2026-08-21  
**Baseline:** `main` at `5d08358dda89b8bb00e1c0076f37d3cfa78da709`

This file is deliberately broader than the older repository `ARCHITECTURE.md`. It documents the current two-generation reality and the intended integration boundary.

---

# 1. System objective

ASC is an orchestration/control system for long-running autonomous software-development missions.

The architecture is based on separation of concerns:

```text
ASC        = mission/control plane
OMP        = execution/coding plane
OmniRoute  = model/provider routing plane
Git        = durable source-history plane
Tests      = deterministic acceptance evidence
```

The central invariant is:

> No executor may declare mission truth by itself; ASC must decide whether evidence allows lifecycle progression.

---

# 2. Repository architecture

```text
ASC-Orchestrator-v2/
│
├── src/
│   ├── asc_orchestrator/    # frozen rich v1.x control-plane engine
│   └── asc/                 # Universal ASC v2 compact core
│
├── tests/                   # legacy + Universal test suites
├── docs/                    # formal contract specifications
├── .project-os/             # project/control-plane artifacts and historical state layout
├── .github/workflows/       # CI
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md          # older repository architecture document
├── CHANGELOG.md
└── RELEASE_NOTES.md
```

---

# 3. Package/runtime generation A — `asc_orchestrator`

## 3.1 Role

This is the original contract-heavy deterministic control plane.

It is now considered a **frozen legacy engine**, but “legacy” does not mean useless.

It contains mature functionality that should be preserved or integrated rather than blindly reimplemented.

## 3.2 Contract map

### ACP — Agent Communication Protocol
Responsible for message schema, validation, deterministic serialization, payload binding and audit records.

### ACR — Agent Capability Registry
Responsible for capability definitions, department/specialist registry and deterministic registry loading.

### PESE — Persistent Execution State Engine
Responsible for authoritative persistent state, revisions, integrity hashes, checkpoints, locks, recovery, migrations, resume, repository observation and reconciliation.

### TBE — Team Builder Engine
Responsible for specialist selection, assignment ownership, dependency/resource graphs, reviewer/validator interfaces and team manifests.

### MSS — Mission Specification Standard
Responsible for mission structure, acceptance criteria, constraints, authority and semantic validation.

### EEF — Execution Engine Foundation
Responsible for mission start/schedule/pause/resume/cancel/complete, lifecycle progression and execution event journal.

### CKS — Cryptographic Key Service
Responsible for signing keys, signatures, rotation, revocation and ledger validation.

### AEX — Agent Execution/Assignment Engine
Responsible for dispatch/claim, assignment completion/failure/blocking, execution result records, artifacts and optional signing.

### AHP — Agent Health
Responsible for heartbeats and ALIVE/STALLED/UNKNOWN state.

### VAL — Validation
Responsible for gate lifecycle, artifact binding, validation verdicts and tamper detection.

### RKM — Risk
Responsible for risk ledger, blocking conditions and autonomous HOLD behavior.

### AGC — Agent Governance/Lifecycle
Responsible for register, activate, ready, busy, fail, quarantine, replace and release.

### REC — Recovery
Responsible for diagnosing failed/stalled agents and deterministic replacement flow.

### ETR — Encrypted Transport
Responsible for authenticated encryption, channels/envelopes and endpoint authorization.

### AWS — Autonomous Workflow Scheduler
Responsible for one prioritized decision per scheduler tick.

### REL — Release verifier
Responsible for deterministic release contract for the old engine.

---

# 4. Package/runtime generation B — `asc`

Universal ASC v2 is the compact core intended to make future executor integration simpler.

## 4.1 `models.py`

Current data model includes:

```text
TaskStatus:
    PENDING
    RUNNING
    COMPLETED
    FAILED
    BLOCKED
    CANCELLED

SchedulerState:
    RUNNABLE
    COMPLETE
    BLOCKED

VerificationCommand
VerificationResult
Task
MissionDefaults
MissionSpec
Mission
AttemptRecord
MissionStateRecord
AgentResult
```

`MissionDefaults` currently includes:

```text
max_attempts = 3
verification_timeout = 300
```

Important: declaring these defaults does not mean the complete retry contract is already implemented.

---

# 5. Mission specification — `spec.py`

Current parser supports YAML and JSON.

Required mission fields:

```text
id
goal
tasks
```

Required task fields:

```text
id
title
prompt
```

Optional:

```text
depends_on
command
```

The parser checks:

- duplicate task IDs,
- self-dependency,
- missing dependency references,
- basic task structure.

## Current inconsistency

The generated CLI sample uses `verify:` while the parser reads `command:`.

This must be normalized before mission files become a stable long-term public contract.

---

# 6. DAG — `dag.py`

The DAG layer answers:

```text
Is a task ready?
Which tasks are runnable?
Is the mission RUNNABLE, COMPLETE or BLOCKED?
```

A task is ready only when:

```text
status == PENDING
AND
all dependencies == COMPLETED
```

Mission evaluation:

```text
all completed        → COMPLETE
runnable tasks exist → RUNNABLE
otherwise            → BLOCKED
```

This is intentionally simple and deterministic.

---

# 7. State — `state.py`

Universal ASC uses SQLite.

Default database:

```text
.asc/asc.db
```

Current tables:

```text
missions
tasks
attempts
events
```

## Missions store
- ID
- goal
- status
- created/updated time

## Tasks store
- task identity
- mission
- title
- status
- dependencies
- prompt
- command
- attempt count
- commit SHA
- timestamps
- exit code

## Attempts store
- attempt ID
- task ID
- attempt number
- status
- exit code
- stdout
- stderr
- timestamp

## Events store
- mission
- task
- event type
- JSON payload
- timestamp

### Architectural issue to resolve later

The historical architecture already treats PESE / `.project-os/` as authoritative control-plane state.

Universal ASC also has SQLite mission state.

Before the system becomes one final runtime, the authority/convergence boundary must be explicit.

Do not allow both stores to independently claim final truth for the same mission.

---

# 8. Verification — `verifier.py`

Current verifier:

- executes a command,
- captures stdout/stderr,
- captures exit code,
- handles timeout,
- works with Windows shell built-ins.

Current API accepts a list of commands but only executes the first command.

Future stable verification must define one of:

```text
one explicit command per task
```

or:

```text
ordered command sequence with fail-fast/all-result semantics
```

Do not leave this ambiguous.

---

# 9. Repository integration — `repo.py`

Current repository helper can:

- read HEAD,
- read current branch,
- detect Git repository,
- list dirty files,
- detect changes,
- stage and commit.

## Current safety limitation

Commit implementation stages:

```text
git add .
```

That is not safe enough for a general autonomous executor if the user already has unrelated local changes.

Future architecture needs:

- baseline dirty-state capture,
- allowlist/change ownership,
- task-scoped staging,
- no accidental user-file inclusion,
- no commit when verification fails.

---

---

# 10. Adapter layer

Adapter directory:

```text
src/asc/adapters/
    base.py
    mock.py
    shell.py
    omp.py
```

## Base adapter (`base.py`)
Defines the executor contract (`execute(task, context) -> AgentResult`).

## Mock adapter (`mock.py`)
Used for deterministic unit testing.

## Shell adapter (`shell.py`)
Runs task prompt as a shell command.

## OMP adapter (`omp.py`) — Implemented in v2.1
Integrates with the installed OMP CLI runtime (`omp.exe` v17.4.0+):
- Discovers `omp` executable from PATH or user bin directories.
- Constructs command using the exact top-level OMP syntax:
  ```text
  omp -p --auto-approve --cwd <target_dir> [--model <model>] <prompt>
  ```
- Uses `stdin=subprocess.DEVNULL` to isolate subprocess stdio and prevent Windows piped-input blocking.
- Enforces process-level timeouts (maps timeout to exit code 124).
- Captures stdout/stderr and returns structured `AgentResult`.

---

# 11. Mission driver — `driver.py`

The mission driver implements the authoritative single-driver deterministic execution loop:

```text
adapter.execute(task, context)
       ↓
structured execution result recorded (attempt #N)
       ↓
verification command(s) evaluated in target cwd
       ↓
verification attempt recorded
       ↓
PASS?
   ├── YES → git commit feat(<task>): <title> → COMPLETE task → advance DAG
   └── NO  → attempt < max_attempts?
               ├── YES → bounded retry (increment attempt, re-run adapter)
               └── NO  → mark task BLOCKED/FAILED → mission BLOCKED
```

### Key Driver Invariants (v2.1):
1. **Execution precedes verification**: The coding adapter always runs before verification is evaluated.
2. **Commit only on verify PASS**: Unverified or failed changes are never committed.
3. **Target repository context**: Concretely resolves working directory (`effective_cwd`) preserving `task > mission/default > "."` precedence.
4. **Single-driver scheduler**: Deterministic single-threaded execution per mission in v2.1.
5. **Resume consistency**: Resumed missions use the spec/task-defined executor consistently.

---

# 12. CLI — `cli.py`

Universal CLI command:

```text
asc
```

Current commands:

```text
init
validate
run
status
resume
doctor
```

Current responsibilities:

## init
Creates/loads a sample mission and persists it.

## validate
Parses and validates mission structure.

## run
Runs a mission through `MissionDriver`.

## status
Displays mission/task state and the next runnable task.

## resume
Loads persisted mission state and restarts the driver.

## doctor
Reports basic Python, database, Git and mission-state diagnostics.

---

# 13. Packaging

Current package metadata:

```text
name = asc-orchestrator
version = 2.0.0
requires-python = >=3.11
dependency = pyyaml>=6.0
```

Console scripts:

```text
asc = asc.cli:main
asc-orchestrator = asc_orchestrator.cli:main
```

This is intentional coexistence.

---

# 14. CI/release architecture

Current GitHub CI validates:

```text
Lint & Format
Type Check
Tests: Python 3.11
Tests: Python 3.12
Tests: Python 3.13
Documentation
Release Gate on push to main
```

Latest merged baseline is green.

This proves the current source tree satisfies the current automated contracts.

It does **not** prove future OMP integration because that feature does not yet exist.

---

# 15. Intended OMP integration architecture

```text
┌─────────────────────────────────────────┐
│                 ASC                     │
│ mission / task / dependency / gates     │
└────────────────────┬────────────────────┘
                     │ structured Task
                     ▼
┌─────────────────────────────────────────┐
│             Executor Adapter            │
│ translates ASC task ↔ executor process  │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│                 OMP                     │
│ inspect / plan / edit / test / repair   │
└────────────────────┬────────────────────┘
                     │ inference
                     ▼
┌─────────────────────────────────────────┐
│              OmniRoute                  │
│ provider/model routing + fallback       │
└─────────────────────────────────────────┘

OMP modifies target repository
                     │
                     ▼
ASC Verifier → evidence → acceptance decision
                     │
             PASS ───┴─── FAIL
               │           │
               ▼           ▼
         safe commit    retry/block
               │
               ▼
         DAG progression
```

---

# 16. Executor result contract — recommended future shape

The exact schema is not yet implemented, but the future adapter should return at least:

```text
executor
task_id
session_id
started_at
finished_at
exit_code
stdout_summary
stderr_summary
changed_files
commands_run
tests_run
timed_out
provider/model observations (metadata only)
```

ASC should not depend on prose such as:

```text
"Everything is done."
```

Lifecycle progression must depend on structured result + deterministic verification.

---

# 17. Retry architecture

There must be two different budgets.

## OMP internal/task-level repair
OMP may retry implementation inside one ASC-authorized attempt.

## ASC mission-level retry
ASC decides whether another full attempt is allowed.

Rule:

```text
no infinite loops
```

When budget is exhausted:

```text
FAILED / BLOCKED
```

must become truthful terminal/holding state until a new authorized action occurs.

---

# 18. Git architecture

Required future safe flow:

```text
capture baseline
    ↓
detect pre-existing changes
    ↓
execute task
    ↓
identify task-owned changes
    ↓
verify
    ↓
stage only allowed task changes
    ↓
commit once
```

Never:

```text
task fails
→ commit anyway
```

Never use `git add .` in a way that silently absorbs unrelated user work.

---

# 19. Prime concept

Prime-style supervision is a behavior/policy layer, not an independent authoritative orchestrator.

Desired states such as:

```text
PLANNING
EXECUTING
TESTING
VALIDATING
REPAIRING
```

should map onto ASC lifecycle and executor metadata.

Do not create a second mission database merely to make the UI look sophisticated.

---

# 20. Architecture invariants

1. **One mission truth.**
2. **Execution before verification.**
3. **Evidence before completion.**
4. **Retries are bounded.**
5. **No silent user-work destruction.**
6. **No automatic push/merge/tag/release without authorization.**
7. **OMP executes; ASC governs.**
8. **OmniRoute routes; ASC does not duplicate provider logic.**
9. **Legacy capabilities are preserved until deliberately superseded.**
10. **Docs change before major architecture changes.**
11. **PASS terminates a bounded verification loop.**
