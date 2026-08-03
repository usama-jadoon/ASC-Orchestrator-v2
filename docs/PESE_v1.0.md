# PERSISTENT EXECUTION STATE ENGINE (PESE v1.0) SPECIFICATION

## Official Persistent State Standard for ASC Orchestrator v2

---

## 1. Purpose, scope, and normative conventions

### 1.1 Purpose

Persistent Execution State Engine (PESE) v1.0 is the durable, deterministic state layer for an ASC Orchestrator repository. It records the state needed to stop, inspect, validate, recover, and resume work without relying on an agent's transient context or an unverified narrative.

PESE SHALL make the result of reading the repository and `.project-os` reproducible: two conforming implementations given the same verified inputs SHALL select the same current milestone, active/completed missions, interrupted work, and next executable task or the same safety halt.

### 1.2 Principles

1. **Evidence before assertion.** A completed item, green gate, repository identity, or recovery point SHALL be represented by verifiable evidence, not a status string alone.
2. **Append-only provenance.** State revisions, checkpoints, migrations, and audits SHALL be hash chained and SHALL NOT be silently rewritten.
3. **Atomicity.** A reader SHALL observe either the previously valid live state or the next completely valid live state, never a partial write.
4. **Deterministic recovery.** Recovery and resume decisions SHALL follow the algorithms in this specification; an implementation SHALL halt where their required evidence is absent or contradictory.
5. **Least authority.** PESE records authority and ownership; it does not grant authority beyond a current TBE manifest or an ACR contract.
6. **Separation of concerns.** PESE is a state, checkpoint, integrity, lock, and recovery engine. It is not an agent-messaging, team-selection, mission-authoring, execution, or validation engine.
7. **Portable durability.** The canonical state is UTF-8 JSON stored below the repository root. No host-private memory is authoritative.

### 1.3 Non-goals and boundaries

PESE SHALL NOT:

- replace ACP's immutable message audit or parse, sign, transmit, retry, or order ACP messages;
- author a mission contract, choose a team, allocate ownership, construct a dependency graph, or appoint a validator (TBE responsibilities);
- execute assignments, run tools, alter repository contents, or decide a validation verdict;
- replace ACR entries, their authority rules, dependencies, recovery duties, INPUT CONTRACTS, or OUTPUT CONTRACTS;
- infer missing evidence from an agent claim, or restore arbitrary uncheckpointed work;
- store credentials, private keys, message payloads, source-code copies, or other secrets.

ACP's `.project-os/AUDIT/` message log remains a separate audit system. PESE SHALL emit its own access and state-transition audit entries and SHALL reference relevant ACP correlation IDs, but it SHALL NOT duplicate full ACP messages.

### 1.4 Normative language

The terms **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative. `SHA-256` means lowercase hexadecimal SHA-256. An `id` is an ASCII string matching the declared pattern. All times are UTC RFC 3339 timestamps with millisecond precision (`YYYY-MM-DDTHH:mm:ss.sssZ`).

---

## 2. Canonical persistence model

### 2.1 Canonical JSON and hashes

Every JSON file governed by PESE SHALL be encoded as UTF-8 without BOM, use LF line endings, end with one LF, and contain exactly one JSON object or array. JSON values used for hashes SHALL be serialized using [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785); hashes are calculated from the resulting UTF-8 bytes. This is the **canonical JSON bytes**.

Keys named `*_sha256` SHALL contain exactly 64 lowercase hexadecimal characters. A `content_sha256` hashes the canonical JSON value named by that entry, excluding the field that carries the hash. A file's `file_sha256` hashes the canonical JSON of the complete parsed file with its own `file_sha256` field omitted. A `state_hash` hashes only `state` in a state envelope. `snapshot_sha256` hashes only `snapshot` in a checkpoint envelope.

Unknown fields are invalid in a v1.0 object unless that object's schema explicitly provides an `extensions` object. `extensions` keys MUST use reverse-DNS names and MUST NOT affect v1.0 transition or resume decisions. Consumers SHALL reject an unknown required enum value as incompatible, not guess its meaning.

### 2.2 Canonical layout

The following layout is the sole canonical PESE storage layout. Directories marked `required` SHALL exist after PESE initialization. File names use only `[A-Za-z0-9._-]`; `<utc>` is `YYYYMMDDTHHmmssSSSZ` and `<n>` is a zero-padded decimal sequence.

```text
.project-os/
  PESE/
    state/                                      # required
      live.json                                 # required current state envelope
      history/<revision>.json                   # required immutable state revision
    checkpoints/                                # required
      CP-<mission-id>-<utc>-<n>.json
    locks/                                      # required
      state.lock.json                           # exists only while held
    migrations/                                 # required
      MIG-<utc>-<n>.json
    audit/                                      # required
      access/<utc>-<n>.json
      transitions/<utc>-<n>.json
    recovery/                                   # required
      REC-<utc>-<n>.json
```

PESE SHALL NOT make an alternate location authoritative. Repository and team artifacts remain at locations defined by their owning specifications, including TBE manifests under `.project-os/COMPANY/TEAMS/<team-id>/TEAM.md` and ACP audit records under `.project-os/AUDIT/`.

`state/live.json` is a convenience copy of the highest committed history revision. `state/history/<revision>.json`, checkpoints, audit entries, migration records, and recovery records are immutable after publication. A conforming implementation MAY retain temporary files with a `.tmp` suffix only while holding the writer lock; a reader SHALL ignore them.

### 2.3 Identifier and path rules

| Value | Pattern / rule |
|---|---|
| `repository_id` | `REPO:<sha256>`; SHA-256 of the normalized repository origin identity defined in Section 8.2 |
| `mission_id` | `MISSION:[A-Za-z0-9._-]+` |
| `team_id` | TBE form `TEAM:<mission-id>:<sequence>` |
| `agent_id` | ACP form `AGENT:<agent-type>:<instance-id>` |
| `assignment_id` | `ASSIGNMENT:[A-Za-z0-9._-]+` |
| `checkpoint_id` | `CP-<mission-id>-<utc>-<n>` |
| `revision` | positive integer, increasing by one for each successful state commit |
| artifact reference | repository-relative POSIX path; SHALL NOT be absolute, contain `..`, or resolve outside the repository |

---

## 3. On-disk object encodings

The JSON examples in this section define exact object shapes and field encodings, not pseudocode. Example hash values illustrate the required lowercase-hex format; a persisted object SHALL contain hashes computed from its actual canonical content. Ellipses are not valid PESE JSON.

### 3.1 Live and history state envelope

`state/live.json` and each `state/history/<revision>.json` SHALL use this shape. `live.json` SHALL byte-for-byte represent the same JSON value as the current history file, except no path is encoded in either file.

```json
{
  "format": "PESE/v1.0",
  "kind": "state",
  "revision": 42,
  "created_at": "2026-08-04T12:30:00.000Z",
  "writer": "AGENT:orchestrator:6ea582f2-4b21-4f55-9e82-3d174ab2312e",
  "previous_revision": 41,
  "previous_state_sha256": "e75e6064cdbc4343b9e2fc5ab16743e28062e413b23f393bc1a24c94efd265bb",
  "state_sha256": "53542033528052280f5d8d82a83c1f3de8af2116ca737251543ae67d25d0a04b",
  "file_sha256": "c0d7760af2d47d4c4f423cd0a7c72eb651f9bf3a2e82bf5d72d92db59295db54",
  "state": {
    "schema_version": "1.0.0",
    "company_state": {},
    "repo_state": {},
    "mission_state": {},
    "execution_state": {},
    "validation_state": {},
    "risk_state": {},
    "agent_state": {},
    "extensions": {}
  }
}
```

