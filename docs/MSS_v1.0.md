# MISSION SPECIFICATION STANDARD (MSS v1.0) SPECIFICATION

## Canonical Mission-Intake Contract for ASC Orchestrator v2

---

## 1. PURPOSE, SCOPE, AND NORMATIVE CONVENTIONS

### 1.1 Purpose

Mission Specification Standard (MSS) v1.0 defines the canonical, machine-readable mission-intake contract: the deterministic JSON object an operator submits to declare a mission before the Team Builder Engine (TBE v1.0) assembles a team and before the Persistent Execution State Engine (PESE v1.0) persists any state.

MSS SHALL make every declared mission parseable, validatable, and deterministic: two conforming implementations given the same JSON input SHALL produce the same `MissionSpec` dataclass and the same validation result.

### 1.2 Principles

1. **Evidence before assertion.** A mission, its type, its priority, and its acceptance criteria SHALL be explicit in the intake JSON; the runtime SHALL NOT infer missing facts.
2. **Deterministic parsing.** Given identical JSON, the parser SHALL produce an identical `MissionSpec` and SHALL NOT read external state.
3. **Schema-first identity.** Every `MissionSpec` carries explicit `schema` and `version` fields; these MUST be present in the intake JSON and MUST equal `MSS` and `1.0` respectively.
4. **Provenance.** Every `MissionSpec` carries `created_at`, `created_by`, and `source` metadata; these MUST be present in the intake JSON.
5. **Structured validation.** Semantic validation produces a `MissionValidationResult` containing typed findings with severity levels (`error`, `warning`, `info`), enabling future policy layers without changing the parser.
6. **Intake boundary.** MSS is a contract-definition and intake-validation layer. It does not plan, schedule, execute, orchestrate, or activate agents; those are responsibilities of later milestones.

### 1.3 Non-goals and boundaries

MSS v1.0 (this specification) SHALL NOT:

- plan execution sequences or assign agents (TBE responsibility);
- persist mission state or write to PESE (PESE and CLI responsibility);
- define transport, identity, encryption, or messaging protocols (ACP responsibility);
- define registry entry structure (ACR responsibility).

MSS v1.0 is consumed by TBE via `MissionSpec` (which is a `Mapping[str, Any]` that `MissionContract.from_mapping` accepts without adapter functions) and by PESE as mission facts when bound via `--bind-state`.

### 1.4 Normative language

The terms **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative. A `mission_id` is an ASCII string matching the declared pattern. All times are UTC RFC 3339 timestamps with millisecond precision (`YYYY-MM-DDTHH:mm:ss.sssZ`).

---

## 2. MISSION VOCABULARY — MISSION TYPES

Every mission declares exactly one mission type. The following enumerator is closed for MSS v1.0 and MUST NOT be extended without a revision to this specification.

### 2.1 Canonical mission types

| Mission type | Description |
| --- | --- |
| `greenfield-project` | A new system built from scratch; multiple integration surfaces. |
| `single-file-fix` | A focused bug fix or regression repair in a known codebase. |
| `enhancement` | One or more additive changes to an existing system. |
| `legacy-rescue` | Stabilization, remediation, or security hardening of an inherited codebase. |
| `multi-repo-orchestration` | Coordinated changes across multiple repositories or packages. |
| `spike` | A time-boxed investigation; produces evidence, not production code. |
| `compliance-audit` | Regulatory, legal, or policy compliance verification and reporting. |

### 2.2 Mission-type selection rules

The mission type MUST reflect the primary nature of the declared work. Where multiple types are plausible, the operator SHOULD select the type whose baseline capability set (Section 5) matches the work's minimum required roles.

---

## 3. MISSION VOCABULARY — MISSION CLASS AND PRIORITY

### 3.1 Mission class

Every mission declares exactly one mission class. The following enumerator is closed for MSS v1.0:

| Mission class | Description |
| --- | --- |
| `bounded` | A mission with a defined termination criterion; complete when acceptance criteria are met. |
| `open-ended` | An ongoing engagement (e.g., long-running team, recurring releases) without a single termination point. |

