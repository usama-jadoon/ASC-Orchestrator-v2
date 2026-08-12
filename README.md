# ASC Orchestrator v2

Autonomous Software Company Orchestrator - Version 2

A professional open-source repository serving as the permanent Global Software Company Operating System.

## Mission

To establish a foundation for autonomous software company operations through a modular, extensible CLI-based orchestration system.

## Repository Structure

This repository serves as the foundation for the ASC Orchestrator v2, containing:

- Python runtime foundation for ACP v1.0 and ACR v1.0 validation
- Canonical PESE v1.0 specification for persistent mission, execution, validation, risk, agent, repository, and checkpoint state
- PESE v1.0 runtime for atomic state history, checkpoints, integrity validation, deterministic resume, locking, recovery, and migration records
- TBE v1.0 deterministic assembly runtime for specialist selection, ownership, dependency graphs, validation interfaces, and canonical team manifests
- EEF v1.0 execution runtime for deterministic mission lifecycle management (start, schedule, pause, resume, cancel, complete) with a hash-chained execution event journal
- CKS v1.0 cryptographic key service for HMAC-SHA256 key lifecycle, signing/verification, and a hash-chained signing ledger for production audit attestation
- AEX v1.0 agent execution runtime for claiming dispatched assignments, persisting work-product artifacts, and signing execution attestations via CKS
- AHP v1.0 agent health runtime for append-only, hash-chained heartbeat journals that derive ALIVE, STALLED, and UNKNOWN liveness status
- VAL v1.0 validation runtime for driving PESE validation gates through their lifecycle, registering SHA-256-bound artifacts, and emitting gate verdicts to the EEF execution journal
- RKM v1.0 risk-management runtime for operating the PESE risk ledger, enforcing the risk status state machine, and implementing the hold mechanism that blocks autonomous execution on HALT / unresolved CRITICAL / declared HIGH block conditions
- AGC v1.0 agent-lifecycle runtime for operating the PESE agent ledger, enforcing the agent status state machine, dependency environment verification, and the registration → release lifecycle with `AGENT_*` events to the EEF journal
- REC v1.0 recovery runtime for deterministic agent recovery — a single `recovery-run` that automates quarantine → release → register replacement → activate → dependency VERIFIED → ready → claim when an agent fails or stalls, with a durable recovery ledger over PESE `recovery_state` and `RECOVERY_*` events to the EEF journal
- ETR v1.0 encrypted-transport runtime for deterministic symmetric authenticated encryption — RFC 8439 ChaCha20-Poly1305 AEAD sealing of ACP payloads and artifact files into tamper-evident envelopes over PESE `transport_state`, with CKS key binding and `ETR_*` events to the EEF journal
- AWS v1.0 autonomous workflow scheduler — the deterministic top-level orchestration runtime that evaluates full system state (consuming PESE, EEF, AGC, AHP, REC, RKM, VAL, CKS, and ETR) and produces one prioritized scheduling decision per tick, delegating actionable decisions to the owning runtime and persisting durable cycle records under the `org.asc.aws` PESE extension with `SCHEDULER_*` events to the EEF journal
- REL v1.0 production-release verifier — a deterministic, stdlib-only release gate that certifies packaging metadata (version 1.0.1, dependency-free wheel contract, `src/` layout), canonical contract coverage, runtime module importability, and per-contract test suite presence, with a machine-readable `release` command output
- Local configuration and CLI validation commands
- JSON ACR department registry entries and deterministic registry loading
- Standard-library automated tests
- GitHub community files (CONTRIBUTING, ISSUE_TEMPLATES, etc.)

## Local development

Python 3.11 or later is required. No third-party runtime dependencies are needed.

