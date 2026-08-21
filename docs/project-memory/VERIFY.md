# ASC Orchestrator — Verification & Acceptance Contract

**Purpose:** Define what is proven, what is only planned, what remains incomplete, and how future milestones reach PASS.

**Current baseline:** `main` at `5d08358dda89b8bb00e1c0076f37d3cfa78da709`

---

# 1. Verification philosophy

The project follows an evidence hierarchy:

```text
statement
    < file content
    < Git commit
    < deterministic tests
    < exact CI run
    < release gate tied to the exact commit
```

A feature is not “done” because:

- an AI says it is done,
- a file exists,
- one test passes,
- a PR is mergeable.

A milestone is accepted only when its predefined gates are satisfied.

---

# 2. Current verified baseline

## Git

```text
branch: main
commit: 5d08358dda89b8bb00e1c0076f37d3cfa78da709
```

This is the merge commit for PR #6.

## GitHub Actions

```text
workflow run: 32370325630
event: push
branch: main
status: completed
conclusion: success
```

Jobs:

```text
Lint & Format       PASS
Type Check          PASS
Test Python 3.11    PASS
Test Python 3.12    PASS
Test Python 3.13    PASS
Documentation       PASS
Release Gate        PASS
```

## Python 3.11 full suite

```text
691 tests collected
685 passed
6 skipped
4 subtests passed
```

## Local package/release sanity check

The local tree was aligned to the same main commit and `python -m pip install -e .` successfully installed `asc-orchestrator 2.0.0`.

The v2 release verifier returned:

```text
release=PASS
version=2.0.0
gate.version=PASS
gate.package_name=PASS
gate.dependencies=PASS
gate.console_entry_point=PASS
gate.src_layout=PASS
gate.runtime_modules=PASS
gate.test_suite=PASS
```

---

---

# 3. Verification Matrix (Universal ASC v2.2)

### A. VERIFIED (Proven with Passing Automated Tests & Diagnostic Introspection)
- **Interactive Operator Console**: `asc` launches Textual/Rich interactive REPL; headers, mission progress panel, runtime telemetry panel, and live activity stream render cleanly.
- **One-Shot CLI Subcommands & Flags**: `asc doctor`, `asc status [--watch]`, `asc logs`, `asc run`, `asc resume`, `asc validate`, `--version`, `--help`.
- **Project Execution Mutual Exclusion**: `ProjectLock` at `<repo>/.git/asc/lock` prevents concurrent runs and recovers dead PIDs cleanly.
- **Real-Project Git Safety**:
  - Pre-execution check fails closed on dirty repository.
  - `commit_scoped()` stages only task-created delta files (no broad `git add .`).
  - `rollback_attempt()` cleanly deletes task delta on attempt failure without touching user files.
- **Safe Repository State Storage**: State defaults to `<repo>/.git/asc/asc.db` to avoid dirtying user projects.
- **Scheduler RUNNING State Fix**: `evaluate_mission` returns `SchedulerState.RUNNING` when active tasks are running (preventing false `BLOCKED` states).
- **Heartbeat Event Streaming**: Background executor loop emits periodic heartbeats during execution, preventing silent CLI freezes.
- **Separate Timeouts**: `execution_timeout` (600s) and `verification_timeout` (300s) independently enforced.
- **Real OMP Runtime Adapter**: `omp -p --auto-approve --cwd <dir> [--model <model>] <prompt>`, isolates stdin (`DEVNULL`), handles timeouts (exit code 124).
- **Static Quality & Test Counts**:
  - Universal + OMP + Console Suite: **72/72 PASS** (`tests/test_universal_asc.py` + `tests/test_omp_runtime.py` + `tests/test_v22_console_safety.py`)
  - Full Test Suite: **730+ passed**
  - Ruff Linter: **All checks passed**
  - Ruff Formatter: **All files formatted**
  - MyPy: **Success across 39 source files**
  - Documentation Validation: **PASS** (`python scripts/validate_docs.py`)
  - git diff --check: **PASS**

### B. INTERRUPTED / NOT VERIFIED
- **InboxShield-AI First Pilot**:
  - Target: `InboxShield-AI` repository (`feature/asc-runtime-foundation`).
  - Status: **INTERRUPTED / NOT VERIFIED**.
  - Rationale: During execution, OMP modified files (`.env.example`, `package.json`, etc.), but the run was interrupted before verification due to silent CLI freezing and lack of scoped staging.
  - Disposition: Uncommitted changes safely stashed in `stash@{0}`; runtime foundation is NOT considered complete for InboxShield until a controlled clean pilot is run.

### C. OUT OF SCOPE (Explicit Non-Goals)
- **Multi-Driver Concurrent Execution**: Single-driver guarded by `ProjectLock`.
- **Remote Git Operations**: Push, PR creation, merge, release tagging are strictly non-autonomous in ASC.

---

# 4. Milestone: v2.2 Operator Console & Real-Project Safety — ACCEPTED

### Planned gates
- [x] Bare `asc` command launches rich terminal console
- [x] Subcommands `asc doctor`, `asc status`, `asc logs`, `asc resume`, `asc run`, `asc validate`
- [x] `ProjectLock` single-driver execution guard
- [x] Pre-execution clean check (fails closed on dirty repository)
- [x] Scoped staging and safe attempt delta rollback
- [x] Scheduler `RUNNING` vs `BLOCKED` state fix
- [x] Safe state location in `<repo>/.git/asc/`
- [x] Heartbeat event streaming to eliminate freeze
- [x] Static quality checks (Ruff, MyPy, validate_docs, git diff --check)

### Final verdict
**PASS** (Terminal milestone completion on 2026-08-21)

Then:

- use one small mission,
- preserve user changes,
- no autonomous remote Git operations,
- one verified task = one commit,
- independent final review,
- stop on PASS.

---

# 8. Termination rule — mandatory

```text
This is a bounded verification loop.

Continue only while:
- a required gate is failing,
- a concrete unresolved finding exists,
- or required evidence is still missing.

When every predefined acceptance criterion passes:

REPORT
→ STOP
```

Do not:

- invent more review work,
- repeat already-passed checks without new evidence,
- broaden the mission,
- keep running because another iteration is possible.

A PASS is terminal for that task.

---

# 9. Failure handling

## If implementation fails
Fix only the affected scope.

## If CI fails
Inspect the failing job/log before making changes.

## If provider/model fails
Do not automatically label code as broken.

## If Git state differs from narrative
Git wins.

## If code differs from documentation
Record the mismatch and determine which is newer before implementation.

## If old and new ASC state disagree
Do not silently merge truth. Stop and resolve authority.

---

# 10. Verification update protocol

Every future milestone must add:

```markdown
## Milestone: <name>

### Planned gates
- ...

### Exact implementation commit(s)
- ...

### Local evidence
- ...

### CI evidence
- ...

### Known skips
- ...

### Final verdict
PASS / FAIL / BLOCKED

### Date
YYYY-MM-DD
```

Only after PASS should `PROJECT_HISTORY.md` be updated with the completed milestone.