### 3.2 Mission priority

Every mission declares exactly one priority. The following enumerator is closed for MSS v1.0 and MUST be consumed by PESE as the mission's execution priority:

| Priority | Meaning |
| --- | --- |
| `CRITICAL` | Blocking issue, security vulnerability, or data loss risk. |
| `HIGH` | Time-sensitive deliverable; customer-facing impact. |
| `MEDIUM` | Planned feature work; normal development cycle. |
| `LOW` | Nice-to-have, exploratory, or documentation improvement. |

PESE maps these to numeric order via `PRIORITY = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}`; the MSS runtime does not re-implement this mapping.

---

## 4. CANONICAL MISSION-INTAKE SCHEMA

A valid `MissionSpec` JSON object is a JSON object containing the following fields. All fields marked **required** MUST be present and non-empty.

### 4.1 Schema identity

| Field | Type | Required | Value |
| --- | --- | --- | --- |
| `schema` | string | **required** | MUST equal `"MSS"` |
| `version` | string | **required** | MUST equal `"1.0"` |

### 4.2 Mission identity

| Field | Type | Required | Value |
| --- | --- | --- | --- |
| `mission_id` | string | **required** | Matches `MISSION:[A-Za-z0-9][A-Za-z0-9._-]*` |
| `mission_type` | string | **required** | One of the canonical mission types (Section 2.1) |
| `mission_class` | string | **required** | One of `bounded` or `open-ended` (Section 3.1) |
| `priority` | string | **required** | One of `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` (Section 3.2) |
| `objective` | string | **required** | A human-readable description of the mission's goal |

### 4.3 Work definition

| Field | Type | Required | Value |
| --- | --- | --- | --- |
| `acceptance_criteria` | array of objects | **required** | Each object MUST contain at least `id` (string) and `description` (string). Optional: `evidence_ref` (string), `gate` (string, MUST be a canonical validation gate) |
| `constraints` | array of objects | **required** | Each object MUST contain at least `kind` (string) and `value` (string). Empty array is valid |
| `constraint_tags` | array of strings | **required** | Tags that propagate into TBE staffing and gating decisions (e.g., `regulated:healthcare`, `payments`). Empty array is valid |
| `value_streams` | array of strings | **required** | Business or technical value streams this mission serves. Empty array is valid |

### 4.4 Scope and boundaries

| Field | Type | Required | Value |
| --- | --- | --- | --- |
| `boundaries` | array of strings | **required** | Explicit constraints on what agents may not do. Empty array is valid |
| `stakeholders` | array of strings | **required** | Roles or agent-ids with interest in mission outcomes. Empty array is valid |
| `validation_gates` | array of strings | **required** | Each string MUST be a canonical validation gate (Section 6). Empty array is valid |
| `authority_scope` | array of strings | **required** | Each string MUST be a canonical authority-scope phrase (Section 7). Empty array is valid |

### 4.5 Provenance and metadata

| Field | Type | Required | Value |
| --- | --- | --- | --- |
| `created_at` | string | **required** | UTC RFC 3339 timestamp with millisecond precision (e.g., `2026-08-04T00:00:00.000Z`) |
| `created_by` | string | **required** | ACP agent-id of the mission author |
| `source` | string | **required** | Human-readable provenance reference (e.g., path, ticket, or spec section) |
| `extensions` | object | optional | Reverse-DNS namespaced extension data; keys MUST match `^[a-z0-9-]+(\.[a-z0-9_-]+)+$` (case-insensitive). Extensions MUST NOT affect v1.0 validation or resume decisions |

### 4.6 TBE consumption

`MissionSpec` implements `collections.abc.Mapping[str, Any]`. Its `__getitem__` exposes all fields in Sections 4.1–4.5. When passed to `TBE.MissionContract.from_mapping` or `TBE.build_team` as a `Mapping`, the following keys are consumed directly without adapter functions:

- `mission_id`, `mission_type`, `objective`, `acceptance_criteria`, `constraint_tags`

