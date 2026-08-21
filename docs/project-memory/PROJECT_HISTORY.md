# ASC Orchestrator — Project History

**Purpose:** Append-only human-readable record of what was actually built, changed, fixed or merged, and why.

**Rule:** Future planned work belongs in `PLAN.md`, not here. Add a new history entry only after the event actually occurs.

---

# 1. Before the codebase became mature

The original direction was broader than a normal coding assistant.

The project was conceived as an **Autonomous Software Company / software-development operating system** capable of maintaining project truth over long-running work.

Early design themes included:

- mission-driven execution,
- agents with defined capabilities,
- persistent project state,
- assignment ownership,
- checkpoints,
- validation gates,
- recovery,
- risk controls,
- auditable execution,
- eventual connection to an external coding runtime.

The project gradually moved from “make an autonomous coding system” to a more disciplined separation:

```text
ASC = mission/control plane
OMP = coding/execution plane
OmniRoute = model/provider routing plane
```

This separation became critical later because recreating OMP and OmniRoute inside ASC would duplicate working systems.

---

# 2. 2026-08-03 — Milestone foundation merged

## PR #1

```text
Feature/milestone 1 foundation
```

This established the repository foundation on which the later control-plane contracts were built.

The broader v1.0.0 milestone series eventually established formal interfaces and a local deterministic runtime.

---

# 3. M001–M005 — foundation, communication and registry

The initial production architecture established:

- Python `src/` package layout,
- package configuration,
- console entry point,
- ACP v1.0 Agent Communication Protocol,
- ACR v1.0 Agent Capability Registry,
- hash-chained audit records,
- local configuration,
- CLI validation surfaces,
- seeded department/capability entries.

## Why this existed

The system needed explicit machine-readable rules for:

- what an agent is,
- how agents communicate,
- how capability metadata is stored,
- how messages are validated,
- how history is audited.

The design chose deterministic local contracts instead of free-form agent communication.

---

# 4. M006–M007 — PESE persistent state

PESE became the central persistent-state engine.

It added:

- canonical mission/execution state,
- immutable history revisions,
- hash integrity,
- atomic state mutation,
- locks,
- checkpoints,
- recovery,
- migration records,
- resume,
- repository observation,
- access/transition audit trails.

## Why this mattered

A long-running autonomous development system cannot rely on chat memory.

PESE was created so the system could stop, restart and still know what was true.

This became one of the strongest architectural assets of the original engine.

---

# 5. M008 — TBE team builder

TBE added deterministic team assembly:

- registry-only specialist selection,
- capability matching,
- ownership,
- dependencies,
- resource conflicts,
- reviewers/validators,
- escalation routes,
- canonical `TEAM.md`,
- PESE binding.

## Why

The system needed to answer:

> Which agent should own which work, and what relationships exist between assignments?

TBE formalized that answer instead of leaving it to ad-hoc prompts.

---

# 6. M009 — MSS mission specification

MSS introduced structured mission intake.

It defined:

- mission types/classes,
- priority,
- authority scope,
- validation gates,
- acceptance criteria,
- constraints,
- extension keys,
- semantic validation.

## Why

Before execution, the system needed a formal statement of “what are we trying to accomplish?” and “what counts as accepted?”

This prevented mission intent from living only in a chat prompt.

---

# 7. M010 — EEF mission/execution lifecycle

EEF added the deterministic mission lifecycle:

- start,
- schedule,
- pause,
- resume,
- cancel,
- complete,
- status,
- FIFO scheduling,
- dependency-aware dispatch decisions,
- execution event journal.

## Important boundary

EEF schedules and progresses work.

It was not originally a full external AI coding executor.

That distinction later became central to the OMP integration plan.

---

# 8. M011 — CKS signing/key service

CKS added:

- key creation,
- signing,
- verification,
- rotation,
- revocation,
- status journals,
- signing ledgers,
- integrity validation.

## Why

Agent work and validation evidence needed attestable records rather than unsigned claims.

---

# 9. M012 — AEX assignment execution lifecycle

AEX added agent-owned assignment transitions and execution artifacts:

- dispatch,
- complete,
- fail,
- block,
- unblock,
- status,
- results,
- artifact persistence,
- CKS-signed attestations.

## Important clarification

AEX created a formal execution/result lifecycle.

It did not yet solve the later requirement of launching OMP as the real coding agent for arbitrary target repositories.

---

# 10. M013 — AHP health

AHP added:

- heartbeat journals,
- hash chaining,
- ALIVE / STALLED / UNKNOWN liveness,
- mission health reporting.

## Why

A real autonomous system needs to distinguish:

```text
agent is working
agent is stalled
agent has never reported
```

without relying on assumptions.

---

# 11. M014 — VAL validation engine

VAL added:

- validation-gate lifecycle,
- GREEN/RED/BLOCKED outcomes,
- SHA-256 artifact binding,
- validation evidence,
- tamper detection,
- invalidation/recovery path.

