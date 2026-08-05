# Agent Execution Engine — AEX v1.0

## 1. PURPOSE AND SCOPE

AEX v1.0 is the deterministic local agent execution runtime that completes the EEF-specified work loop. EEF schedules and dispatches assignments; AEX *claims, executes, records, and attests* the work performed by each assigned agent.

AEX transitions assignments through their lifecycle (`READY → IN_PROGRESS → COMPLETED | FAILED`), records work product artifacts under a canonical layout, and signs execution attestations using CKS for production audit integrity. AEX emits agent-owned events to the EEF execution journal, closing the event gap identified in M010.

**Boundary.** AEX *executes and attests* local agent work. It does not schedule dispatch decisions (EEF), assemble teams (TBE), intake missions (MSS), persist general state (PESE), or manage cryptographic keys (CKS). AEX is the "agent execution" runtime that M010 explicitly deferred.

## 2. ARCHITECTURE AND BOUNDARY

AEX operates as a stateless local executor layered on top of four existing runtimes:

```text
+-----------------------------------------------+
|       Agents / CLI operators / drivers        |
+-----------------------------------------------+
| AEX v1.0  (this contract)                    |
|   - dispatch, complete, fail, block, unblock  |
|   - artifact persistence and attestation      |
|   - CKS signing of execution records          |
+-----------------------------------------------+
| EEF v1.0  Execution Journal, Event Types      |
| PESE v1.0 Assignment transitions, output_refs |
| CKS v1.0  HMAC-SHA256 signing and verification|
| TBE v1.0  TEAM.md assignment ownership        |
+-----------------------------------------------+
```

**Key design decisions:**

1. AEX transitions flow through `PESEStore.update()` — no PESE invariants are bypassed. The legal `ASSIGNMENT_STATUS` map governs all transitions.
2. For `ASSIGNMENT_STATUS` transitions, the actor must equal the assignment's `assigned_agent_id` (PESE authorization rule). The CLI `--actor` flag must therefore match the assigned agent.
3. AEX populates the assignment's `output_refs` field on completion, linking to canonical artifact paths.
4. AEX emits agent-owned EEF event types (`ASSIGNMENT_DISPATCHED`, `ASSIGNMENT_COMPLETED`, `ASSIGNMENT_FAILED`, `ASSIGNMENT_BLOCKED`, and `ASSIGNMENT_ACTIVATED` for unblock/re-activation) to the existing hash-chained execution journal.
5. AEX writes immutable execution result records under `.project-os/ARTIFACTS/` with optional CKS signatures for audit attestation.

## 3. ASSIGNMENT EXECUTION LIFECYCLE

The AEX execution lifecycle maps directly to legal PESE assignment transitions:

```text
       dispatch()
           |
           v
        [READY] -----------> [IN_PROGRESS]
                               |
              +----------------+----------------+
              |                |                |
         complete()        fail()           block()
              |                |                |
              v                v                v
         [COMPLETED]       [FAILED]         [BLOCKED]
                                            |
                                        unblock()
                                            |
                                            v
                                         [READY]
```

| Operation | PESE Transition | Legal Map | EEF Event | Condition |
|---|---|---|---|---|
| `dispatch` | READY → IN_PROGRESS | READY → IN_PROGRESS | ASSIGNMENT_DISPATCHED | actor == assigned_agent_id |
| `complete` | IN_PROGRESS → COMPLETED | IN_PROGRESS → COMPLETED | ASSIGNMENT_COMPLETED | output_refs set; optional CKS key |
| `fail` | IN_PROGRESS → FAILED | IN_PROGRESS → FAILED | ASSIGNMENT_FAILED | reason required |
| `block` | READY\|IN_PROGRESS → BLOCKED | READY\|IN_PROGRESS → BLOCKED | ASSIGNMENT_BLOCKED | reason required |
| `unblock` | BLOCKED → READY | BLOCKED → READY | ASSIGNMENT_ACTIVATED | re-activation |

**Completion semantics.** On `complete`, AEX: (1) transitions IN_PROGRESS → COMPLETED, (2) writes the execution result record and copies any artifacts to the canonical workspace, (3) updates the assignment's `output_refs` with the artifact paths, and (4) emits ASSIGNMENT_COMPLETED. PESE's computed milestone auto-advances when all milestone assignments are COMPLETED and relevant gates are GREEN — AEX does not manage milestones directly.

**Failure semantics.** Failed assignments are terminal. The mission author or orchestrator decides whether to re-create the assignment or cancel the mission. AEX does not auto-retry.

**Block semantics.** Blocked assignments are released back to READY via `unblock`. The BLOCKED status indicates the assignment cannot proceed until a precondition (resolved dependency, external input, or human decision) is satisfied.

## 4. EXECUTION RESULT RECORD

Each `complete` or `fail` operation writes an immutable result record at:

```
.project-os/ARTIFACTS/<mission_id>/<assignment_id>/result.json
```

Record fields:

