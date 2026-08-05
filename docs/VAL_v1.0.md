# Validation Engine — VAL v1.0

## 1. PURPOSE AND SCOPE

VAL v1.0 is the deterministic validation runtime that drives PESE validation gates through their lifecycle (`PENDING → RUNNING → GREEN/RED/BLOCKED`), registers and verifies validation artifacts via SHA-256, and emits validation events to the hash-chained EEF execution journal. Every state mutation flows through `PESEStore.update()` with transition type `VALIDATION_GATE`; VAL never bypasses PESE invariants.

VAL closes the final gap in the mission-lifecycle chain: TBE assembles the team and defines gates, AEX executes agent work, and AHP observes liveness, but nothing yet *drives* gate verdicts. VAL supplies the validation runtime that the M017 recovery engine and M019 autonomous scheduler consume to gate mission completion.

**Boundary.** VAL drives gate lifecycle, registers artifacts, and emits events. It does not execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), or schedule dispatch (EEF). VAL reads PESE state to drive gates and appends events to the EEF execution journal; it never bypasses either contract.

## 2. ARCHITECTURE AND BOUNDARY

VAL operates as a deterministic validation runtime layered on top of the existing runtimes:

```text
+-----------------------------------------------+
|       Validators / CLI operators / drivers    |
+-----------------------------------------------+
| VAL v1.0  (this contract)                     |
|   - gate lifecycle, artifact verification      |
|   - validation events to EEF journal          |
+-----------------------------------------------+
| PESE v1.0  (read/write: validation_state)     |
| EEF v1.0   (append: execution events)         |
| TBE v1.0   (read-only: gate definitions)      |
+-----------------------------------------------+
```

**Key design decisions:**

1. All state mutations flow through `PESEStore.update()` with transition type `VALIDATION_GATE`. VAL never writes PESE state directly; it relies on the store's legal-transition enforcement and actor authorization.
2. Gate lifecycle follows PESE's validation_state contract: `PENDING → RUNNING → {GREEN, RED, BLOCKED, PENDING}`; additionally, `GREEN → INVALIDATED` when artifact/repository binding fails.
3. Artifact records are registered in PESE `validation_state.artifacts` with SHA-256 hashes computed at registration time. Verification compares stored hashes against on-disk file bytes, detecting tampering or deletion.
4. When tampered artifacts make PESE state unloadable (`STATE_CORRUPT`), VAL's `verify()` reads `live.json` directly (read-only, not asserting state validity) to provide per-artifact diagnostic information. Tampered state is a security halt for mutations — invalidation of tampered evidence is an operator recovery action, not a programmatic operation.
5. `invalidate()` enforces a binding-failure precondition: it only proceeds when `_binding_failed()` returns at least one reason (artifact hash mismatch, missing artifact, or repository divergence). This implements PESE specification section 5.3: GREEN → INVALIDATED only when the artifact/repository binding fails.
6. Actor resolution in the CLI falls back to the gate's `validator_agent_id` for mutation commands, mirroring the execution-engine's actor resolution pattern.

## 3. VALIDATION STATE AND GATES

VAL operates over the `validation_state` section of PESE state:

```json
{
  "validation_state": {
    "gates": {
      "GATE:MISSION:example:functional": {
        "gate_id": "GATE:MISSION:example:functional",
        "mission_id": "MISSION:example",
        "status": "PENDING",
        "validator_agent_id": "AGENT:qa-validator:abc",
        "manifest_version": 1,
        "criteria_refs": [],
        "artifact_ids": [],
        "last_checkpoint_id": null,
        "verdict_at": null
      }
    },
    "artifacts": {}
  }
}
```

**Gate record fields:**

| Field | Meaning |
|---|---|
| `gate_id` | Canonical gate identifier |
| `mission_id` | Mission this gate belongs to |
| `status` | Current gate status (see vocabulary below) |
| `validator_agent_id` | Agent authorized to drive this gate |
| `manifest_version` | Team manifest version at gate creation |
| `criteria_refs` | Validation criteria references |
| `artifact_ids` | Artifacts bound to this gate |
| `last_checkpoint_id` | PESE checkpoint written after the last transition |
| `verdict_at` | UTC timestamp when the gate received a verdict |

**Gate status vocabulary:**

