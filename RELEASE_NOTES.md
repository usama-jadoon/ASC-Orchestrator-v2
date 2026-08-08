# ASC Orchestrator v2 — Release Notes

**Version 1.0.0** · 2026-08-08 · Initial production release

ASC Orchestrator v2 is a deterministic, auditable, standard-library-only
Python runtime for the assembly and operation of autonomous
software-company agents. It turns a mission specification into a
registry-backed team, executes that team's work through a typed lifecycle,
and records every mutation in a hash-chained journal — with no third-party
runtime dependencies and no network calls.

This release ships **16 canonical v1.0 contracts**, **22 runtime modules**,
and **630+ passing tests**. A built-in `release` verifier (REL v1.0)
deterministically certifies the source tree as production-ready before
publication.

---

## What this release delivers

| Contract | Name | What it does |
| --- | --- | --- |
| ACP | Agent Communication Protocol | Fixed-header, ordered-payload messages with SHA-256 payload binding and semantic validation; also the audit-record format. |
| ACR | Agent Capability Registry | Deterministic JSON registry of agent capabilities, loaded from `.project-os/COMPANY/DEPARTMENTS/`. |
| PESE | Persistent Execution State Engine | Canonical persistent state, checkpoints, locking, integrity validation, deterministic resume, recovery, and migration. |
| TBE | Team Builder Engine | Deterministic registry-only team assembly with ownership, dependency graphs, reviewer/validator assignment, and `TEAM.md` manifests. |
| MSS | Mission Specification Standard | Immutable mission-intake contract with structural and semantic validation. |
| EEF | Execution Engine Foundation | Mission lifecycle (start, schedule, pause, resume, cancel, complete) with a hash-chained execution event journal. |
| CKS | Cryptographic Key Service | HMAC-SHA256 key lifecycle, constant-time signing/verification, and a hash-chained signing ledger. |
| AEX | Agent Execution Engine | Claims EEF-dispatched assignments, persists work-product artifacts, and signs execution attestations. |
| AHP | Agent Health Protocol | Append-only, hash-chained heartbeat journals deriving ALIVE / STALLED / UNKNOWN liveness. |
| VAL | Validation Engine | Drives PESE validation gates (`PENDING → RUNNING → GREEN/RED/BLOCKED`), binds artifacts by SHA-256. |
| RKM | Risk Management | Operates the risk ledger and the hold mechanism that blocks autonomous execution on blocking risks. |
| AGC | Agent Lifecycle Control | Agent status state machine from registration through release, with dependency-gated readiness. |
| REC | Recovery Engine | One-command deterministic agent recovery: quarantine → release → register replacement → ready → claim. |
| ETR | Encrypted Transport | RFC 8439 ChaCha20-Poly1305 AEAD sealing of payloads into tamper-evident envelopes. |
| AWS | Autonomous Workflow Scheduler | One prioritized scheduling decision per tick (HOLD, RECOVER, START_MISSION, DISPATCH, VALIDATE, COMPLETE_MISSION, MONITOR_HEALTH, IDLE). |
| REL | Production Release | Nine-gate, deterministic release verifier (`release=PASS`, exit 0 only when all gates pass). |

---

## Installation

Requires **Python 3.11 or later**. No third-party runtime dependencies.

### From source

```powershell
git clone https://github.com/osama-jadoon/ASC-Orchestrator-v2.git
cd ASC-Orchestrator-v2
python -m pip install .
```

### From the wheel

Build the wheel, then install it (on any offline or air-gapped host):

```powershell
python -m pip install build        # build frontend only; not a runtime dep
python -m build
python -m pip install dist/asc_orchestrator-1.0.0-py3-none-any.whl
```

### Verify the installation

```powershell
asc-orchestrator --root . release
```

or, from a checkout:

```powershell
python -m asc_orchestrator --root . release
```

A healthy release prints `release=PASS` with `gate.*=PASS` for all nine
gates and exits 0.

---

## Quick start

The runtime is exercised through the `asc-orchestrator` console command
(or `python -m asc_orchestrator`) against a repository root. All commands
accept `--root <path>` and emit machine-readable outcomes with
deterministic exit codes.