```powershell
python -m unittest discover -s tests -t . -v
$env:PYTHONPATH = "src"
python -m asc_orchestrator --root . config
python -m asc_orchestrator --root . registry
python -m asc_orchestrator --root . state --initialize
python -m asc_orchestrator --root . state
python -m asc_orchestrator --root . validate-state
python -m asc_orchestrator --root . resume
python -m asc_orchestrator --root . checkpoint --mission-id MISSION:example
python -m asc_orchestrator --root . team-build --mission mission.json --classification classification.json
python -m asc_orchestrator --root . validate-mission --file mission.json
python -m asc_orchestrator --root . execution-start --mission-id MISSION:example
python -m asc_orchestrator --root . execution-status --mission-id MISSION:example
python -m asc_orchestrator --root . execution-schedule --mission-id MISSION:example
python -m asc_orchestrator --root . execution-pause --mission-id MISSION:example
python -m asc_orchestrator --root . execution-resume --mission-id MISSION:example
python -m asc_orchestrator --root . execution-cancel --mission-id MISSION:example
python -m asc_orchestrator --root . execution-complete --mission-id MISSION:example
python -m asc_orchestrator --root . key-create --actor AGENT:orchestrator:local --purpose "audit signing"
python -m asc_orchestrator --root . key-list
python -m asc_orchestrator --root . key-sign --key-id KEY-... --file checkpoint.json
python -m asc_orchestrator --root . key-verify --key-id KEY-... --file checkpoint.json --signature <hex>
python -m asc_orchestrator --root . key-rotate --key-id KEY-... --actor AGENT:orchestrator:local
python -m asc_orchestrator --root . key-revoke --key-id KEY-... --actor AGENT:orchestrator:local
python -m asc_orchestrator --root . key-validate
python -m asc_orchestrator --root . aex-dispatch --mission-id MISSION:example --assignment-id ASSIGNMENT:build --actor AGENT:developer:local
python -m asc_orchestrator --root . aex-complete --mission-id MISSION:example --assignment-id ASSIGNMENT:build --actor AGENT:developer:local --output "work done" --artifact report.md --key-id KEY-...
python -m asc_orchestrator --root . aex-fail --mission-id MISSION:example --assignment-id ASSIGNMENT:build --actor AGENT:developer:local --reason "gate failed"
python -m asc_orchestrator --root . aex-block --mission-id MISSION:example --assignment-id ASSIGNMENT:build --actor AGENT:developer:local --reason "waiting on input"
python -m asc_orchestrator --root . aex-unblock --mission-id MISSION:example --assignment-id ASSIGNMENT:build --actor AGENT:developer:local
python -m asc_orchestrator --root . aex-status --mission-id MISSION:example --assignment-id ASSIGNMENT:build
python -m asc_orchestrator --root . aex-result --mission-id MISSION:example --assignment-id ASSIGNMENT:build
python -m asc_orchestrator --root . health-heartbeat --agent AGENT:developer:local --mission-id MISSION:example --assignment-id ASSIGNMENT:build --note "starting work"
python -m asc_orchestrator --root . health-status --agent AGENT:developer:local --timeout 300
python -m asc_orchestrator --root . health-report --mission-id MISSION:example --timeout 300
python -m asc_orchestrator --root . health-check --mission-id MISSION:example --timeout 300
python -m asc_orchestrator --root . validation-gates --mission-id MISSION:example
python -m asc_orchestrator --root . validation-start --mission-id MISSION:example --gate-id GATE:MISSION:example:functional
python -m asc_orchestrator --root . validation-finish --mission-id MISSION:example --gate-id GATE:MISSION:example:functional --verdict GREEN --artifact validation/qa-result.json
python -m asc_orchestrator --root . validation-verify --mission-id MISSION:example --gate-id GATE:MISSION:example:functional
python -m asc_orchestrator --root . validation-invalidate --mission-id MISSION:example --gate-id GATE:MISSION:example:functional
python -m asc_orchestrator --root . validation-report --mission-id MISSION:example
python -m asc_orchestrator --root . risk-open --risk-id RISK:MISSION:example:001 --severity HIGH --description "deploy gate pending" --mission-id MISSION:example --block-condition "deploy gate pending"
python -m asc_orchestrator --root . risk-list
python -m asc_orchestrator --root . risk-status --risk-id RISK:MISSION:example:001
python -m asc_orchestrator --root . risk-mitigate --risk-id RISK:MISSION:example:001
python -m asc_orchestrator --root . risk-accept --risk-id RISK:MISSION:example:001
python -m asc_orchestrator --root . risk-resolve --risk-id RISK:MISSION:example:001
python -m asc_orchestrator --root . risk-halt --risk-id RISK:MISSION:example:001 --reason "investigation"
python -m asc_orchestrator --root . risk-check --mission-id MISSION:example
python -m asc_orchestrator --root . risk-report --mission-id MISSION:example
python -m asc_orchestrator --root . agent-register --agent AGENT:developer:local --acr-ref ACR:developer:specialist
python -m asc_orchestrator --root . agent-activate --agent AGENT:developer:local
python -m asc_orchestrator --root . agent-dependency --agent AGENT:developer:local --dep-status VERIFIED --tool python=3.11
python -m asc_orchestrator --root . agent-ready --agent AGENT:developer:local
python -m asc_orchestrator --root . agent-claim --agent AGENT:developer:local --mission-id MISSION:example --assignment-id ASSIGNMENT:build
python -m asc_orchestrator --root . agent-complete --agent AGENT:developer:local
python -m asc_orchestrator --root . agent-block --agent AGENT:developer:local --reason "waiting on input"
python -m asc_orchestrator --root . agent-unblock --agent AGENT:developer:local
python -m asc_orchestrator --root . agent-fail --agent AGENT:developer:local --reason "gate failed"
python -m asc_orchestrator --root . agent-quarantine --agent AGENT:developer:local --reason "diagnosis"
python -m asc_orchestrator --root . agent-replace --agent AGENT:developer:local --reason "replacing"
python -m asc_orchestrator --root . agent-release --agent AGENT:developer:local
python -m asc_orchestrator --root . agent-heartbeat --agent AGENT:developer:local
python -m asc_orchestrator --root . agent-checkpoint --agent AGENT:developer:local --checkpoint-id CHECKPOINT:...
python -m asc_orchestrator --root . agent-list
python -m asc_orchestrator --root . agent-status --agent AGENT:developer:local
python -m asc_orchestrator --root . agent-report
python -m asc_orchestrator --root . recovery-diagnose --agent AGENT:developer:local
python -m asc_orchestrator --root . recovery-run --agent AGENT:developer:local
python -m asc_orchestrator --root . recovery-status --recovery-id RECOVERY:0001
python -m asc_orchestrator --root . recovery-list
python -m asc_orchestrator --root . recovery-report
python -m asc_orchestrator --root . key-create --actor AGENT:orchestrator:local --purpose "transport"
python -m asc_orchestrator --root . etr-bind-channel --from AGENT:sender:local --to AGENT:receiver:local --key-id KEY-... --actor AGENT:orchestrator:local
python -m asc_orchestrator --root . etr-channel --channel-id CHANNEL-... --actor AGENT:orchestrator:local
python -m asc_orchestrator --root . etr-list-channels
python -m asc_orchestrator --root . etr-seal --file secret.txt --key-id KEY-... --message-type ACP --from AGENT:sender:local --to AGENT:receiver:local --mission-id MISSION:example
python -m asc_orchestrator --root . etr-open --envelope secret.txt.etr --output revealed.txt
python -m asc_orchestrator --root . etr-list-envelopes
python -m asc_orchestrator --root . etr-revoke-channel --channel-id CHANNEL-...
python -m asc_orchestrator --root . etr-report
python -m asc_orchestrator --root . scheduler-tick
python -m asc_orchestrator --root . scheduler-status
python -m asc_orchestrator --root . scheduler-enable
python -m asc_orchestrator --root . scheduler-disable
python -m asc_orchestrator --root . scheduler-cycle --cycle-id CYCLE:00001
python -m asc_orchestrator --root . scheduler-list
python -m asc_orchestrator --root . scheduler-report
python -m asc_orchestrator --root . release
```