For revision `1`, `previous_revision` SHALL be `0` and `previous_state_sha256` SHALL be 64 zeroes. A history filename SHALL equal the decimal `revision` value plus `.json`. The `state_hash` term in audits and checkpoints means this envelope's `state_sha256`.

### 3.2 Checkpoint encoding

Each checkpoint captures a self-contained, verified point for one mission. It SHALL embed the complete state snapshot needed to resume; it SHALL reference, rather than copy, source and validation artifacts.

```json
{
  "format": "PESE/v1.0",
  "kind": "checkpoint",
  "checkpoint_id": "CP-MISSION-007-20260804T123000000Z-0001",
  "reason": "MISSION_START",
  "created_at": "2026-08-04T12:30:00.000Z",
  "created_by": "AGENT:orchestrator:6ea582f2-4b21-4f55-9e82-3d174ab2312e",
  "mission_id": "MISSION-007",
  "state_revision": 42,
  "state_sha256": "53542033528052280f5d8d82a83c1f3de8af2116ca737251543ae67d25d0a04b",
  "repository": {
    "repository_id": "REPO:fae7102fb9d50c2912b3b7f5e2e77503477a40ae7dd32c7154493489726f5f82",
    "head": "a1c853eec79a74b0e398c6ca9d4b66b48a26a179",
    "branch": "codex/mission-007",
    "worktree_fingerprint_sha256": "1f7397cf04d33d476f16e6f6e20f6419603760c7aa3a44d0cd5a4f42f3796b1e"
  },
  "snapshot": {
    "mission_id": "MISSION-007",
    "milestone_id": "IMPLEMENT",
    "active_assignments": ["ASSIGNMENT:implement-pese"],
    "completed_assignments": [],
    "validation_gate_refs": [],
    "evidence_refs": []
  },
  "snapshot_sha256": "336f1bb19e122aa5bd2ff2c4dcbaf08a3ae843784da125f3b3dd0ddb5a8e9fd2",
  "previous_checkpoint_id": null,
  "previous_checkpoint_sha256": null,
  "file_sha256": "1f4e1c3c3a7ff67c1a323b37bd24cd4b97b4a2cc8b2baf5203172f632486015a"
}
```

`reason` SHALL be one of `MISSION_START`, `MISSION_FINISH`, `VALIDATION`, `COMMIT`, `FAILURE`, `INTERRUPTION`, or `MANUAL`. `MANUAL` SHALL NOT replace a mandatory automatic checkpoint. `previous_checkpoint_*` refer to the immediately preceding accepted checkpoint for the same `mission_id`; for the first it is `null`.

### 3.3 Lock encoding

`locks/state.lock.json` is a lease, not an audit record. Its creation is atomic and exclusive. It MUST be deleted only by the holder after a successful release or by the verified stale-lock recovery process in Section 9.

```json
{
  "format": "PESE/v1.0",
  "kind": "lock",
  "lock_name": "state",
  "lock_id": "LOCK-20260804T123000000Z-0001",
  "owner_agent_id": "AGENT:orchestrator:6ea582f2-4b21-4f55-9e82-3d174ab2312e",
  "owner_process_id": "host-process-opaque-31d3c6",
  "acquired_at": "2026-08-04T12:30:00.000Z",
  "lease_expires_at": "2026-08-04T12:32:00.000Z",
  "last_renewed_at": "2026-08-04T12:30:00.000Z",
  "purpose": "state-update",
  "expected_revision": 42,
  "file_sha256": "f59eaf0f24f9b0157d38cf4d4b5b1c6c9c4a32e7a73ea912410319efbc8a16d9"
}
```

### 3.4 Migration encoding

```json
{
  "format": "PESE/v1.0",
  "kind": "migration",
  "migration_id": "MIG-20260804T123000000Z-0001",
  "from_schema_version": "1.0.0",
  "to_schema_version": "1.1.0",
  "started_at": "2026-08-04T12:30:00.000Z",
  "completed_at": "2026-08-04T12:30:02.000Z",
  "initiated_by": "AGENT:orchestrator:6ea582f2-4b21-4f55-9e82-3d174ab2312e",
  "pre_migration_checkpoint_id": "CP-MISSION-007-20260804T123000000Z-0001",
  "input_revision": 42,
  "output_revision": 43,
  "result": "SUCCEEDED",
  "transform_sha256": "67442d49e3ec6ce0ae6a4c67d41442945c4844768ee00be0a2ee605e22d6dd5b",
  "error": null,
  "file_sha256": "70bd14206f295f17e3d9b2f40da7b2a42d1d5ea5209d9d1ab462d858c7301908"
}
```

`result` is `STARTED`, `SUCCEEDED`, `FAILED`, or `ROLLED_BACK`. A `FAILED` migration has `completed_at` and `output_revision` set to `null` and a non-null `error` object with `code` and non-secret `detail`. `STARTED` is permitted only during execution; an unfinished `STARTED` record triggers recovery.

### 3.5 Access audit encoding

Each load, validation, writer-lock attempt, save, checkpoint read, checkpoint write, migration, and recovery operation SHALL create an access entry. Reads MAY be batched only for a single operation and never across actors.

```json
{
  "format": "PESE/v1.0",
  "kind": "access-audit",
  "audit_id": "ACCESS-20260804T123000000Z-0001",
  "occurred_at": "2026-08-04T12:30:00.000Z",
  "actor_agent_id": "AGENT:orchestrator:6ea582f2-4b21-4f55-9e82-3d174ab2312e",
  "operation": "SAVE",
  "target": "PESE/state/live.json",
  "result": "ALLOWED",
  "state_revision": 42,
  "correlation_id": "9f1e2d3c-4b5a-6d7e-8f9a-0b1c2d3e4f5a",
  "detail_sha256": "3a194f8a78c55b74404b3e1d9a73e3f8bb0a5374de4acecc668d22ab54af8b6b",
  "previous_audit_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "file_sha256": "3ed93324b02c443f00eb15d9e5cfa16cc7ae6b3d92e83a1c7053f6a6d267f9ee"
}
```

`operation` is one of `LOAD`, `VALIDATE`, `LOCK_ACQUIRE`, `LOCK_RENEW`, `LOCK_RELEASE`, `SAVE`, `CHECKPOINT_READ`, `CHECKPOINT_WRITE`, `MIGRATE`, `RECOVER`, or `VERIFY`. `result` is `ALLOWED`, `DENIED`, `SUCCEEDED`, `FAILED`, or `HALTED`. Access audits SHALL NOT contain source content, credentials, ACP payloads, or unrestricted error traces.

### 3.6 State-transition audit encoding

Every committed change to a status, assignment, validation gate, risk, agent availability, or top-level state component SHALL create exactly one transition audit entry in the same durable transaction as its new state revision.

