# Risk Management — RKM v1.0

## 1. PURPOSE AND SCOPE

RKM v1.0 is the deterministic risk-management runtime that operates the risk ledger over PESE `risk_state`, enforces the RKM-level status state machine, and implements the hold mechanism that blocks autonomous execution on unresolved HALT / CRITICAL / HIGH-with-block-condition risks. Every state mutation flows through `PESEStore.update()` with transition type `RISK_STATUS`; RKM never bypasses PESE invariants.

RKM closes the gap between execution (AEX) and autonomous scheduling (AWS M019): without a risk ledger and hold mechanism, the scheduler cannot evaluate whether autonomous execution is safe. The RKM `risk-check` command is the gate that M019 and M020 consume before allowing unattended dispatch.

**Boundary.** RKM operates the risk ledger and hold mechanism. It does not execute agent work (AEX), assemble teams (TBE), intake missions (MSS), persist general state (PESE), manage keys (CKS), observe liveness (AHP), drive validation gates (VAL), or schedule dispatch (EEF). RKM reads PESE state to evaluate blocking conditions and writes risk records via PESE `RISK_STATUS` transitions.

## 2. ARCHITECTURE AND BOUNDARY

RKM operates as a deterministic risk-management runtime layered on top of the existing runtimes:

```text
+-----------------------------------------------+
|     Operators / CLI / M019 scheduler / AEX    |
+-----------------------------------------------+
| RKM v1.0  (this contract)                     |
|   - risk lifecycle, blocking evaluation        |
|   - RISK_* events to EEF journal              |
+-----------------------------------------------+
| PESE v1.0  (read/write: risk_state)           |
| EEF v1.0   (append: execution events)         |
| ACR v1.0   (read-only: owner validation)      |
+-----------------------------------------------+
```

**Key design decisions:**

1. All state mutations flow through `PESEStore.update()` with transition type `RISK_STATUS`. RKM never writes PESE state directly; it relies on the store's legal-transition enforcement and actor authorization.
2. RKM enforces its own status state machine (`OPEN → {MITIGATING, ACCEPTED, RESOLVED, HALT}`, `MITIGATING → RESOLVED`) because `RISK_STATUS` is not in PESE's legal-transition map (the same pattern used by EEF's `MISSION_INTERRUPT_RECOVERY` and VAL's `VALIDATION_GATE`).
3. Block conditions for HIGH risks are stored under the `extensions["org.asc.rkm"]` reverse-DNS key, not in the risk record itself, because the PESE risk record contract requires exactly 9 fields (section 4.7).
4. Company-wide risks (`mission_id=None`) block all missions; mission-scoped risks block only their designated mission.
5. Event emission is best-effort: `_emit_event` swallows exceptions to prevent journal failures from blocking risk mutations.

## 3. RISK RECORD SCHEMA

Each risk is a 9-field record stored in `risk_state.risks` under its `risk_id` key. The canonical schema is defined by PESE v1.0 section 4.7:

```json
{
  "risk_id": "RISK:MISSION:example:001",
  "status": "OPEN",
  "severity": "MEDIUM",
  "description": "Upstream dependency may be discontinued",
  "mission_id": "MISSION:example",
  "evidence_refs": ["EVIDENCE:analysis-001"],
  "owner_agent_id": "AGENT:developer:abc",
  "opened_at": "2026-08-05T04:00:00.000Z",
  "resolved_at": null
}
```

**Risk record fields:**

| Field | Meaning |
|---|---|
| `risk_id` | Canonical risk identifier, unique across all missions |
| `status` | Current status (see vocabulary below) |
| `severity` | Risk severity level |
| `description` | Human-readable risk description |
| `mission_id` | Owning mission identifier, or `null` for company-wide risks |
| `evidence_refs` | Evidence references supporting the risk assessment |
| `owner_agent_id` | Agent authorized to manage this risk |
| `opened_at` | UTC timestamp when the risk was opened |
| `resolved_at` | UTC timestamp when the risk was resolved, or `null` |

**Risk status vocabulary:**

| Status | Meaning |
|---|---|
| `OPEN` | Risk is active and unresolved |
| `MITIGATING` | Risk is being actively mitigated |
| `ACCEPTED` | Risk has been accepted (no mitigation planned) |
| `RESOLVED` | Risk has been resolved with evidence |
| `HALT` | Risk halts autonomous execution |

**Severity vocabulary:**

| Severity | Meaning |
|---|---|
| `LOW` | Minor risk, no blocking |
| `MEDIUM` | Moderate risk, no blocking |
| `HIGH` | Significant risk; blocks only when a block condition is declared |
| `CRITICAL` | Resolved only by RESOLVED or ACCEPTED status; always blocks when open |

