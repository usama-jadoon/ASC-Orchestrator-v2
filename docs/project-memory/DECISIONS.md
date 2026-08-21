# ASC Orchestrator — Architecture & Product Decision Log

**Purpose:** Explain why the project looks the way it does.

This is not a simple changelog. Each entry records a choice, why it was made, and what must not be accidentally reversed later.

---

# ADR-001 — Build a control plane, not just a coding bot

**Status:** Accepted

## Decision

ASC will own mission-level truth and lifecycle rather than acting as a single code-generation agent.

## Reason

Coding agents can perform tasks, but long-running autonomous development requires state, dependencies, validation, recovery, risk, audit and completion rules.

## Consequence

External executors may come and go without redefining mission truth.

---

# ADR-002 — Persist project truth outside chat context

**Status:** Accepted

## Decision

Persistent state is required.

The first-generation engine implemented PESE with durable state/history/checkpoints.

Universal ASC v2 also introduced SQLite state.

## Reason

Chat context is temporary and eventually becomes too long, incomplete or misleading.

## Consequence

Future convergence must choose one authoritative mission-state model or define a strict hierarchy.

---

# ADR-003 — Deterministic lifecycle over free-form “agent says done”

**Status:** Accepted

## Decision

Work completion must be based on state transitions and verification evidence.

## Reason

An LLM can confidently claim success when work is incomplete.

## Consequence

Validation and release gates are first-class architecture, not optional reporting.

---

# ADR-004 — Keep Git/repository state part of mission integrity

**Status:** Accepted

## Decision

Repository identity/HEAD changes matter to mission truth.

## Reason

A mission verified against one code state must not silently continue against unrelated history.

## Consequence

v1.0.1 added explicit repository reconciliation rather than weakening integrity checks.

---

# ADR-005 — Explicit reconciliation, never automatic trust

**Status:** Accepted in v1.0.1

## Decision

A legitimate repository HEAD advance must be explicitly reconciled.

## Rejected alternative

Automatically accept whatever Git HEAD currently exists.

## Reason

Automatic acceptance would hide rewritten/diverged history.

---

# ADR-006 — Dependencies must progress automatically when prerequisites complete

**Status:** Accepted in v1.0.2

## Decision

When a required parent assignment completes, eligible dependent work must become runnable/ready.

## Reason

Real InboxShield execution exposed a lifecycle deadlock.

## Consequence

Dependency progression became a runtime invariant rather than a static graph property.

---

# ADR-007 — Validation may not run before required execution finishes

**Status:** Accepted in v1.0.2

## Decision

Validation must wait until required assignments are complete.

## Reason

A deterministic scheduler that validates too early can produce a false “green” mission.

---

# ADR-008 — Mission completion may not skip unfinished assignments

**Status:** Accepted in v1.0.2

## Decision

Execution completion must fail when required assignments remain unfinished.

## Reason

Mission status must reflect actual work state.

---

# ADR-009 — Backward-compatible state reading over destructive migration

**Status:** Accepted in v1.0.3

## Decision

Historical PESE gates missing `milestone_id` remain valid historical records when all other required fields are valid.

## Reason

Real earlier state used that shape even though later code expected the new field.

## Rejected alternatives

- rewrite historical state,
- bump schema and force migration,
- disable strict validation entirely.

## Consequence

Historical compatibility is narrow and explicit.

---

# ADR-010 — Preserve the legacy engine when Universal ASC is introduced

**Status:** Accepted

## Decision

Create `src/asc/` without deleting `src/asc_orchestrator/`.

## Reason

The original engine contains major investment in PESE, validation, audit, risk, recovery, security, scheduler and compatibility.

## Consequence

Two generations coexist until a deliberate migration/convergence plan is approved.

---

# ADR-011 — Universal ASC should be compact

**Status:** Accepted

## Decision

The new core uses a smaller model:

```text
Task
Mission
DAG
SQLite state
Verifier
Repository
Driver
Adapters
CLI
```

## Reason

The rich engine was difficult to integrate directly with an external coding runtime.

A smaller core makes the execution boundary easier to test.

---

# ADR-012 — ASC is control plane; OMP is execution plane

**Status:** Accepted

## Decision

```text
ASC determines WHAT is ready and whether it is accepted.
OMP determines HOW to perform the coding work.
```

## Reason

OMP already provides long coding-session autonomy.

