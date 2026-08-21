# ASC Orchestrator — READ FIRST

**Purpose:** This is the permanent entry point for the ASC Orchestrator project memory.

**Snapshot date:** 2026-08-21  
**Authoritative repository:** `usama-jadoon/ASC-Orchestrator-v2`  
**Current merged baseline:** `main` at `5d08358dda89b8bb00e1c0076f37d3cfa78da709`  
**Current package version:** `2.0.0`  
**Current release status:** merged and post-merge CI green, including Release Gate.

---

## 1. Why this documentation pack exists

The project became large enough that a long chat prompt was no longer a reliable source of truth. The goal of this pack is to make the project understandable even if:

- the original chats are unavailable,
- the project is reopened years later,
- a different AI or engineer takes over,
- the implementation direction changes,
- the repository contains both old and new architectures,
- a future contributor needs to know not only **what exists**, but also **why it exists**.

The files in this pack are designed like the documents used before and during construction of a building:

1. **PLAN.md** — what we are building, why, scope, milestones, future direction.
2. **PROJECT_HISTORY.md** — what happened, in chronological order, including major fixes and pivots.
3. **MIND_MAP.md** — one visual/conceptual map of the entire system.
4. **ARCHITECTURE.md** — how the system is structured and how components interact.
5. **DECISIONS.md** — important decisions, alternatives rejected, and reasons.
6. **VERIFY.md** — what “working” means, what was actually verified, current gaps, and acceptance rules.

This file is the index and operating protocol.

---

## 2. The one-sentence definition

**ASC is the authoritative mission/control plane for an autonomous software company: it decides what work is ready, tracks lifecycle/state, dependencies, validation, risk, recovery and completion; execution tools such as OMP perform the actual coding work, and OmniRoute handles model/provider routing.**

---

## 3. The naming problem — understand this before anything else

The repository contains two generations of runtime.

### A. Frozen legacy/control-plane engine

Package:

```text
src/asc_orchestrator/
```

Console command:

```text
asc-orchestrator
```

Historical software releases:

```text
1.0.0
1.0.1
1.0.2
1.0.3
```

This engine contains the larger deterministic contract stack:

```text
ACP
ACR
PESE
TBE
MSS
EEF
CKS
AEX
AHP
VAL
RKM
AGC
REC
ETR
AWS
REL
```

It is preserved because it already contains significant state, audit, lifecycle, security, recovery and validation logic.

### B. Universal ASC v2 core

Package:

```text
src/asc/
```

Console command:

```text
asc
```

Current package version:

```text
2.0.0
```

This is the compact universal orchestration core introduced by PR #6.

It contains:

```text
models
spec
dag
state
verifier
repo
driver
cli
release
adapters/
```

### Rule

Do not confuse the repository name `ASC-Orchestrator-v2` with the historical `1.0.x` legacy engine releases or the current Universal ASC package version `2.0.0`.

This naming collision is one of the main reasons this documentation pack is necessary.

---

## 4. Current truth snapshot

At this snapshot:

```text
PR #6                       MERGED
Merge commit                5d08358dda89b8bb00e1c0076f37d3cfa78da709
GitHub workflow run         32370325630
Lint & Format               PASS
Type Check                  PASS
Python 3.11 tests           PASS
Python 3.12 tests           PASS
Python 3.13 tests           PASS
Documentation               PASS
Release Gate                PASS
```

The Python 3.11 CI job collected:

```text
691 tests
685 passed
6 skipped
4 subtests passed
```

The local repository was also aligned to the same merge commit and the current release verifier returned:

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

This is the current verified baseline.

---

## 5. Documentation-first law

From now on, **no important architectural or product change should begin directly in code**.

The required sequence is:

```text
Idea / requested change
        ↓
Update PLAN.md
        ↓
Update MIND_MAP.md if system relationships change
        ↓
Update ARCHITECTURE.md if boundaries/data-flow/interfaces change
        ↓
Append DECISIONS.md with WHY
        ↓
Update VERIFY.md with acceptance criteria
        ↓
Only then implement
        ↓
Run verification
        ↓
Update VERIFY.md with evidence
        ↓
Append PROJECT_HISTORY.md after the milestone is actually completed/merged
```

### Important distinction

`PLAN.md` may describe proposed future work.

`PROJECT_HISTORY.md` must describe facts that actually happened.

Never write a planned feature into history as if it already exists.

---

## 6. AI handoff protocol

Before any AI starts implementation on ASC, it must first read, in this order:

```text
00_READ_FIRST.md
PLAN.md
PROJECT_HISTORY.md
MIND_MAP.md
ARCHITECTURE.md
DECISIONS.md
VERIFY.md
```

Then it must inspect the **current Git repository state**.

The AI must not assume these documents override newer code. If a mismatch is found:

1. record the mismatch,
2. determine which side is newer and authoritative,
3. update the documentation before broad implementation,
4. never silently invent missing architecture.

---

## 7. Sources of truth hierarchy

When sources disagree, use this order:

```text
1. Current Git repository + exact commit
2. Current tests / CI / release-gate evidence
3. Current master documentation in this pack
4. Historical PRs / changelog / release notes
5. Old prompts / chats / reports
6. AI narrative
```

A confident AI statement is never stronger than actual Git/code/test evidence.

---

## 8. Permanent project rules

- ASC owns mission truth.
- OMP should own coding-session execution.
- OmniRoute should own model/provider routing.
- Do not create duplicate authoritative lifecycle state.
- Do not create a third independent orchestration loop.
- Use bounded retries; never infinite retries.
- Verification must happen after execution, not instead of execution.
- Never auto-push, auto-merge, auto-tag or auto-release unless explicitly authorized.
- One verified task may create one commit.
- Do not silently overwrite pre-existing user changes.
- PASS is terminal for a bounded verification mission: **REPORT → STOP**.
- A new plan must update the master docs before implementation.

---

## 9. Next planned engineering boundary

The current most important unimplemented bridge is:

```text
ASC mission/control plane
        ↓
real OMP executor adapter
        ↓
actual repository edits
        ↓
deterministic verification
        ↓
bounded repair/retry
        ↓
safe Git commit
        ↓
next ASC task
```

That work belongs to the next milestone and is **not** considered complete in this snapshot.

Read `PLAN.md` and `VERIFY.md` before implementing it.