```json
{
  "format": "PESE/v1.0",
  "kind": "transition-audit",
  "audit_id": "TRANSITION-20260804T123000000Z-0001",
  "occurred_at": "2026-08-04T12:30:00.000Z",
  "actor_agent_id": "AGENT:orchestrator:6ea582f2-4b21-4f55-9e82-3d174ab2312e",
  "transition_type": "MISSION_STATUS",
  "subject": "MISSION-007",
  "from": "PLANNED",
  "to": "ACTIVE",
  "reason": "mission-start",
  "before_state_sha256": "e75e6064cdbc4343b9e2fc5ab16743e28062e413b23f393bc1a24c94efd265bb",
  "after_state_sha256": "53542033528052280f5d8d82a83c1f3de8af2116ca737251543ae67d25d0a04b",
  "evidence_refs": ["PESE/checkpoints/CP-MISSION-007-20260804T123000000Z-0001.json"],
  "acp_correlation_id": "9f1e2d3c-4b5a-6d7e-8f9a-0b1c2d3e4f5a",
  "previous_audit_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "file_sha256": "b00d5ad9c21d1bdb351b55207352d0d30d8c0dc71c7b1b062c8f9c5e12454ce0"
}
```

`transition_type` is `COMPANY_STATUS`, `REPO_HEAD`, `MISSION_STATUS`, `ASSIGNMENT_STATUS`, `VALIDATION_GATE`, `RISK_STATUS`, `AGENT_STATUS`, `RECOVERY_STATUS`, or `SCHEMA_VERSION`. `from` and `to` are scalar status/identifier values; a multi-field change SHALL use multiple entries or set both values to a canonical JSON SHA-256 and include individual details in `evidence_refs`.

---

## 4. Top-level state schema

### 4.1 Required top-level state

The `state` object SHALL contain exactly these eight keys: `schema_version`, `company_state`, `repo_state`, `mission_state`, `execution_state`, `validation_state`, `risk_state`, `agent_state`, and optional `extensions`. The components below are required even when empty.

| Component | Required contents | PESE use |
|---|---|---|
| `company_state` | company identity, operating status, ACR/TBE/ACP compatibility references | protects cross-contract compatibility |
| `repo_state` | repository identity, canonical root, valid `HEAD`, valid `BRANCH`, worktree fingerprint | binds state to the actual repository |
| `mission_state` | mission records, current active mission, assigned agent and manifest reference | locates work without authoring it |
| `execution_state` | milestones, assignments, dependency status, next-task candidates, interruption | determines resume order |
| `validation_state` | gates, verdicts, validator identity, immutable validation artifacts | blocks unsafe advancement |
| `risk_state` | open/accepted/mitigated risks and halts | prevents silent unsafe continuation |
| `agent_state` | identity, assignment, availability, last verified checkpoint/heartbeat reference | identifies active and failed actors |

### 4.2 COMPANY-STATE

```json
{
  "company_id": "COMPANY:asc-orchestrator-v2",
  "status": "ACTIVE",
  "protocols": {
    "ACP": "1.0",
    "ACR": "1.0",
    "TBE": "1.0",
    "PESE": "1.0"
  },
  "registry_ref": "docs/ACR_v1.0.md",
  "team_builder_ref": "docs/TBE_v1.0.md",
  "message_protocol_ref": "docs/ACP_v1.0.md",
  "created_at": "2026-08-04T12:30:00.000Z",
  "updated_at": "2026-08-04T12:30:00.000Z"
}
```

`status` is `INITIALIZING`, `ACTIVE`, `RECOVERING`, `HALTED`, or `ARCHIVED`. PESE MAY change it only through an authorized state transition; no company policy is created by this field.

### 4.3 REPO-STATE

```json
{
  "repository_id": "REPO:fae7102fb9d50c2912b3b7f5e2e77503477a40ae7dd32c7154493489726f5f82",
  "root": ".",
  "vcs": "git",
  "origin_identity": "https://example.invalid/org/asc-orchestrator-v2.git",
  "HEAD": "a1c853eec79a74b0e398c6ca9d4b66b48a26a179",
  "BRANCH": "codex/mission-007",
  "head_kind": "COMMIT",
  "worktree_fingerprint_sha256": "1f7397cf04d33d476f16e6f6e20f6419603760c7aa3a44d0cd5a4f42f3796b1e",
  "dirty_paths": [],
  "last_verified_at": "2026-08-04T12:30:00.000Z"
}
```

`HEAD` SHALL be a full, existing Git commit object ID. `BRANCH` SHALL name an existing local branch whose commit equals `HEAD`; detached HEAD is invalid while an active mission exists. `origin_identity` is the normalized remote URL with credentials, query, fragment, and trailing `.git` removed, or `local:<canonical-root>` when no remote exists. `repository_id` is SHA-256 of `vcs + "\\n" + origin_identity`. `worktree_fingerprint_sha256` is SHA-256 of canonical JSON `{ "HEAD": HEAD, "BRANCH": BRANCH, "dirty_paths": sorted dirty repository-relative paths }`.

### 4.4 MISSION-STATE

```json
{
  "active_mission_id": "MISSION-007",
  "missions": {
    "MISSION-007": {
      "status": "ACTIVE",
      "priority": "HIGH",
      "manifest_ref": ".project-os/COMPANY/TEAMS/TEAM:MISSION-007:1/TEAM.md",
      "manifest_version": 1,
      "assigned_agent_ids": ["AGENT:orchestrator:6ea582f2-4b21-4f55-9e82-3d174ab2312e"],
      "started_at": "2026-08-04T12:30:00.000Z",
      "completed_at": null,
      "last_checkpoint_id": "CP-MISSION-007-20260804T123000000Z-0001",
      "acceptance_evidence_refs": []
    }
  }
}
```

Mission status is `PLANNED`, `ACTIVE`, `BLOCKED`, `INTERRUPTED`, `VALIDATING`, `COMPLETED`, `CANCELLED`, `FAILED`, or `ARCHIVED`. At most one mission may be `ACTIVE`, `INTERRUPTED`, or `VALIDATING` per repository unless an active TBE manifest proves all corresponding ownership and dependency partitions are disjoint. `active_mission_id` is `null` only if none is active. An active agent's `mission_id` and `assignment_id` in AGENT-STATE SHALL match this mission and a non-terminal assignment in EXECUTION-STATE.

`ARCHIVED` is permitted only when the mission carries a complete `dissolution_record` consistent with TBE Section 19. Its required shape is:

```json
{
  "dissolution_record": {
    "status": "COMPLETE",
    "trigger": "VERIFIED_COMPLETION",
    "freeze_checkpoint_id": "CP-MISSION-007-20260804T123000000Z-0009",
    "final_validation": {
      "required": true,
      "green_gate_ids": ["GATE:qa"],
      "validated_at": "2026-08-04T13:30:00.000Z"
    },
    "mission_record_ref": {
      "path": ".project-os/COMPANY/TEAMS/TEAM:MISSION-007:1/MISSION_RECORD.json",
      "sha256": "4a9e45a9bfa93625e3f707d6fb2ac0a70fd0c7bb1d1e2bb807cc98dcaa348a88"
    },
    "consolidated_evidence_refs": [".project-os/evidence/mission-007/index.json"],
    "consolidated_gate_refs": ["GATE:qa"],
    "consolidated_review_refs": [".project-os/reviews/mission-007/index.json"],
    "consolidated_kpi_refs": [".project-os/kpis/mission-007.json"],
    "consolidated_conflict_refs": [".project-os/conflicts/mission-007.json"],
    "knowledge_extraction_refs": ["ACP:CORRELATION:9f1e2d3c-4b5a-6d7e-8f9a-0b1c2d3e4f5a"],
    "retention_applied_at": "2026-08-04T13:31:00.000Z",
    "membership_release_verified_at": "2026-08-04T13:31:00.000Z",
    "final_manifest_ref": ".project-os/COMPANY/TEAMS/TEAM:MISSION-007:1/TEAM.md",
    "dissolution_report_ref": ".project-os/COMPANY/TEAMS/TEAM:MISSION-007:1/DISSOLUTION.md",
    "completed_at": "2026-08-04T13:32:00.000Z"
  }
}
```