`asc-orchestrator.toml` is the canonical local runtime configuration. ACP audit records are written beneath `.project-os/AUDIT/`; ACR entries are loaded from `.project-os/COMPANY/DEPARTMENTS/`.

PESE persists only beneath `.project-os/PESE/`. `state --initialize` creates the required layout and revision 1; all normal state changes belong to the typed PESE runtime API, so the CLI `checkpoint` command deliberately creates only a `MANUAL` checkpoint. `resume` is read-only. Every state command emits a structured outcome, including its operation ID and non-secret integrity findings.

PESE is specified in [PESE v1.0](./docs/PESE_v1.0.md), which remains the canonical contract. Validate a checkout with:

```powershell
python -m unittest discover -s tests -t . -v
python -m mypy
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python scripts/validate_docs.py
```

TBE is specified in [TBE v1.0](./docs/TBE_v1.0.md). `team-build` accepts an explicit mission-contract JSON object and a repository-classification JSON array, selects only registered ACR specialists, and writes canonical `TEAM.md` under `.project-os/COMPANY/TEAMS/`. The literal `TEAM:<mission-id>:<sequence>` remains inside the manifest; its filesystem directory reversibly encodes `:` as `%3A` for Windows compatibility. Use `--assembled-at <ISO-8601-UTC>` when a reproducible byte-identical manifest is required; otherwise the required assembly timestamp records the current assembly event. Add `--bind-state` only after PESE has been initialized to register the validated manifest as planned mission state; this does not execute agents or start work.