```json
{
  "format": "AEX/v1.0",
  "kind": "execution-result",
  "assignment_id": "ASSIGNMENT:investigator",
  "mission_id": "MISSION:example",
  "agent_id": "AGENT:investigator:local",
  "status": "COMPLETED",
  "output_text": "investigation report produced",
  "artifact_hashes": {
    "report.md": "abc123..."
  },
  "started_at": "2026-08-05T04:00:00.000Z",
  "completed_at": "2026-08-05T04:01:00.000Z",
  "pese_revision": 5,
  "pese_state_sha256": "def456...",
  "entry_hash": "sha256-canonical-hash"
}
```

The `entry_hash` is computed over the canonical JSON of all fields except `entry_hash` itself, using the same `_entry_hash` / `_canonical_json` pattern as CKS.

Result records are written once via atomic replace and never modified. If the assignment is completed multiple times (e.g., after a PESE migration), each completion creates a new result file with a unique timestamp.

## 5. ARTIFACT PERSISTENCE

When `aex-complete` receives `--artifact` paths, AEX:

1. Verifies each path is a regular file inside the repository root (no path traversal).
2. Reads the file and computes its SHA-256 hash.
3. Copies the file to `.project-os/ARTIFACTS/<mission_id>/<assignment_id>/artifacts/<filename>`.
4. Records the hash in the execution result record under `artifact_hashes`.
5. Updates the assignment's `output_refs` to `["ARTIFACTS/<mission_id>/<assignment_id>/artifacts/<filename>", ...]`.

All artifact files are stored in flat `artifacts/` subdirectories. AEX uses atomic writes (write-to-temp, then rename) for consistency. Artifact files are read-only and never modified after initial write.

## 6. CKS ATTESTATION

When `aex-complete` receives `--key-id`, AEX:

1. Loads the CKS key via `KeyStore.load_key()` and verifies it is ACTIVE.
2. Computes the canonical JSON of the result record (before signature).
3. Signs the canonical JSON bytes with `KeyStore.sign(key_id, canonical_bytes, actor)`.
4. Writes the signature (`key_id` and `signature_hex`) into the result record under the `signature` field.
5. Records the signature in the CKS signing ledger for the specified key.

This provides cryptographic audit attestation: a signed execution record can be independently verified against the CKS key, proving the record was produced by a known agent at a known time.

## 7. EEF EVENT INTEGRATION

AEX uses the existing `EEFEventJournal` public API to append agent-owned events. Every transition emits the corresponding EEF event type with a `detail` dict:

| AEX Event | EEF Type | Detail |
|---|---|---|
| dispatch | ASSIGNMENT_DISPATCHED | `{agent_id, assignment_id}` |
| complete | ASSIGNMENT_COMPLETED | `{artifact_count, output_refs, signed}` |
| fail | ASSIGNMENT_FAILED | `{reason}` |
| block | ASSIGNMENT_BLOCKED | `{reason, blocked_from_status}` |
| unblock | ASSIGNMENT_ACTIVATED | `{reactivated_from: "BLOCKED"}` |

All events include `mission_id`, `assignment_id`, `actor_agent_id`, `pese_revision`, and `pese_state_sha256`. The journal remains hash-chained and verifiable via `EEFEventJournal.verify_chain()`.

## 8. ON-DISK LAYOUT

```
.project-os/
  ARTIFACTS/
    <mission_id>/
      <assignment_id>/
        result.json                        # immutable execution result
        artifacts/
          <filename>                       # copied output artifacts
```

AEX creates the `.project-os/ARTIFACTS/` directory on first write. The layout mirrors PESE's mission-scoped partitioning. Result records are immutable (atomic write). Artifact files are read-only after creation.

## 9. CLI REFERENCE

AEX commands are wired through `asc-orchestrator` with machine-readable `key=value` output and deterministic exit codes.

```
asc-orchestrator [--root <path>] aex-dispatch --mission-id <id> --assignment-id <id> --actor <agent>
asc-orchestrator [--root <path>] aex-complete --mission-id <id> --assignment-id <id> --actor <agent> [--output <text>] [--artifact <path> ...] [--key-id <key-id>]
asc-orchestrator [--root <path>] aex-fail --mission-id <id> --assignment-id <id> --actor <agent> --reason <text>
asc-orchestrator [--root <path>] aex-block --mission-id <id> --assignment-id <id> --actor <agent> --reason <text>
asc-orchestrator [--root <path>] aex-unblock --mission-id <id> --assignment-id <id> --actor <agent>
asc-orchestrator [--root <path>] aex-status --mission-id <id> --assignment-id <id>
asc-orchestrator [--root <path>] aex-result --mission-id <id> --assignment-id <id>
```

