# TEAM BUILDER ENGINE (TBE v1.0) SPECIFICATION

## Official Dynamic Team Assembly Standard for ASC Orchestrator v2

**Status:** Permanent Specification — Ratified
**Version:** 1.0
**Applies to:** All missions executed under ASC Orchestrator v2
**Dependencies:** ACP v1.0 (Agent Communication Protocol), ACR v1.0 (Agent Capability Registry), MSS v1.0 (Mission Specification Standard)

---

## 1. TEAM ASSEMBLY PHILOSOPHY

### 1.1 PURPOSE

The Team Builder Engine (TBE) determines, for every repository and every mission, exactly which software company must be assembled to complete the work. TBE is the sole authority responsible for answering seven questions before any agent is activated:

1. Which departments are required?
2. Which specialist agents are required?
3. How many agents are needed?
4. Which repository areas does each agent own?
5. Which agents may execute in parallel?
6. Which agents must execute sequentially?
7. Who reviews, and who validates?

### 1.2 CORE PHILOSOPHY

The following principles are normative and permanent. They govern every team assembly decision and may not be relaxed by any mission, orchestrator, or agent.

**Rule 1.2.1 — No Fixed Teams.**
ASC Orchestrator v2 never assumes a pre-existing team. Every mission begins with zero assumed personnel. The team is derived from evidence: the repository classification, the mission type (per MSS v1.0), the acceptance criteria, and the available capability registry.

**Rule 1.2.2 — Smallest Capable Team.**
The engine must assemble the smallest team that can reliably satisfy the mission's acceptance criteria and validation gates. Every additional agent beyond necessity introduces coordination overhead, communication risk, and ownership ambiguity. An agent may only be added when a specific, named capability gap justifies it.

**Rule 1.2.3 — Capability Before Headcount.**
Departments exist as logical capability groupings, not as hiring quotas. A repository that requires no security gate does not receive a security auditor "for completeness." Capability needs are proven, never presumed.

**Rule 1.2.4 — Evidence-Driven Assembly.**
Every team assembly decision must be traceable to concrete inputs: repository classification results, mission requirements, risk assessment, or explicit resource policy. No agent may be assigned "because it is usually needed."

**Rule 1.2.5 — Deterministic and Auditable.**
Given identical inputs, TBE must produce an identical team manifest. All selection, sizing, ownership, and scheduling decisions are recorded in the team manifest (Section 2.4) and remain auditable for the lifetime of the mission and after dissolution.

**Rule 1.2.6 — Ownership Is Exclusive.**
No file, artifact, or repository area may be owned by more than one active agent at any point in time (Section 8). Exclusive ownership is the primary conflict-prevention mechanism and takes precedence over speed or convenience.

**Rule 1.2.7 — Builders Never Gate Their Own Work.**
Every unit of work must pass through at least one reviewer and, where mandated by the project profile, an independent validator. The final gate must be independent of the builder. No exceptions exist at any team size, including single-agent teams; when the team is minimal, gating responsibility reverts to the orchestrator.

**Rule 1.2.8 — Teams Are Ephemeral.**
A team exists to serve one mission. It is assembled for that mission, operates under an immutable manifest, recovers from failure within defined bounds, and is dissolved upon verified completion. Long-running teams (Section 17) are a governed exception for multi-mission engagements, not a default.

**Rule 1.2.9 — Adaptation Without Redesign.**
TBE must support every project type and mission type — AI SaaS, WordPress plugins, Next.js applications, React libraries, Python packages, Go and Rust CLIs, healthcare and regulated systems, enterprise platforms, infrastructure, mobile applications, and browser extensions — without modification to this specification. New project types are absorbed through the capability registry and classification inputs, never through changes to the assembly algorithm.

### 1.3 NON-GOALS

The following are explicitly outside TBE's scope:

- Writing, reviewing, or executing code (agents do this; TBE assembles them).
- Executing missions or managing runtime state (the Orchestrator's role).
- Defining agent capabilities (owned by ACR v1.0).
- Defining communication mechanics (owned by ACP v1.0).
- Persisting mission results outside the records defined in Section 2.4 and Section 19.

### 1.4 OPERATING MODES

TBE operates in four modes, selected automatically by orchestrator context:

| Mode | Trigger | Behavior |
|------|---------|----------|
| **ASSEMBLY** | New mission accepted | Full Section 5 algorithm executes; new team manifest produced |
| **ADJUSTMENT** | Scaling trigger fires (Section 7.3) mid-mission | Members added or removed under manifest versioning; in-flight work protected |
| **RECOVERY** | Agent failure or degraded execution detected | Failed member quarantined and replaced (Section 18); ownership reassigned via ACP ownership transfer |
| **DISSOLUTION** | Mission reaches terminal state | Final validation runs, records archived, team released (Section 19) |

---

## 2. ORGANIZATION MODEL

### 2.1 LAYER STRUCTURE

All ASC Orchestrator v2 organizations, regardless of size, conform to exactly three operational layers:

1. **Orchestration Layer** — The Orchestrator. Exactly one per mission tree. Owns the mission contract, team assembly decisions, escalation arbitration, and final mission disposition. Never performs builder work.
2. **Leadership Layer** — Team Leads and Department Leads. Zero or more per team (Section 7 determines count). Translate mission objectives into assignments, arbitrate intra-team disputes, and consolidate evidence.
3. **Execution Layer** — Specialist agents in builder, reviewer, validator, and support roles. Perform all concrete work on the repository.

### 2.2 NORMATIVE LAYER RULES

**Rule 2.2.1 — Single Authority Chain.**
Every agent has exactly one direct superior in the authority chain. Matrix authority is prohibited. A validator's duty to block a release (Section 14) is an ACP right, not a second authority line.

**Rule 2.2.2 — No Peer Assignment.**
An Execution-layer agent may never issue an ASSIGNMENT message (per ACP v1.0 Message Types) to a peer. Work distribution flows only down the authority chain; coordination flows only through defined ACP message types.

**Rule 2.2.3 — Lead Presence Threshold.**
A Leadership-layer role must exist when the team exceeds five Execution-layer agents. Below the threshold, the Orchestrator assumes leadership duties directly. Leads are never created below the threshold, because a lead coordinating fewer than five agents wastes a slot that could hold a builder.

**Rule 2.2.4 — Department Lead Scope.**
A Department Lead may coordinate agents from multiple TBE departments when those agents share a project phase. Department boundaries organize capabilities; they do not create organizational silos.

### 2.3 ROLES

Every team member occupies exactly one primary role:

| Role | Layer | Core Duty | Selection Source |
|------|-------|-----------|------------------|
| Orchestrator | Orchestration | Own mission contract; assemble team; arbitrate escalations | Fixed (system) |
| Team Lead | Leadership | Translate mission into assignments; consolidate evidence | Selected if size mandates |
| Builder | Execution | Produce and modify artifacts in owned areas | ACR query by purpose |
| Reviewer | Execution | Verify work products against acceptance criteria; issue APPROVAL or REVIEW | ACR query; disjoint from builder (Section 13) |
| Validator | Execution | Execute independent validation gates; hold release-blocking authority | ACR query; independent (Section 14) |
| Investigator | Execution | Produce read-only analysis and classification | ACR query; investigation-phase only |
| Support | Execution | Perform maintenance duties (documentation refresh, dependency hygiene) | ACR query on trigger |

A single agent instance may not simultaneously hold a builder role and a reviewer or validator role over the same work product (Section 13.2, independence rules).

### 2.4 TEAM MANIFEST

Every assembled team is described by a **Team Manifest**, stored at:

```
.project-os/COMPANY/TEAMS/<team-id>/TEAM.md
```

The manifest is the authoritative, human-readable record of the team. It must contain, in fixed order:

1. **TEAM IDENTITY** — team-id, mission-id, assembly timestamp (ISO 8601 UTC), operating mode.
2. **PROJECT CLASSIFICATION** — every detected project's type, root path, language, framework, platform, and constraint tags (e.g., `regulated:healthcare`).
3. **MEMBERSHIP TABLE** — one row per active member: agent id (ACP format `AGENT:<agent-type>:<instance-id>`), role, department, ACR registry reference.
4. **OWNERSHIP MATRIX** — mapping of every mutable repository area and artifact class to exactly one owning agent (Section 8.1).
5. **EXECUTION GRAPH** — the parallel groups (Section 9) and sequential groups (Section 10), expressed as a phase index per member, plus the full dependency graph (Section 11).
6. **REVIEW MATRIX** — reviewer assignment per deliverable type, including rotation state (Section 13.6).
7. **VALIDATOR ASSIGNMENT** — the independent validator, gates owned, and fallback validator for regulated projects (Section 14).
8. **ESCALATION ROUTES** — every escalation level and destination (Section 15).
9. **CAPACITY RECORD** — declared capacity per member and headroom (ACR `PARALLEL EXECUTION RULES`).
10. **ACTIVE POLICIES** — constraint-controlled policy resolutions (e.g., regulated-project validator requirement) with evidence references.

The manifest is versioned. Every change (ADJUSTMENT mode, RECOVERY mode) increments the version and records the change reason, and every team member must receive a MISSION_UPDATE message (ACP v1.0) containing the new version before the change takes effect. A member acting on a stale manifest version is a protocol violation handled per ACP v1.0 conflict-resolution rules.

### 2.5 TEAM IDENTITY

Teams carry a globally unique identifier:

```
TEAM:<mission-id>:<sequence>
```

- `mission-id` — the immutable mission identifier from the mission contract.
- `sequence` — incrementing integer distinguishing successive teams serving one mission across RECOVERY or ADJUSTMENT events.

Individual members are identified exclusively by their ACP agent identifiers (`AGENT:<agent-type>:<instance-id>`). Team membership is recorded in the manifest and propagated to each member during activation; agents derive all routing decisions from ACP addressing rules using these identifiers.

---

## 3. DEPARTMENT MODEL

### 3.1 THE CANONICAL DEPARTMENTS

TBE recognizes exactly eight logical departments. A department is a capability grouping used for selection coverage analysis and leadership organization; it is not an employment unit and carries no minimum staffing.

| Department | Capability Domain | Typical Coverage Trigger |
|------------|-------------------|--------------------------|
| ENGINEERING | Implementation of features, fixes, refactors across all languages and frameworks | Any mission with code changes |
| QUALITY | Test authorship, test execution, coverage analysis, acceptance verification | Any project with a test surface |
| SECURITY | Threat modeling, vulnerability audit, dependency security, compliance evidence | `security` flag, credential handling, public interfaces |
| OPERATIONS | CI/CD, release engineering, deployment, environment configuration, rollback | Pipelines, deployment targets, release missions |
| PRODUCT | Requirements clarification, scope arbitration, acceptance wording, backlog | Ambiguous acceptance criteria; product-feature missions |
| DESIGN | UI/UX decisions, accessibility, layout, design system consistency | User-facing interface surfaces |
| DATA | Schema design, migrations, data pipelines, seed data, analytics models | Database or pipeline presence |
| RESEARCH | Repository investigation, dependency research, external API verification, classification | Investigation phases; greenfield exploration |

### 3.2 NORMATIVE DEPARTMENT RULES

**Rule 3.2.1 — Demand-Driven Existence.**
A department exists within a team only if at least one selection demand (Section 5, Phase D) maps to it. Departments with zero demand are omitted entirely.

**Rule 3.2.2 — One Agent, Many Departments.**
A single specialist agent may satisfy demands from multiple departments when its ACR entry's `REQUIRED SKILLS` and `mission-types` cover those demands. Department counts never force headcount.

**Rule 3.2.3 — Department Lead Optionality.**
A Department Lead is created only when a single department's demand requires three or more concurrent specialists. Otherwise those specialists report to the Team Lead or Orchestrator.

**Rule 3.2.4 — Cross-Department Work Products.**
Deliverables spanning departments (e.g., a UI feature touching DESIGN, ENGINEERING, QUALITY) receive a single owning builder (Section 8) and a reviewer selected from a department different from the builder's primary department whenever staffing permits.

**Rule 3.2.5 — Department Registries.**
Department scope is realized through ACR entries stored in `.project-os/COMPANY/DEPARTMENTS/` (one file per agent type, per ACR v1.0). TBE never duplicates capability data; it references ACR as the single authority.

### 3.3 DEPARTMENT ACTIVATION TABLE

The following table defines the minimum project-profile evidence that activates each department during selection. Activation is necessary but not sufficient for staffing — the final decision always belongs to the Section 5 algorithm.

| Department | Activating Evidence |
|------------|---------------------|
| ENGINEERING | Mutable source files within mission scope |
| QUALITY | Test infrastructure present, or acceptance criteria requiring verification evidence |
| SECURITY | `security` mission flag; network-facing surface; auth/payment/credential code; regulated constraint tag |
| OPERATIONS | CI configuration, deployment target, container definitions, or release-type mission |
| PRODUCT | Acceptance criteria containing unresolved ambiguity (per mission intake) |
| DESIGN | Rendered UI surfaces (markup templates, components, styles) within scope |
| DATA | Schema files, migration tooling, seed fixtures, or pipeline definitions |
| RESEARCH | Unfamiliar repository (no prior classification), missing documentation, unverified external dependencies |

---

## 4. SPECIALIST AGENT MODEL

### 4.1 SPECIALIST DEFINITION

A specialist agent is an instance of a registered agent type whose complete behavioral contract is defined by its ACR v1.0 entry. TBE never defines agent behavior; it selects from the registry. Each ACR entry supplies the -> fixed subsections (IDENTITY through OUTPUT CONTRACTS) that TBE consumes during selection, sizing, ownership mapping, and escalation route construction.

### 4.2 SPECIALIST SELECTION FIELDS

The Section 5 algorithm consumes these ACR subsections directly:

- **mission-types** — which mission types the specialist is authorized to serve.
- **REQUIRED SKILLS** — matched against classified languages and frameworks.
- **OWNS ARTIFACTS / OWNS REPOSITORY AREAS** — drives the Ownership Matrix.
- **PARALLEL EXECUTION RULES** — drives parallel-group membership and capacity.
- **DEPENDENCIES** — declares prerequisite roles, driving sequential-group construction.
- **INPUT CONTRACTS / OUTPUT CONTRACTS** — drive dependency-graph edge validation and handoff compatibility.
- **ESCALATION RIGHTS and validation gates** — drive escalation route construction.
- **VALIDATION DUTIES / RECOVERY DUTIES** — drive validator assignment and recovery planning.

### 4.3 CANONICAL SPECIALIST CATALOG

The following canonical specialist types complete the selection vocabulary of this specification. Each type's full behavioral contract lives in the ACR registry; the summaries below are non-normative orientation only.

| Specialist | Department | Primary Function |
|------------|-----------|------------------|
| investigator | RESEARCH | Read-only repository classification, structure analysis, evidence gathering |
| developer | ENGINEERING | Core implementation across languages and frameworks |
| frontend-developer | ENGINEERING | UI implementation: React, Next.js, styling systems, frontend build tooling |
| backend-developer | ENGINEERING | Server logic, APIs, services, integration layers |
| wordpress-developer | ENGINEERING | Theme/plugin development, hooks, multisite, WP-CLI, core conventions |
| mobile-developer | ENGINEERING | iOS, Android, and cross-platform mobile implementation |
| extension-developer | ENGINEERING | Browser extension architecture, manifest, content/background scripts |
| infrastructure-engineer | OPERATIONS | IaC, containers, cloud resources, environment definitions |
| devops-engineer | OPERATIONS | CI/CD pipelines, release automation, deployment configuration |
| release-manager | OPERATIONS | Versioning, changelog, release execution, rollback coordination |
| test-engineer | QUALITY | Test authorship, coverage enforcement, flaky-test remediation |
| qa-validator | QUALITY | Independent verification, acceptance testing, regression validation |
| security-auditor | SECURITY | Vulnerability audit, secrets scanning, dependency security review |
| compliance-validator | SECURITY | Regulated-domain evidence gates (HIPAA, 21 CFR Part 11, SOC 2) |
| ui-ux-designer | DESIGN | Layout, interaction, accessibility, design system application |
| database-engineer | DATA | Schema design, migrations, query optimization, integrity constraints |
| data-engineer | DATA | Pipelines, ETL, dataset validation |
| ai-ml-engineer | DATA / ENGINEERING | Model integration, prompt engineering, evaluation harnesses |
| technical-writer | PRODUCT | Documentation, API references, changelog prose |
| product-analyst | PRODUCT | Requirements clarification, acceptance wording, scope arbitration |

### 4.4 NORMATIVE SPECIALIST RULES

**Rule 4.4.1 — Registry-Only Selection.**
Only agent types present in the ACR registry and authorized for the mission type may be selected. A capability gap with no registered specialist is escalated to the Orchestrator as a mission-scope exception; it is never silently bridged.

**Rule 4.4.2 — Specialist Generalization.**
Where a demand is narrow (e.g., a three-line CSS fix), the orchestrator may assign it to a broader specialist whose skills cover it rather than activating a narrow type. Generalization must be recorded in the manifest with the justification.

**Rule 4.4.3 — Instance Multiplicity.**
Multiple instances of one specialist type may serve a single team only when ownership regions are disjoint and capacity demands exceed one instance. The `instance-id` component of the ACP identity guarantees address uniqueness.

**Rule 4.4.4 — Role Purity Per Task.**
One agent instance may sequence through roles across a mission (e.g., developer earlier, reviewer later) but may never hold conflicting roles over the same work product. Role transitions are recorded as manifest adjustments.

---

## 5. TEAM SELECTION ALGORITHM

### 5.1 ALGORITHM OVERVIEW

The Team Selection Algorithm is a deterministic, six-phase procedure executed in ASSEMBLY mode. Its inputs and outputs are fixed:

**Inputs:**
- `mission-contract` — objectives, acceptance criteria, constraints, mission type (per MSS v1.0).
- `repository-classification` — per-project: type, languages, frameworks, platform targets, test surface, deployment surface, regulated/security constraint tags.
- `capability-registry` — the current ACR v1.0 registry.
- `resource-policy` — capacity ceilings and budget constraints, if any.

**Outputs:**
- A complete Team Manifest (Section 2.4), validated and versioned.

The six phases execute strictly in order. Each phase must complete and record its output before the next begins.

### 5.2 PHASE A — CLASSIFY REPOSITORY

For each detected project in the repository, derive the classification tuple:

```
project := { type, root-path, languages[], frameworks[], platform, test-surface, deployment-surface, constraint-tags[] }
```

Classification sources, in precedence order:
1. Explicit declarations in the mission contract.
2. Automated repository inspection (manifests, lockfiles, CI configuration, directory structure).
3. An `investigator` specialist activation when sources 1–2 are inconclusive.

Multi-project repositories produce one tuple per project; all downstream phases iterate over the tuple set. Constraint tags (e.g., `regulated:healthcare`, `public-api`, `financial`) propagate into every staffing and gating decision involving the affected project.

### 5.3 PHASE B — DERIVE CAPABILITY DEMANDS

From the mission contract and classification, derive the explicit work demand set. Each demand names one capability, its source, and its scope:

```
demand := { capability, source-project, source-criterion, mutable-paths[], validation-gates[] }
```

Demands derive from three generators:
- **Mission-type demands** — the baseline capability set mandated by the mission type (per MSS v1.0 mission-type definitions).
- **Criterion demands** — one demand per acceptance criterion, mapping the criterion to the capabilities and validation gates that can satisfy it.
- **Constraint demands** — demands injected by constraint tags. Example: `regulated:healthcare` injects a mandatory `compliance-validator` demand and a primary-validator independence requirement.

A demand with no capable specialist in the registry halts assembly and escalates per Section 15 with severity CRITICAL.

### 5.4 PHASE C — DETERMINE TEAM SIZE

Apply the Team Sizing Rules (Section 7) to the demand set. This phase produces:
- The initial headcount target.
- Department-level staffing (Section 3).
- The Leadership-layer decision (Rule 2.2.3).
- Reserved capacity declarations per member.

Sizing never overrides capability coverage: a larger team missing a required capability is invalid; a smaller team covering all capabilities is preferred.

### 5.5 PHASE D — MAP SPECIALISTS

Demands are mapped to concrete specialist types in five deterministic steps:

1. **Exact-type match** — a specialist whose type aligns directly with the demand capability (e.g., schema migration demand → `database-engineer`).
2. **Skill-overlap consolidation** — merge demands coverable by one already-selected specialist (Rule 4.4.2), recording each consolidation in the manifest.
3. **Department balancing** — verify no department holds three-plus specialists without a Department Lead (Rule 3.2.3); split or add leadership as required.
4. **Constraint gating** — enforce constraint-injected requirements (regulated projects: validator independence; public-API projects: documentation coverage).
5. **Ownership pre-check** — compute candidate ownership regions; reject any mapping that would assign the same mutable area to two builders (Section 8). Resolve by re-partitioning scope, not by adding coordination agents.

### 5.6 PHASE E — ASSIGN OWNERSHIP

Construct the Ownership Matrix (Section 8.1):
- Assign every mutable path from every demand to exactly one builder.
- Assign shared artifacts their artifact-ownership class (`exclusive` or `shared-with-validator`) per the owning specialist's ACR entry.
- Record path restrictions (e.g., `["/.git/", "/.project-os/", "/secrets/"]`) for every member from its ACR entry.

The completed matrix must pass the Section 8.2 validation predicates before Phase F begins.

### 5.7 PHASE F — SELECT REVIEWERS, VALIDATORS, AND ESCALATION ROUTES

Final assembly steps, in order:
1. Apply Reviewer Assignment rules (Section 13): every deliverable type receives a reviewer disjoint from its builder.
2. Apply Validator Assignment rules (Section 14): select the independent validator; for regulated projects, designate and publish the fallback validator.
3. Construct the Escalation Hierarchy routes (Section 15) from selected members' ACR escalation rights.
4. Validate the complete manifest against Sections 2.4, 8.2, 9.2, 10.2, 11.2, 13.2, and 14.2. Any validation failure halts assembly and escalates; a partially assembled team may never activate.

### 5.8 DETERMINISM AND REBUILD INVARIANCE

Given identical inputs, the algorithm must produce a byte-identical Membership Table, Ownership Matrix, and Execution Graph (timestamps and generated instance-ids excepted). Any non-determinism discovered in production is a specification-compliance defect and must be remediated before further assemblies.

---

## 6. AGENT SELECTION RULES

### 6.1 MANDATORY SELECTION RULES

**Rule 6.1.1 — Registry Presence.**
A candidate specialist must exist in the ACR registry, be in `active` lifecycle status (per ACR v1.0 REGISTRY MANAGEMENT RULES — deprecated types are selectable only within their documented backward-compatibility window and only for maintainer-mode missions on legacy repositories).

**Rule 6.1.2 — Mission-Type Authorization.**
The candidate's ACR `mission-types` must include the current mission type, or include a wildcard authorization explicitly covering it. Example: a `qa-validator` whose entry lists `[enhancement, security-audit, refactor, test-coverage-boost]` may not staff an `infrastructure-provisioning` mission unless its entry also authorizes that type.

**Rule 6.1.3 — Input/Output Contract Compatibility.**
Handoff compatibility must hold for every adjacent pair in the Execution Graph: a downstream agent's ACR INPUT CONTRACTS must accept the upstream agent's OUTPUT CONTRACTS message types and schemas. Adjacency without contract compatibility forks the execution sequence (Section 10.3) rather than forcing an incompatible pairing.

**Rule 6.1.4 — Path Right Consistency.**
The candidate's ACR `OWNED REPOSITORY AREAS` (owned-paths, writable-paths, path-restrictions) must be compatible with the areas implied by its assigned demands. A `frontend-developer` restricted from `/server/` may not receive a demand whose `mutable-paths` include server code; the demand is repartitioned or reassigned.

**Rule 6.1.5 — Capacity Availability.**
Declared parallel capacity (ACR `PARALLEL EXECUTION RULES`) must accommodate the assignment. An agent already at its parallel ceiling in an active long-running engagement may not receive additional concurrent assignments from a new team.

### 6.2 TIE-BREAKING ORDER

When multiple specialists satisfy all mandatory rules, selection proceeds by these criteria, in order:

1. **Scope coverage** — prefer the specialist satisfying the most demands (reinforces Rule 1.2.2).
2. **Skill precision** — prefer the specialist whose REQUIRED SKILLS match the classified languages/frameworks most specifically (e.g., `wordpress-developer` over generic `developer` for a plugin project).
3. **Constraint qualification** — for regulated projects, prefer specialists with compliance evidence duties registered.
4. **Registry stability** — prefer higher-version, non-deprecated entries.
5. **Deterministic order** — final tie-break by lexicographic agent-type name (guarantees Section 5.8 invariance).

### 6.3 PROHIBITED SELECTIONS

The following selections are forbidden under all circumstances:

- An agent as reviewer of its own output (Section 13.2).
- A builder from the same department as the primary validator for the final release gate on regulated projects (Section 14.2).
- Any specialist whose escalations would route to itself (self-loop in the Section 15 graph).
- More than one Orchestrator-role member per mission tree.

### 6.4 SELECTION RECORD

Every selection decision is recorded in the manifest as:

```
selection-record := { demand-id, chosen-agent-type, rejected-candidates[], applied-rules[], justification }
```

Rejected candidates are listed with the specific rule that excluded them. This record is the audit basis for post-mission assembly review (Section 19.3).

---

## 7. TEAM SIZING RULES

### 7.1 SIZING FORMULA

Initial headcount is computed as:

```
headcount = max(minimum-viable, capability-coverage-count)
```

where:

- **capability-coverage-count** — the number of distinct specialists required after Section 5.5 consolidation to cover every demand.
- **minimum-viable** — derived from the project class table below.

| Project Class | Minimum Viable Team | Composition |
|---------------|--------------------:|-------------|
| Trivial task (single-criterion, single-file scope) | 2 | builder + reviewer (validator duties to orchestrator per Rule 1.2.7) |
| Small (single project, ≤3 criteria) | 3 | builder + reviewer + validator (or combined quality role) |
| Medium (single project, multiple subsystems) | 4–6 | add dedicated test-engineer, operations as demanded |
| Large (multi-project or regulated) | 6–9 | full gating chain, dedicated validators, leadership |
| Enterprise/monorepo (5+ projects) | 9+ (partitioned) | subteams per project cluster (Section 7.4) |

**Rule 7.1.1 — Coverage Overrides Minimum.** If capability-coverage-count exceeds the table minimum, the larger number wins. Minimums never justify understaffing a mandated capability (e.g., a compliance validator on a healthcare project).

**Rule 7.1.2 — Hard Ceiling.** A single team must not exceed fifteen Execution-layer members. Exceeding the ceiling triggers subteam partitioning (Section 7.4), never a larger flat team.

### 7.2 SIZING DETERMINANTS

The sizing phase must evaluate, and record, each determinant:

- **Project count and perceptibility** — number of classified projects and whether each has its own ownership region.
- **Acceptance-criterion count** — more criteria demand more parallel verification capacity.
- **Constraint tags** — regulated and public-API tags add mandatory roles that raise the floor.
- **Mission-type baseline** — per MSS v1.0 (e.g., `multi-repo-orchestration` implies investigator plus per-repository builders).
- **Risk indicators** — unfamiliar repository, missing tests, or undocumented subsystems add investigator and quality capacity.

### 7.3 DYNAMIC RESIZING

Team size may change mid-mission (ADJUSTMENT mode) under exactly two trigger classes:

- **Scale-up triggers** — newly discovered demands (unowned scope found during investigation); sustained capacity exhaustion (all instances of a type at ceiling for two consecutive phases); mandated-role discovery (a constraint tag identified late).
- **Scale-down triggers** — demands completed and their specialists idle for one full phase; scope formally reduced by mission-contract amendment.

Every resize is a manifest version increment accompanied by MISSION_UPDATE broadcast. In-flight assignments are never preempted by a resize; scaled-down members complete or hand off active work first.

### 7.4 SUBTEAM PARTITIONING

When headcount would exceed the Rule 7.1.2 ceiling, TBE partitions the team into subteams:

1. Partition by project cluster, keeping each subteam under the ceiling.
2. Assign each subteam its own Team Lead reporting to the Orchestrator.
3. Shared integration surfaces (e.g., a monorepo's shared libraries) receive cross-subteam ownership per Section 8.4 (shared-surface rules) and a designated integration reviewer.
4. Subteams appear in one manifest under distinct membership groups; inter-subteam communication follows ACP v1.0 addressing normally.

### 7.5 LONG-RUNNING TEAM SIZING

Long-running teams (Section 17) size to the demand profile of the engagement, not any single mission: staff the persistent core (Section 17.2) at the engagement's steady-state demand, and rely on Temporary Teams (Section 16) for demand spikes.

---

## 8. OWNERSHIP RULES

### 8.1 OWNERSHIP MATRIX

The Ownership Matrix is the normative machine-checkable mapping:

```
ownership := { area | artifact-class → single owning agent, ownership-class, path-restrictions[] }
```

Every mutable repository area within mission scope and every produced artifact class must appear in exactly one matrix entry. Areas outside mission scope are implicitly owned by no team member and must not be modified.

### 8.2 MATRIX VALIDATION PREDICATES

Before team activation, the orchestrator must verify all of:

1. **Coverage** — every demand's `mutable-paths` appear in the matrix.
2. **Exclusivity** — no area or artifact class maps to more than one builder.
3. **Registry consistency** — each entry's ownership class matches the owning specialist's ACR entry (`artifact-ownership: exclusive | shared-with-validator`).
4. **Restriction enforcement** — every member's path-restrictions are recorded and include at minimum `/.git/`, `/.project-os/` (leadership-excepted), and any project-declared sensitive paths such as `/secrets/`.
5. **Write-path containment** — each builder's writable areas are a subset of its owned areas plus explicitly shared surfaces.

### 8.3 NORMATIVE OWNERSHIP RULES

**Rule 8.3.1 — Write Exclusivity.** Only the owning builder may write to an owned area. All other agents hold read-only access to areas they do not own.

**Rule 8.3.2 — Ownership Discovery.** Before touching any path, an agent must resolve its ownership from the current manifest version. Acting on stale ownership data is a protocol violation (Section 2.4).

**Rule 8.3.3 — Ownership Transfer.** Ownership moves only through the ACP v1.0 ownership-transfer protocol, initiated by the current owner or the leadership layer, and takes effect only after the receiving agent confirms the ASSUMPTION payload. Unilateral claiming is prohibited.

**Rule 8.3.4 — Artifact-Ownership Classes.** Artifacts carry one of two classes from the producer's ACR entry: `exclusive` (only the producer writes; e.g., an investigation report) or `shared-with-validator` (the producer writes; the assigned validator may append validation evidence without taking ownership). No third class exists.

**Rule 8.3.5 — Ownership on Recovery.** When an agent is removed (Section 18), its ownership entries transfer to the replacement agent through the formal transfer protocol before the replacement activates. Interim ownership reverts to the Team Lead, who holds it in escrow and does not write with it.

### 8.4 SHARED SURFACES

Surfaces legitimately touched by multiple builders (root configuration, shared lockfiles, monorepo shared libraries that cross subteam boundaries) are handled by one of:

1. **Single-owner designation** (preferred) — one builder owns the surface; others submit change requests through ACP REVIEW messages.
2. **Serialized ownership windows** — the surface carries a single owner at a time; ownership transfers between phases using Section 8.3.3.

Concurrent multi-writer shared surfaces are prohibited. Lockfile and generated-file ownership always follows Rule 1 (single owner, typically the builder whose demands most affect the file).

---

## 9. PARALLEL EXECUTION RULES

### 9.1 MAXIMUM-PARALLELISM PRINCIPLE

Independent work must run in parallel. TBE constructs the widest parallel execution groups consistent with the dependency graph (Section 11) and ownership exclusivity (Section 8). Serialization is permitted only when a rule in this section or a dependency edge requires it; convenience, caution, or habit never justify serialization.

### 9.2 PARALLEL GROUP CONSTRUCTION

Members are assigned to parallel groups by the following predicates. Two builders may share a parallel group only if all hold:

1. **Disjoint ownership** — their Ownership Matrix entries share no area or artifact class.
2. **No dependency edge** — neither depends on the other's output in the current phase (Section 11).
3. **Capacity compliance** — neither exceeds its ACR `PARALLEL EXECUTION RULES` capacity (e.g., `resource-limits: max: 5`).
4. **No shared-resource conflict** — any shared resource named in either agent's ACR entry (build directory, test database, exemplar services) is either partitioned per agent or explicitly scheduled under Section 12.3.

Reviewers and validators join the parallel group of the items they gate, activating when upstream EVIDENCE arrives (reactive scheduling, ACP v1.0 evidence flow).

### 9.3 PARALLELISM LIMITS

- **Agent-level limit** — the ACR `resource-limits` for each type (or `unbounded` where declared).
- **Team-level limit** — the Rule 7.1.2 ceiling bounds total concurrent Execution-layer members.
- **Environment limit** — shared infrastructure (single test database, licensed tooling) caps the groups that may execute simultaneously; such limits must be recorded in the manifest's ACTIVE POLICIES.

### 9.4 PARALLEL GROUP RECORD

The manifest's EXECUTION GRAPH records each group as:

```
parallel-group := { group-id, members[], shared-resource-partitions, activation-condition }
```

Activation conditions reference ACP message flows (e.g., "activates on EVIDENCE from PHASE-1 builders"). Groups execute without inter-group coordination; any discovered need to coordinate across groups is evidence of a missing dependency edge and triggers a manifest adjustment adding that edge.

---

## 10. SEQUENTIAL EXECUTION RULES

### 10.1 SEQUENTIAL GROUPS

Work that cannot run in parallel is organized into sequential groups ordered by phase index. The canonical phase ordering is:

```
INVESTIGATION → PLANNING → BUILD → TEST → SECURITY → STAGING/INTEGRATION → RELEASE-VALIDATION → RELEASE
```

Phases with no demands are skipped. A project's Execution Graph is the subsequence of this ordering containing its required phases, with parallel groups (Section 9) nested inside phases.

### 10.2 NORMATIVE SEQUENCING RULES

**Rule 10.2.1 — Hard Sequential Dependencies.** The following orderings may never be violated:

- Investigation before planning before build.
- Build before that build's review.
- Review APPROVAL before that deliverable's validation gates execute.
- All mandated validation gates GREEN before release.

**Rule 10.2.2 — Phase-Gate Advancement.** A phase advances only when every member of the prior phase reports COMPLETION and every inter-phase handoff contract (Rule 6.1.3) is satisfied. Partial advancement (starting downstream work on completed upstream items while others continue) is permitted within one project when the advanced items' dependency edges are individually satisfied; this pipelining must not skip any gate.

**Rule 10.2.3 — No Gate Skipping Under Pressure.** Deadline pressure, client urgency, or orchestrator convenience never authorize skipping a sequential gate. If a gate is genuinely unnecessary, it must be removed from the demand set by mission-contract amendment, not bypassed at runtime.

**Rule 10.2.4 — Integration Sequencing for Multi-Project Repos.** When multiple projects integrate (shared API contract, shared database schema), integration work forms its own sequential group after the contributing projects' BUILD phases, staffed by integration owners designated in the manifest, with its own reviewer.

### 10.3 SEQUENCE FORKING

Where Rule 6.1.3 (contract compatibility) fails for a preferred ordering, TBE forks the sequence: the incompatible downstream work is re-planned behind a compatible intermediary (e.g., a transformation-oriented builder) or deferred to a later phase. Forking is recorded with its rationale; it never results in silent contract violation.

---

## 11. DEPENDENCY RULES

### 11.1 DEPENDENCY GRAPH

TBE constructs a directed dependency graph over all assignments. Every edge is one of four normative types:

| Edge Type | Meaning | Construction Source |
|-----------|---------|---------------------|
| INPUT | Assignment B consumes assignment A's output | ACR INPUT/OUTPUT CONTRACTS of the mapped specialists |
| RESOURCE | Assignments share a scarce resource | ACR `shared-resources` declarations |
| PHASE | Assignment B's phase follows A's phase | Section 10 phase ordering |
| GATE | Assignment B is blocked until assignment A's gate passes GREEN | Demand `validation-gates` and Section 14 assignments |

### 11.2 NORMATIVE DEPENDENCY RULES

**Rule 11.2.1 — Completeness.** Every prerequisite of every assignment must appear as an edge. An assignment whose execution requires another agent's output but carries no edge is a manifest defect; discovery mid-mission triggers ADJUSTMENT mode.

**Rule 11.2.2 — Acyclicity.** The dependency graph must be a DAG. Cycle detection is part of manifest validation (Section 5.7, step 4). Cycles are resolved by re-partitioning scope, inserting an intermediary phase, or escalating as an architecture decision — never by tolerating the cycle.

**Rule 11.2.3 — Environment Dependencies.** Tool and environment dependencies from ACR `DEPENDENCIES` subsections must be verified present in the orchestrator's environment state before the dependent agent activates. Missing environment dependencies block activation and escalate (severity HIGH).

**Rule 11.2.4 — Dependency-Informed Parallelism.** Section 9 group construction treats the graph as authoritative: absence of an edge between two assignments is a necessary (not sufficient) condition for co-grouping; presence of an edge is sufficient exclusion.

**Rule 11.2.5 — Cross-Mission Dependencies.** Long-running engagements (Section 17) may carry dependency edges into future missions (e.g., a schema migration consumed by a later feature). Such edges are recorded in the persistent engagement record, not the per-mission manifest, and re-validated at each subsequent assembly.

---

## 12. CONFLICT PREVENTION

### 12.1 PREVENTION-FIRST PRINCIPLE

Conflicts between agents are prevented by construction, not resolved after occurrence. The primary prevention mechanisms, in order of precedence, are: exclusive ownership (Section 8), dependency-graph scheduling (Section 11), capacity limits (Section 9.3), and ACP v1.0 conflict-resolution protocol as the last resort. A mission whose conflicts are routinely resolved by ACP timestamp-order arbitration (`conflict-resolution: timestamp-order: earliest-start-wins`) has a defective manifest and must be re-planned.

### 12.2 CONFLICT CLASSES AND PREVENTION

| Conflict Class | Prevention Mechanism | Residual Handling |
|----------------|----------------------|-------------------|
| File/content collision | Section 8 exclusivity; shared-surface rules (8.4) | ACP conflict-resolution; offending write rejected |
| Artifact double-production | Demand-set deduplication (Phase B); artifact-ownership class enforcement | Later producer stands down; evidence merged by validator |
| Reviewer/validator contradiction | Disjoint gate scopes (Sections 13.4, 14.3); single final-gate owner | Escalation to Orchestrator (Section 15, Level 3) |
| Resource contention | Resource partitioning (Rule 9.2.4); environment limits (9.3) | ACP resource-lock protocol per conflicting ACR entries |
| Stale-manifest action | Manifest versioning + MISSION_UPDATE acknowledgment (Section 2.4) | Action voided; agent re-syncs to current version |

### 12.3 RESOURCE PARTITIONING

Where parallel agents require the same logical resource:

1. **Partition** — give each agent an isolated instance (separate test schema, separate build output directory). This is the default.
2. **Time-slice** — where partitioning is impossible (a single hardware device), schedule access in ordered windows recorded in the manifest.
3. **Serialize** — where neither is possible, insert a dependency edge forcing sequential execution.

### 12.4 CONFLICT TELEMETRY

Every conflict occurrence — prevented or handled — must be recorded with its class, participants, and mechanism used. Post-mission review (Section 19.3) analyzes this telemetry; more than two runtime-resolved conflicts of the same class in one mission mandates an assembly-rules review before the next assembly of the same project class.

---

## 13. REVIEWER ASSIGNMENT

### 13.1 MANDATORY REVIEW COVERAGE

Every deliverable produced under the mission must pass review by a Reviewer-role agent before entering validation. No deliverable class is exempt, including documentation, infrastructure definitions, and test code itself.

### 13.2 REVIEWER VALIDATION PREDICATES

A candidate reviewer is valid for a deliverable only if all hold:

1. **Non-authorship** — the reviewer did not author or co-author the deliverable.
2. **Departmental separation (when staffing permits)** — the reviewer's primary department differs from the builder's (Rule 3.2.4); on teams too small for separation, this predicate is waived and recorded.
3. **Competence coverage** — the reviewer's ACR REQUIRED SKILLS cover the deliverable's language, framework, and domain.
4. **Gate availability** — the reviewer's declared capacity accommodates review volume for the parallel group it gates.
5. **No self-loop escalation** — review disputes involving this reviewer must route to a distinct escalation target (Rule 6.3).

### 13.3 REVIEW MATRIX

The manifest's REVIEW MATRIX maps every deliverable type to its reviewer:

```
review-matrix := { deliverable-type, owning-builder, assigned-reviewer, review-criteria-ref, rotation-state }
```

`review-criteria-ref` points to the acceptance criteria and validation gates the review must enforce, keeping review anchored to the mission contract rather than reviewer preference.

### 13.4 REVIEW SCOPE DISCIPLINE

Reviewers verify conformance to acceptance criteria, architectural decisions of record, and registered quality gates. Reviewers do not:
- Redesign accepted approaches absent a criteria violation (scope disputes escalate rather than expand).
- Write fixes directly into builder-owned areas (violates Section 8; fixes arrive as REVIEW feedback).
- Substitute for validation gates (review is qualitative conformance; validation is objective verification — Section 14).

### 13.5 REVIEW FLOW (ACP-ALIGNED)

1. Builder emits EVIDENCE with the completed deliverable reference.
2. Assigned reviewer consumes per its ACR INPUT CONTRACTS and emits REVIEW containing APPROVAL or structured findings.
3. Findings return to the owning builder; the builder resolves and re-submits EVIDENCE.
4. Two consecutive unresolved review cycles on one deliverable auto-escalate to the Team Lead (Section 15, Level 1).

### 13.6 REVIEWER ROTATION

On long-running teams (Section 17), deliverable-to-reviewer mappings rotate at each mission boundary to prevent familiarity drift. Rotation state is tracked in the REVIEW MATRIX (`rotation-state`). Rotation never violates predicate 13.2.1 (a reviewer never rotates onto deliverables it authored).

---

## 14. VALIDATOR ASSIGNMENT

### 14.1 INDEPENDENT VALIDATION PRINCIPLE

Validation is objective, evidence-based verification against the mission's validation gates (per MSS v1.0) and is independent of both building and review. The validator's authority is the release-blocking right: a gate that is not GREEN blocks release, and only the designated validator may declare a gate GREEN.

### 14.2 VALIDATOR VALIDATION PREDICATES

1. **Independence** — the validator authored none of the deliverables under its gates and reviewed none of them.
2. **Registry authorization** — the validator's ACR entry declares relevant `validation-gates` (e.g., a `qa-validator` whose entry mandates security-audit participation, or a `security-auditor` owning the security-audit gate).
3. **Regulated-project escalation** — on `regulated:*` constraint-tagged projects, the primary release gate must be held by a dedicated validator instance, and a fallback validator must be named in the manifest (per constraint-derived policy); the fallback meets identical predicates.
4. **Departmental separation on regulated projects** — the final-gate validator's department differs from every builder's primary department (Rule 6.3).

### 14.3 GATE ALLOCATION

Validation gates are allocated to validators by domain:

| Gate Domain | Default Validator | Notes |
|-------------|-------------------|-------|
| Functional/acceptance | qa-validator | Consumes builder EVIDENCE plus assigned-reviewer APPROVAL |
| Security | security-auditor | Includes dependency and secrets scanning per its ACR entry |
| Compliance/regulated | compliance-validator | Evidence-bundle production required; blocks on missing evidence |
| Release readiness | release-manager (as validating role) | Confirms version, changelog, rollback path; final operational gate |

One agent may hold multiple gate domains only when predicates 14.2 hold for each and capacity permits. On regulated projects, functional and compliance gates must be held by distinct instances.

### 14.4 VALIDATION EVIDENCE FLOW

For every gate, the validator must produce, and file in the mission's evidence record:
- The executed check suite and its complete output references.
- The gate verdict (GREEN / BLOCKED) with criterion-level granularity.
- For BLOCKED verdicts: the minimal remediation description routed to the owning builder through ACP VALIDATION messaging.

Re-validation after remediation is the same validator's duty; gate ownership does not move during remediation cycles.

### 14.5 VALIDATOR MINIMUMS BY PROJECT CLASS

- **Unregulated, small** — one validator instance covering functional and release gates.
- **Public-API or multi-project** — dedicated functional validator plus release validator.
- **Regulated** — distinct functional, security, and compliance validators, plus a named fallback for the final gate.

---

## 15. ESCALATION HIERARCHY

### 15.1 ESCALATION LEVELS

All escalations follow ACP v1.0 ESCALATION semantics and route through exactly five levels:

| Level | Destination | Handles |
|------:|-------------|---------|
| 0 | Owning agent itself | Recovery attempts within ACR `RECOVERY DUTIES` (bounded retries) |
| 1 | Team Lead (or Orchestrator when no lead exists) | Review deadlocks, assignment ambiguity, builder-resource shortfalls |
| 2 | Department Lead or designated senior specialist | Cross-agent technical disputes, dependency conflicts within a project |
| 3 | Orchestrator | Contradictory gate verdicts, ownership deadlocks, missed critical deadlines |
| 4 | Human stakeholder / mission-contract authority | Scope change, requirement conflict, budget/quality trade-off beyond contract |

### 15.2 NORMATIVE ESCALATION RULES

**Rule 15.2.1 — No Level Skipping Below Level 3.** Escalations progress through levels in order. An agent may escalate directly to Level 3 only for safety-critical events (data loss, security exposure, compliance breach). Level 4 is reachable only from Level 3.

**Rule 15.2.2 — Escalation Content.** Every ESCALATION message must state: the blocking condition, the levels already attempted, the decision requested, and the mission impact if unresolved by a stated time. Content-free escalations ("need help") are protocol violations.

**Rule 15.2.3 — Response Obligation.** Each escalation level must produce a DECISION message within the phase in which it receives the escalation, or escalate upward itself with justification. Silent escalation disappearance is handled as agent failure (Section 18).

**Rule 15.2.4 — Team Dissolution Events Are Level 3.** Team dissolution (Section 19) executes at Orchestrator authority; member-level agents cannot dissolve, expand, or re-purpose a team.

**Rule 15.2.5 — Escalation Route Integrity.** The manifest's ESCALATION ROUTES are validated at assembly for completeness (every member has a route to Level 3) and acyclicity (no route loops). A member without a valid route blocks team activation.

---

## 16. TEMPORARY TEAMS

### 16.1 DEFINITION AND SCOPE

A temporary team is assembled for a bounded, single-purpose objective: one feature, one fix, one investigation, one focused technical discovery. Temporary teams are the default output of ASSEMBLY mode.

### 16.2 NORMATIVE TEMPORARY-TEAM RULES

**Rule 16.2.1 — Single Objective.** The manifest records exactly one objective. Discovering a second objective mid-mission requires either a mission-contract amendment (converted into the recorded objective set) or a new team; scope must not silently grow.

**Rule 16.2.2 — Minimal Duration.** A temporary team exists for one mission and dissolves at terminal state (Section 19). It must not be retained "in case something comes up."

**Rule 16.2.3 — Minimal Size.** Section 7 minimums apply strictly; the burden of proof is on every member above the coverage floor.

**Rule 16.2.4 — Narrow Ownership.** Ownership grants cover only mission scope. Areas discovered in-scope during investigation are added by manifest adjustment, with fresh exclusivity validation.

**Rule 16.2.5 — No Persistent State.** Temporary teams leave no standing organizational residue beyond the archived manifest, KPI records, and evidence record. Persistent relationships belong to long-running teams.

### 16.3 INVESTIGATION CELLS

The minimal temporary team is the **investigation cell**: one `investigator` specialist, orchestrator-held review, no validator. Investigation cells produce analysis artifacts only, hold read-only repository access, and their findings feed subsequent ASSEMBLY decisions. An investigation cell graduates into a build team only through a fresh Section 5 execution informed by the investigation's classification output.

---

## 17. LONG-RUNNING TEAMS

### 17.1 DEFINITION AND ACTIVATION CRITERIA

A long-running team serves a product or codebase across multiple missions. Activation is permitted only when the engagement record evidences at least one of:

1. Three or more completed or scheduled missions on the same repository within one quarter.
2. A standing maintenance or SLA obligation (e.g., update-window monitoring for a distributed plugin).
3. A declared product roadmap spanning multiple release cycles.

Absent such evidence, missions on the same repository still assemble fresh temporary teams (with classification reuse — Section 17.5 — preserving efficiency).

### 17.2 CORE AND FLEX STRUCTURE

Long-running teams are organized as:

- **Persistent core** — the minimal membership retained across missions: typically one Team Lead, one lead builder per active project, and one validator instance. Core members hold standing ownership of their areas and standing escalation routes.
- **Flex roster** — specialists activated per mission via standard Section 5 assembly, joining the core's manifest as a versioned mission extension and released at mission dissolution.

The core must satisfy Rule 1.2.2 against steady-state demand, not peak demand. Persistent cores exceeding five Execution-layer members require orchestrator justification recorded in the engagement record.

### 17.3 OWNERSHIP CONTINUITY

Ownership entries for core members persist across missions and are inherited by each mission manifest by reference rather than re-derivation. Every mission-start re-validates the inherited matrix against the mission scope (coverage and exclusivity predicates, Section 8.2) — continuity never grants scope outside the current mission.

### 17.4 REVIEWER ROTATION AND DRIFT CONTROL

Long-running teams execute reviewer rotation (Section 13.6) and must re-run the qualification predicates (Section 6.1) for core members whenever the ACR registry publishes updated entries for their types. A core member whose registry entry deprecates is replaced at the next mission boundary through RECOVERY-mode replacement mechanics (Section 18.3).

### 17.5 CLASSIFICATION REUSE

Repository classification results persist in the engagement record and seed subsequent assemblies. Reuse is rebuttable: material repository change events (new project detected, framework migration, constraint-tag change) invalidate the cached classification and force Phase A re-execution.

### 17.6 DISSOLUTION OF LONG-RUNNING TEAMS

A long-running team dissolves when its activation criteria cease to hold (engagement completed, SLA terminated, roadmap retired) or at human-stakeholder decision. Dissolution follows Section 19, with the engagement record — not merely a mission record — archived.

---

## 18. TEAM RECOVERY

### 18.1 FAILURE CLASSES

TBE recognizes four team-member failure classes, detected via ACP v1.0 signals (HEARTBEAT absence, FAILURE message, stalled PROGRESS, or evidence-integrity failure):

| Class | Detection Signal | Example |
|-------|------------------|---------|
| CRASH | Heartbeat timeout | Agent process terminated mid-assignment |
| STALL | Progress silence past phase threshold | Agent alive but producing no evidence |
| PROTOCOL-VIOLATION | Malformed messages, unauthorized writes, stale-manifest action | Writing outside owned areas |
| QUALITY-FAILURE | Repeated gate rejections on the member's deliverables | Three consecutive BLOCKED gates with same root cause |

### 18.2 RECOVERY SEQUENCE

Recovery executes in this fixed order, with each step bounded:

1. **Level-0 self-recovery** — the member attempts recovery per its ACR `RECOVERY DUTIES` (e.g., retry-with-backoff, checkpoint reload, diagnostic collection). Bounded by the entry's declared attempt limits.
2. **Quarantine** — on self-recovery exhaustion, the member is quarantined: its assignments freeze, its ownership transfers to Team Lead escrow (Rule 8.3.5), and its message rights are restricted to RECOVERY and STATUS_UPDATE.
3. **Diagnosis** — the Team Lead (or Orchestrator) classifies the failure and decides: resume (transient cause confirmed), reassign (work transferable, member degraded), or replace.
4. **Replacement** — a new instance of the same agent type (or the next-best candidate per Rule 6.2) is selected via abbreviated Section 6 evaluation, receives ownership transfer per Section 8.3.3, and ingests the mission context: current manifest version, the failed member's checkpoint state, and completed-evidence record.
5. **Manifest update** — RECOVERY-mode version increment with the failure class, disposition, and replacement identity recorded; MISSION_UPDATE broadcast to all members.

### 18.3 NORMATIVE RECOVERY RULES

**Rule 18.3.1 — Work Preservation.** Completed, evidence-backed work of a failed member is never discarded by recovery. Only unevidenced in-flight work is suspect; suspect work is re-validated by the assigned validator before the replacement builds upon it.

**Rule 18.3.2 — Bounded Replacement.** One assignment position may consume at most two replacements per mission. A third failure at the same position escalates to Level 3 as a systemic defect (assignment ill-posed, environment broken, or manifest defective) — replacing repeatedly is prohibited.

**Rule 18.3.3 — No Validator Substitution by Builders.** If the failed member is the designated validator, the replacement must be another validator-qualified instance satisfying Section 14.2. A builder may never absorb validation duties, even temporarily; regulated projects activate the named fallback validator immediately upon validator quarantine.

**Rule 18.3.4 — Recovery Neutrality for Gates.** Gates already GREEN remain GREEN through member replacement. Gates in progress reset to the last checkpointed verdict; validators never inherit a predecessor's in-flight partial verdict.

**Rule 18.3.5 — Team-Level Failure.** Failure of the majority of Execution-layer members within one phase, or failure of the Team Lead concurrent with an active Level-3 escalation, constitutes team failure: the mission freezes, the Orchestrator assumes escrow of all ownership, and reassembly (fresh Section 5 execution informed by diagnostic findings) decides continuation.

---

## 19. TEAM DISSOLUTION

### 19.1 DISSOLUTION TRIGGERS

A team dissolves upon the earliest of:

1. **Verified completion** — all acceptance criteria met, all mandated validation gates GREEN, final review cycle closed.
2. **Mission cancellation** — ACP CANCELLATION processed at Orchestrator authority.
3. **Mission withdrawal** — human stakeholder withdraws or materially redefines the mission (Level-4 decision).
4. **Team failure** — Section 18.3.5 with reassembly deciding against continuation.

### 19.2 DISSOLUTION SEQUENCE

Dissolution executes in fixed order; each step is recorded:

1. **Freeze** — no new assignments; in-flight assignments complete or are checkpointed.
2. **Final validation** — the designated validator re-confirms all gates GREEN against final artifact state (completion trigger only).
3. **Evidence consolidation** — the Team Lead consolidates EVIDENCE, gate verdicts, review records, KPI records, and conflict telemetry into the mission record under `.project-os/COMPANY/TEAMS/<team-id>/`.
4. **Knowledge extraction** — durable findings (classification results, systemic defects, dependency discoveries) are emitted as KNOWLEDGE_UPDATE messages for registry and engagement-record enrichment.
5. **Artifact retention** — retention applied per each artifact's ACR `artifact-retention` class; expired ephemeral artifacts are purged; audit-grade artifacts are archived per regulated retention floors where applicable.
6. **Membership release** — member instances are released at Phase 0 (per ACP lifecycle semantics); standing ownership dissolves with the manifest.
7. **Manifest archival** — the final manifest version, complete mission record, and dissolution report are archived; the team-id becomes immutable history.

### 19.3 POST-MISSION ASSEMBLY REVIEW

For every dissolved team, the Orchestrator performs an assembly review recorded in the mission record: sizing accuracy (members added or removed via ADJUSTMENT), conflict telemetry analysis (Section 12.4), recovery events (Section 18), and selection-rule efficacy (rejected-candidate patterns). Findings feed future assemblies as policy annotations; they never retroactively alter the dissolved team's record.

### 19.4 DISSOLUTION INVARIANTS

- No member retains repository write rights after membership release.
- No ownership entry survives dissolution except transfers explicitly recorded to a successor team (e.g., core members of a continuing long-running team, Section 17.3).
- The mission record must be complete before archival; incomplete records block dissolution and escalate to Level 3.

---

## 20. COMPLETE EXAMPLES

The following examples are normative illustrations of the full Section 5 algorithm applied end to end. Each shows inputs 18selection decisions, manifest essentials, and execution structure. Team sizes are outcomes of the rules, not targets.

### EXAMPLE 20.1 — AI SaaS APPLICATION (Next.js + Python ML Backend)

**Mission (MSS type: `greenfield-project`)**: Build a document-summarization SaaS: Next.js 14 frontend, FastAPI inference service, Postgres for accounts/documents, Stripe billing, deployed via containers.

**Phase A classification** (two projects):
- `web/` — type: nextjs-app; languages: [TypeScript]; frameworks: [Next.js 14, Tailwind]; platform: web; test-surface: vitest+playwright; deployment: containers.
- `api/` — type: python-service; languages: [Python]; frameworks: [FastAPI, transformers]; platform: linux-containers; test-surface: pytest; deployment: containers.
- Constraint tags: `payments` (Stripe) -> `security` demand injected.

**Phase B demands (abbreviated)**: UI implementation; API implementation; ML pipeline; schema + migrations; billing integration (`payments` -> security-audit demand); containers + CI; functional + security gates; documentation.

**Phase C sizing**: capability-coverage-count 8 builders/specialists + leadership (12 members > 5 threshold per Rule 2.2.3) -> headcount 11: lead, frontend-dev, backend-dev, ai-ml-engineer, database-engineer, devops-engineer, ui-ux-designer, test-engineer, security-auditor, qa-validator, release-manager.

**Phase D mapping highlights**: billing demand -> `backend-developer` (skill overlap: Stripe SDK 20 server code ownership); ML evaluation harness -> `ai-ml-engineer` with `test-engineer` support; documentation demand consolidated onto `backend-developer` (API docs within owned area, Rule 4.4.2).

**Phase E ownership (excerpt)**:
- `web/**` -> frontend-developer (exclusive); `web/shared/ui-tokens.json` -> ui-ux-designer owns, frontend consumes via REVIEW requests (Rule 8.4.1).
- `api/**` -> backend-developer; `api/ml/**` -> ai-ml-engineer; `db/migrations/**` -> database-engineer (exclusive; backend submits schema change requests).
- `infra/**`, `.github/workflows/**` -> devops-engineer; `/.git/`, `/secrets/` restricted for all.

**Phase F gates**: functional -> qa-validator; security (payments surface) -> security-auditor; release -> release-manager. Escalation: members -> Team Lead -> Orchestrator (levels 1, 3; no department exceeds 2 specialists -> no level-2 leads needed).

**Execution structure**: INVESTIGATION (investigator cell, 1 day) -> PLANNING -> parallel BUILD groups {frontend | backend | ml | db} with serialized integration on the API contract (Rule 10.2.4) -> TEST -> SECURITY -> RELEASE-VALIDATION -> RELEASE.

### EXAMPLE 20.2 — WORDPRESS PLUGIN BUG FIX (Single Focused Task)

**Mission (MSS type: `single-file-fix` class scope, two acceptance criteria)**: Fix a multisite activation fatal in an existing plugin's activation hook; add regression coverage.

**Phase A**: one project — type: wordpress-plugin; languages: [PHP]; frameworks: [WordPress 6.x hooks API]; platform: wordpress-multisite; test-surface: WP integration suite via wp-env.

**Sizing (Rule 7.1 + minimum-viable: Small)**: capability-coverage-count = 2. `wordpress-developer` (fix in `includes/class-activator.php`, regression test in `tests/`) + `test-engineer` (harness execution, multisite matrix). qa-validator duties: combined onto `test-engineer`? **Rejected** — predicate 14.2.1 (validator authored test deliverables). Resolution: `qa-validator` selected as third member; reviewer duties consolidated onto same instance (reviewer predicates allow: non-author of the fix; competence covers PHP/WordPress). **Final team: 3 + orchestrator-held leadership.** No Team Lead (3 1a 5, Rule 2.2.3).

**Ownership**: plugin source -> wordpress-developer exclusive; `tests/**` -> wordpress-developer (test authorship within builder scope per demand) with qa-validator `shared-with-validator` rights on the evidence artifacts; validator executes gates read-only.

**Execution**: strictly sequential (INVESTIGATION -> BUILD -> TEST -> gates), zero parallel groups — a legal outcome of Section 9 when every pairing fails predicate 9.2.2.

### EXAMPLE 20.3 — GO CLI TOOL (Library + Binary, High Parallelism)

**Mission (MSS type: `enhancement`)**: Add three independent subcommands (`config`, `export`, `doctor`) to an existing Go CLI, each with distinct packages, plus integration tests.

**Classification**: one project — go-cli; languages: [Go]; frameworks: [cobra]; test-surface: go test + golden files.

**Demand mapping**: three independent command demands -> ownership partitions: `cmd/config/**`+`internal/config/**`, `cmd/export/**`+`internal/export/**`, `cmd/doctor/**`+`internal/doctor/**` — three disjoint regions (Rule 4.4.3 -> three `developer` instances, instance-ids distinct). Shared surface: `cmd/root.go` and `go.mod` -> single-owner designation (developer-1 owns; others submit REVIEW requests, Rule 8.4.1).

**Team**: 3 developers + 1 test-engineer (integration tests across commands; ownership `tests/integration/**`) + qa-validator + Team Lead (6 members > 5 threshold? No — 5 builders/quality + lead = 6 total; execution-layer = 5 -> lead created per Rule 2.2.3 exactly at threshold crossing with the validator counted: Execution-layer = 6 -> lead mandated). Escalation: developers -> Team Lead -> Orchestrator.

**Parallel structure**: one parallel group of three developers (predicates 9.2.1–9.2.4 hold: disjoint ownership, no edges, Go build cache partitioned per agent); test-engineer in same group, reactive on EVIDENCE; validator gates after review APPROVAL per Rule 10.2.1.

### EXAMPLE 20.4 — HIPAA-REGULATED PATIENT PORTAL (Constrained Team)

**Mission (MSS type: `legacy-rescue` initial remediation mission)**: Stabilize authentication and audit logging in an inherited Rails application handling PHI.

**Classification with constraint tag**: `regulated:healthcare` -> Phase B constraint demands inject:
- `security-auditor` (mandatory), `compliance-validator` (mandatory), primary-validator independence (14.2.3), distinct functional/compliance validator instances (14.3), named fallback validator, audit-evidence retention floor (19.2.5).

**Team (sized to Large floor, 8)**: Team Lead, backend-developer (Rails auth), database-engineer (audit-log schema), devops-engineer (log-shipping infra), test-engineer, security-auditor, qa-validator (functional), compliance-validator (final gate + evidence bundles; fallback: second qa-validator instance named in manifest).

**Key adjacency decisions**: `known threat actors` — none; the `investigator` cell runs Phase A deep-dive first (unfamiliar legacy repo per 7.2 risk indicators). Backend and database work carry an INPUT edge (audit schema before log-writing code) -> same phase excluded from co-grouping; serialized as BUILD-1 -> BUILD-2 (Rule 11.2.4).

**Gates**: functional -> qa-validator; security -> security-auditor (auth surface); compliance -> compliance-validator with evidence-bundle output (14.4); release blocked unless all three GREEN (10.2.1). Reviewer rotation state initialized at R0 (first mission of a candidate long-running engagement, Section 17.1 criterion 3 pending roadmap confirmation).

### EXAMPLE 20.5 — MULTI-REPO PLATFORM ORCHESTRATION (Monorepo-with-Subteams Crossover)

**Mission (MSS type: `multi-repo-orchestration`)**: Coordinate a breaking API change across five repositories: api-gateway (Go), web-client (Next.js), mobile (React Native), shared-types (TypeScript package), infra (Terraform).

**Sizing path**: naive coverage -> 14 builders + gating exceeds Rule 7.1.2 ceiling of 15 -> **subteam partitioning (Section 7.4)**: Subteam-A {api-gateway, shared-types} (5 members), Subteam-B {web-client, mobile} (5 members), Subteam-C {infra + release} (3 members), each with Team Lead; one orchestrator; shared contract surface (`shared-types`) owned within Subteam-A with cross-subteam consumption via REVIEW protocol (Rule 7.4.3); integration reviewer designated for the contract-change deliverable.

**Sequencing**: `shared-types` BUILD -> gateway BUILD -> parallel {web, mobile} BUILD -> INTEGRATION group (Rule 10.2.4) -> per-repo gates -> coordinated RELEASE-VALIDATION -> staggered RELEASE with rollback path per repo (release-manager validating).

**Cross-mission note**: engagement evidence (quarterly coordinated releases) qualifies a long-running team; core = 3 leads + api owner + functional validator (5 execution members, at the Section 17.2 core ceiling -> orchestrator justification recorded), all other roles flex-activated per mission.

---

**END OF SPECIFICATION — TBE v1.0**