The following keys are read with defaults when absent:
- `project_class` (default `"small"`), `sequence` (default `1`), `demands` (default `()`)

Unknown keys are silently ignored by TBE.

---

## 5. MISSION-TYPE BASELINE CAPABILITIES

Every mission type mandates a minimum set of validation gates. This table is normative: a declared `validation_gates` array that omits a baseline gate SHOULD produce a `warning`-severity finding.

| Mission type | Baseline gates |
| --- | --- |
| `greenfield-project` | `GATE:qa`, `GATE:release` |
| `single-file-fix` | `GATE:qa` |
| `enhancement` | `GATE:qa`, `GATE:release` |
| `legacy-rescue` | `GATE:qa`, `GATE:security`, `GATE:compliance` |
| `multi-repo-orchestration` | `GATE:qa`, `GATE:release` |
| `spike` | `GATE:qa` |
| `compliance-audit` | `GATE:compliance`, `GATE:security` |

An operator MAY declare gates beyond the baseline (e.g., `GATE:security` on a `greenfield-project`). Only omitted baseline gates produce warnings.

---

## 6. VALIDATION-GATE VOCABULARY

The following validation-gate identifiers are canonical for MSS v1.0:

| Gate | Scope |
| --- | --- |
| `GATE:qa` | Functional correctness, test coverage, acceptance-criteria conformance |
| `GATE:security` | Vulnerability, secret, and license compliance scanning |
| `GATE:integrity` | Artifact and data-integrity verification |
| `GATE:release` | Release-readiness: deployment, rollback, and documentation verification |
| `GATE:compliance` | Regulatory, legal, or policy compliance verification |

A `validation_gates` entry that does not match this vocabulary produces an `error`-severity finding.

---

## 7. AUTHORITY-SCOPE VOCABULARY

The following authority-scope phrases are canonical for MSS v1.0. An `authority_scope` entry that does not match this vocabulary produces an `error`-severity finding.

| Authority-scope phrase | Meaning |
| --- | --- |
| `Repository State: read-only access` | Observe repository contents without mutation |
| `Repository State: read/write within owned paths` | Modify repository contents within designated ownership boundaries |
| `Mission State: observation of assigned mission` | Read assigned mission facts in PESE |
| `Mission State: update own mission facts` | Update assigned mission facts in PESE |
| `Execution State: update own progress and step completion` | Report execution progress |
| `Validation State: read/write for security gate artifacts` | Produce and consume security-related validation artifacts |
| `Validation State: read/write for owned gate artifacts` | Produce and consume validation artifacts within owned scope |
| `Risk State: read/write for active risk registry` | Maintain risk observations and mitigations |

The vocabulary is intentionally aligned with the authority-scope strings in the existing ACR seed entries (`investigator.json`, `security-auditor.json`) and with PESE state-schema fields.

---

## 8. METADATA AND PROVENANCE

Every `MissionSpec` MUST declare:

- `created_at` — the UTC timestamp when this mission specification was authored;
- `created_by` — the ACP agent-id of the author;
- `source` — a human-readable reference to the originating context.

These fields are mandatory, not optional, because provenance is a security invariant: an anonymous or undated mission is an auditable gap.

---

## 9. CANONICAL JSON EXAMPLES

Each example below is normative. A conforming `MissionSpec.from_mapping` implementation MUST accept each example without error and MUST pass validation with `ok = True` and zero errors.

### Example 1 — greenfield-project