**Legal transitions:**

| From | To |
|---|---|
| `OPEN` | `MITIGATING`, `ACCEPTED`, `RESOLVED`, `HALT` |
| `MITIGATING` | `RESOLVED` |

## 4. HOLD MECHANISM — BLOCKING EVALUATION

The hold mechanism evaluates whether autonomous execution is blocked per PESE section 4.7. It is implemented by `RiskEngine.check()`.

**Blocking conditions (any one triggers the hold):**

1. **HALT risk.** Any risk with `status == "HALT"` blocks — regardless of severity.
2. **Unresolved CRITICAL risk.** Any risk with `severity == "CRITICAL"` and `status not in {"RESOLVED", "ACCEPTED"}` blocks.
3. **HIGH risk with declared block condition.** Any risk with `severity == "HIGH"` whose block condition is declared in the `org.asc.rkm` extension blocks.

**Mission scoping:**

- When `mission_id` is provided, only risks where `risk.mission_id == requested OR risk.mission_id is None` are evaluated. Company-wide risks (`mission_id=None`) block all missions.
- When `mission_id` is omitted, all risks are evaluated (no filtering).

**Block condition storage:**

Block conditions for HIGH risks are stored in the `extensions["org.asc.rkm"]` section:

```json
{
  "extensions": {
    "org.asc.rkm": {
      "RISK:example:001": {
        "block_condition": {
          "declared": true,
          "description": "deploy gate pending",
          "declared_at": "2026-08-05T04:00:00.000Z",
          "declared_by": "AGENT:developer:abc"
        }
      }
    }
  }
}
```

## 5. RISK LIFECYCLE

Risks progress through a deterministic lifecycle:

```
OPEN ──► MITIGATING ──► RESOLVED
  │                        ▲
  ├──► ACCEPTED            │
  │                        │
  ├──► HALT                │
  │                        │
  └────────────────────────┘
```

**Transitions:**

| Command | From Status | To Status | Sets `resolved_at` |
|---|---|---|---|
| `risk-open` | — (creates) | `OPEN` | No |
| `risk-mitigate` | `OPEN` | `MITIGATING` | No |
| `risk-accept` | `OPEN` | `ACCEPTED` | No |
| `risk-resolve` | `OPEN`, `MITIGATING` | `RESOLVED` | Yes |
| `risk-halt` | `OPEN` | `HALT` | No |

## 6. EVENT JOURNAL

Every risk mutation emits an event to the EEF execution journal (hash-chained `execution-events.jsonl`). Events use the `RISK_*` event types registered in the EEF `EVENT_TYPES` frozenset:

| Transition | Event Type |
|---|---|
| `OPEN` (creation) | `RISK_OPENED` |
| `OPEN → MITIGATING` | `RISK_MITIGATED` |
| `OPEN → ACCEPTED` | `RISK_ACCEPTED` |
| `OPEN/MITIGATING → RESOLVED` | `RISK_RESOLVED` |
| `OPEN → HALT` | `RISK_HALTED` |

Event emission is best-effort: exceptions are swallowed so journal failures never block risk mutations. The journal event includes `severity` and `description` in the `detail` field.

## 7. CLI REFERENCE

All commands accept `--root <path>` (default: current directory) and emit machine-readable `key=value` output to stdout. Deterministic exit codes: 0 for success, 2 for error or hold.

| Command | Description | Exit 2 on |
|---|---|---|
| `risk-open` | Register a new OPEN risk | invalid severity, duplicate risk_id, empty risk_id |
| `risk-list` | List risks (optionally mission-scoped) | — |
| `risk-status` | Read a single risk snapshot | risk not found |
| `risk-mitigate` | Transition OPEN → MITIGATING | risk not in OPEN status |
| `risk-accept` | Transition OPEN → ACCEPTED | risk not in OPEN status |
| `risk-resolve` | Resolve an OPEN/MITIGATING risk | risk not in OPEN/MITIGATING status |
| `risk-halt` | Transition OPEN → HALT (blocks execution) | risk not in OPEN status |
| `risk-check` | Hold-mechanism evaluation | autonomous execution is blocked |
| `risk-report` | Mission-level risk summary | — |

**Arguments:**