| Status | Meaning |
|---|---|
| `PENDING` | Gate defined but not yet started |
| `RUNNING` | Validator is executing validation |
| `GREEN` | Gate passed with artifacts bound |
| `RED` | Gate failed |
| `BLOCKED` | Gate blocked by a precondition |
| `INVALIDATED` | GREEN verdict revoked due to binding failure |
| `WAIVED` | Gate waived by operator decision |

**Legal transitions:**

| From | To |
|---|---|
| `PENDING` | `RUNNING` |
| `RUNNING` | `GREEN`, `RED`, `BLOCKED`, `PENDING` |
| `GREEN` | `INVALIDATED` (only when binding fails) |

The `GREEN → INVALIDATED` transition requires a binding failure (PESE spec section 5.3). If the artifact/repository binding is sound, VAL raises `BINDING_INTACT`.

## 4. ARTIFACT RECORDS

When a gate finishes with a GREEN verdict, validation artifacts are registered in `validation_state.artifacts`:

```json
{
  "ARTIFACT:VAL:MISSION:example:functional:GATE:MISSION:example:functional:0000": {
    "path": "validation/qa-result.json",
    "sha256": "sha256-hex-of-file-bytes",
    "type": "validation-result",
    "produced_at": "2026-08-05T04:00:00.000Z",
    "producer_agent_id": "AGENT:qa-validator:abc",
    "retention_class": "mission"
  }
}
```

**Artifact record fields:**

| Field | Meaning |
|---|---|
| `path` | Repository-relative file path (forward slashes) |
| `sha256` | SHA-256 hex digest of the file bytes at registration time |
| `type` | Artifact type (e.g., `validation-result`) |
| `produced_at` | UTC timestamp when the artifact was registered |
| `producer_agent_id` | Agent that produced the artifact |
| `retention_class` | Retention policy (e.g., `mission`) |

Artifact IDs follow the format `ARTIFACT:VAL:<mission_id>:<gate_id>:<counter:04d>`.

## 5. VERIFICATION

`verify()` compares bound artifact files against their recorded SHA-256 hashes:

1. Load PESE state (which validates artifact contracts via `_validate_contracts`).
2. For each artifact in the gate's `artifact_ids`, read the on-disk file and compute its SHA-256.
3. Return a `VerificationResult` with per-artifact `MATCH`, `MISMATCH`, or `MISSING` status.

When tampered artifacts make PESE state unloadable (`STATE_CORRUPT`), a raw read of `live.json` provides per-artifact diagnostic information. This is strictly read-only and does not assert state validity. The operator can use the per-artifact MISMATCH report to identify which file broke the integrity chain.

## 6. INVALIDATION

`invalidate()` transitions a GREEN gate to INVALIDATED when the artifact/repository binding fails:

1. Load PESE state (raises `STATE_LOAD_FAILED` if state is corrupt — tamper is a security halt).
2. Find the gate and verify the actor is the designated validator.
3. Verify the gate is GREEN (raises `GATE_NOT_GREEN` otherwise).
4. Check binding integrity via `_binding_failed()`:
   - **Artifact binding**: every artifact record in `validation_state.artifacts` is checked against its on-disk file (hash, existence, path escape).
   - **Repository binding**: compare stored `repo_state` (frozen at `initialize()` time) against the current `repository_observation()`. Divergence in `HEAD`, `BRANCH`, `repository_id`, or `worktree_fingerprint_sha256` constitutes a binding failure.
5. If binding is sound, raise `BINDING_INTACT` — invalidation requires a binding failure.
6. Transition `GREEN → INVALIDATED` via `PESEStore.update()`.
7. Emit a `GATE_INVALIDATED` event to the EEF execution journal.

**Tamper is a halt condition by design.** When artifacts are tampered, PESE state becomes unloadable (`STATE_CORRUPT`), which prevents `invalidate()` from proceeding. This is intentional: allowing programmatic invalidation of tampered evidence would let an attacker sweep tampering under the rug. Recovery of tampered evidence is an operator recovery action.

## 7. EVENT JOURNAL

VAL emits events to the EEF execution journal (`EEFEventJournal`) at `.project-os/AUDIT/execution-events.jsonl`:

| Event | Trigger |
|---|---|
| `GATE_STARTED` | Gate transitioned `PENDING → RUNNING` |
| `GATE_PASSED` | Gate verdict `GREEN` |
| `GATE_FAILED` | Gate verdict `RED` |
| `GATE_BLOCKED` | Gate verdict `BLOCKED` |
| `GATE_INVALIDATED` | Gate transitioned `GREEN → INVALIDATED` |

Events carry the PESE revision and state SHA-256 at the time of the transition, plus a `detail` object with validator identity or binding-failure reasons. The EEF journal's `EVENT_TYPES` frozenset is extended with these five event types in M014.

Event emission is best-effort: failures are silently swallowed to prevent logging issues from blocking gate transitions.

## 8. CLI REFERENCE

VAL commands are wired through `asc-orchestrator` with machine-readable `key=value` output and deterministic exit codes.

```
asc-orchestrator [--root <path>] validation-gates --mission-id <id>
asc-orchestrator [--root <path>] validation-start --mission-id <id> --gate-id <id>
asc-orchestrator [--root <path>] validation-finish --mission-id <id> --gate-id <id> --verdict GREEN|RED|BLOCKED [--artifact <path>] [--reason <text>]
asc-orchestrator [--root <path>] validation-verify --mission-id <id> --gate-id <id>
asc-orchestrator [--root <path>] validation-invalidate --mission-id <id> --gate-id <id>
asc-orchestrator [--root <path>] validation-report --mission-id <id>
```

| Command | Output | Exit 0 | Exit 2 |
|---|---|---|---|
| `validation-gates` | `gate_count=<n>`, then per gate: `gate_id=`, `status=`, `artifact_count=`, `verdict_at=` | Gates listed | State load error |
| `validation-start` | Standard PESE outcome (`outcome=UPDATED`, `state_revision=`, etc.) | Gate transitioned to RUNNING | Gate not pending, not found, or unauthorized |
| `validation-finish` | Standard PESE outcome | Gate transitioned to GREEN/RED/BLOCKED | Gate not running, unauthorized, or artifact errors |
| `validation-verify` | `gate_id=`, `all_match=true\|false`, per artifact: `artifact_id=`, `status=MATCH\|MISMATCH\|MISSING` | All artifacts match | One or more artifacts mismatched, missing, or state corrupt (tamper) |
| `validation-invalidate` | Standard PESE outcome | Gate INVALIDATED | Gate not GREEN, binding intact, unauthorized, or state corrupt |
| `validation-report` | `gate_count=`, per status: `green_count=`, `red_count=`, ..., `overall=PASS\|FAIL\|HOLD` | Report produced (PASS or HOLD overall) | State load error, or FAIL overall |

All commands accept `--root <path>` (default `.`) and `--actor <id>` (default `AGENT:orchestrator:local`). Mutation commands (`start`, `finish`, `invalidate`) resolve the actor to the gate's designated validator when the provided actor is not it.

Errors print `error: <code>: <detail>` with exit code 2.

## 9. ERROR HANDLING

VAL uses `VALError` (subclass of `RuntimeError`) for structured errors:

| Code | Meaning |
|---|---|
| `STATE_LOAD_FAILED` | PESE state could not be loaded (corrupt or missing) |
| `GATE_NOT_FOUND` | Gate identifier not found in validation state |
| `GATE_NOT_PENDING` | Gate is not in PENDING status for a start transition |
| `GATE_NOT_RUNNING` | Gate is not in RUNNING status for a finish transition |
| `GATE_NOT_GREEN` | Gate is not in GREEN status for invalidation |
| `ARTIFACTS_REQUIRED` | GREEN verdict requires at least one artifact |
| `ARTIFACT_NOT_FOUND` | Artifact file does not exist on disk |
| `ARTIFACT_ESCAPE` | Artifact path escapes the repository root |
| `ARTIFACT_PATH_MISSING` | Artifact descriptor has no path |
| `INVALID_VERDICT` | Verdict is not GREEN, RED, or BLOCKED |
| `UNAUTHORIZED` | Actor is not the designated validator for this gate |
| `BINDING_INTACT` | Artifact/repository binding is sound; invalidation rejected |
| `MISSION_NOT_FOUND` | Mission identifier not found in PESE state |

VAL errors are caught by the CLI `main()` function and printed as `error: <code>: <detail>` with exit code 2.

## 10. ON-DISK LAYOUT