```json
{
  "schema": "MSS",
  "version": "1.0",
  "mission_id": "MISSION:greenfield-saas",
  "mission_type": "greenfield-project",
  "mission_class": "bounded",
  "priority": "HIGH",
  "objective": "Build a document-summarization SaaS: Next.js 14 frontend, FastAPI inference service, Postgres for accounts/documents, Stripe billing, deployed via containers.",
  "acceptance_criteria": [
    {"id": "AC-1", "description": "Users can sign up, upload a document, and receive a summary.", "evidence_ref": "tests/e2e", "gate": "GATE:qa"},
    {"id": "AC-2", "description": "Billing via Stripe is functional for subscriptions.", "evidence_ref": "tests/billing", "gate": "GATE:qa"},
    {"id": "AC-3", "description": "Containerized deployment is reproducible from a fresh checkout.", "evidence_ref": "infra/", "gate": "GATE:release"}
  ],
  "constraints": [
    {"kind": "timeline", "value": "6 weeks"},
    {"kind": "stack", "value": "Next.js 14, FastAPI, Postgres, Stripe"}
  ],
  "constraint_tags": ["payments"],
  "value_streams": ["customer-acquisition", "document-intelligence"],
  "boundaries": ["No agent may call external LLM providers at runtime", "Secrets live only in the deployment environment"],
  "stakeholders": ["product-strategist", "security-lead"],
  "validation_gates": ["GATE:qa", "GATE:security", "GATE:release"],
  "authority_scope": ["Repository State: read/write within owned paths", "Mission State: update own mission facts", "Execution State: update own progress and step completion"],
  "created_at": "2026-08-04T00:00:00.000Z",
  "created_by": "AGENT:orchestrator:local",
  "source": "docs/MSS_v1.0.md example 1",
  "extensions": {}
}
```

### Example 2 — single-file-fix

```json
{
  "schema": "MSS",
  "version": "1.0",
  "mission_id": "MISSION:wp-multisite-activation",
  "mission_type": "single-file-fix",
  "mission_class": "bounded",
  "priority": "HIGH",
  "objective": "Fix a multisite activation fatal in an existing plugin's activation hook; add regression coverage.",
  "acceptance_criteria": [
    {"id": "AC-1", "description": "Activating the plugin on a multisite network no longer raises a fatal error.", "evidence_ref": "tests/activation", "gate": "GATE:qa"},
    {"id": "AC-2", "description": "Regression coverage exercises the multisite activation path.", "evidence_ref": "tests/regression", "gate": "GATE:qa"}
  ],
  "constraints": [
    {"kind": "stack", "value": "PHP 8.2, WordPress 6.x hooks API"},
    {"kind": "surface", "value": "wordpress-multisite"}
  ],
  "constraint_tags": [],
  "value_streams": ["support", "bug-resolution"],
  "boundaries": ["No dependency upgrades beyond the plugin's declared support matrix"],
  "stakeholders": ["product-strategist"],
  "validation_gates": ["GATE:qa"],
  "authority_scope": ["Repository State: read/write within owned paths", "Mission State: update own mission facts"],
  "created_at": "2026-08-04T00:00:00.000Z",
  "created_by": "AGENT:orchestrator:local",
  "source": "docs/MSS_v1.0.md example 2",
  "extensions": {}
}
```

### Example 3 — enhancement

```json
{
  "schema": "MSS",
  "version": "1.0",
  "mission_id": "MISSION:go-cli-subcommands",
  "mission_type": "enhancement",
  "mission_class": "bounded",
  "priority": "MEDIUM",
  "objective": "Add three independent subcommands (config, export, doctor) to an existing Go CLI, each with distinct packages, plus integration tests.",
  "acceptance_criteria": [
    {"id": "AC-1", "description": "Each subcommand is callable and produces the expected output.", "evidence_ref": "tests/unit", "gate": "GATE:qa"},
    {"id": "AC-2", "description": "Integration tests cover cross-command interactions.", "evidence_ref": "tests/integration", "gate": "GATE:qa"},
    {"id": "AC-3", "description": "Binary passes go vet and staticcheck.", "evidence_ref": "lint", "gate": "GATE:release"}
  ],
  "constraints": [
    {"kind": "stack", "value": "Go 1.22+, cobra"},
    {"kind": "scope", "value": "three independent command packages"}
  ],
  "constraint_tags": [],
  "value_streams": ["developer-tooling"],
  "boundaries": ["No changes to the existing root command", "No external dependencies added"],
  "stakeholders": ["product-strategist"],
  "validation_gates": ["GATE:qa", "GATE:release"],
  "authority_scope": ["Repository State: read/write within owned paths", "Execution State: update own progress and step completion"],
  "created_at": "2026-08-04T00:00:00.000Z",
  "created_by": "AGENT:orchestrator:local",
  "source": "docs/MSS_v1.0.md example 3",
  "extensions": {}
}
```

