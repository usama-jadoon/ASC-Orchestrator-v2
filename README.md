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

## Documentation

See the [docs](./docs) directory for detailed documentation.

## Contributing

Please read [CONTRIBUTING.md](.github/CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Security Policy

See our [security policy](SECURITY.md) for details on reporting security vulnerabilities.

## Acknowledgments

- Built as part of the Autonomous Software Company initiative
