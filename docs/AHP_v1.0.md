# Agent Health Protocol — AHP v1.0

## 1. PURPOSE AND SCOPE

AHP v1.0 is the deterministic local agent-health contract that tracks agent liveness so stalled or unresponsive agents can be detected. Every agent emits an append-only, hash-chained heartbeat history under `.project-os/HEALTH/`; a health evaluator derives each agent's status (`ALIVE`, `STALLED`, or `UNKNOWN`) from the freshness of its last heartbeat relative to a configurable timeout.

AHP closes the observability gap left by M012: AEX records *what* an agent produced, but nothing records *whether* the agent is still responsive. AHP supplies the liveness signal that the M016 recovery engine consumes to retry, reassign, or escalate stalled work.

**Boundary.** AHP *observes and records* agent liveness. It does not execute agent work (AEX), schedule dispatch decisions (EEF), assemble teams (TBE), intake missions (MSS), persist general state (PESE), or manage cryptographic keys (CKS). AHP heartbeats are independent of PESE state; they are a companion observability layer, not a state authority.

## 2. ARCHITECTURE AND BOUNDARY

AHP operates as a lightweight local health store layered beside the existing runtimes:

```text
+-----------------------------------------------+
|       Agents / CLI operators / drivers        |
+-----------------------------------------------+
| AHP v1.0  (this contract)                    |
|   - heartbeats, health status, stall checks  |
|   - per-agent hash-chained health journals   |
+-----------------------------------------------+
| PESE v1.0  (read-only: mission agent lists)  |
| M016 (later)  Recovery Engine consumes AHP   |
+-----------------------------------------------+
```

**Key design decisions:**

1. Heartbeats are independent of PESE state. An agent may emit a heartbeat before, during, or after a mission; health history is never blocked by PESE transition legality.
2. Each agent's heartbeat history is append-only and hash-chained (`previous_heartbeat_sha256` → `heartbeat_sha256`), mirroring the CKS signing-ledger and EEF event-journal integrity patterns.
3. Health status is derived, never stored: `ALIVE` when the last heartbeat age is within the timeout, `STALLED` when older than the timeout, and `UNKNOWN` when no heartbeat exists. Time is injected at query time so stall detection is deterministic and testable.
4. `health-report` and `health-check` read PESE state *only* to learn which agents a mission is assigned to. If the mission is unknown, the report degrades to an empty agent set (no hard failure).

## 3. HEARTBEAT RECORD

Every `heartbeat()` call appends one immutable record to the agent's journal:

```json
{
  "format": "AHP/v1.0",
  "kind": "heartbeat",
  "sequence": 3,
  "agent_id": "AGENT:developer:local",
  "mission_id": "MISSION:example",
  "assignment_id": "ASSIGNMENT:build",
  "occurred_at": "2026-08-05T04:00:00.000Z",
  "note": "working",
  "previous_heartbeat_sha256": "sha256-of-previous-record",
  "heartbeat_sha256": "sha256-of-this-record"
}
```

Record fields:

| Field | Meaning |
|---|---|
| `format` | Fixed `"AHP/v1.0"` |
| `kind` | Fixed `"heartbeat"` |
| `sequence` | Monotonic per-agent counter, starting at 1 |
| `agent_id` | Canonical agent identity emitting the heartbeat |
| `mission_id` | Optional mission scope (may be absent) |
| `assignment_id` | Optional assignment scope (may be absent) |
| `occurred_at` | UTC ISO-8601 timestamp with milliseconds, `Z` suffix |
| `note` | Optional human- or machine-readable context |
| `previous_heartbeat_sha256` | Hash of the previous record, or `null` for the first |
| `heartbeat_sha256` | SHA-256 over the canonical JSON of all other fields |

The `heartbeat_sha256` uses the canonical-JSON (`sort_keys`, compact separators) hashing pattern shared by CKS and EEF. Records are written once via atomic replace and never modified.

## 4. AGENT HEALTH MODEL

A health evaluator computes an `AgentHealth` snapshot from the tail of an agent's journal:

| Status | Condition |
|---|---|
| `ALIVE` | At least one heartbeat exists and `last_heartbeat_age <= timeout` |
| `STALLED` | At least one heartbeat exists and `last_heartbeat_age > timeout` |
| `UNKNOWN` | No heartbeat record exists |

`last_heartbeat_age` is computed at query time as `query_time - occurred_at`, where `query_time` defaults to the current UTC time and may be injected for deterministic testing. A timeout of `0` treats every heartbeat as stale (useful for probing). Negative or missing timeout values are rejected.

The snapshot exposes: `agent_id`, `last_heartbeat_at`, `heartbeat_count`, `age_seconds`, `status`, `last_mission_id`, and `last_assignment_id`.

## 5. ON-DISK LAYOUT

```
.project-os/
  HEALTH/
    agents/
      <safe_agent_id>.jsonl        # append-only hash-chained heartbeat journal
```

`<safe_agent_id>` percent-encodes reserved characters (`:` → `%3A`) using the same Windows-safe encoding as TBE and AEX. The `.project-os/HEALTH/` directory is created on first write. There is no separate index file: per-agent summaries are computed by reading each journal's tail, keeping a single source of truth.

## 6. INTEGRITY AND VALIDATION

`HealthStore.validate()` verifies, for every journal under `agents/`:

1. Every line is valid canonical JSON.
2. Every record carries a `heartbeat_sha256` equal to the SHA-256 of the canonical JSON of its other fields.
3. Every record's `previous_heartbeat_sha256` equals the `heartbeat_sha256` of the preceding record.
4. `sequence` values are strictly increasing by one.

A broken chain, malformed record, or out-of-sequence counter makes validation fail. `validate()` never mutates state.

## 7. CLI REFERENCE

AHP commands are wired through `asc-orchestrator` with machine-readable `key=value` output and deterministic exit codes.

```
asc-orchestrator [--root <path>] health-heartbeat --agent <id> [--mission-id <id>] [--assignment-id <id>] [--note <text>]
asc-orchestrator [--root <path>] health-status --agent <id> [--timeout <seconds>]
asc-orchestrator [--root <path>] health-report --mission-id <id> [--timeout <seconds>]
asc-orchestrator [--root <path>] health-check --mission-id <id> [--timeout <seconds>]
```

| Command | Output | Exit 0 | Exit 2 |
|---|---|---|---|
| `health-heartbeat` | `agent_id=<id>`, `occurred_at=<ts>`, `sequence=<n>` | Heartbeat appended | Invalid arguments |
| `health-status` | `agent_id=<id>`, `status=<S>`, `heartbeat_count=<n>`, `age_seconds=<n>\|`, `last_heartbeat_at=<ts>\|` | Snapshot produced | Invalid timeout |
| `health-report` | One `agent_id=`/`status=` block per mission agent, `agent_count=<n>` | Mission agents reported | Invalid timeout |
| `health-check` | `agent_count=<n>`, `stalled_count=<n>`, `stalled=` (JSON list) | No mission agent STALLED | At least one mission agent STALLED |

All commands accept `--root <path>` (default `.`). Exit 0 for success, exit 2 for errors. Errors print `error: <code>: <detail>`.

## 8. ERROR HANDLING

AHP uses `AHPError` (subclass of `RuntimeError`) for structured errors:

| Code | Meaning |
|---|---|
| `INVALID_TIMEOUT` | Timeout is negative, non-numeric, or otherwise unusable |
| `INVALID_AGENT` | Agent id is empty or not provided |
| `JOURNAL_CORRUPT` | A heartbeat journal is unreadable or malformed |
| `CHAIN_BROKEN` | A journal's hash chain fails verification |

AHP errors are caught by the CLI `main()` function and printed as `error: <code>: <detail>` with exit code 2.

## 9. COMPATIBILITY

AHP v1.0 is compatible with:

- **PESE v1.0**: `health-report`/`health-check` read mission `assigned_agent_ids` from PESE state (read-only). AHP never mutates PESE state and never bypasses PESE invariants.
- **AEX v1.0**: Heartbeats may carry an assignment id that matches an AEX-owned assignment, but AHP does not read or write AEX result records.
- **EEF v1.0**: Heartbeats are independent of the execution journal; AHP emits no EEF events in M013.
- **TBE v1.0**: Agent ids in heartbeats are opaque strings compatible with TEAM.md identities.
- **CKS v1.0**: AHP uses no keys in M013; heartbeats are integrity-protected by their hash chain, not by cryptographic signatures.

AHP does not modify or bypass any contract in PESE, AEX, EEF, TBE, CKS, ACP, or MSS. It is an additive observability layer.

## 10. IMPLEMENTATION REQUIREMENTS

1. AHP runtime (`src/asc_orchestrator/health.py`) must use only Python 3.11+ stdlib.
2. Heartbeat journals must be append-only and hash-chained with process-safe locking.
3. Health status must be derived at query time; no status field is persisted.
4. Records must be written via atomic write (temp + rename) with fsync.
5. Windows-safe `<safe_agent_id>` encoding must match the `%3A` scheme used by TBE/AEX.
6. `validate()` must be read-only and detect chain breaks, malformed JSON, and out-of-sequence counters.
7. Time must be injectable at query time for deterministic stall detection.

## 11. IMPLEMENTATION GATES

AHP v1.0 is complete when:

1. `docs/AHP_v1.0.md` is ratified with all required sections (purpose, architecture, heartbeat record, health model, layout, integrity, CLI reference, error handling, compatibility, requirements, implementation gates, and terminal marker).
2. `src/asc_orchestrator/health.py` implements `HealthStore`, `AHPError`, and supporting types using only stdlib.
3. Heartbeat records are append-only, hash-chained, atomically written, and immutable.
4. Health status (`ALIVE`/`STALLED`/`UNKNOWN`) is derived from last-heartbeat age against a configurable timeout with injectable query time.
5. `validate()` detects chain breaks, malformed records, and sequence violations without mutating state.
6. Four `health-*` CLI subcommands emit machine-readable outcomes and deterministic exit codes.
7. `tests/test_health.py` exercises heartbeat append, chain integrity, tamper detection, status derivation, timeout handling, and validation.
8. `tests/test_health_cli.py` exercises the CLI lifecycle including the STALLED exit-2 path.
9. `python -m mypy` passes on `src`.
10. `python -m ruff check src tests scripts` and `ruff format --check` pass.
11. `python scripts/validate_docs.py` passes with AHP spec coverage.
12. `python -m unittest discover -s tests -t .` passes (existing + new AHP tests).

**END OF SPECIFICATION — AHP v1.0**