MSS is specified in [MSS v1.0](./docs/MSS_v1.0.md). `validate-mission` accepts an MSS v1.0 mission-specification JSON file, parses it structurally, and reports semantic validation findings for mission type, class, priority, validation gates, authority scope, baseline gates, acceptance criteria, constraints, and extension keys. It returns exit code 0 when the mission validates (with at most warning findings) and exit code 2 for structural or error-severity failures.

EEF is specified in [EEF v1.0](./docs/EEF_v1.0.md). The execution commands drive a PESE-bound, TBE-assigned mission through its lifecycle: `execution-start` activates a planned mission and its root assignments, `execution-schedule` computes the deterministic FIFO dispatch decision, `execution-pause`/`execution-resume` interrupt and recover a mission, `execution-cancel` terminates it, `execution-complete` advances it to VALIDATING, and `execution-status` reads the lifecycle snapshot. All state changes flow through PESE's audited transition API, and every event is appended to the hash-chained journal at `.project-os/AUDIT/execution-events.jsonl`. EEF schedules and dispatches work; it does not execute agents.

CKS is specified in [CKS v1.0](./docs/CKS_v1.0.md). The `key-*` commands manage a deterministic, stdlib-only HMAC-SHA256 key lifecycle: `key-create` generates a 256-bit key and persists an immutable record, `key-rotate` retires an active key and creates its replacement, `key-revoke` permanently disables an active key, `key-sign` produces an HMAC-SHA256 signature and records it in a hash-chained signing ledger, `key-verify` performs constant-time signature verification, `key-list` enumerates all keys, and `key-validate` checks key record integrity, fingerprints, and ledger chains. Keys live under `.project-os/KEYS/` and never read or mutate PESE, ACP, TBE, MSS, or EEF state.

AEX is specified in [AEX v1.0](./docs/AEX_v1.0.md). The `aex-*` commands execute the agent work that EEF dispatches: `aex-dispatch` claims a READY assignment and transitions it to IN_PROGRESS, `aex-complete` finishes an IN_PROGRESS assignment by persisting an immutable execution result record (optionally copying artifacts and signing the record via `--key-id` with CKS), `aex-fail` marks a failed assignment terminal, `aex-block`/`aex-unblock` gate an assignment on a precondition, `aex-status` reads the assignment lifecycle snapshot, and `aex-result` loads the persisted execution result record. Result records and copied artifacts live beneath `.project-os/ARTIFACTS/` with IDs percent-encoded for Windows compatibility, and every transition emits an agent-owned event to the EEF execution journal. AEX executes and attests local agent work; it does not schedule, assemble teams, or manage keys.

AHP is specified in [AHP v1.0](./docs/AHP_v1.0.md). The `health-*` commands observe agent liveness: `health-heartbeat` appends a hash-chained heartbeat to an agent's journal, `health-status` derives the ALIVE/STALLED/UNKNOWN status from the freshness of the last heartbeat against a configurable timeout, `health-report` lists the per-agent status for every agent assigned to a mission, and `health-check` exits 2 when any mission agent is STALLED (a signal the M016 recovery engine consumes). Heartbeat journals live beneath `.project-os/HEALTH/agents/` with IDs percent-encoded for Windows compatibility. AHP observes liveness only; it does not execute work, schedule dispatch, or persist general state.

