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

# 3. Verification Matrix (Universal ASC v2.1)

### A. VERIFIED (Proven with Passing Automated Tests & Real Sandbox E2E)
- **Real OMP Runtime Adapter**: Discovers `omp.exe`, invokes `omp -p --auto-approve --cwd <dir> [--model <model>] <prompt>`, isolates stdin (`DEVNULL`), handles timeouts (exit code 124).
- **Execution-before-Verification**: Adapter always executes first; verification evaluates second.
- **Bounded Retries & Persistence**: `max_attempts` enforced; attempts, events, and task status persisted in SQLite.
- **Database-Level Attempt Counting**: SQL-level atomic `UPDATE tasks SET attempt_count = COALESCE(attempt_count, 0) + 1` within transaction.
- **Typed Mission Persistence**: `State.get_last_mission_id() -> Optional[str]` verified.
- **Model Parameter Support**: Configurable across `defaults`, `spec`, and `task` overrides.
- **Working Directory Propagation**: Target directory with Windows spaces handled properly across adapter, verification, and git operations.
- **Commit Guarding**: Commit created only when execution + verification pass. Failed tasks produce 0 commits.
- **DAG Dependency Progression**: Downstream tasks remain blocked until upstream prerequisites complete.
- **No ASC Push/Merge/Tag/Release**: ASC creates only local task commits (`feat(<id>): <title>`).
- **Single-Driver Scheduler**: Deterministic serial task scheduling in v2.1.
- **Real Sandbox E2E Vertical Slice**:
  - Baseline commit: `49e56e6`
  - Task 1 (`fix-alpha`): Real OMP edit -> `test_alpha` PASS -> commit `714c192`
  - Task 2 (`fix-beta`): Real OMP edit -> `test_beta` PASS -> commit `5311597`
  - Mission state: `COMPLETE`, 2/2 tasks, clean tree.
- **Static Quality & Test Counts**:
  - OMP Runtime Suite: **28/28 PASS**
  - Universal + OMP Suite: **54/54 PASS**
  - Full Test Suite: **715 passed, 6 skipped, 4 subtests passed**
  - Ruff Linter: **All checks passed**
  - Ruff Formatter: **72 files already formatted**
  - MyPy: **Success across 36 source files**
  - git diff --check: **PASS**

### B. PARTIALLY VERIFIED (Acceptable for v2.1 Sandbox; Hardening in Future Milestones)
- **Target Repository Dirty-State Isolation**: Verified that verified tasks commit cleanly in a dedicated repository; finer-grained staging index isolation (ignoring pre-existing dirty files from user edits) is scheduled for the real-project pilot.
- **Mission Syntax Consistency**: `command:` and `verify:` normalized in core models; ongoing documentation alignment across older example templates.

### C. NOT VERIFIED / OUT OF SCOPE (Explicit Non-Goals for v2.1)
- **Multi-Driver Concurrent Execution**: Not supported in v2.1; scheduler is explicitly single-driver deterministic.
- **Permanent Upstream Model Availability**: External provider quotas (e.g. 401 on free tiers) are external network realities; failover and provider health belong to OMP/OmniRoute, while ASC fails closed via bounded retries.
- **Remote Git Operations**: Push, PR creation, merge, release tagging are strictly non-autonomous in ASC.

---

# 4. Milestone: v2.1 Real OMP Executor Bridge — ACCEPTED

### Planned gates
- [x] OMP CLI invocation aligned with installed runtime (`omp -p --auto-approve --cwd <dir>`)
- [x] Execute-then-verify ordering in `MissionDriver`
- [x] Windows path handling with spaces
- [x] Database-level atomic attempt counting
- [x] Typed `get_last_mission_id`
- [x] Static quality checks (Ruff, MyPy, git diff --check)
- [x] Two-task real OMP E2E sandbox verification

### Local evidence
- `tests/test_omp_runtime.py`: 28 passed
- `tests/test_universal_asc.py`: 26 passed (54 total focused)
- Full repository: 715 passed, 6 skipped, 4 subtests passed
- MyPy: 36 source files clean
- Real sandbox E2E: `D:\ASC-REAL-E2E-20260821-055017` reached `COMPLETE` with 2 verified commits.

### Final verdict
**PASS** (Terminal milestone completion on 2026-08-21)

---

# 5. Next Milestone Acceptance — Real-Project Pilot (Planned)

After sandbox success, the first real product pilot must be bounded.

Before implementation:

```text
PLAN updated
MIND_MAP updated if needed
ARCHITECTURE updated
DECISIONS appended
VERIFY acceptance section added
```

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