| Command | Output | Exit 0 | Exit 2 |
|---|---|---|---|
| `aex-dispatch` | `assignment_id=<id>` | READY → IN_PROGRESS | Assignment not READY, not found, or unauthorized |
| `aex-complete` | `assignment_id=<id>`, `artifact_count=<n>`, `signed=<true\|false>` | IN_PROGRESS → COMPLETED | Not IN_PROGRESS, unauthorized, or CKS error |
| `aex-fail` | `assignment_id=<id>` | IN_PROGRESS → FAILED | Not IN_PROGRESS or unauthorized |
| `aex-block` | `assignment_id=<id>` | READY\|IN_PROGRESS → BLOCKED | Not READY/IN_PROGRESS or unauthorized |
| `aex-unblock` | `assignment_id=<id>` | BLOCKED → READY | Not BLOCKED or unauthorized |
| `aex-status` | `assignment_id=<id>`, `status=<S>`, `mission_id=<id>`, `started_at=<ts>`, `completed_at=<ts>` | Assignment found | Assignment not found |
| `aex-result` | Full result record JSON fields | Result exists | No result found |

All commands accept `--root <path>` (default `.`) for the repository root. Exit 0 for success, exit 2 for errors. Errors print `error: <code>: <detail>`.

## 10. ERROR HANDLING

AEX uses `AEXError` (subclass of `RuntimeError`) for structured errors:

| Code | Meaning |
|---|---|
| `ASSIGNMENT_NOT_FOUND` | Assignment ID does not exist in PESE state |
| `ASSIGNMENT_NOT_READY` | Assignment status is not READY (for dispatch/unblock) |
| `ASSIGNMENT_NOT_ACTIVE` | Assignment status is not IN_PROGRESS (for complete/fail) |
| `ASSIGNMENT_NOT_BLOCKED` | Assignment status is not BLOCKED (for unblock) |
| `UNAUTHORIZED` | Actor does not match assigned_agent_id |
| `ARTIFACT_NOT_FOUND` | Artifact file does not exist |
| `ARTIFACT_ESCAPE` | Artifact path resolves outside repository root |
| `CKS_ERROR` | CKS signing or key validation failed |

AEX errors are caught by the CLI `main()` function and printed as `error: <code>: <detail>` with exit code 2.

## 11. COMPATIBILITY

AEX v1.0 is compatible with:

- **PESE v1.0**: All assignment transitions use `PESEStore.update()` with legal `ASSIGNMENT_STATUS` map entries. AEX populates `output_refs` as defined by the PESE schema validation rules.
- **EEF v1.0**: AEX emits agent-owned event types through the existing `EEFEventJournal` API, filling the emission gap left by M010.
- **TBE v1.0**: AEX consumes assignments as created by TBE's `bind_manifest_to_pese()`, operating on `assigned_agent_id`, `depends_on`, and `output_refs`.
- **CKS v1.0**: AEX uses `KeyStore.sign()` and `KeyStore.load_key()` for optional execution attestation.
- **ACP v1.0**: AEX execution records may be audit-journaled via ACP's `AuditJournal` at the application layer, outside AEX's core contract.
- **MSS v1.0**: AEX reads mission IDs as opaque strings from EEF/PESE state; no mission-level parsing.

AEX does not modify or bypass any contract in PESE, EEF, TBE, CKS, ACP, or MSS. It is a consumer of their public APIs.

## 12. IMPLEMENTATION REQUIREMENTS

1. AEX runtime (`src/asc_orchestrator/aex.py`) must use only Python 3.11+ stdlib.
2. All PESE transitions must flow through `PESEStore.update()` with the legal ASSIGNMENT_STATUS map.
3. Artifact files must be written via atomic write (temp + rename).
4. Result records are immutable after writing (atomic write, never modified).
5. CKS attestation uses `KeyStore.sign()` for HMAC-SHA256 signing; no alternative signing mechanism.
6. Path traversal in artifact paths must be rejected (artifact must resolve inside `repository_root`).
7. All AEX events use existing EEF EVENT_TYPES; no new event types are introduced.
8. Process-safe file access for result records uses `threading.Lock` per directory (matching CKS/EEF patterns).

## 13. IMPLEMENTATION GATES

AEX v1.0 is complete when:

1. `docs/AEX_v1.0.md` is ratified with all required sections (purpose, architecture, lifecycle, records, artifacts, attestation, EEF integration, layout, CLI reference, error handling, compatibility, requirements, implementation gates, and terminal marker).
2. `src/asc_orchestrator/aex.py` implements `AEX`, `AEXError`, and supporting types using only stdlib.
3. All assignment transitions flow through `PESEStore.update()` with the legal `ASSIGNMENT_STATUS` map.
4. Execution result records are written atomically and are immutable.
5. Artifact path validation rejects traversal outside the repository root.
6. CKS attestation produces verifiable HMAC-SHA256 signatures on execution records.
7. EEF events are appended correctly and the journal chain remains verifiable.
8. Seven `aex-*` CLI subcommands emit machine-readable outcomes and deterministic exit codes.
9. `tests/test_aex.py` exercises dispatch, complete, fail, block/unblock, artifacts, attestation, and EEF journal integration.
10. `tests/test_aex_cli.py` exercises the CLI lifecycle.
11. `python -m mypy` passes on `src`.
12. `python -m ruff check src tests scripts` and `ruff format --check` pass.
13. `python scripts/validate_docs.py` passes with AEX spec coverage.
14. `python -m unittest discover -s tests -t .` passes (existing + new AEX tests).

**END OF SPECIFICATION — AEX v1.0**