VAL does not create its own directories. All state is persisted through existing contracts:

| Artifact | Contract | Path |
|---|---|---|
| Gate records | PESE state | `.project-os/PESE/state/live.json` (under `validation_state.gates`) |
| Artifact records | PESE state | `.project-os/PESE/state/live.json` (under `validation_state.artifacts`) |
| Validation events | EEF journal | `.project-os/AUDIT/execution-events.jsonl` |

VAL artifact files (the files referenced by artifact records) live in the repository tree outside `.project-os/` — for example `validation/qa-result.json`.

## 11. COMPATIBILITY

VAL v1.0 is compatible with:

- **PESE v1.0**: All gate transitions flow through `PESEStore.update()` with transition type `VALIDATION_GATE`. Artifact records live in PESE `validation_state.artifacts`. Actor authorization is enforced by PESE's `_validate_transition`.
- **TBE v1.0**: Gate definitions are created by TBE's `bind_manifest_to_pese()` which populates `validation_state.gates`. VAL reads and drives these gates without modifying their schema.
- **EEF v1.0**: Validation events are appended to the EEF execution journal. VAL's five gate event types are added to the EEF `EVENT_TYPES` frozenset in M014.
- **AEX v1.0**: Artifact records may be produced by agent execution, but VAL's artifact records are distinct from AEX execution results.
- **CKS v1.0**: VAL does not sign artifacts in M014; artifact integrity is protected by SHA-256 hashes in PESE state.
- **AHP v1.0**: VAL is independent of agent liveness; gate transitions are not blocked by health status.

VAL does not modify or bypass any contract in PESE, TBE, EEF, AEX, CKS, ACP, AHP, or MSS. It is an additive validation layer.

## 12. IMPLEMENTATION REQUIREMENTS

1. VAL runtime (`src/asc_orchestrator/validation.py`) must use only Python 3.11+ stdlib.
2. All state mutations must flow through `PESEStore.update()` with `transition_type="VALIDATION_GATE"`.
3. Gate transitions must follow the legal transition table; illegal transitions must raise `VALError`.
4. Artifact files must be validated against repository-root containment (no path escapes).
5. Artifact SHA-256 hashes must be computed from file bytes at registration time.
6. `verify()` must detect tampered, missing, or mismatched artifacts and provide per-artifact status.
7. `verify()` must provide raw-read fallback diagnostics when PESE state is corrupt.
8. `invalidate()` must enforce the binding-failure precondition; it must not proceed when binding is sound.
9. Tampered state must trigger a secure halt for mutations (no programmatic sweep under the rug).
10. Event emission must be best-effort; logging failures must not block gate transitions.
11. Actor resolution in the CLI must fall back to the gate's `validator_agent_id` for mutation commands.

## 13. IMPLEMENTATION GATES

VAL v1.0 is complete when:

1. `docs/VAL_v1.0.md` is ratified with all required sections (purpose, architecture, state, artifacts, verification, invalidation, events, CLI reference, error handling, layout, compatibility, requirements, implementation gates, and terminal marker).
2. `src/asc_orchestrator/validation.py` implements `ValidationEngine`, `VALError`, `GateStatus`, `ArtifactRecord`, `ArtifactVerification`, `VerificationResult`, and `ValidationReport` using only stdlib.
3. Gate lifecycle transitions (`start`, `finish`, `invalidate`) flow through `PESEStore.update()`.
4. Artifact verification compares on-disk files against recorded SHA-256 hashes.
5. Invalidation enforces binding-failure precondition per PESE spec section 5.3.
6. `verify()` provides raw-read fallback diagnostics when PESE state is corrupt.
7. Five `validation-*` CLI subcommands plus `validation-report` emit machine-readable outcomes and deterministic exit codes.
8. `tests/test_validation.py` exercises gate lifecycle, artifact verification, invalidation, tamper handling, event journal integrity, and backward compatibility.
9. `tests/test_validation_cli.py` exercises the full CLI lifecycle including tamper detection.
10. `python -m mypy` passes on `src`.
11. `python -m ruff check src tests scripts` and `ruff format --check` pass.
12. `python scripts/validate_docs.py` passes with VAL spec coverage.
13. `python -m unittest discover -s tests -t .` passes (existing + new VAL tests).

**END OF SPECIFICATION — VAL v1.0**
