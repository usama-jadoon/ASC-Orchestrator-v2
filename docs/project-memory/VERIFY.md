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

# 3. What this baseline proves

It proves:

- package metadata is internally valid for the current release contract,
- Universal `asc` runtime imports,
- the full current repository test suite is green on supported CI Python versions,
- Ruff/format/MyPy/docs gates pass,
- legacy tests still coexist with the new Universal core,
- PR #6 is merged,
- the current `main` tree passes the current release gate.

---

# 4. What this baseline does NOT prove

It does not prove:

- OMP can be launched by ASC,
- OMP can edit a target project through ASC,
- execution always happens before verification,
- mission-level retry is correctly enforced,
- `max_attempts` is fully respected,
- task commits never include pre-existing user changes,
- multi-command verification works,
- executor selection works,
- a real target project can run end to end through ASC,
- Universal SQLite state and legacy PESE state are fully converged.

These remain future acceptance scope.

---

# 5. Current known code gaps

## G-001 — execution ordering

Current driver chooses verification when `task.command` exists instead of always executing the adapter first.

**Severity:** High for real autonomous coding.

**Required acceptance:** adapter invocation observed before verifier invocation.

---

## G-002 — OMP adapter absent

Current adapter directory contains:

```text
base.py
mock.py
shell.py
```

No OMP adapter.

**Required acceptance:** a mocked process-level integration test plus a real disposable sandbox proof.

---

## G-003 — bounded retry incomplete

`MissionDefaults.max_attempts` exists, but the driver does not implement the full retry contract.

**Required acceptance:**

- attempt numbers increase,
- each attempt persists,
- retry stops at max,
- exhausted task becomes FAILED/BLOCKED,
- no infinite loop.

---

## G-004 — target working directory incomplete

Execution, verification and repository actions need one explicit target project root.

**Required acceptance:** a Windows path containing spaces must work end-to-end.

---

## G-005 — Git dirty-state safety incomplete

Current commit helper may stage all changes.

**Required acceptance:**

- pre-existing user changes detected,
- unrelated changes not committed,
- failed task creates no commit,
- verified task commits only its intended changes.

---

## G-006 — mission syntax mismatch

Generated sample uses `verify`, parser uses `command`.

**Required acceptance:** one documented stable mission syntax, round-trip tests and backwards rule if needed.

---

## G-007 — only first verification command runs

Verifier accepts a list but currently selects element zero.

**Required acceptance:** either formally restrict task to one command, or implement an ordered command sequence with deterministic failure semantics.

---

# 6. Next milestone acceptance — v2.1 Real Executor Bridge

A v2.1 milestone is PASS only when all sections below succeed.

## A. Static quality

```text
ruff check src tests
ruff format --check src tests
python -m mypy src
python -m pytest tests/ -q --tb=short
python scripts/validate_docs.py
git diff --check
```

All must pass.

## B. Execution pipeline tests

Must prove:

1. executor runs before verification,
2. successful execution + verification = COMPLETE,
3. execution failure can retry,
4. verification failure can retry,
5. max attempts enforced,
6. exhausted task becomes FAILED/BLOCKED,
7. dependent task remains blocked,
8. commit occurs only after verification PASS,
9. failed task creates no commit.

## C. OMP adapter tests

Must prove:

1. executable discovery,
2. safe argument construction,
3. Windows path with spaces,
4. correct target cwd,
5. stdout capture,
6. stderr capture,
7. exit code capture,
8. timeout,
9. no test suite dependency on live paid APIs.

## D. Sandbox E2E

A disposable repository must demonstrate:

```text
ASC mission
→ READY task
→ real OMP execution
→ actual file edit
→ deterministic verification
→ commit
→ next dependent task
→ actual edit
→ verification
→ commit
→ COMPLETE
```

No push. No merge. No tag. No release.

## E. Evidence report

Final v2.1 report must include:

- exact branch,
- exact commits,
- changed files,
- tests added,
- test totals,
- OMP invocation actually discovered,
- sandbox path/fixture description,
- resulting Git commits,
- remaining limitations.

---

# 7. Real-project pilot acceptance

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