```powershell
# 1. Validate the environment
python -m asc_orchestrator --root . config
python -m asc_orchestrator --root . registry

# 2. Initialize persistent state
python -m asc_orchestrator --root . state --initialize

# 3. Assemble a team from a mission specification
python -m asc_orchestrator --root . team-build --mission mission.json --classification classification.json
python -m asc_orchestrator --root . validate-mission --file mission.json

# 4. Run the mission lifecycle
python -m asc_orchestrator --root . execution-start --mission-id MISSION:example
python -m asc_orchestrator --root . execution-schedule --mission-id MISSION:example
python -m asc_orchestrator --root . execution-status --mission-id MISSION:example

# 5. Register and ready an agent, then dispatch its assignment
python -m asc_orchestrator --root . agent-register --agent AGENT:developer:local --acr-ref ACR:developer:specialist
python -m asc_orchestrator --root . agent-dependency --agent AGENT:developer:local --dep-status VERIFIED --tool python=3.11
python -m asc_orchestrator --root . agent-ready --agent AGENT:developer:local
python -m asc_orchestrator --root . aex-dispatch --mission-id MISSION:example --assignment-id ASSIGNMENT:build --actor AGENT:developer:local
python -m asc_orchestrator --root . aex-complete --mission-id MISSION:example --assignment-id ASSIGNMENT:build --actor AGENT:developer:local --output "work done"

# 6. Validate gates, manage risk, and check agent health
python -m asc_orchestrator --root . validation-gates --mission-id MISSION:example
python -m asc_orchestrator --root . health-report --mission-id MISSION:example
python -m asc_orchestrator --root . risk-check --mission-id MISSION:example

# 7. Run the autonomous scheduler (one decision per tick)
python -m asc_orchestrator --root . scheduler-enable
python -m asc_orchestrator --root . scheduler-tick

# 8. Certify the release
python -m asc_orchestrator --root . release
```

The full command reference — including `recovery-*`, `etr-*`, and the
complete `agent-*`/`risk-*`/`validation-*` families — is documented in the
[README](./README.md) and the per-contract specifications in `docs/`.

---

## Key security features

- **Fail-closed authorization.** PESE transitions are default-deny. Every
  transition kind (assignments, missions, gates, agents, risks, transport,
  scheduler, recovery) is checked against the actor; unknown kinds require
  orchestrator authority (`AGENT:orchestrator:local`). Only the assigned
  agent may transition its own assignment; only the risk owner or an
  orchestrator-role actor may mutate risks.
- **Fail-closed integrity.** Health, key-status, and signing journals verify
  their hash chains before reporting; a corrupted journal raises
  (`JOURNAL_CORRUPT`, `LEDGER_BROKEN`) instead of serving unverified state.
  VAL `verify()` never computes an authoritative verdict from unverified
  state.
- **Hash-chained journals.** ACP audit records, EEF execution events, CKS
  signing ledgers, and AHP heartbeat journals are all append-only and
  hash-chained, so any tampering breaks the chain and is detected.
- **Tamper-evident transport.** ETR seals payloads with RFC 8439
  ChaCha20-Poly1305 AEAD; the envelope header is bound as authenticated
  data, so metadata or ciphertext tampering fails at open time.
- **Input containment.** Agent IDs and key IDs are validated and
  percent-encoded before any filesystem path is constructed, rejecting
  traversal names (`..`, `/`, `\`, NUL).
- **Deterministic release gate.** REL v1.0 verifies packaging metadata,
  contract coverage, module importability, and test-suite presence with no
  network or wall-clock dependence.

---

## Known limitations

- **Local-only runtime.** All state, journals, keys, artifacts, and
  envelopes live beneath `.project-os/` in the local checkout. There is no
  distributed consensus, remote store, or multi-host locking; process-safe
  locking is local to one machine.
- **Symmetric encryption only.** ETR provides authenticated symmetric
  encryption (ChaCha20-Poly1305). It does not implement asymmetric
  key-exchange or public-key infrastructure.
- **No built-in AI/LLM integration.** AWS decisions are deterministic and
  rule-based (`SchedulingDecision.requires_ai` is always `False`); agents
  execute work through the CLI/runtime API, not through model inference.
- **Single-actor orchestrator.** The orchestrator authority is a single
  identity (`AGENT:orchestrator:local`); there is no role-based
  administration or delegated sub-authority beyond the per-kind rules.
- **`async` not supported.** The runtime is synchronous and
  single-process; there is no async/await API surface.
- **Python floor.** Requires Python 3.11+; the CI matrix covers 3.11-3.13
  and the verified development stack is Python 3.14.

---

## License

MIT. The license is declared in `pyproject.toml`
(`license = { text = "MIT" }`). See `docs/` for the canonical contract
specifications and `.github/CONTRIBUTING.md` for contribution guidelines.

---

## Acknowledgements

Built as part of the Autonomous Software Company initiative.