VAL is specified in [VAL v1.0](./docs/VAL_v1.0.md). The `validation-*` commands drive PESE validation gates through their lifecycle: `validation-gates` lists the gates for a mission, `validation-start` transitions a PENDING gate to RUNNING, `validation-finish` records a GREEN/RED/BLOCKED verdict (binding validation artifacts by SHA-256 when GREEN), `validation-verify` compares bound artifact files against their recorded hashes (detecting tampering or deletion), `validation-invalidate` revokes a GREEN verdict when its artifact/repository binding fails, and `validation-report` aggregates a mission's gate status into a PASS/FAIL/HOLD overall. Every gate transition flows through PESE's audited transition API with type `VALIDATION_GATE`, and each verdict emits a `GATE_*` event to the EEF execution journal. Tampered artifacts are a secure halt for mutations; artifact integrity is protected by SHA-256 hashes in PESE state. VAL drives gates and verifies artifacts; it does not execute work, assemble teams, or schedule dispatch.

RKM is specified in [RKM v1.0](./docs/RKM_v1.0.md). The `risk-*` commands operate the deterministic risk ledger over PESE `risk_state`: `risk-open` registers an OPEN risk record, `risk-list`/`risk-status` read risk snapshots (optionally mission-scoped), `risk-mitigate`/`risk-accept`/`risk-resolve`/`risk-halt` transition risks along the OPEN → MITIGATING/ACCEPTED/RESOLVED/HALT state machine, `risk-check` evaluates the hold mechanism (exiting 2 when any HALT risk, unresolved CRITICAL risk, or HIGH risk with a declared block condition blocks autonomous execution), and `risk-report` aggregates a mission-level risk summary. Every risk mutation flows through PESE's audited transition API with type `RISK_STATUS`, and each transition emits a `RISK_*` event to the EEF execution journal. Block conditions for HIGH risks live under the `org.asc.rkm` extension key. RKM operates the risk ledger and hold mechanism; it does not execute work, assemble teams, or schedule dispatch.

AGC is specified in [AGC v1.0](./docs/AGC_v1.0.md). The `agent-*` commands operate the deterministic agent-lifecycle ledger over PESE `agent_state`: `agent-register` creates an agent record in INITIALIZING status, `agent-activate` transitions it to REGISTERED, `agent-dependency` records the 4-field dependency environment state (VERIFIED/MISSING/MISMATCH/UNKNOWN), `agent-ready` transitions REGISTERED → READY only after dependencies verify, `agent-claim`/`agent-complete` claim and release an agent on a mission/assignment, `agent-block`/`agent-unblock` gate an agent on a precondition, `agent-fail`/`agent-quarantine` record interruption state, `agent-replace` transitions a failed/quarantined agent to REPLACED, `agent-release` retires an agent, `agent-heartbeat`/`agent-checkpoint` update liveness and checkpoint references, and `agent-list`/`agent-status`/`agent-report` read lifecycle snapshots. Every agent mutation flows through PESE's audited transition API with type `AGENT_STATUS`, and each transition emits an `AGENT_*` event to the EEF execution journal. Actor authority requires the orchestrator or the agent itself. AGC operates the agent lifecycle ledger; it does not execute work, schedule dispatch, assemble teams, or persist general state.

REC is specified in [REC v1.0](./docs/REC_v1.0.md). The `recovery-*` commands automate the deterministic agent-recovery sequence over PESE `recovery_state`: `recovery-diagnose` runs a read-only pre-flight assessment deriving the recovery trigger (FAILED / QUARANTINED from AGC status, STALLED from AHP liveness), `recovery-run` orchestrates quarantine → release → register replacement → activate → dependency VERIFIED → ready → claim (skipping claim when no assignment exists) and persists a durable recovery ledger record, `recovery-status` reads a single recovery record, `recovery-list` enumerates recovery records (optionally mission-, agent-, or status-filtered), and `recovery-report` aggregates the recovery ledger. Every recovery-ledger mutation flows through PESE's audited transition API with type `RECOVERY_STATUS` (a mandatory FAILURE checkpoint only when a recovery FAILS), and each transition emits a `RECOVERY_*` event to the EEF execution journal. REC orchestrates recovery by calling AGC lifecycle transitions and reading AHP liveness; it does not define new lifecycle states, execute work, assemble teams, or schedule dispatch.

