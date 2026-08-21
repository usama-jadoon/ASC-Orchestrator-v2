# ASC Orchestrator — Master Mind Map

**Purpose:** One-page conceptual map of what ASC is, what exists, what is frozen, what is current, and what comes next.

---

# 1. Core idea

```mermaid
mindmap
  root((ASC Orchestrator))
    Purpose
      Autonomous software company control plane
      Preserve project truth
      Decide what work is ready
      Verify before completion
      Resume after interruption
    Human / Product Layer
      Goal
      Mission
      Acceptance criteria
      Constraints
      Status
    ASC Mission Control
      Mission state
      Task state
      Dependencies
      Scheduling
      Validation
      Risk
      Recovery
      Completion
    Execution Plane
      OMP
        Inspect
        Plan
        Edit
        Test
        Repair
        Review
      Shell adapter
      Mock adapter
      Future executors
    Model Routing
      OmniRoute
        Free providers
        Fallback
        Provider health
        Local models
        Quotas
    Repository
      Target project
      Git state
      Verified commits
      No automatic push
    Evidence
      Tests
      Validation gates
      Logs
      Attempts
      Audit
      Release gate
```

---

# 2. Current repository generations

```mermaid
flowchart TD
    R[ASC-Orchestrator-v2 Repository]

    R --> L[Legacy / Rich Control Plane<br/>src/asc_orchestrator]
    R --> U[Universal ASC v2 Core<br/>src/asc]

    L --> ACP[ACP Communication]
    L --> ACR[ACR Capability Registry]
    L --> PESE[PESE Persistent State]
    L --> TBE[TBE Team Builder]
    L --> MSS[MSS Mission Standard]
    L --> EEF[EEF Lifecycle]
    L --> CKS[CKS Keys/Signing]
    L --> AEX[AEX Assignment Lifecycle]
    L --> AHP[AHP Health]
    L --> VAL[VAL Validation]
    L --> RKM[RKM Risk]
    L --> AGC[AGC Agent Lifecycle]
    L --> REC[REC Recovery]
    L --> ETR[ETR Encrypted Transport]
    L --> AWS[AWS Scheduler]
    L --> REL[REL Release]

    U --> MODELS[models]
    U --> SPEC[spec]
    U --> DAG[dag]
    U --> STATE[state / SQLite]
    U --> DRIVER[driver]
    U --> VER[verifier]
    U --> REPO[repo / Git]
    U --> ADAPT[adapters]
    U --> CLI[asc CLI]
    U --> REL2[v2 release verifier]

    ADAPT --> MOCK[Mock]
    ADAPT --> SHELL[Shell]
    ADAPT -. planned .-> OMP[OMP Adapter]
```

---

# 3. Intended final runtime flow

```mermaid
flowchart TD
    G[Goal / Mission] --> P[Mission Specification]
    P --> A[ASC State + DAG]
    A --> R{READY task?}

    R -->|No, all complete| C[Mission COMPLETE]
    R -->|No, unresolved dependency/risk| B[BLOCKED / recovery decision]
    R -->|Yes| E[Executor Adapter]

    E --> O[OMP coding session]
    O --> M[Model requests]
    M --> OR[OmniRoute]
    OR --> PROVIDER[Free/local provider]

    O --> CODE[Target repository edits]
    CODE --> V[ASC deterministic verification]

    V -->|PASS| COMMIT[Safe task commit]
    COMMIT --> A

    V -->|FAIL, attempts remain| RETRY[Repair / retry]
    RETRY --> O

    V -->|FAIL, exhausted| FAIL[FAILED / BLOCKED]
    FAIL --> A
```

---

# 4. Two autonomy loops

```mermaid
flowchart LR
    subgraph Mission["ASC mission loop — authoritative"]
        A1[Select READY work]
        A2[Authorize attempt]
        A3[Evaluate result]
        A4[Advance dependency/gate state]
        A5[Decide complete/block/recover]
        A1 --> A2 --> A3 --> A4 --> A5 --> A1
    end

    subgraph Task["OMP task loop — execution"]
        O1[Inspect]
        O2[Plan]
        O3[Edit]
        O4[Test]
        O5[Repair]
        O1 --> O2 --> O3 --> O4
        O4 -->|fail within task budget| O5 --> O3
    end

    A2 --> O1
    O4 --> A3
```

**Never add a third independent mission-state loop.**

---

# 5. State ownership

```mermaid
flowchart TD
    TRUTH[Authoritative Mission Truth]

    TRUTH --> PEO[.project-os / PESE lineage]
    TRUTH --> UV2[Universal ASC SQLite state<br/>current compact runtime]

    META[Executor / integration metadata] --> ASC[.asc/]
    ASC --> SID[OMP session IDs]
    ASC --> GW[Gateway/model observations]
    ASC --> LOG[Integration diagnostics]

    NOTE[Future convergence work must prevent<br/>PESE and Universal state from becoming<br/>competing authorities.]
```

---

# 6. Historical evolution

```text
Foundation
   ↓
ACP / ACR
   ↓
PESE persistent truth
   ↓
TBE team assembly
   ↓
MSS mission intake
   ↓
EEF lifecycle
   ↓
CKS signing
   ↓
AEX assignment lifecycle
   ↓
AHP health
   ↓
VAL validation
   ↓
RKM risk
   ↓
AGC agent lifecycle
   ↓
REC recovery
   ↓
ETR encrypted transport
   ↓
AWS scheduler
   ↓
REL release verifier
   ↓
v1.0.1 repository reconciliation
   ↓
v1.0.2 dependency/lifecycle fixes
   ↓
v1.0.3 historical-state compatibility
   ↓
Universal ASC v2 compact core
   ↓
PR #6 merged + CI/Release Gate green
   ↓
NEXT: real OMP executor bridge
```

---

# 7. What is complete vs incomplete

## Complete / merged

```text
[✓] Rich legacy control-plane contracts
[✓] Persistent/audited state
[✓] Dependency/lifecycle foundations
[✓] Risk/recovery/validation foundations
[✓] Universal task/DAG core
[✓] SQLite mission/task/attempt/event state
[✓] Universal CLI
[✓] Mock/Shell adapter foundation
[✓] Git helper foundation
[✓] Release verifier
[✓] CI across Python 3.11 / 3.12 / 3.13
[✓] PR #6 merged
```

## Not complete

```text
[ ] Real OMP adapter
[ ] Execute → verify pipeline
[ ] Full bounded retry integration
[ ] Safe target-repository dirty-state isolation
[ ] Explicit executor selection
[ ] Multi-command verification contract
[ ] Sandbox OMP E2E
[ ] Real project pilot
[ ] Final convergence of old rich control plane and Universal core
```

---

# 8. The mental model to remember

If only one picture survives ten years from now, remember this:

```text
                 ┌────────────────────────┐
                 │          ASC           │
                 │ brain / mission truth  │
                 └───────────┬────────────┘
                             │ assignment
                             ▼
                 ┌────────────────────────┐
                 │          OMP           │
                 │ hands / coding runtime │
                 └───────────┬────────────┘
                             │ model calls
                             ▼
                 ┌────────────────────────┐
                 │       OmniRoute        │
                 │ model/network routing  │
                 └───────────┬────────────┘
                             │
                             ▼
                      AI providers/models

ASC decides WHAT and whether it is accepted.
OMP decides HOW to perform the coding task.
OmniRoute decides WHICH model/provider handles inference.
```