- `risk-open`: `--risk-id` (required), `--severity` (required, one of LOW/MEDIUM/HIGH/CRITICAL), `--description` (required), `--mission-id` (optional, default: company-wide), `--owner` (optional, default: AGENT:orchestrator:local), `--evidence` (repeatable), `--block-condition` (optional, HIGH risks only).
- `risk-list`: `--mission-id` (optional), `--actor` (optional).
- `risk-status`: `--risk-id` (required), `--actor` (optional).
- `risk-mitigate`, `risk-accept`: `--risk-id` (required), `--actor` (optional).
- `risk-resolve`: `--risk-id` (required), `--evidence` (repeatable), `--actor` (optional).
- `risk-halt`: `--risk-id` (required), `--reason` (required), `--actor` (optional).
- `risk-check`: `--mission-id` (optional), `--actor` (optional).
- `risk-report`: `--mission-id` (optional), `--actor` (optional).

## 8. ERROR HANDLING

| Error Code | When |
|---|---|
| `INVALID_SEVERITY` | Severity not in {LOW, MEDIUM, HIGH, CRITICAL} |
| `INVALID_RISK_ID` | Empty risk_id string |
| `DUPLICATE_RISK_ID` | risk_id already exists in risk_state |
| `RISK_NOT_FOUND` | Requested risk_id does not exist |
| `RISK_NOT_OPEN` | Mutation requires OPEN status but risk has a different status |
| `INVALID_TRANSITION` | resolve requires OPEN or MITIGATING but status is different |
| `STATE_LOAD_FAILED` | PESE state could not be loaded or is missing revision/sha256 |

## 9. ON-DISK LAYOUT

RKM state is persisted within PESE's canonical layout:

```
.project-os/
├── PESE/
│   ├── live.json          ← risk_state.risks + extensions["org.asc.rkm"]
│   └── ...
└── AUDIT/
    └── execution-events.jsonl   ← RISK_* events appended here
```

Block conditions live in `state.extensions["org.asc.rkm"][risk_id].block_condition`. Risk records live in `state.risk_state.risks[risk_id]`.

## 10. COMPATIBILITY

RKM v1.0 is additive — it adds risk records and block conditions to existing PESE state without modifying any prior contract. Existing PESE, TBE, EEF, AEX, CKS, AHP, and VAL commands continue to work unchanged.

The `RISK_STATUS` transition type is not in PESE's legal-transition map; RKM enforces its own state machine (same pattern as EEF's `MISSION_INTERRUPT_RECOVERY` and VAL's `VALIDATION_GATE`).

## 11. IMPLEMENTATION REQUIREMENTS

1. `src/asc_orchestrator/risk.py` must implement `RiskEngine`, `RiskError`, `RiskRecord`, `BlockingRisk`, `RiskCheck`, and `RiskReport` using only stdlib.
2. All state mutations must flow through `PESEStore.update()` with `transition_type="RISK_STATUS"`.
3. Blocking evaluation must implement the three blocking rules from PESE section 4.7 (HALT, unresolved CRITICAL, HIGH with block condition).
4. Mission scoping must include company-wide risks (`mission_id=None`) in all mission-filtered evaluations.
5. Event emission must use `EEFEventJournal.append()` with the five `RISK_*` event types.
6. Block conditions must be stored under `extensions["org.asc.rkm"]`, not in the risk record.

## 12. IMPLEMENTATION GATES

RKM v1.0 is complete when:

1. `docs/RKM_v1.0.md` is ratified with all required sections (purpose, architecture, schema, hold mechanism, lifecycle, events, CLI reference, error handling, layout, compatibility, requirements, implementation gates, and terminal marker).
2. `src/asc_orchestrator/risk.py` implements `RiskEngine`, `RiskError`, `RiskRecord`, `BlockingRisk`, `RiskCheck`, and `RiskReport` using only stdlib.
3. Risk mutations flow through `PESEStore.update()` with `transition_type="RISK_STATUS"`.
4. Blocking evaluation implements HALT, unresolved CRITICAL, and HIGH-with-block-condition rules.
5. Five `RISK_*` event types are registered in EEF's `EVENT_TYPES` frozenset.
6. Nine `risk-*` CLI subcommands emit machine-readable outcomes and deterministic exit codes.
7. `tests/test_risk.py` exercises all risk transitions, blocking evaluation, mission scoping, event journal integrity, and backward compatibility.
8. `tests/test_risk_cli.py` exercises the full CLI lifecycle including hold-mechanism exit codes.
9. `python -m mypy` passes on `src`.
10. `python -m ruff check src tests scripts` and `ruff format --check` pass.
11. `python scripts/validate_docs.py` passes with RKM spec coverage.
12. `python -m pytest tests/ -q` passes (existing + new RKM tests).

**END OF SPECIFICATION — RKM v1.0**