Reimplementing that loop inside ASC would duplicate capability and increase failure modes.

---

# ADR-013 — OmniRoute owns provider/model routing

**Status:** Accepted

## Decision

ASC must not build another provider router.

## Reason

Routing, free-provider fallback, quotas and provider health already belong to OmniRoute.

## Consequence

Executor/model failures should be attributed to the correct layer.

---

# ADR-014 — Do not create a third orchestration loop

**Status:** Accepted

## Decision

The system has two intentional autonomy levels:

```text
OMP task-level loop
ASC mission-level loop
```

## Rejected alternative

A separate DevOS/Prime loop independently controlling mission states.

## Reason

Three schedulers/state machines would conflict and make debugging impossible.

---

# ADR-015 — Prime-style states map onto ASC instead of replacing ASC

**Status:** Accepted

## Decision

Prime concepts such as `PLANNING`, `EXECUTING`, `TESTING`, `VALIDATING` and `REPAIRING` should map to existing ASC lifecycle or integration metadata.

## Reason

Prime should improve supervision, not create another source of truth.

---

# ADR-016 — `.project-os/` remains historical control-plane truth; `.asc/` is integration/runtime metadata

**Status:** Accepted historically; convergence work still required

## Decision

Do not use `.asc/` to create a second authoritative queue/lifecycle when `.project-os/`/PESE already owns that meaning.

## Reason

Duplicated state inevitably drifts.

## Current complication

Universal ASC v2 currently persists its own SQLite state in `.asc/asc.db`.

Future architecture must explicitly reconcile this with the earlier source-of-truth rule before large production use.

---

# ADR-017 — Bounded retries only

**Status:** Accepted

## Decision

Retries must have explicit maximum attempts.

## Reason

Autonomous systems otherwise become expensive/infinite failure loops.

## Consequence

PASS or exhausted failure must terminate the current bounded path.

---

# ADR-018 — PASS is terminal for a bounded verification mission

**Status:** Accepted

## Decision

When all predefined acceptance gates pass:

```text
REPORT
→ STOP
```

## Rejected behavior

Continuing to review indefinitely because another iteration is technically possible.

## Reason

Repeated re-review wastes time and can create regressions after an already-valid state.

---

# ADR-019 — Verification follows execution

**Status:** Accepted & Implemented in v2.1

## Decision

Task execution loop must always execute the coding adapter first, then evaluate deterministic verification second:

```text
adapter.execute(task, context)
       ↓
verifier.run_verification(task.command, cwd)
       ↓
verification PASS → commit → COMPLETE
verification FAIL → bounded retry
```

## Reason

Allowing a task with `command:` to skip adapter execution would falsely declare pre-existing repository code as completed without performing the requested coding task.

---

# ADR-020 — Commit only verified work

**Status:** Accepted & Implemented in v2.1

## Decision

A task may create a commit only after required verification passes. Execution failures or verification failures must never trigger a Git commit.

## Reason

Git history is part of durable evidence.

## Future hardening scope

Task-scoped Git staging index isolation for repositories with pre-existing dirty files.

---

# ADR-021 — Never automatically push/merge/tag/release

**Status:** Accepted

## Decision

Autonomous task execution may create local verified commits, but remote publication/release actions require explicit authority.

## Reason

Those operations have broader consequences than local implementation.

---

# ADR-022 — Documentation changes before major implementation

**Status:** Accepted 2026-08-21

## Decision

Every significant feature or architectural change must first update:

```text
PLAN.md
MIND_MAP.md (if relationships change)
ARCHITECTURE.md (if boundaries change)
DECISIONS.md
VERIFY.md
```

Then implementation starts.

After implementation and acceptance, `PROJECT_HISTORY.md` is appended.

## Reason

Long prompts caused the project intent and current state to become difficult to remember.

The documentation pack becomes durable project memory.

---

# ADR-023 — Code and CI outrank old narrative

**Status:** Accepted

## Decision

When an AI report says “complete” but code/CI disagrees, trust the repository and evidence.

## Reason

During PR #6 work, narrative reports were sometimes ahead of actual Git state or omitted skipped/unfinished gates.

## Consequence

Future acceptance requires exact commit + exact gate evidence.

---

# ADR-024 — Keep historical backup before destructive local Git repair

**Status:** Accepted operational rule

## Decision