## Why

The system needed a hard rule:

> Work is not complete because an agent says it is complete; work is complete because required evidence/gates pass.

---

# 12. M015 — RKM risk management

RKM added:

- risk ledger,
- OPEN/MITIGATING/ACCEPTED/RESOLVED/HALT states,
- blocking conditions,
- mission/company-scoped risk checks.

## Why

Autonomy requires a mechanism to stop itself when risk makes further execution unsafe or invalid.

---

# 13. M016 — AGC agent lifecycle

AGC added an agent state machine:

```text
INITIALIZING
REGISTERED
READY
BUSY
BLOCKED
FAILED
QUARANTINED
REPLACED
RELEASED
```

and dependency-environment verification.

## Why

An “agent” needed a governed lifecycle rather than simply being a process that happens to run.

---

# 14. M017 — REC recovery

REC added deterministic recovery:

- diagnose failed/stalled agent,
- quarantine,
- release,
- register replacement,
- activate,
- verify dependency environment,
- return to READY,
- reclaim work where appropriate.

## Why

Long autonomous missions must recover instead of requiring a total restart.

---

# 15. M018 — ETR encrypted transport

ETR added authenticated encrypted payload/artifact transport using ChaCha20-Poly1305 concepts with key binding.

## Why

The architecture anticipated multiple agent/process boundaries where integrity and confidentiality might matter.

---

# 16. M019 — AWS top-level deterministic scheduler

AWS added one prioritized scheduling decision per tick.

Priority model included:

```text
HOLD
RECOVER
START_MISSION
DISPATCH
VALIDATE
COMPLETE_MISSION
MONITOR_HEALTH
IDLE
```

## Why

The system needed a deterministic top-level decision maker that reads system state and chooses the next allowed operation.

---

# 17. M020 — REL release verifier

REL added deterministic release checks for the original engine.

## Why

The repository itself needed a machine-checkable release boundary instead of a human statement that “everything looks ready.”

---

# 18. 2026-08-08 — v1.0.0 initial production release

The 1.0.0 release represented the first complete contract-heavy control-plane stack.

It included the formal modules above and a large automated test suite.

The design at this stage was intentionally deterministic, local and highly audited.

---

# 19. 2026-08-11 to 2026-08-12 — v1.0.1 repository reconciliation

## PR #2

```text
v1.0.1: add safe PESE repository state reconciliation
```

## Problem discovered

PESE recorded repository HEAD at mission initialization.

Legitimate authorized Git commits advanced HEAD.

PESE later interpreted this as:

```text
REPOSITORY_DIVERGENCE
```

and resume could halt.

## Fix

Added explicit:

```text
reconcile-repository
```

with rules:

- orchestrator authority,
- same repository identity,
- old HEAD must be ancestor of new HEAD,
- fail closed on Git ambiguity,
- optional expected revision,
- audit old/new HEAD,
- preserve PESE hash chain,
- mandatory checkpoint.

## Why this modification was correct

Repository state needed to advance **explicitly and audibly**, not by weakening integrity checks.

---

# 20. 2026-08-13 — v1.0.2 lifecycle deadlock fixes

## PR #3

```text
v1.0.2: fix lifecycle progression and validation deadlocks
```

## Real-world trigger

InboxShield Phase 1 exposed cases where:

- completed dependencies did not promote downstream work,
- validation could begin before all required assignments were complete,
- mission completion could move forward while assignments remained unfinished.

## Fixes

### D1 — dependency progression
Completed parent work now promotes eligible dependent assignments.

### D2 — validation timing
AWS must not start validation while mission assignments remain unfinished.

### D3 — completion integrity
EEF must not move an active mission to validation while required assignments remain incomplete.

## Why

The earlier design had strong schemas but real project use proved lifecycle progression itself needed stronger invariants.

---

# 21. 2026-08-15 to 2026-08-18 — v1.0.3 backward compatibility

## PR #4

```text
fix: v1.0.3 backward-compatible PESE state loading
```

## PR #5

```text
v1.0.3: finalize backward compatibility remediation
```

## Trigger

Historical PESE 1.0.0 state produced by earlier software versions legitimately omitted `milestone_id` on validation gates.

A newer validator treated this as invalid.

Real historical InboxShield state therefore triggered schema failures.

## Root issue

The state schema version had not changed, but validator expectations had become stricter than historical valid persisted state.

## Fix

- treat missing `milestone_id` as a compatible historical shape,
- preserve strict validation when the field is present,
- do not migrate the state schema,
- prove the state chain remained valid,
- add regression/audit fixtures.

## Why

The correct solution was compatibility, not destructive migration or weakening every validation rule.

---

# 22. Architecture pivot — do not rebuild an orchestrator around OMP

During later DevOS planning, an important design correction occurred.

An earlier direction risked building:

```text
ASC DevOS
    + a new orchestrator
    + another Prime supervisor
    + another queue
    + OMP
```