The record SHALL confirm, in order: freeze and an in-flight-work checkpoint; **for verified-completion only**, final independent validation that all required gates are GREEN; evidence, gate, review, KPI, and conflict-telemetry consolidation; knowledge extraction; applicable retention; release of membership repository write rights and standing ownership; and archival of the final manifest and dissolution report. `trigger` is `VERIFIED_COMPLETION`, `MISSION_CANCELLATION`, `MISSION_WITHDRAWAL`, or `TEAM_FAILURE`. `final_validation.required` SHALL be `true` only for `VERIFIED_COMPLETION`; it SHALL be `false` with an empty `green_gate_ids` array for the other triggers.

`mission_record_ref` is REQUIRED and SHALL contain exactly `path` and `sha256`. Its path SHALL be repository-relative, remain beneath `.project-os/COMPANY/TEAMS/<team-id>/`, and resolve to a mission record whose bytes match `sha256`. That mission record SHALL contain, or content-addressably resolve, the consolidated evidence, gate verdicts, review records, KPI records, and conflict telemetry named by the corresponding consolidation fields. Every listed record SHALL resolve and hash-validate where a PESE artifact record is available. A missing, out-of-team-directory, hash-mismatched, or incomplete mission record SHALL block `ARCHIVED`, retain the mission in its prior terminal state, set/retain a blocking risk, and require a Level-3 escalation.

### 4.5 EXECUTION-STATE

```json
{
  "current_milestone_id": "IMPLEMENT",
  "milestones": [
    {"id": "DISCOVER", "order": 10, "status": "COMPLETED"},
    {"id": "IMPLEMENT", "order": 20, "status": "ACTIVE"},
    {"id": "VALIDATE", "order": 30, "status": "PENDING"}
  ],
  "assignments": {
    "ASSIGNMENT:implement-pese": {
      "mission_id": "MISSION-007",
      "milestone_id": "IMPLEMENT",
      "status": "IN_PROGRESS",
      "assigned_agent_id": "AGENT:orchestrator:6ea582f2-4b21-4f55-9e82-3d174ab2312e",
      "manifest_version": 1,
      "depends_on": [],
      "input_refs": [],
      "output_refs": [],
      "started_at": "2026-08-04T12:30:00.000Z",
      "completed_at": null,
      "last_checkpoint_id": "CP-MISSION-007-20260804T123000000Z-0001",
      "position_id": "POSITION:implement-pese",
      "replacement_count": 0,
      "replacement_lineage": [],
      "interruption": null
    }
  },
  "next_task_candidates": ["ASSIGNMENT:implement-pese"]
}
```

Milestone status is `PENDING`, `ACTIVE`, `COMPLETED`, `BLOCKED`, or `SKIPPED`. Assignment status is `PENDING`, `READY`, `IN_PROGRESS`, `BLOCKED`, `INTERRUPTED`, `COMPLETED`, `CANCELLED`, or `FAILED`. `depends_on` contains assignment IDs and SHALL form a DAG. `input_refs` and `output_refs` SHALL match the assigned agent's ACR INPUT CONTRACTS and OUTPUT CONTRACTS where applicable. `next_task_candidates` is ordered by the deterministic sort in Section 7.3 and is advisory until Resume Manager revalidates it.

`position_id` is immutable for the mission assignment position and remains unchanged across reassignment or replacement. `replacement_count` is the number of replacement instances already activated for that position and SHALL be in `0..2`. `replacement_lineage` is append-only and each entry SHALL contain `failed_agent_id`, `replacement_agent_id`, `failure_class`, `recovery_record_ref`, `manifest_version`, and `occurred_at`. Before a replacement activates, State Manager SHALL increment `replacement_count` and append its lineage entry in the same committed transition. When a third failure occurs at the same `position_id` after two replacements, PESE SHALL record the failure and a Level-3 escalation requirement; it SHALL NOT activate or record a third replacement.

### 4.6 VALIDATION-STATE

```json
{
  "gates": {
    "GATE:qa": {
      "mission_id": "MISSION-007",
      "status": "PENDING",
      "validator_agent_id": "AGENT:qa-validator:0d1f5a09-e789-4a40-8d14-0f3c5c1f3de1",
      "manifest_version": 1,
      "criteria_refs": [".project-os/COMPANY/TEAMS/TEAM:MISSION-007:1/TEAM.md"],
      "artifact_ids": [],
      "last_checkpoint_id": null,
      "verdict_at": null
    }
  },
  "artifacts": {}
}
```

Gate status is `PENDING`, `RUNNING`, `GREEN`, `RED`, `BLOCKED`, `INVALIDATED`, or `WAIVED`. `GREEN` requires a validator authorized by the current TBE manifest and ACR entry. `WAIVED` requires a referenced ACP APPROVAL and SHALL be treated as non-green by a gate that TBE marks mandatory. Each validation artifact SHALL be represented under `artifacts` as `{ "path", "sha256", "type", "produced_at", "producer_agent_id", "retention_class" }`; the path SHALL resolve, SHA-256 SHALL match bytes on disk, and it SHALL be immutable or content-addressed. A validation result without its required artifacts is `INVALIDATED`, not `GREEN`.

### 4.7 RISK-STATE

Each risk is `{ "risk_id", "status", "severity", "description", "mission_id", "evidence_refs", "owner_agent_id", "opened_at", "resolved_at" }`. Status is `OPEN`, `MITIGATING`, `ACCEPTED`, `RESOLVED`, or `HALT`. Severity is `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`. Any `HALT` risk, any unresolved `CRITICAL` risk, or a `HIGH` risk whose declared block condition is met SHALL prevent autonomous execution.

### 4.8 AGENT-STATE

Each agent record is `{ "agent_id", "status", "mission_id", "assignment_id", "manifest_version", "last_heartbeat_at", "last_checkpoint_id", "acr_ref", "dependency_environment_state", "interruption" }`. Status is `INITIALIZING`, `REGISTERED`, `READY`, `BUSY`, `BLOCKED`, `FAILED`, `QUARANTINED`, `REPLACED`, or `RELEASED` and SHALL agree with applicable ACP state. `acr_ref` identifies the agent type/version used for contract validation. `dependency_environment_state` is an object with required keys `status` (`VERIFIED`, `MISSING`, `MISMATCH`, `UNKNOWN`), `verified_at`, `tool_dependencies`, and `environment_dependencies`.

Before an assignment may become `READY` or `IN_PROGRESS`, its agent's `dependency_environment_state.status` SHALL be `VERIFIED`; this implements ACR dependency validation requiring dependencies to be present in PESE environment state. `BUSY`, `BLOCKED`, `FAILED`, or `QUARANTINED` agents SHALL have a matching active assignment, unless their status is a documented company-level operational state.