### Example 4 — legacy-rescue

```json
{
  "schema": "MSS",
  "version": "1.0",
  "mission_id": "MISSION:rails-ph-i-stabilization",
  "mission_type": "legacy-rescue",
  "mission_class": "open-ended",
  "priority": "CRITICAL",
  "objective": "Stabilize authentication and audit logging in an inherited Rails application handling PHI.",
  "acceptance_criteria": [
    {"id": "AC-1", "description": "Authentication is functional and passes the penetration-test checklist.", "evidence_ref": "tests/security", "gate": "GATE:security"},
    {"id": "AC-2", "description": "Audit logging captures all PHI access events with correct retention.", "evidence_ref": "tests/compliance", "gate": "GATE:compliance"},
    {"id": "AC-3", "description": "Functional test suite is green on the current database schema.", "evidence_ref": "tests/functional", "gate": "GATE:qa"}
  ],
  "constraints": [
    {"kind": "regulatory", "value": "HIPAA Security Rule compliance required"},
    {"kind": "stack", "value": "Rails 7.x, PostgreSQL, PHI-handling services"}
  ],
  "constraint_tags": ["regulated:healthcare"],
  "value_streams": ["data-protection", "regulatory-compliance"],
  "boundaries": ["No new external services without legal review", "PHI never leaves the deployment environment"],
  "stakeholders": ["security-lead", "compliance-officer", "product-strategist"],
  "validation_gates": ["GATE:qa", "GATE:security", "GATE:compliance", "GATE:release"],
  "authority_scope": ["Repository State: read/write within owned paths", "Mission State: update own mission facts", "Validation State: read/write for security gate artifacts", "Risk State: read/write for active risk registry"],
  "created_at": "2026-08-04T00:00:00.000Z",
  "created_by": "AGENT:orchestrator:local",
  "source": "docs/MSS_v1.0.md example 4",
  "extensions": {}
}
```

### Example 5 — multi-repo-orchestration

```json
{
  "schema": "MSS",
  "version": "1.0",
  "mission_id": "MISSION:cross-repo-api-change",
  "mission_type": "multi-repo-orchestration",
  "mission_class": "open-ended",
  "priority": "HIGH",
  "objective": "Coordinate a breaking API change across five repositories: api-gateway (Go), web-client (Next.js), mobile (React Native), shared-types (TypeScript package), infra (Terraform).",
  "acceptance_criteria": [
    {"id": "AC-1", "description": "shared-types package is updated with the breaking change and published.", "evidence_ref": "packages/shared-types/", "gate": "GATE:qa"},
    {"id": "AC-2", "description": "All consuming repositories compile and pass integration tests against the new shared-types.", "evidence_ref": "tests/cross-repo", "gate": "GATE:qa"},
    {"id": "AC-3", "description": "Staggered release is performed with rollback paths documented per repository.", "evidence_ref": "infra/releases", "gate": "GATE:release"}
  ],
  "constraints": [
    {"kind": "scope", "value": "five repositories, four languages, coordinated release window"},
    {"kind": "stack", "value": "Go, Next.js, React Native, TypeScript, Terraform"}
  ],
  "constraint_tags": ["multi-repo"],
  "value_streams": ["platform-consistency", "developer-experience"],
  "boundaries": ["No breaking change may ship before shared-types is published", "Each repository retains independent rollback capability"],
  "stakeholders": ["product-strategist", "release-manager"],
  "validation_gates": ["GATE:qa", "GATE:release"],
  "authority_scope": ["Repository State: read/write within owned paths", "Mission State: update own mission facts", "Execution State: update own progress and step completion"],
  "created_at": "2026-08-04T00:00:00.000Z",
  "created_by": "AGENT:orchestrator:local",
  "source": "docs/MSS_v1.0.md example 5",
  "extensions": {}
}
```

---

## 10. COMPATIBILITY WITH ACP, ACR, PESE, AND TBE