This would duplicate functionality already present in ASC.

The corrected architecture became:

```text
ASC-Orchestrator = brain/control plane
OMP              = hands/coding runtime
OmniRoute        = model/network routing
DevOS/integration = adapter/operating layer
```

## Why

The project already contained:

- PESE,
- lifecycle,
- audit,
- validation,
- recovery,
- repository reconciliation,
- scheduling.

Rewriting those systems would increase bugs and create competing sources of truth.

---

# 23. Prime-style supervision was redefined

The “Prime” concept was originally at risk of becoming a separate supervisor state machine.

The design changed to:

- map Prime-style states onto ASC lifecycle where equivalent,
- keep UI/executor-only state outside authoritative mission truth,
- ASC decides whether another attempt is allowed,
- OMP performs the repair,
- retries are bounded,
- no third independent orchestration loop.

## Why

Multiple lifecycle engines would eventually disagree.

---

# 24. Two-level autonomy model established

The agreed autonomy model became:

## Level 1 — OMP task loop

Inside one ASC assignment, OMP may:

- inspect,
- plan,
- edit,
- test,
- repair,
- retry,
- review.

## Level 2 — ASC mission loop

ASC controls:

- assignment selection,
- dependencies,
- mission progression,
- validation,
- milestones,
- recovery,
- completion.

## Rule

Do not recreate OMP’s long coding loop inside ASC.

Do not make OMP the authoritative mission database.

---

# 25. State ownership rule established

Historical integration planning defined:

```text
.project-os/
```

as the authoritative ASC mission/control-plane state.

And:

```text
.asc/
```

as runtime/integration metadata only.

The purpose was to prevent:

```text
PESE says one thing
.asc queue says another
OMP session says a third thing
```

Mission truth must have one owner.

---

# 26. 2026-08-20 — Universal ASC v2 core created

A new compact engine was created under:

```text
src/asc/
```

The Universal ASC branch introduced:

- `models.py`
- `spec.py`
- `dag.py`
- `state.py`
- `verifier.py`
- `repo.py`
- `driver.py`
- `cli.py`
- adapters
- v2 release verifier
- Universal ASC tests

The compact core was designed to make a reusable mission runtime easier to integrate and reason about.

---

# 27. PR #6 — Universal ASC v2

## PR

```text
Feature/universal asc v2
```

## Base

The branch was built on the frozen v1.0.3 main baseline.

## Key work

- introduced `src/asc/`,
- added `asc` console command,
- preserved legacy `asc-orchestrator` command,
- added YAML dependency via PyYAML,
- added DAG/runtime/state/adapter/verification/Git foundations,
- added Universal ASC test suite,
- added v2 release verifier,
- updated CI for Python 3.11/3.12/3.13,
- preserved legacy engine.

## Important correction during PR work

Cross-platform execution and release-verification details required several iterations.

A Copilot WIP PR (#7) was opened against the feature branch, but it was closed unmerged.

The final PR #6 itself was merged.

---

# 28. 2026-08-20 — PR #6 merged

Merge commit:

```text
5d08358dda89b8bb00e1c0076f37d3cfa78da709
```

Post-merge workflow:

```text
Run 32370325630
```

Result:

```text
overall CI       PASS
Lint & Format    PASS
Type Check       PASS
Python 3.11      PASS
Python 3.12      PASS
Python 3.13      PASS
Documentation    PASS
Release Gate     PASS
```

Python 3.11 evidence:

```text
691 collected
685 passed
6 skipped
4 subtests passed
```

This is the current official merged baseline.

---

# 29. Local repository repair after merge

The local repository contained diverged/local-only history.

To avoid losing work:

- a backup branch was created,
- remote refs were fetched,
- local `main` was reset to `origin/main`,
- local `main` was verified at the merge SHA,
- package was reinstalled editable,
- local v2 release verification returned PASS.

A backup branch preserved local-only work:

```text
backup/local-main-4acdba
```

## Why

The goal was to align the working `main` to remote truth without destroying local historical work.

---

# 30. Current state — 2026-08-21

The project now contains:

```text
A. Frozen rich legacy/control-plane engine
B. Universal ASC v2 compact core
C. Green CI/release baseline
D. A clear OMP/OmniRoute integration direction
```

But the real executor bridge is not finished.

The biggest next gap is:

```text
ASC selects task
→ OMP executes work
→ ASC verifies
→ bounded retry if necessary
→ safe commit
→ next task
```

This belongs to future work and is documented in `PLAN.md`.

---

# 31. How to append future history

Use this template only after a real milestone completes:

```markdown
# YYYY-MM-DD — <milestone name>

## Trigger
What problem or need caused this work?

## Before
What was the prior behavior?

## Change
What was implemented?

## Why
Why was this design chosen?

## Verification
What exact tests/gates/evidence passed?

## Commit / PR
Exact commit / PR identifiers.

## Result
What is now true that was not true before?
```

Do not delete old history because the plan later changes.