When local history diverges and must be reset to remote truth, create a backup branch first.

## Reason

This preserved local-only commits while restoring a clean `main`.

---

# ADR-025 — Real OMP Top-Level Invocation Contract

**Status:** Accepted in v2.1

## Context

Earlier adapter code assumed a non-existent `omp launch` subcommand.

## Decision

Use the actual top-level non-interactive OMP CLI contract:

```text
omp -p --auto-approve --cwd <target_dir> [--model <model>] <prompt>
```

with `stdin=subprocess.DEVNULL` to avoid Windows console input hangs.

## Reason

Verified directly against installed `omp.exe` v17.4.0+.

---

# ADR-026 — Configurable Model Parameter Propagation Without Hardcoded ASC Defaults

**Status:** Accepted in v2.1

## Context

Free upstream model endpoints can experience transient 401 quota limits, rate limits, or deprecation.

## Decision

Support `model` configuration across `defaults`, `spec`, and `task` levels, and pass it to the OMP adapter via `--model`. Do **not** hardcode a specific model (e.g. `stepfun/step-3.7-flash:free`) as an ASC production default.

## Reason

Provider selection, quota management, and failover belong to OMP and OmniRoute, not ASC.

---

# ADR-027 — Database-Level Atomic Increment with Single-Driver v2.1 Scheduler Invariant

**Status:** Accepted in v2.1

## Decision

Implement `State.increment_attempt_count` using atomic SQL:

```sql
UPDATE tasks SET attempt_count = COALESCE(attempt_count, 0) + 1 WHERE id = ?
```

inside a single SQLite transaction and query back the resulting count.

# ADR-028 — Interactive Developer Operator Console as Primary Experience

**Status:** Accepted in v2.2

## Context
Running `python script.py mission.yaml` does not provide an enterprise-grade developer CLI experience. Operators need live visual telemetry, DAG progress, system diagnostics, and interactive controls similar to modern developer CLIs (OMP, Claude Code).

## Decision
1. Bare `asc` command launches the interactive terminal operator console (Textual/Rich).
2. Subcommands (`asc doctor`, `asc status`, `asc logs`, `asc run`, `asc resume`, `asc validate`) provide one-shot scripting integration.
3. System diagnostics (`asc doctor`) report real environment metadata and truthful provider status (`OmniRoute: UNKNOWN / NOT PROBED`).

---

# ADR-029 — Project Execution Mutual Exclusion Lock

**Status:** Accepted in v2.2

## Context
Running multiple ASC driver instances concurrently against the same repository risks database lock conflicts and corrupting git worktrees.

## Decision
Implement `ProjectLock` using a file-based lock (`<repo>/.git/asc/lock` or `<cwd>/.asc/lock`) containing PID and mission metadata.
Single driver acquires lock on start, releases on termination.
If existing lock PID is dead, lock auto-recovers safely.

---

# ADR-030 — Real-Project Git Safety: Pre-Execution Dirty Check & Scoped Staging

**Status:** Accepted in v2.2

## Context
Running autonomous coding missions on real projects can accidentally stage or commit unrelated uncommitted files, or wipe out uncommitted user changes if using destructive `git reset --hard` / `git add .`.

## Decision
1. Pre-execution clean check: fail closed if repository has uncommitted modifications or untracked files before starting.
2. Scoped staging (`commit_scoped`): stage only files created or modified by the specific task attempt. Never use broad `git add .`.
3. Safe attempt delta rollback: on failed execution or failed verification, delete only task-created untracked delta files and restore modified files. Never reset user working tree broadly.

---

# ADR-031 — Safe State Location in `<repo>/.git/asc/`

**Status:** Accepted in v2.2

## Context
Storing SQLite state in `<cwd>/.asc/asc.db` introduces untracked files into the user's working tree.

## Decision
If inside a Git repository, default state path resolves to `<repo_root>/.git/asc/asc.db`.
If outside a Git repository, falls back to `<cwd>/.asc/asc.db`.

---

# Decision entry template

Append future choices as:

```markdown
# ADR-NNN — Title

**Status:** Proposed / Accepted / Superseded / Rejected

## Context
What problem exists?

## Decision
What are we choosing?

## Alternatives
What else was considered?

## Reason
Why this option?

## Consequences
What becomes easier/harder?

## Verification impact
What new acceptance gates are required?
```