---

## 5. State Manager

### 5.1 Required operations and outcomes

| Operation | Required behavior | Success | failure / safety outcome |
|---|---|---|---|
| `LOAD` | Read, canonicalize, validate live/history selection | `STATE_LOADED` with revision/hash | `STATE_MISSING`, `STATE_CORRUPT`, `STATE_INCOMPATIBLE`, or `SAFETY_HALT` |
| `VALIDATE` | Run Section 8 without mutation | `VALID` | `INVALID` with machine-readable findings |
| `UPDATE` | Apply an authorized typed transition to a loaded revision | `UPDATED` | `CONFLICT`, `UNAUTHORIZED`, `INVALID_TRANSITION`, or `HALTED` |
| `SAVE` | Atomically persist exactly one next revision | `SAVED` | `LOCKED`, `CONFLICT`, `IO_FAILURE`, or `HALTED` |
| `CHECKPOINT` | Validate and persist a checkpoint | `CHECKPOINTED` | `DUPLICATE`, `INVALID`, or `HALTED` |
| `RESUME` | Execute Section 7 read-only decision algorithm | `RESUME_PLAN` | `NO_WORK`, `RECOVERY_REQUIRED`, or `SAFETY_HALT` |

Outcomes SHALL include `operation_id`, `occurred_at`, `state_revision` when available, `state_sha256` when available, and non-secret structured findings. An implementation SHALL make no state mutation after returning `SAFETY_HALT` except a recovery/audit transition permitted by Section 10.

### 5.2 Load and validation

State Manager SHALL first validate the lock-independent history chain, then select the greatest continuous valid revision. `live.json` SHALL match that revision exactly. If history is valid but `live.json` is missing or differs, State Manager SHALL halt normal execution, write an access audit if possible, and require Recovery Engine to repair `live.json` from the highest verified history file. It SHALL NOT select a lower revision merely because it is more convenient.

### 5.3 Update authorization and transition semantics

An update SHALL specify `expected_revision`, actor, typed `transition_type`, subject, requested `from`, requested `to`, evidence references, and ACP correlation ID when triggered by a message. State Manager SHALL reject the update unless:

1. `expected_revision` equals the currently verified revision;
2. actor authority is consistent with the current TBE manifest and ACR authority/OUTPUT CONTRACT;
3. the requested transition is legal below;
4. all referenced evidence paths/hashes validate; and
5. the resulting entire state validates under Section 8.

| Subject | Legal direction |
|---|---|
| mission | `PLANNED -> ACTIVE -> VALIDATING -> COMPLETED`; `ACTIVE/VALIDATING -> BLOCKED/INTERRUPTED/FAILED/CANCELLED`; a terminal mission -> `ARCHIVED` only with the complete TBE Section 19 dissolution record in Section 4.4 |
| assignment | `PENDING -> READY -> IN_PROGRESS -> COMPLETED`; `READY/IN_PROGRESS -> BLOCKED/INTERRUPTED/FAILED/CANCELLED`; `BLOCKED/INTERRUPTED -> READY` only after recovery evidence |
| gate | `PENDING -> RUNNING -> GREEN/RED/BLOCKED`; `RUNNING -> PENDING` only by checkpointed validator recovery; `GREEN -> INVALIDATED` only if its artifact/repository binding fails |
| agent | ACP-compatible lifecycle changes; `FAILED -> READY` only after accepted ACP RECOVERY and verified checkpoint; `QUARANTINED` changes follow TBE Section 18 |
| risk | `OPEN -> MITIGATING/ACCEPTED/RESOLVED/HALT`; `HALT` exits only by authorized recovery evidence |

No terminal completed evidence may be removed by a transition. A transition that changes repository HEAD, BRANCH, manifest version, artifact hash, checkpoint binding, or validator identity SHALL be separately audited.

### 5.4 Atomic save protocol

While holding the single-writer lock, State Manager SHALL:

1. re-load and validate the highest revision;
2. verify `expected_revision` and authorization;
3. materialize and fully validate revision `N + 1`, compute its state/file hashes, and create its transition audit entry;
4. write each new file to a same-directory unique `.tmp` file, flush file content and directory metadata where the filesystem supports it;
5. atomically rename the history temp file to `history/<N+1>.json`, then atomically replace `live.json`, then publish the transition audit entry;
6. release the lock only after all published files validate when read back.

If a failure happens before history publication, the operation SHALL fail with no new state. If it happens after history publication but before live replacement/audit publication, recovery SHALL preserve the history revision and repair derived files; it SHALL NOT delete the history revision. A writer SHALL never overwrite a history revision.

---

## 6. Checkpoint Manager

### 6.1 Mandatory checkpoint triggers

Checkpoint Manager SHALL create a verified automatic checkpoint immediately after, and only after, the corresponding state transition commits:

| Trigger | Reason | Required contents |
|---|---|---|
| mission begins | `MISSION_START` | initial active mission, manifest/version, HEAD/BRANCH, assignments |
| mission completes/cancels/fails | `MISSION_FINISH` | terminal status, all gate/evidence refs, final HEAD/BRANCH |
| validation gate reaches a verdict or resets from recovery | `VALIDATION` | gate, validator, artifact hashes, verdict and checkpointed prior verdict |
| repository commit changes `HEAD` | `COMMIT` | prior/new HEAD, BRANCH, dirty fingerprint, affected assignment refs |
| ACP FAILURE, agent failure, or state integrity failure is recorded | `FAILURE` | failure class/ref, agent/assignment, evidence and last good point |
| orderly interruption, stale heartbeat, shutdown, or lock crash is detected | `INTERRUPTION` | interrupted agent/assignment, safe next point, unknown work declaration |

An operation that needs a mandatory checkpoint SHALL be incomplete until that checkpoint is committed. `MISSION_FINISH` is required for each terminal mission state. The checkpoint's state revision SHALL be the just-committed revision.

### 6.2 Duplicate, replay, and ordering rules

A checkpoint is duplicate if its `mission_id`, `reason`, `state_sha256`, repository `head`, and `snapshot_sha256` equal an accepted prior checkpoint. Checkpoint Manager SHALL return that existing checkpoint ID and SHALL NOT create a second file. A replay with the same `checkpoint_id` and unequal canonical content is corruption and SHALL halt. A replay with identical canonical content is idempotent success.

For one mission, `previous_checkpoint_id` SHALL point to the prior accepted checkpoint. Creation times need not be unique across missions, but ordering for each mission is `(created_at, checkpoint_id)`. An older checkpoint SHALL never overwrite or downgrade `mission_state.last_checkpoint_id`. Checkpoints for a terminal mission may be read but no new non-recovery checkpoint may be created.

### 6.3 Snapshot validity

Checkpoint Manager SHALL reject a snapshot unless its mission exists; its `state_revision/state_sha256` match a verified state history file; repository identity, HEAD, and BRANCH match that state; assignment, gate, and artifact references resolve; and its snapshot contains no secret. A checkpoint does not authorize a repository rollback. It records evidence only.

---

## 7. Resume Manager

### 7.1 Inputs and precedence

Resume Manager is read-only. Its authoritative inputs, in descending precedence, are:

1. a valid repository Git identity and working-tree observation;
2. the highest continuous valid PESE history state and its matching `live.json`;
3. the latest valid checkpoint chain for each mission;
4. the current TBE team manifest and its version/ownership/dependency graph;
5. current ACR entry requirements, including INPUT CONTRACTS, OUTPUT CONTRACTS, RECOVERY DUTIES, and DEPENDENCIES;
6. ACP audit references only to verify identity/correlation where available; ACP messages are never synthesized.

An assertion from a lower-precedence source SHALL NOT override a conflict in a higher-precedence source. A mismatch at a safety-critical field produces `SAFETY_HALT`, not heuristic reconciliation.

### 7.2 Deterministic resume algorithm

Given repository root `R` and `.project-os`, Resume Manager SHALL execute the following order exactly:

1. Discover `R`, confirm Git is available, obtain current full `HEAD`, current `BRANCH`, dirty path list, and normalized repository identity.
2. Run PESE integrity validation. If it reports corruption, missing required history, an unclosed migration, or an unverified stale lock, return `SAFETY_HALT` with `PESE_INTEGRITY_FAILURE`.
3. Load highest valid state. Confirm its `repository_id`, `HEAD`, and `BRANCH` match the current repository. A HEAD/branch mismatch on an active or validating mission returns `SAFETY_HALT` with `REPOSITORY_DIVERGENCE`; a dirty path not covered by a checkpoint returns `RECOVERY_REQUIRED` with `UNTRACKED_WORKTREE_CHANGE`.
4. Verify the current active mission record against the referenced current TBE manifest. If mission, team ID, manifest version, agent assignment, ownership, or dependency graph is missing/mismatched, return `SAFETY_HALT` with `MANIFEST_OR_ASSIGNMENT_MISMATCH`.
5. Determine milestones by ascending `order`: a milestone is completed only if all its assignments are `COMPLETED` with their required outputs and every required gate is `GREEN`; otherwise the lowest non-completed non-skipped milestone is current. If `current_milestone_id` disagrees, select the computed value and return `RECOVERY_REQUIRED` rather than mutating it.
6. Determine completed missions from terminal status plus the required `MISSION_FINISH` checkpoint. Determine active missions from non-terminal status and a valid latest checkpoint; if more than one active mission lacks manifest-proven disjointness, return `SAFETY_HALT` with `CONCURRENT_MISSION_CONFLICT`.
7. Mark an assignment interrupted when it is `IN_PROGRESS`, its agent is `FAILED`, `QUARANTINED`, or heartbeat-stale, or its last checkpoint is older than its last claimed progress. Preserve completed evidence; classify the remainder as suspect. If ACR recovery duties cannot establish a valid recovery point, return `RECOVERY_REQUIRED`.
8. Reject candidates whose mission is not active, assigned agent is not `READY`, required `dependency_environment_state` is not `VERIFIED`, input contract/evidence is missing, dependency assignment is not completed, gate predecessor is not `GREEN`, ownership is stale, or an applicable risk blocks execution.
9. From remaining `READY` assignments in the current milestone, choose the lexicographically smallest tuple `(mission priority rank CRITICAL,HIGH,MEDIUM,LOW; milestone order; assignment_id)`. If none remains but a prior unresolved condition exists, return its earlier safety/recovery outcome; otherwise return `NO_WORK`.
10. Return `RESUME_PLAN` containing the computed milestone, active/completed mission IDs, interrupted assignments, selected next assignment, required checkpoint, and validation of all preconditions. It SHALL NOT claim that the selected work has begun.

### 7.3 Safety-halt behavior

On any `SAFETY_HALT`, PESE SHALL record an access audit if safely possible, set a `HALT` risk through an authorized recovery transaction if state integrity permits, and require ACP `ESCALATION` with `ISSUE-TYPE:STATE_CORRUPTION` when ACP Section 23 requires it. It SHALL NOT acquire a work assignment, mark a task ready, change a gate, discard files, or reconstruct a message. Human or authorized orchestrator intervention is required to choose recovery.

---

## 8. Integrity validation

### 8.1 Required validation gates

Integrity validation SHALL yield every applicable finding, not only the first. A state is valid only when all required checks pass.

| Gate | Required checks | Failure result |
|---|---|---|
| layout | required directories, `live.json`, history, valid filenames, no conflicting temp publication | `LAYOUT_INVALID` |
| encoding | UTF-8/no BOM/LF, parseable JSON, exact kind/format, schema/enum/type checks | `MALFORMED_JSON` or `SCHEMA_INVALID` |
| state chain | revision sequence starts at 1, previous revision/hash links, state/file hashes, live equals highest history | `STATE_CHAIN_INVALID` |
| checkpoint chain | IDs/filenames, state bindings, snapshot/file hashes, predecessor chain, duplicate/replay rules | `CHECKPOINT_CHAIN_INVALID` |
| audit chain | file hashes and `previous_audit_sha256` chains in each audit stream | `AUDIT_CHAIN_INVALID` |
| migration | migration record hash, version continuity, terminal result, pre-migration checkpoint | `MIGRATION_INVALID` |
| repository | repository ID, valid HEAD, valid BRANCH, branch commit equals HEAD, worktree fingerprint | `REPOSITORY_DIVERGENCE` |
| contract | active mission/assignment match, manifest version, ACR dependency environment state, output/input references | `CONTRACT_INVALID` |
| validation | gates and validation artifacts exist, resolve, hash-match, and satisfy current repository binding | `VALIDATION_EVIDENCE_INVALID` |
| dissolution | every `ARCHIVED` mission has the complete Section 4.4 record, including a hash-validated `mission_record_ref` beneath the TBE team directory that contains/resolves consolidated evidence, gate verdicts, reviews, KPIs, and conflict telemetry; required freeze/checkpoint, completion-only GREEN validation, knowledge, retention, release, final manifest, and dissolution report | `DISSOLUTION_RECORD_INCOMPLETE` |

Malformed/corrupt content includes unreadable bytes, invalid JSON, duplicate keys, hash mismatch, unexpected required-field omission, an unknown required enum, chain break, conflicting duplicate identifier, or any object that cannot be canonicalized. PESE SHALL preserve such files as evidence, not repair them in place.

### 8.2 Repository checks

Repository validation SHALL use Git plumbing or equivalent authoritative Git data, not a cached text file. It SHALL verify all of:

- `repo_state.repository_id` matches the current normalized repository identity;
- `HEAD` resolves to a commit; `BRANCH` exists locally and resolves to the same commit;
- current `HEAD` and `BRANCH` equal state for active/validating work, or divergence is represented by a committed transition/checkpoint;
- every checkpoint HEAD resolves in the same repository;
- each artifact reference remains inside root and has the declared hash; and
- current dirty paths equal the stored fingerprint or are recorded in a later checkpoint/recovery record.

### 8.3 Validation artifacts and exact ACR bindings

PESE SHALL enforce the ACR contract facts it stores, without reinterpreting the contracts: `REPO-STATE must contain valid HEAD and BRANCH`; active agents' mission and assignment SHALL match; every required agent dependency SHALL be represented by verified `dependency_environment_state`; and every declared validation artifact SHALL resolve and hash-match before its gate can be GREEN. PESE does not decide whether a test passed; it decides whether the validator's result is durably bound to declared evidence and repository state.

---

## 9. State locking

### 9.1 Single-writer protocol