### 10.1 ACP

MSS mission specifications are the payload of `ASSIGNMENT` and `MISSION_UPDATE` messages (ACP v1.0). The `mission_id`, `acceptance_criteria`, `constraint_tags`, and `objective` fields defined in this specification correspond directly to the fields referenced in ACP message definitions.

### 10.2 ACR

ACR v1.0 seed entries declare `mission-types`, `authority-scope`, and `validation-gates` on each agent. The vocabulary in Sections 2, 6, and 7 is intentionally aligned:

- The `mission-types` field in ACR entries (e.g., `["Investigation", "Security"]`) describes an agent's capability scope; the `mission_type` in an MSS `MissionSpec` describes the work itself. A mission of type `greenfield-project` may be served by agents whose ACR `mission-types` include `["Investigation"]`.
- The `authority-scope` strings in `investigator.json` and `security-auditor.json` are a strict subset of the MSS authority-scope vocabulary (Section 7).
- The `validation-gates` in ACR's `validation-duties` reference gate names drawn from the MSS vocabulary (Section 6).

### 10.3 PESE

PESE v1.0 stores mission facts under `mission_state.missions[*]`. When a `MissionSpec` is bound via `--bind-state`, PESE records:

- `mission_id` as the mission key,
- `priority` via the `PRIORITY` map,
- `acceptance_criteria` as mission evidence references,
- `constraint_tags` as mission-scope tags.

The `schema` and `version` fields are carried under the `extensions.org.asc.mss` namespace in PESE, preserving forward compatibility without affecting v1.0 resume decisions.

### 10.4 TBE

`MissionSpec` implements `collections.abc.Mapping[str, Any]` with keys matching TBE's `MissionContract.from_mapping` contract:

| MissionSpec key | TBE consumption |
| --- | --- |
| `mission_id` | `mission_id` or `id` |
| `mission_type` | `mission_type` or `type` |
| `objective` | `objective` |
| `acceptance_criteria` | `acceptance_criteria` or `acceptance-criteria` |
| `constraint_tags` | `constraint_tags` or `constraint-tags` |
| `project_class` (absent → default `"small"`) | `project_class` |
| `sequence` (absent → default `1`) | `sequence` |
| `demands` (absent → default `()`) | `demands` |

A `MissionSpec` can therefore be passed directly to `TBE.build_team` or `TBE.MissionContract.from_mapping` with no adapter function.

---

## 11. M009 IMPLEMENTATION GATES

This section documents the release criteria for the MSS v1.0 runtime implementation. All criteria MUST be satisfied before M009 is marked complete.

| Gate | Criterion |
| --- | --- |
| **S-1** | `docs/MSS_v1.0.md` exists, contains all sections above, and ends with `**END OF SPECIFICATION — MSS v1.0**` |
| **S-2** | All five canonical JSON examples (Section 9) parse via `MissionSpec.from_mapping` without error |
| **S-3** | `validate_mission_spec` returns `ok = True` and zero error-severity findings for each canonical example |
| **S-4** | `validate_mission_spec` returns `ok = False` for invalid `mission_type`, `mission_class`, `priority`, `mission_id`, `validation_gates`, and `authority_scope` values |
| **S-5** | `validate_mission_spec` returns `warning`-severity findings for missing baseline gates |
| **S-6** | `MissionSpec` instances are `Mapping`-compatible and accepted by `TBE.MissionContract.from_mapping` without adapter functions |
| **S-7** | `validate-mission` CLI command returns `validation=PASS` for a valid spec file and `validation=FAIL` (exit 2) for an invalid one |
| **S-8** | `scripts/validate_docs.py` reports `documentation=PASS` with `mss_required_headings=6` and `mss_json_examples=5` |
| **S-9** | `python -m unittest discover -s tests -t . -v` passes all tests including the MSS suite |
| **S-10** | `python -m mypy` and `python -m ruff check` pass |
| **S-11** | `python scripts/validate_docs.py` passes with no errors |

---

**END OF SPECIFICATION — MSS v1.0**