ETR is specified in [ETR v1.0](./docs/ETR_v1.0.md). The `etr-*` commands provide a deterministic symmetric authenticated-encryption runtime over PESE `transport_state`: `etr-bind-channel` binds an ACTIVE transport channel to a CKS key (the ACP session key), `etr-revoke-channel` permanently revokes an ACTIVE channel, `etr-channel`/`etr-list-channels` read channel snapshots (optionally from/to/status-filtered), `etr-seal` encrypts a payload file into a ChaCha20-Poly1305 envelope (exactly one of `--key-id` or `--channel-id`; channel-based sealing resolves sender, recipient, and key from the channel), `etr-open` authenticates and opens an envelope by PESE id or `.etr` JSON file, writing plaintext on success and flipping the record to AUTH_FAILED when the Poly1305 tag rejects tampering, `etr-list-envelopes` enumerates envelopes (optionally key/message-type/status-filtered), and `etr-report` aggregates channel and envelope statistics. Every channel and envelope mutation flows through PESE's audited transition API with type `TRANSPORT_STATUS`, and each transition emits an `ETR_*` event (`ETR_CHANNEL_BOUND`, `ETR_CHANNEL_REVOKED`, `ETR_SEALED`, `ETR_UNSEALED`, `ETR_AUTH_FAILED`) to the EEF execution journal. ETR uses a pure-Python, stdlib-only RFC 8439 ChaCha20-Poly1305 implementation with the envelope header bound as authenticated data, so any metadata or ciphertext tampering fails at open time. ETR seals and transports payloads; it does not generate or rotate keys (CKS owns those), execute work, assemble teams, or schedule dispatch.

AWS is specified in [AWS v1.0](./docs/AWS_v1.0.md). The `scheduler-*` commands operate the deterministic top-level orchestration runtime over PESE `extensions["org.asc.aws"]`: `scheduler-tick` evaluates the full system state once and produces exactly one prioritized scheduling decision (HOLD, RECOVER, START_MISSION, DISPATCH, VALIDATE, COMPLETE_MISSION, MONITOR_HEALTH, or IDLE), executing actionable decisions via the owning runtime and persisting a durable cycle record, `scheduler-enable`/`scheduler-disable` toggle whether actionable decisions are executed, `scheduler-status` reads the current scheduler snapshot, `scheduler-cycle` reads a single cycle record, `scheduler-list` enumerates cycle records, and `scheduler-report` aggregates cycle statistics. Every scheduler state mutation flows through PESE's audited transition API with type `SCHEDULER_STATUS`, and each tick/toggle emits a `SCHEDULER_*` event (`SCHEDULER_ENABLED`, `SCHEDULER_DISABLED`, `SCHEDULER_CYCLE_COMPLETED`) to the EEF execution journal. AWS is fully deterministic and stdlib-only; it evaluates and delegates work, but does not assemble teams, execute agents, validate gates, or manage keys itself.

REL is specified in [REL v1.0](./docs/REL_v1.0.md). The `release` command verifies production-release readiness of the source tree by checking the packaging metadata (version 1.0.1, dependency-free wheel contract, `src/` layout, console entry point), the presence of every canonical v1.0 contract specification, the importability of every runtime module, and the completeness of the per-contract test suites. Every check is deterministic and stdlib-only: the verifier reads only local files and never touches the network or the wall clock. The report emits `release=PASS` (exit 0) when all gates pass, or `release=FAIL` (exit 2) with per-gate details when any gate fails. REL certifies the release; it does not publish packages, manage keys, encrypt transport, schedule work, or operate any runtime state.

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — system overview, module map, state and authorization models, data-flow diagrams, security architecture
- [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) — setup, tests, mypy/ruff gates, packaging, and how to add a new contract
- [CHANGELOG.md](./CHANGELOG.md) — release history
- [RELEASE_NOTES.md](./RELEASE_NOTES.md) — v1.0.1 maintenance release announcement and quick start
- [docs](./docs) — the 16 canonical v1.0 contract specifications

## Contributing

Please read [CONTRIBUTING.md](.github/CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License, as declared in `pyproject.toml`.

## Security Policy

The security architecture is described in [ARCHITECTURE.md](./ARCHITECTURE.md), section 6, including the fail-closed authorization model, hash-chained journals, and the RB-1..12 release-blocker remediation summary. Production-readiness is certified by the deterministic [REL v1.0](docs/REL_v1.0.md) release gate (`python -m asc_orchestrator --root . release`).

## Acknowledgments

- Built as part of the Autonomous Software Company initiative