PESE has one writer lock for the entire PESE state store. A writer SHALL acquire `state.lock.json` using an atomic exclusive-create primitive, validate its content after acquisition, and hold it across all state/checkpoint/audit publications. It SHALL renew the lease before 50% of the lease duration elapses. The v1.0 default lease is 120 seconds; an implementation MAY use a shorter lease no less than 30 seconds if recorded in the lock `extensions`.

Readers SHALL NOT wait on the lock and SHALL NOT write it. They SHALL read a stable `live.json`, validate against history, retry once if a replacement races their read, and otherwise return `RETRYABLE_READ_CONFLICT`. Readers MUST ignore `.tmp` files.

### 9.2 Stale lock recovery and crash handling

A lock is stale only if (a) current time is later than `lease_expires_at`, (b) the owner process/liveness check is unavailable or negative, and (c) the candidate successor validates all existing history/checkpoints before acting. Clock uncertainty SHALL cause a wait/retry, not stale takeover.

The successor SHALL atomically rename the stale lock to a preserved evidence filename under `recovery/`, write a `RECOVERY` record with `STALE_LOCK_RECOVERY`, validate temp/publication state, publish an `INTERRUPTION` checkpoint if state allows, and only then acquire a new writer lock. It SHALL not delete an expired lock without preserving it. A non-expired lock, ambiguous liveness, ownership mismatch, or invalid lock content causes `SAFETY_HALT` rather than takeover.

On process crash/power loss, a later implementation SHALL use this procedure. It SHALL reconcile publication as described in Section 5.4 and keep both valid history and all suspect temp files for forensics until retention permits deletion.

---

## 10. Recovery Engine

### 10.1 Recovery record

Every recovery attempt SHALL append `recovery/REC-<utc>-<n>.json` with format/kind, recovery ID, started/completed timestamps, trigger, affected mission/agent/assignment, immutable `position_id`, `replacement_count_before`, `replacement_count_after`, a `replacement_lineage_ref`, `last_good_checkpoint_id`, observed evidence references, actions, outcome (`RESUMED`, `REASSIGNED`, `REPLACED`, `HALTED`, `FAILED`), ACP failure/correlation references where known, and `file_sha256`. `replacement_count_after` SHALL equal `replacement_count_before` except when one qualified replacement actually activates; it SHALL never exceed `2`.

### 10.2 Deterministic recovery sequence

Recovery SHALL obey TBE Section 18 ordering and ACP corrupted-state behavior:

1. **Preserve and inspect.** Freeze affected assignment activation; capture repository/PESE evidence and validate integrity. If PESE corruption is detected while processing an ACP message, send ACP `ESCALATION` with `ISSUE-TYPE:STATE_CORRUPTION` and halt autonomous work as ACP Section 23 requires.
2. **Level-0 self-recovery.** The affected agent performs only the bounded procedures and checkpoint reload/diagnostic actions declared by its ACR `RECOVERY DUTIES`.
3. **Quarantine.** After self-recovery exhaustion, mark the agent `QUARANTINED`; freeze assignments and transfer ownership to Team Lead escrow exactly as TBE Section 18 requires. The agent is restricted to ACP `RECOVERY` and `STATUS_UPDATE` rights.
4. **Diagnosis.** Team Lead or Orchestrator classifies evidence and selects `resume`, `reassign`, or `replace`. In-flight work lacking evidence is suspect; completed evidence-backed work is never discarded. It SHALL load the affected assignment's immutable `position_id` and replacement lineage before selecting `replace`.
5. **Replacement.** If selected and `replacement_count < 2`, choose a TBE-qualified replacement, validate ACR inputs/dependencies, transfer ownership through the manifest contract, and provide the failed member's valid checkpoint and completed-evidence record. State Manager SHALL atomically increment the count and append lineage before activation. A builder SHALL NOT replace a validator contrary to TBE Section 18.3.3. If a failure occurs at a position with `replacement_count = 2`, Recovery Engine SHALL NOT select a third replacement: it SHALL record `HALTED`, freeze that position, retain evidence, and issue/require an ACP Level-3 escalation identifying the systemic defect, as TBE Rule 18.3.2 requires.
6. **Manifest update.** Apply TBE RECOVERY-mode manifest increment and ACP `MISSION_UPDATE` before replacement work activates. Gates already GREEN remain GREEN; gates in progress reset only to their last checkpointed verdict.
7. **Resume validation.** Run Resume Manager. It returns a next assignment only when all preconditions validate; otherwise remain halted/recovery-required.

For an invalid/missing checkpoint, Recovery Engine SHALL select the newest earlier fully valid checkpoint for the same mission and treat post-checkpoint work as suspect. It SHALL not infer completion, overwrite repository files, or claim rollback. If no valid checkpoint exists for active work, halt and escalate.

### 10.3 ACP message corruption

PESE SHALL not repair ACP message audit content. An invalid ACP payload hash is handled as ACP `MESSAGE_INTEGRITY`/`MESSAGE_RESEND`; PESE records only the access/transition/recovery reference. A corrupt PESE state is distinct and triggers the Section 10.2 safety halt. No corrupted message or state file may be silently discarded, substituted, or treated as accepted.

---

## 11. Version Manager and compatibility

### 11.1 PESE semantic versioning

PESE uses `MAJOR.MINOR.PATCH` in `schema_version` and file `format` (`PESE/v1.0` for the 1.0 family). PATCH changes clarify behavior or repair implementation defects without changing valid encodings. MINOR changes may add optional fields or extension semantics while preserving reads/writes of the earlier minor schema. MAJOR changes may remove/rename required fields, change hashes/canonicalization, or change resume/transition semantics and SHALL have a migration.

A v1.0 implementation SHALL accept `PESE/v1.0` and compatible `1.0.x` state. It SHALL reject an unknown higher major. It MAY read a higher minor only if every unfamiliar field is optional/extension and all required semantics remain known; it SHALL otherwise return `STATE_INCOMPATIBLE`.

### 11.2 Migration procedure and failure recovery

Before migration, Version Manager SHALL acquire the lock, run integrity validation, create a `MANUAL` pre-migration checkpoint, and persist a `STARTED` migration record. It SHALL transform a copied in-memory state, validate all resulting files and hashes, commit one new revision, and finalize the migration record as `SUCCEEDED`. Original history SHALL remain intact.

On failure it SHALL leave the prior state authoritative, finalize `FAILED` with non-secret evidence, and halt normal execution. An unfinished `STARTED` migration after crash requires Recovery Engine: validate the old state/checkpoint; if no output revision exists, finalize `ROLLED_BACK`; if a complete valid output revision exists, finalize `SUCCEEDED`; otherwise halt. In-place mutation of an old revision is prohibited.

### 11.3 Compatibility matrix

| System | PESE receives | PESE guarantees | Boundary |
|---|---|---|---|
| ACP v1.0 | agent IDs, correlation/failure references, message audit availability | separate PESE access/transition audit; corrupted state detection escalation | ACP remains source of message truth |
| ACR v1.0 | recovery duties, dependencies, INPUT/OUTPUT CONTRACTS, validation/authority declarations | durable checkpoint/recovery/input/output state required by those contracts | PESE does not edit/interpret registry capability choices |
| TBE v1.0 | manifest, ownership, execution/dependency graph, validator assignments, recovery ordering | checkpointed missions/manifests, verified gate/evidence and resume inputs | TBE selects teams; PESE never does |

---

## 12. Integration requirements

### 12.1 ACP integration

For every PESE access or state transition related to ACP activity, PESE SHALL record `acp_correlation_id` where supplied and SHALL audit its own access/transition. ACP's immutable message audit remains separate under `.project-os/AUDIT/`; neither system may use the other file as its append target. A PESE recovery record that corresponds to ACP `FAILURE` or `RECOVERY` SHALL retain references (`FAILURE-REF`, correlation ID, recovery point) sufficient for cross-audit, never the message payload.

### 12.2 ACR integration

Before activating/resuming an assignment, PESE SHALL provide state that lets ACR contracts verify: valid `REPO-STATE.HEAD` and `REPO-STATE.BRANCH`; active mission and assignment matching the agent; verified environment dependencies; declared input references; output references; checkpoint/recovery point; and validation artifacts. An ACR OUTPUT CONTRACT state change SHALL be accepted only after State Manager authorization and PESE integrity validation. ACR is the authority on what an agent may require or emit; PESE is the durable fact store.

### 12.3 TBE integration

TBE SHALL supply the manifest/versions, mission ownership, dependency edges, selected team, reviewers, validators, and recovery decisions. PESE SHALL store the manifest reference/version in mission, assignment, agent, validation, and checkpoint records; it SHALL consume these for safety validation. PESE SHALL NOT choose team members, adjust team size, declare dependencies, or select a replacement. TBE consumes PESE's checkpointed mission and manifest/evidence inputs when performing its Section 18 recovery sequence.

---

## 13. Security, privacy, and retention

PESE files SHALL use filesystem permissions appropriate to the repository policy: only the current authorized writer may modify state/locks; audit/history/checkpoint files SHALL be append-only or immutable where the filesystem supports it. PESE SHALL validate all artifact paths against traversal, normalize paths before comparison, redact credentials/tokens/authorization headers from errors and audits, and never persist secret values. Hashes and repository URLs may be sensitive metadata and SHOULD receive the repository's audit-grade protection.

PESE SHALL retain state history, checkpoints, transition/access audits, migration records, recovery records, and validation artifact references at least until the mission is archived and any ACR/TBE retention class expires. Audit-grade or regulated evidence SHALL follow the longer applicable retention floor. Retention deletion SHALL be an authorized, separately audited transition; it SHALL never delete the last valid checkpoint for an unarchived mission, the history needed to validate the current revision, or evidence under active investigation. Deletion is outside ordinary resume/recovery behavior.

---

## 14. End-to-end examples

### 14.1 Mission start and commit

1. TBE supplies a current manifest for `MISSION-007`; State Manager validates that its assigned agent, manifest version, ACR environment state, `HEAD`, and `BRANCH` are valid.
2. State Manager commits `PLANNED -> ACTIVE`, appends a `MISSION_STATUS` audit, and Checkpoint Manager writes `CP-MISSION-007-...-0001` with reason `MISSION_START`.
3. When an authorized repository commit changes `HEAD`, State Manager commits a `REPO_HEAD` transition. Checkpoint Manager writes a `COMMIT` checkpoint containing both the state and repository fingerprint.
4. Resume Manager will now consider only `READY` assignments whose inputs, ownership, dependencies, and environment state verify against this checkpoint.

### 14.2 Interrupted validation

A validator's process stops while a gate is `RUNNING`. PESE creates an `INTERRUPTION` checkpoint identifying the gate's last checkpointed verdict and preserves all artifact references. The agent performs its ACR Level-0 recovery. If it fails, TBE quarantines it; PESE records that state but does not appoint a successor. When TBE names a qualified replacement and updates the manifest, PESE verifies the new agent/manifest/contracts. The in-progress gate returns to its last checkpointed verdict; a prior `GREEN` gate remains `GREEN` only if artifact and repository binding still validate.

### 14.3 Power loss between history and live publication

After a crash, `history/43.json` is complete and validates, but `live.json` still equals revision 42. Integrity validation reports `STATE_CHAIN_INVALID` for the live alias. Recovery Engine preserves files, records recovery evidence, atomically replaces `live.json` with the verified revision 43, validates it, and appends the missing access/transition audit only if its transition was committed and recoverable from the revision. It does not discard revision 43 or invent a checkpoint.

### 14.4 Unsafe branch change

An active mission state says `HEAD=a1c...` and `BRANCH=codex/mission-007`; the repository is now on a different branch. Resume Manager returns `SAFETY_HALT:REPOSITORY_DIVERGENCE`, records a halt risk if safe, and requests ACP escalation. It SHALL NOT infer that the new branch is a continuation, update `REPO-STATE`, or begin the next assignment.

### 14.5 Replacement limit and dissolution

For `POSITION:implement-pese`, the first and second qualified replacement increment `replacement_count` from `0` to `1` and from `1` to `2`, with a recovery record and lineage entry for each. A subsequent failure at that same immutable position freezes work and produces a Level-3 ACP escalation; PESE records no third replacement.

When a mission reaches verified completion, TBE freezes work and PESE records the freeze checkpoint. Only then does the designated validator produce final GREEN validation. PESE permits `COMPLETED -> ARCHIVED` only after the Section 4.4 dissolution record hash-validates `mission_record_ref` beneath the TBE team directory and that record contains or resolves consolidated evidence, gate verdicts, reviews, KPIs, and conflicts, plus knowledge extraction, retention action, membership write-right/ownership release, final manifest, and dissolution report. A missing, misplaced, mismatched, or incomplete item leaves the mission `COMPLETED`, creates a blocking risk, and requires Level-3 escalation.

---

## 15. MISSION-007 implementation gates

An implementation claiming PESE v1.0 conformance SHALL demonstrate all applicable gates below before it is treated as complete:

| Gate | Required evidence |
|---|---|
| layout/encoding | initializes exactly Section 2.2 layout and round-trips all Section 3 encodings |
| state atomicity | failure-injection proves readers observe revision N or N+1 only |
| integrity | detects malformed JSON, altered hashes, gaps, bad audit/checkpoint chains, invalid HEAD/BRANCH, and missing artifacts |
| checkpointing | creates each Section 6.1 mandatory checkpoint and handles duplicate/replay deterministically |
| locking | proves writer exclusion, reader safety, expired-lock recovery, and ambiguous-lock halt |
| resume | demonstrates each Section 7 outcome, including deterministic candidate ordering and all safety halts |
| recovery | demonstrates TBE Section 18 ordering, ACP corrupted-state halt, preservation of evidence-backed work, and missing-checkpoint behavior |
| replacement limit | proves immutable per-position lineage/count, allows at most two replacements, and halts/escalates Level 3 on a third failure at one position |
| dissolution/archive | proves archive rejects incomplete TBE Section 19 records; requires freeze/checkpoint and completion-only final GREEN validation; hash-validates a `mission_record_ref` beneath the TBE team directory containing/resolving evidence, gate verdicts, reviews, KPIs, and conflicts; and verifies knowledge, retention, release, final manifest, and dissolution report |
| compatibility | validates ACP/ACR/TBE integration boundaries and version/migration rollback behavior |
| security/privacy | proves path containment and secret redaction in state/audits |

These gates define behavior, not a required language, process model, runtime, storage database, or command-line interface. A conforming implementation MAY add APIs, provided they cannot bypass this specification's state, checkpoint, lock, validation, or audit invariants.

---

**END OF SPECIFICATION — PESE v1.0**
