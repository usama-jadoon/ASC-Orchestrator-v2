"""Command-line entry point for M006 runtime validation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .aex import AEXError
from .agent import AGCError
from .aws import AwsError
from .config import ConfigurationError, load_config
from .etr import EtrError
from .execution import EEFError
from .health import AHPError
from .keys import CKSError
from .pese import PESEError, PESEOutcome, PESEStore
from .recovery import RecoveryError
from .risk import RiskError
from .validation import VALError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asc-orchestrator")
    parser.add_argument(
        "--root", default=".", help="repository root (default: current directory)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "config", help="validate and display resolved runtime configuration"
    )
    commands.add_parser("registry", help="validate the configured ACR registry")
    acp = commands.add_parser("acp", help="validate an ACP v1.0 message file")
    acp.add_argument("--file", required=True, help="UTF-8 ACP message file")
    acp.add_argument(
        "--direction", choices=("IN", "OUT"), help="append a verified audit record"
    )
    state = commands.add_parser("state", help="load or initialize the PESE state store")
    state.add_argument(
        "--initialize",
        action="store_true",
        help="create the canonical PESE layout and initial state",
    )
    state.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor recorded for initialization or state access",
    )
    commands.add_parser(
        "resume", help="compute the read-only deterministic PESE resume plan"
    )
    checkpoint = commands.add_parser(
        "checkpoint", help="write an explicit MANUAL PESE checkpoint"
    )
    checkpoint.add_argument(
        "--mission-id", required=True, help="canonical mission identifier"
    )
    checkpoint.add_argument(
        "--actor", default="AGENT:orchestrator:local", help="checkpoint writer identity"
    )
    commands.add_parser(
        "validate-state",
        help="run PESE layout, chain, contract, and repository integrity checks",
    )
    reconcile = commands.add_parser(
        "reconcile-repository",
        help="record an authorized Git HEAD advance in PESE repository state",
    )
    reconcile.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="orchestrator actor recording the reconciliation",
    )
    reconcile.add_argument(
        "--expected-revision",
        type=int,
        default=None,
        help="expected state revision; defaults to the loaded state revision",
    )
    mission_validate = commands.add_parser(
        "validate-mission", help="validate an MSS v1.0 mission-specification file"
    )
    mission_validate.add_argument(
        "--file", required=True, help="UTF-8 MSS mission-specification JSON"
    )
    team_build = commands.add_parser(
        "team-build", help="assemble and persist a deterministic TBE v1.0 TEAM.md"
    )
    team_build.add_argument(
        "--mission", required=True, help="UTF-8 mission-contract JSON"
    )
    team_build.add_argument(
        "--classification",
        required=True,
        help="UTF-8 repository-classification JSON array",
    )
    team_build.add_argument(
        "--bind-state",
        action="store_true",
        help="register the validated manifest as PESE planned mission state",
    )
    team_build.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used when binding the manifest to PESE",
    )
    team_build.add_argument(
        "--assembled-at",
        help="explicit UTC assembly timestamp for reproducible manifest generation",
    )
    execution_commands = {
        "execution-start": "activate a planned mission and dispatch root assignments",
        "execution-schedule": "compute the deterministic FIFO dispatch decision",
        "execution-status": "read the current execution lifecycle snapshot",
        "execution-pause": "interrupt an active mission and its assignments",
        "execution-resume": "recover an interrupted mission to ACTIVE",
        "execution-cancel": "terminate an active or interrupted mission",
        "execution-complete": "advance an active mission to VALIDATING",
    }
    for name, help_text in execution_commands.items():
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--mission-id", required=True, help="canonical mission identifier"
        )
        command.add_argument(
            "--actor",
            default="AGENT:orchestrator:local",
            help=(
                "session actor; PESE authorizes transitions only for mission "
                "members, so a non-member actor resolves to the first assigned agent"
            ),
        )
    key_writer_commands = {
        "key-create": "generate a new CKS HMAC-SHA256 key",
        "key-rotate": "rotate an active CKS key to a new active key",
        "key-revoke": "revoke an active CKS key",
    }
    for name, help_text in key_writer_commands.items():
        command = commands.add_parser(name, help=help_text)
        if name in {"key-rotate", "key-revoke"}:
            command.add_argument(
                "--key-id", required=True, help="canonical key identifier"
            )
        if name in {"key-create", "key-rotate"}:
            command.add_argument("--purpose", help="human-readable role for the key")
        if name == "key-revoke":
            command.add_argument(
                "--reason", default="REVOCATION", help="revocation reason"
            )
        command.add_argument(
            "--actor",
            default="AGENT:orchestrator:local",
            help="actor performing the key operation",
        )
    commands.add_parser("key-list", help="list all CKS keys sorted by creation time")
    key_sign = commands.add_parser(
        "key-sign", help="sign a file with a CKS key and record the signature"
    )
    key_sign.add_argument("--key-id", required=True, help="canonical key identifier")
    key_sign.add_argument("--file", required=True, help="UTF-8 or binary file to sign")
    key_sign.add_argument("--purpose", help="optional signing context")
    key_sign.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="signing actor recorded in the ledger",
    )
    key_verify = commands.add_parser(
        "key-verify", help="verify a CKS signature over a file (read-only)"
    )
    key_verify.add_argument("--key-id", required=True, help="canonical key identifier")
    key_verify.add_argument(
        "--file", required=True, help="file whose signature is being verified"
    )
    key_verify.add_argument("--signature", required=True, help="64-char hex signature")
    commands.add_parser(
        "key-validate", help="verify CKS key records, fingerprints, and ledgers"
    )
    aex_commands = {
        "aex-dispatch": "claim a READY assignment: READY → IN_PROGRESS",
        "aex-fail": "mark an IN_PROGRESS assignment as FAILED",
        "aex-block": "block a READY or IN_PROGRESS assignment",
        "aex-unblock": "release a BLOCKED assignment back to READY",
    }
    for name, help_text in aex_commands.items():
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--mission-id", required=True, help="canonical mission identifier"
        )
        command.add_argument(
            "--assignment-id", required=True, help="canonical assignment identifier"
        )
        command.add_argument(
            "--actor",
            default="AGENT:orchestrator:local",
            help="agent actor owning the assignment (must match assigned_agent_id)",
        )
        if name in {"aex-fail", "aex-block"}:
            command.add_argument(
                "--reason", required=True, help="reason for the transition"
            )
    aex_complete = commands.add_parser(
        "aex-complete",
        help="complete an IN_PROGRESS assignment and persist the result record",
    )
    aex_complete.add_argument(
        "--mission-id", required=True, help="canonical mission identifier"
    )
    aex_complete.add_argument(
        "--assignment-id", required=True, help="canonical assignment identifier"
    )
    aex_complete.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="agent actor owning the assignment (must match assigned_agent_id)",
    )
    aex_complete.add_argument(
        "--output", help="output text recorded in the execution result"
    )
    aex_complete.add_argument(
        "--artifact",
        action="append",
        help="artifact path to persist (repeatable, resolved relative to repository root)",
    )
    aex_complete.add_argument(
        "--key-id", help="CKS key used to sign the execution result record"
    )
    aex_status = commands.add_parser(
        "aex-status", help="read the current state of an assignment"
    )
    aex_status.add_argument(
        "--mission-id", required=True, help="canonical mission identifier"
    )
    aex_status.add_argument(
        "--assignment-id", required=True, help="canonical assignment identifier"
    )
    aex_status.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    aex_result = commands.add_parser(
        "aex-result", help="load the execution result record, if any"
    )
    aex_result.add_argument(
        "--mission-id", required=True, help="canonical mission identifier"
    )
    aex_result.add_argument(
        "--assignment-id", required=True, help="canonical assignment identifier"
    )
    aex_result.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    health_heartbeat = commands.add_parser(
        "health-heartbeat", help="record a liveness heartbeat for an agent"
    )
    health_heartbeat.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    health_heartbeat.add_argument(
        "--mission-id", help="optional canonical mission identifier"
    )
    health_heartbeat.add_argument(
        "--assignment-id", help="optional canonical assignment identifier"
    )
    health_heartbeat.add_argument("--note", help="optional human-readable context")
    health_status_cmd = commands.add_parser(
        "health-status", help="report liveness status for a single agent"
    )
    health_status_cmd.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    health_status_cmd.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="staleness threshold in seconds (default: 300)",
    )
    health_report = commands.add_parser(
        "health-report", help="report liveness for every agent assigned to a mission"
    )
    health_report.add_argument(
        "--mission-id", required=True, help="canonical mission identifier"
    )
    health_report.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="staleness threshold in seconds (default: 300)",
    )
    health_check_cmd = commands.add_parser(
        "health-check", help="exit 2 when any mission agent is STALLED"
    )
    health_check_cmd.add_argument(
        "--mission-id", required=True, help="canonical mission identifier"
    )
    health_check_cmd.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="staleness threshold in seconds (default: 300)",
    )
    validation_commands = {
        "validation-gates": "list validation gates for a mission",
        "validation-start": "begin gate execution: PENDING -> RUNNING",
        "validation-verify": "verify gate artifacts match their recorded hashes",
        "validation-invalidate": "invalidate a GREEN gate on binding failure",
        "validation-report": "mission-level validation summary",
    }
    for name, help_text in validation_commands.items():
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--mission-id", required=True, help="canonical mission identifier"
        )
        if name not in {"validation-gates", "validation-report"}:
            command.add_argument(
                "--gate-id", required=True, help="canonical gate identifier"
            )
        command.add_argument(
            "--actor",
            default="AGENT:orchestrator:local",
            help="actor used for PESE state access",
        )
    validation_finish = commands.add_parser(
        "validation-finish",
        help="conclude gate execution: RUNNING -> GREEN/RED/BLOCKED",
    )
    validation_finish.add_argument(
        "--mission-id", required=True, help="canonical mission identifier"
    )
    validation_finish.add_argument(
        "--gate-id", required=True, help="canonical gate identifier"
    )
    validation_finish.add_argument(
        "--verdict",
        required=True,
        choices=("GREEN", "RED", "BLOCKED"),
        help="validation verdict for the gate",
    )
    validation_finish.add_argument(
        "--artifact",
        action="append",
        help="artifact path to bind to the gate (repeatable)",
    )
    validation_finish.add_argument("--reason", help="context for the verdict")
    validation_finish.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    risk_open = commands.add_parser(
        "risk-open", help="register a new risk in OPEN status"
    )
    risk_open.add_argument("--risk-id", required=True, help="canonical risk identifier")
    risk_open.add_argument(
        "--severity",
        required=True,
        choices=("LOW", "MEDIUM", "HIGH", "CRITICAL"),
        help="risk severity",
    )
    risk_open.add_argument("--description", required=True, help="risk description")
    risk_open.add_argument(
        "--mission-id",
        help="canonical mission identifier (default: company-wide risk)",
    )
    risk_open.add_argument(
        "--owner",
        default="AGENT:orchestrator:local",
        help="owner agent recorded on the risk",
    )
    risk_open.add_argument(
        "--evidence",
        action="append",
        help="evidence reference (repeatable)",
    )
    risk_open.add_argument(
        "--block-condition",
        help="human-readable block condition description (HIGH risks only)",
    )
    risk_list = commands.add_parser(
        "risk-list", help="list risks, optionally filtered by mission"
    )
    risk_list.add_argument(
        "--mission-id", help="filter to a canonical mission identifier"
    )
    risk_list.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    risk_status = commands.add_parser("risk-status", help="read a single risk snapshot")
    risk_status.add_argument(
        "--risk-id", required=True, help="canonical risk identifier"
    )
    risk_status.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    risk_resolve = commands.add_parser(
        "risk-resolve", help="resolve an OPEN or MITIGATING risk"
    )
    risk_resolve.add_argument(
        "--risk-id", required=True, help="canonical risk identifier"
    )
    risk_resolve.add_argument(
        "--evidence",
        action="append",
        help="evidence reference (repeatable)",
    )
    risk_resolve.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor performing the transition",
    )
    risk_halt = commands.add_parser(
        "risk-halt", help="halt an OPEN risk (blocks autonomous execution)"
    )
    risk_halt.add_argument("--risk-id", required=True, help="canonical risk identifier")
    risk_halt.add_argument("--reason", required=True, help="halt reason")
    risk_halt.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor performing the transition",
    )
    risk_check = commands.add_parser(
        "risk-check", help="hold-mechanism evaluation; exit 2 when blocked"
    )
    risk_check.add_argument(
        "--mission-id", help="scope evaluation to a canonical mission"
    )
    risk_check.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    risk_report = commands.add_parser("risk-report", help="mission-level risk summary")
    risk_report.add_argument("--mission-id", help="scope report to a canonical mission")
    risk_report.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    for name in ("risk-mitigate", "risk-accept"):
        command = commands.add_parser(
            name,
            help=(
                "transition an OPEN risk to MITIGATING"
                if name == "risk-mitigate"
                else "accept an OPEN risk"
            ),
        )
        command.add_argument(
            "--risk-id", required=True, help="canonical risk identifier"
        )
        command.add_argument(
            "--actor",
            default="AGENT:orchestrator:local",
            help="actor performing the transition",
        )
    agent_simple = {
        "agent-activate": "transition an agent INITIALIZING -> REGISTERED",
        "agent-ready": "transition an agent REGISTERED -> READY",
        "agent-complete": "transition an agent BUSY -> READY",
        "agent-unblock": "transition an agent BLOCKED -> READY",
        "agent-release": "transition an agent to RELEASED",
    }
    for name, help_text in agent_simple.items():
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--agent", required=True, help="canonical agent identifier"
        )
        command.add_argument(
            "--actor",
            default="AGENT:orchestrator:local",
            help="actor managing the agent",
        )
    agent_reason_commands = {
        "agent-block": "transition an agent READY/BUSY -> BLOCKED",
        "agent-fail": "transition an agent to FAILED",
        "agent-quarantine": "transition an agent to QUARANTINED",
        "agent-replace": "transition an agent QUARANTINED/FAILED -> REPLACED",
    }
    for name, help_text in agent_reason_commands.items():
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--agent", required=True, help="canonical agent identifier"
        )
        command.add_argument(
            "--reason", required=True, help="reason for the transition"
        )
        command.add_argument(
            "--actor",
            default="AGENT:orchestrator:local",
            help="actor managing the agent",
        )
    agent_register = commands.add_parser(
        "agent-register", help="register a new agent in INITIALIZING status"
    )
    agent_register.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    agent_register.add_argument(
        "--acr-ref", required=True, help="ACR registry reference for the agent"
    )
    agent_register.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor registering the agent",
    )
    agent_dependency = commands.add_parser(
        "agent-dependency", help="set the agent's dependency environment state"
    )
    agent_dependency.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    agent_dependency.add_argument(
        "--dep-status",
        required=True,
        choices=("VERIFIED", "MISSING", "MISMATCH", "UNKNOWN"),
        help="dependency environment status",
    )
    agent_dependency.add_argument(
        "--verified-at", help="explicit UTC verification timestamp"
    )
    agent_dependency.add_argument(
        "--tool",
        action="append",
        help="tool dependency as name=version (repeatable)",
    )
    agent_dependency.add_argument(
        "--environment",
        action="append",
        help="environment dependency as name=value (repeatable)",
    )
    agent_dependency.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor managing the agent",
    )
    agent_claim = commands.add_parser(
        "agent-claim", help="transition an agent READY -> BUSY"
    )
    agent_claim.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    agent_claim.add_argument(
        "--mission-id", required=True, help="canonical mission identifier"
    )
    agent_claim.add_argument(
        "--assignment-id", required=True, help="canonical assignment identifier"
    )
    agent_claim.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor managing the agent",
    )
    agent_heartbeat = commands.add_parser(
        "agent-heartbeat", help="update the agent's last_heartbeat_at reference"
    )
    agent_heartbeat.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    agent_heartbeat.add_argument("--at", help="explicit UTC heartbeat timestamp")
    agent_heartbeat.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor managing the agent",
    )
    agent_checkpoint = commands.add_parser(
        "agent-checkpoint", help="update the agent's last_checkpoint_id reference"
    )
    agent_checkpoint.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    agent_checkpoint.add_argument(
        "--checkpoint-id", required=True, help="canonical checkpoint identifier"
    )
    agent_checkpoint.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor managing the agent",
    )
    agent_list = commands.add_parser(
        "agent-list", help="list agents (optionally filtered)"
    )
    agent_list.add_argument("--status", help="filter to a lifecycle status")
    agent_list.add_argument(
        "--mission-id", help="filter to a canonical mission identifier"
    )
    agent_list.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    agent_status = commands.add_parser(
        "agent-status", help="read a single agent snapshot"
    )
    agent_status.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    agent_status.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    agent_report = commands.add_parser(
        "agent-report", help="aggregated agent lifecycle summary"
    )
    agent_report.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    rec_diagnose = commands.add_parser(
        "recovery-diagnose", help="pre-flight assessment of a potentially failing agent"
    )
    rec_diagnose.add_argument(
        "--agent", required=True, help="canonical agent identifier"
    )
    rec_diagnose.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    rec_run = commands.add_parser(
        "recovery-run", help="execute the full REC v1.0 recovery sequence"
    )
    rec_run.add_argument("--agent", required=True, help="canonical agent identifier")
    rec_run.add_argument(
        "--trigger",
        choices=("FAILED", "QUARANTINED", "STALLED"),
        help="override the derived recovery trigger",
    )
    rec_run.add_argument(
        "--replacement",
        help="override the suggested replacement agent identifier",
    )
    rec_run.add_argument("--mission-id", help="override the mission identifier")
    rec_run.add_argument("--assignment-id", help="override the assignment identifier")
    rec_run.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor managing the recovery",
    )
    rec_status = commands.add_parser(
        "recovery-status", help="read a single recovery record"
    )
    rec_status.add_argument(
        "--recovery-id", required=True, help="canonical recovery identifier"
    )
    rec_status.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    rec_list = commands.add_parser(
        "recovery-list", help="list recovery records (optionally filtered)"
    )
    rec_list.add_argument(
        "--mission-id", help="filter to a canonical mission identifier"
    )
    rec_list.add_argument("--agent-id", help="filter to a canonical agent identifier")
    rec_list.add_argument("--status", help="filter to a recovery status")
    rec_list.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    rec_report = commands.add_parser(
        "recovery-report", help="aggregated recovery summary"
    )
    rec_report.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    etr_bind = commands.add_parser(
        "etr-bind-channel", help="bind an ACTIVE transport channel to a CKS key"
    )
    etr_bind.add_argument("--from", dest="from_id", required=True, help="sender id")
    etr_bind.add_argument("--to", dest="to_id", required=True, help="recipient id")
    etr_bind.add_argument(
        "--key-id", required=True, help="canonical CKS key identifier"
    )
    etr_bind.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    etr_revoke = commands.add_parser(
        "etr-revoke-channel", help="revoke an ACTIVE transport channel"
    )
    etr_revoke.add_argument("--channel-id", required=True, help="channel identifier")
    etr_revoke.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    etr_channel = commands.add_parser(
        "etr-channel", help="read a single transport channel snapshot"
    )
    etr_channel.add_argument("--channel-id", required=True, help="channel identifier")
    etr_channel.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    etr_channels = commands.add_parser(
        "etr-list-channels", help="list transport channels (optionally filtered)"
    )
    etr_channels.add_argument("--from", dest="from_id", help="filter to a sender id")
    etr_channels.add_argument("--to", dest="to_id", help="filter to a recipient id")
    etr_channels.add_argument("--status", help="filter to a channel status")
    etr_channels.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    etr_seal = commands.add_parser(
        "etr-seal", help="seal a payload file into a ChaCha20-Poly1305 envelope"
    )
    etr_seal.add_argument("--file", required=True, help="payload file to seal")
    etr_seal.add_argument("--key-id", help="canonical CKS key identifier")
    etr_seal.add_argument("--channel-id", help="ACTIVE transport channel to seal via")
    etr_seal.add_argument("--message-type", help="ACP message type of the payload")
    etr_seal.add_argument("--from", dest="from_id", help="sender id override")
    etr_seal.add_argument("--to", dest="to_id", help="recipient id override")
    etr_seal.add_argument("--mission-id", help="mission correlation identifier")
    etr_seal.add_argument("--correlation-id", help="message correlation identifier")
    etr_seal.add_argument("--output", help="envelope JSON output path")
    etr_seal.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    etr_open = commands.add_parser(
        "etr-open", help="authenticate and open an envelope (id or envelope file)"
    )
    etr_open.add_argument(
        "--envelope", required=True, help="envelope id or envelope JSON file path"
    )
    etr_open.add_argument("--output", help="plaintext output path")
    etr_open.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    etr_envs = commands.add_parser(
        "etr-list-envelopes", help="list sealed envelopes (optionally filtered)"
    )
    etr_envs.add_argument("--key-id", help="filter to a CKS key identifier")
    etr_envs.add_argument("--message-type", help="filter to a message type")
    etr_envs.add_argument("--status", help="filter to an envelope status")
    etr_envs.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    etr_report = commands.add_parser("etr-report", help="aggregated transport summary")
    etr_report.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    scheduler_tick = commands.add_parser(
        "scheduler-tick", help="execute one deterministic AWS v1.0 scheduling cycle"
    )
    scheduler_tick.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    scheduler_enable = commands.add_parser(
        "scheduler-enable", help="enable autonomous scheduling"
    )
    scheduler_enable.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    scheduler_disable = commands.add_parser(
        "scheduler-disable", help="disable autonomous scheduling"
    )
    scheduler_disable.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    scheduler_status = commands.add_parser(
        "scheduler-status", help="read the current scheduler snapshot"
    )
    scheduler_status.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    scheduler_cycle = commands.add_parser(
        "scheduler-cycle", help="read a single scheduling cycle record"
    )
    scheduler_cycle.add_argument(
        "--cycle-id", required=True, help="canonical cycle identifier"
    )
    scheduler_cycle.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    scheduler_list = commands.add_parser(
        "scheduler-list", help="list scheduling cycle records"
    )
    scheduler_list.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    scheduler_report = commands.add_parser(
        "scheduler-report", help="aggregated scheduler summary"
    )
    scheduler_report.add_argument(
        "--actor",
        default="AGENT:orchestrator:local",
        help="actor used for PESE state access",
    )
    commands.add_parser(
        "release",
        help="verify production-release readiness of the source tree (REL v1.0)",
    )
    return parser


def _emit_pese_outcome(outcome: PESEOutcome) -> None:
    """Print a compact, machine-readable summary without exposing source payloads."""

    print(f"outcome={outcome.code}")
    print(f"operation_id={outcome.operation_id}")
    if outcome.state_revision is not None:
        print(f"state_revision={outcome.state_revision}")
    if outcome.state_sha256 is not None:
        print(f"state_sha256={outcome.state_sha256}")
    print(
        "findings=" + json.dumps(outcome.findings, ensure_ascii=False, sort_keys=True)
    )
    print("data=" + json.dumps(outcome.data, ensure_ascii=False, sort_keys=True))


def _pese_exit_code(outcome: PESEOutcome) -> int:
    return (
        0
        if outcome.code
        in {
            "INITIALIZED",
            "STATE_LOADED",
            "VALID",
            "CHECKPOINTED",
            "RESUME_PLAN",
            "NO_WORK",
            "RECONCILIATED",
        }
        else 2
    )


def _eef_exit_code(code: str) -> int:
    return 0 if code in {"UPDATED", "READY", "NO_WORK"} else 2


def _read_json_argument(repository_root: Path, value: str, label: str) -> object:
    path = Path(value)
    if not path.is_absolute():
        path = repository_root / path
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label} JSON: {error}") from error


def main(argv: Sequence[str] | None = None) -> int:
    """Run a deterministic local foundation command."""

    args = _parser().parse_args(argv)
    try:
        config = load_config(Path(args.root))
        if args.command == "config":
            print(f"repository_root={config.repository_root}")
            print(f"project_os_dir={config.project_os_dir}")
            print(f"registry_dir={config.registry_dir}")
            print(f"audit_dir={config.audit_dir}")
            print(f"protocol_version={config.protocol_version}")
            return 0

        if args.command == "release":
            from .release import render, verify

            release_report = verify(config.repository_root)
            for line in render(release_report):
                print(line)
            return 0 if release_report.passed else 2

        if args.command == "acp":
            from .acp import parse_message

            message_path = Path(args.file)
            if not message_path.is_absolute():
                message_path = config.repository_root / message_path
            message = parse_message(message_path.read_bytes())
            if args.direction:
                from .audit import AuditJournal

                AuditJournal(
                    config.repository_root, audit_directory=config.audit_dir
                ).append(args.direction, message, "VALID")
            print(f"message_type={message.message_type}")
            print("validation=PASS")
            return 0

        if args.command in {
            "state",
            "resume",
            "checkpoint",
            "validate-state",
            "reconcile-repository",
        }:
            store = PESEStore(config.repository_root)
            if args.command == "state":
                outcome = (
                    store.initialize(args.actor)
                    if args.initialize
                    else store.load(actor=args.actor)
                )
            elif args.command == "resume":
                outcome = store.resume()
            elif args.command == "checkpoint":
                outcome = store.checkpoint(args.mission_id, "MANUAL", actor=args.actor)
            elif args.command == "reconcile-repository":
                expected = args.expected_revision
                if expected is None:
                    loaded = store.load(actor=args.actor)
                    if loaded.code != "STATE_LOADED":
                        _emit_pese_outcome(loaded)
                        return _pese_exit_code(loaded)
                    expected = loaded.data["envelope"]["revision"]
                outcome = store.reconcile_repository(
                    actor=args.actor, expected_revision=expected
                )
            else:
                outcome = store.validate()
            _emit_pese_outcome(outcome)
            return _pese_exit_code(outcome)

        if args.command == "validate-mission":
            from .mss import validate_mission_file

            mission_path = Path(args.file)
            if not mission_path.is_absolute():
                mission_path = config.repository_root / mission_path
            result = validate_mission_file(mission_path)
            for finding in result.findings:
                print(f"finding={finding.severity}:{finding.code}:{finding.detail}")
            print(f"mission_id={result.mission_id}")
            print(f"mission_type={result.mission_type}")
            print(f"findings={len(result.findings)}")
            print(f"validation={'PASS' if result.ok else 'FAIL'}")
            return 0 if result.ok else 2

        if args.command == "team-build":
            from .registry import load_registry
            from .tbe import (
                assemble_team,
                bind_manifest_to_pese,
                team_manifest_relative_path,
                validate_manifest,
            )

            mission = _read_json_argument(
                config.repository_root, args.mission, "mission contract"
            )
            classification = _read_json_argument(
                config.repository_root, args.classification, "classification"
            )
            if not isinstance(mission, dict) or not isinstance(classification, list):
                raise ValueError(
                    "mission contract must be an object and classification must be an array"
                )
            registry = load_registry(config.registry_dir)
            manifest = assemble_team(
                mission,
                classification,
                registry,
                assembled_at=args.assembled_at,
            )
            validate_manifest(manifest, registry=registry)
            manifest_ref = team_manifest_relative_path(manifest)
            output = config.repository_root / manifest_ref
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(manifest.to_markdown(), encoding="utf-8", newline="\n")
            if args.bind_state:
                state_result = bind_manifest_to_pese(
                    manifest,
                    PESEStore(config.repository_root),
                    manifest_ref=manifest_ref,
                    actor=args.actor,
                    registry=registry,
                )
                if not state_result.ok:
                    _emit_pese_outcome(state_result)
                    return 2
            print(f"team_id={manifest.team_id}")
            print(f"manifest_path={output.relative_to(config.repository_root)}")
            print("validation=PASS")
            return 0

        if args.command.startswith("execution-"):
            from .execution import (
                ExecutionSession,
                ExecutionStatus,
                ScheduleResult,
                build_context,
            )

            loaded = PESEStore(config.repository_root).load(actor=args.actor)
            if loaded.code != "STATE_LOADED":
                _emit_pese_outcome(loaded)
                return 2
            mission = (
                loaded.data["envelope"]["state"]
                .get("mission_state", {})
                .get("missions", {})
                .get(args.mission_id)
            )
            if mission is None:
                print("outcome=MISSION_NOT_FOUND")
                print(f"mission_id={args.mission_id}")
                return 2
            assigned = tuple(mission.get("assigned_agent_ids", ()))
            actor = (
                args.actor
                if args.actor in assigned
                else (assigned[0] if assigned else args.actor)
            )
            ctx, err = build_context(
                config.repository_root, config, args.mission_id, actor
            )
            if err is not None:
                _emit_pese_outcome(err)
                return 2
            assert ctx is not None
            session = ExecutionSession(ctx, actor=actor)
            if args.command == "execution-status":
                status = session.status()
                if isinstance(status, ExecutionStatus):
                    print(f"mission_id={status.mission_id}")
                    print(f"mission_status={status.mission_status}")
                    print(f"session_status={status.session_status}")
                    print("current_milestone_id=" + (status.current_milestone_id or ""))
                    print(f"active_assignments={status.active_assignments}")
                    print(f"completed_assignments={status.completed_assignments}")
                    print(f"blocked_assignments={status.blocked_assignments}")
                    print(
                        "next_task_candidates="
                        + json.dumps(
                            list(status.next_task_candidates),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                    print(
                        "last_event_sequence="
                        + (
                            str(status.last_event_sequence)
                            if status.last_event_sequence is not None
                            else ""
                        )
                    )
                    return 0
                _emit_pese_outcome(status)
                return 2
            if args.command == "execution-schedule":
                schedule_result = session.schedule()
                if not isinstance(schedule_result, ScheduleResult):
                    _emit_pese_outcome(schedule_result)
                    return 2
                print(f"outcome={schedule_result.code}")
                if schedule_result.assignment_id:
                    print(f"assignment_id={schedule_result.assignment_id}")
                if schedule_result.agent_id:
                    print(f"agent_id={schedule_result.agent_id}")
                if schedule_result.milestone_id:
                    print(f"milestone_id={schedule_result.milestone_id}")
                if schedule_result.pese_revision is not None:
                    print(f"pese_revision={schedule_result.pese_revision}")
                print(
                    "findings="
                    + json.dumps(
                        list(schedule_result.findings),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return _eef_exit_code(schedule_result.code)
            methods = {
                "execution-start": session.start,
                "execution-pause": session.pause,
                "execution-resume": session.resume_session,
                "execution-cancel": session.cancel,
                "execution-complete": session.complete,
            }
            outcome = methods[args.command]()
            _emit_pese_outcome(outcome)
            return _eef_exit_code(outcome.code)

        if args.command.startswith("aex-"):
            from .aex import AEX

            aex = AEX(
                config.repository_root,
                audit_directory=config.audit_dir,
            )
            if args.command == "aex-status":
                aex_status = aex.status(args.mission_id, args.assignment_id, args.actor)
                print(f"assignment_id={aex_status.assignment_id}")
                print(f"status={aex_status.status}")
                print(f"mission_id={aex_status.mission_id}")
                print(f"agent_id={aex_status.agent_id}")
                print(f"started_at={aex_status.started_at or ''}")
                print(f"completed_at={aex_status.completed_at or ''}")
                print(f"milestone_id={aex_status.milestone_id}")
                return 0
            if args.command == "aex-result":
                exec_result = aex.result(args.mission_id, args.assignment_id)
                if exec_result is None:
                    print("outcome=RESULT_NOT_FOUND")
                    print(f"assignment_id={args.assignment_id}")
                    return 2
                print(f"assignment_id={exec_result.assignment_id}")
                print(f"mission_id={exec_result.mission_id}")
                print(f"agent_id={exec_result.agent_id}")
                print(f"status={exec_result.status}")
                print(f"output_text={exec_result.output_text or ''}")
                print(
                    "artifact_hashes="
                    + json.dumps(exec_result.artifact_hashes, sort_keys=True)
                )
                print(f"started_at={exec_result.started_at or ''}")
                print(f"completed_at={exec_result.completed_at or ''}")
                print(
                    "pese_revision="
                    + (
                        str(exec_result.pese_revision)
                        if exec_result.pese_revision is not None
                        else ""
                    )
                )
                print(f"pese_state_sha256={exec_result.pese_state_sha256 or ''}")
                print(f"entry_hash={exec_result.entry_hash}")
                print(
                    "signature="
                    + (
                        json.dumps(exec_result.signature, sort_keys=True)
                        if exec_result.signature
                        else ""
                    )
                )
                return 0
            if args.command == "aex-complete":
                exec_record = aex.complete(
                    args.mission_id,
                    args.assignment_id,
                    args.actor,
                    output_text=args.output,
                    artifacts=args.artifact or None,
                    key_id=args.key_id,
                )
                print(f"assignment_id={exec_record['assignment_id']}")
                print(f"status={exec_record['status']}")
                print(
                    "artifact_count=" + str(len(exec_record.get("artifact_hashes", {})))
                )
                print("signed=" + ("true" if exec_record.get("signature") else "false"))
                print(f"entry_hash={exec_record['entry_hash']}")
                return 0
            methods = {
                "aex-dispatch": lambda: aex.dispatch(
                    args.mission_id, args.assignment_id, args.actor
                ),
                "aex-fail": lambda: aex.fail(
                    args.mission_id,
                    args.assignment_id,
                    args.actor,
                    reason=args.reason,
                ),
                "aex-block": lambda: aex.block(
                    args.mission_id,
                    args.assignment_id,
                    args.actor,
                    reason=args.reason,
                ),
                "aex-unblock": lambda: aex.unblock(
                    args.mission_id, args.assignment_id, args.actor
                ),
            }
            aex_outcome = methods[args.command]()
            if aex_outcome.code == "UPDATED":
                print(f"assignment_id={args.assignment_id}")
                return 0
            _emit_pese_outcome(aex_outcome)
            return 2

        if args.command.startswith("health-"):
            from .health import HealthStore

            hs = HealthStore(config.repository_root)
            if args.command == "health-heartbeat":
                rec = hs.heartbeat(
                    args.agent,
                    mission_id=getattr(args, "mission_id", None),
                    assignment_id=getattr(args, "assignment_id", None),
                    note=getattr(args, "note", None),
                )
                print(f"agent_id={rec.agent_id}")
                print(f"occurred_at={rec.occurred_at}")
                print(f"sequence={rec.sequence}")
                return 0
            if args.command == "health-status":
                h = hs.agent_health(args.agent, timeout=args.timeout)
                print(f"agent_id={h.agent_id}")
                print(f"status={h.status}")
                print(f"heartbeat_count={h.heartbeat_count}")
                print(f"age_seconds={'' if h.age_seconds is None else h.age_seconds}")
                print("last_heartbeat_at=" + (h.last_heartbeat_at or ""))
                print("last_mission_id=" + (h.last_mission_id or ""))
                print("last_assignment_id=" + (h.last_assignment_id or ""))
                return 0
            if args.command == "health-report":
                report = hs.mission_health(args.mission_id, timeout=args.timeout)
                print(f"agent_count={len(report)}")
                for h in report:
                    print(f"agent_id={h.agent_id}")
                    print(f"status={h.status}")
                    print(f"heartbeat_count={h.heartbeat_count}")
                    print(
                        f"age_seconds={'' if h.age_seconds is None else h.age_seconds}"
                    )
                return 0
            if args.command == "health-check":
                stalled = hs.check_stalled(args.mission_id, timeout=args.timeout)
                mission_agents = hs.mission_agents(args.mission_id)
                print(f"agent_count={len(mission_agents)}")
                print(f"stalled_count={len(stalled)}")
                print("stalled=" + json.dumps(list(stalled)))
                return 0 if not stalled else 2
            # Unreachable but keeps type-checker happy.
            return 2  # pragma: no cover

        if args.command.startswith("validation-"):
            from .validation import ValidationEngine

            engine = ValidationEngine(
                config.repository_root, audit_directory=config.audit_dir
            )
            actor = args.actor
            if getattr(args, "gate_id", None) and args.command in {
                "validation-start",
                "validation-finish",
                "validation-invalidate",
            }:
                # Fall back to the gate's designated validator when the caller
                # is not it (mirrors execution- actor resolution).
                try:
                    for gate in engine.gates(args.mission_id, args.actor):
                        if gate.gate_id == args.gate_id:
                            if gate.validator_agent_id != actor:
                                actor = gate.validator_agent_id
                            break
                except VALError:
                    pass  # Mutation will fail with its own specific error.

            if args.command == "validation-gates":
                gates = engine.gates(args.mission_id, actor)
                print(f"gate_count={len(gates)}")
                for gate in gates:
                    print(f"gate_id={gate.gate_id}")
                    print(f"status={gate.status}")
                    print(f"mission_id={gate.mission_id}")
                    print(f"validator_agent_id={gate.validator_agent_id}")
                    print(f"artifact_count={len(gate.artifact_ids)}")
                    print("verdict_at=" + (gate.verdict_at or ""))
                return 0

            if args.command == "validation-report":
                vreport = engine.report(args.mission_id, actor)
                print(f"mission_id={vreport.mission_id}")
                print(f"gate_count={vreport.gate_count}")
                print(f"green_count={vreport.green_count}")
                print(f"red_count={vreport.red_count}")
                print(f"blocked_count={vreport.blocked_count}")
                print(f"pending_count={vreport.pending_count}")
                print(f"running_count={vreport.running_count}")
                print(f"invalidated_count={vreport.invalidated_count}")
                print(f"waived_count={vreport.waived_count}")
                print(f"overall={vreport.overall}")
                return 0 if vreport.overall in {"PASS", "HOLD"} else 2

            if args.command == "validation-verify":
                verification = engine.verify(args.mission_id, args.gate_id, actor)
                print(f"gate_id={verification.gate_id}")
                print(f"mission_id={verification.mission_id}")
                print("all_match=" + ("true" if verification.all_match else "false"))
                print(f"artifact_count={len(verification.artifact_verifications)}")
                for av in verification.artifact_verifications:
                    print(f"artifact_id={av.artifact_id}")
                    print(f"path={av.path}")
                    print(f"status={av.status}")
                return 0 if verification.all_match else 2

            if args.command == "validation-invalidate":
                outcome = engine.invalidate(args.mission_id, args.gate_id, actor)
                _emit_pese_outcome(outcome)
                return 0 if outcome.code == "UPDATED" else 2

            if args.command == "validation-start":
                outcome = engine.start(args.mission_id, args.gate_id, actor)
                _emit_pese_outcome(outcome)
                return 0 if outcome.code == "UPDATED" else 2

            artifacts = None
            if args.artifact:
                artifacts = [
                    {
                        "path": path,
                        "type": "validation-result",
                        "retention_class": "mission",
                    }
                    for path in args.artifact
                ]
            outcome = engine.finish(
                args.mission_id,
                args.gate_id,
                actor,
                status=args.verdict,
                artifacts=artifacts,
                reason=args.reason,
            )
            _emit_pese_outcome(outcome)
            return 0 if outcome.code == "UPDATED" else 2

        if args.command.startswith("risk-"):
            from .risk import RiskEngine

            risk_engine = RiskEngine(
                config.repository_root, audit_directory=config.audit_dir
            )
            actor = getattr(args, "actor", "AGENT:orchestrator:local")

            if args.command == "risk-open":
                block_condition = None
                if args.block_condition:
                    block_condition = {"description": args.block_condition}
                outcome = risk_engine.open(
                    args.risk_id,
                    args.severity,
                    args.description,
                    args.mission_id,
                    args.owner,
                    evidence_refs=args.evidence,
                    block_condition=block_condition,
                )
                if outcome.code == "UPDATED":
                    print(f"risk_id={args.risk_id}")
                    print("status=OPEN")
                    return 0
                _emit_pese_outcome(outcome)
                return 2

            if args.command == "risk-list":
                risk_records = risk_engine.list(args.mission_id, actor=actor)
                print(f"risk_count={len(risk_records)}")
                for risk_rec in risk_records:
                    print(f"risk_id={risk_rec.risk_id}")
                    print(f"status={risk_rec.status}")
                    print(f"severity={risk_rec.severity}")
                    print(f"mission_id={risk_rec.mission_id or ''}")
                return 0

            if args.command == "risk-status":
                risk_rec = risk_engine.status(args.risk_id, actor=actor)
                print(f"risk_id={risk_rec.risk_id}")
                print(f"status={risk_rec.status}")
                print(f"severity={risk_rec.severity}")
                print(f"description={risk_rec.description}")
                print(f"mission_id={risk_rec.mission_id or ''}")
                print(
                    "evidence_refs="
                    + json.dumps(list(risk_rec.evidence_refs), sort_keys=True)
                )
                print(f"owner_agent_id={risk_rec.owner_agent_id}")
                print(f"opened_at={risk_rec.opened_at}")
                print(f"resolved_at={risk_rec.resolved_at or ''}")
                return 0

            if args.command == "risk-check":
                check = risk_engine.check(args.mission_id, actor=actor)
                print(f"blocked={'true' if check.blocked else 'false'}")
                print(f"blocking_count={len(check.blocking_risks)}")
                for br in check.blocking_risks:
                    print(f"blocking_risk_id={br.risk_id}")
                    print(f"blocking_severity={br.severity}")
                    print(f"blocking_status={br.status}")
                    print(f"blocking_mission_id={br.mission_id or ''}")
                    print(f"blocking_reason={br.reason}")
                print(f"reason={check.reason}")
                return 0 if not check.blocked else 2

            if args.command == "risk-report":
                risk_report = risk_engine.report(args.mission_id, actor=actor)
                print(f"mission_id={risk_report.mission_id or ''}")
                print(f"total={risk_report.total}")
                print(f"open_count={risk_report.open_count}")
                print(f"mitigating_count={risk_report.mitigating_count}")
                print(f"accepted_count={risk_report.accepted_count}")
                print(f"resolved_count={risk_report.resolved_count}")
                print(f"halt_count={risk_report.halt_count}")
                print(f"low_count={risk_report.low_count}")
                print(f"medium_count={risk_report.medium_count}")
                print(f"high_count={risk_report.high_count}")
                print(f"critical_count={risk_report.critical_count}")
                print(
                    f"critical_unresolved_count={risk_report.critical_unresolved_count}"
                )
                print(f"blocked={'true' if risk_report.blocked else 'false'}")
                return 0

            if args.command in {"risk-mitigate", "risk-accept"}:
                outcome = (
                    risk_engine.mitigate(args.risk_id, actor)
                    if args.command == "risk-mitigate"
                    else risk_engine.accept(args.risk_id, actor)
                )
                if outcome.code == "UPDATED":
                    print(f"risk_id={args.risk_id}")
                    return 0
                _emit_pese_outcome(outcome)
                return 2

            if args.command == "risk-resolve":
                outcome = risk_engine.resolve(
                    args.risk_id, actor, evidence_refs=args.evidence
                )
                if outcome.code == "UPDATED":
                    print(f"risk_id={args.risk_id}")
                    return 0
                _emit_pese_outcome(outcome)
                return 2

            if args.command == "risk-halt":
                outcome = risk_engine.halt(args.risk_id, actor, args.reason)
                if outcome.code == "UPDATED":
                    print(f"risk_id={args.risk_id}")
                    return 0
                _emit_pese_outcome(outcome)
                return 2
            # Unreachable but keeps type-checker happy.
            return 2  # pragma: no cover

        if args.command.startswith("agent-"):
            from .agent import AgentLifecycle

            agc_engine = AgentLifecycle(
                config.repository_root, audit_directory=config.audit_dir
            )
            agc_actor = getattr(args, "actor", "AGENT:orchestrator:local")

            if args.command == "agent-register":
                agc_outcome = agc_engine.register(args.agent, args.acr_ref, agc_actor)
                if agc_outcome.code == "UPDATED":
                    print(f"agent_id={args.agent}")
                    print("status=INITIALIZING")
                    return 0
                _emit_pese_outcome(agc_outcome)
                return 2

            if args.command == "agent-list":
                agc_records = agc_engine.list(
                    status=getattr(args, "status", None),
                    mission_id=getattr(args, "mission_id", None),
                    actor=agc_actor,
                )
                print(f"agent_count={len(agc_records)}")
                for agc_rec in agc_records:
                    print(f"agent_id={agc_rec.agent_id}")
                    print(f"status={agc_rec.status}")
                    print(f"mission_id={agc_rec.mission_id or ''}")
                    print(f"acr_ref={agc_rec.acr_ref}")
                return 0

            if args.command == "agent-status":
                agc_rec = agc_engine.agent_status(args.agent, actor=agc_actor)
                print(f"agent_id={agc_rec.agent_id}")
                print(f"status={agc_rec.status}")
                print(f"mission_id={agc_rec.mission_id or ''}")
                print(f"assignment_id={agc_rec.assignment_id or ''}")
                print(f"manifest_version={agc_rec.manifest_version or ''}")
                print(f"last_heartbeat_at={agc_rec.last_heartbeat_at or ''}")
                print(f"last_checkpoint_id={agc_rec.last_checkpoint_id or ''}")
                print(f"acr_ref={agc_rec.acr_ref}")
                print(f"dep_status={agc_rec.dep_status}")
                print(f"verified_at={agc_rec.verified_at or ''}")
                print(
                    "interruption="
                    + (
                        json.dumps(agc_rec.interruption, sort_keys=True)
                        if agc_rec.interruption
                        else ""
                    )
                )
                return 0

            if args.command == "agent-report":
                agc_report = agc_engine.report(actor=agc_actor)
                print(f"total={agc_report.total}")
                print(f"initializing_count={agc_report.initializing_count}")
                print(f"registered_count={agc_report.registered_count}")
                print(f"ready_count={agc_report.ready_count}")
                print(f"busy_count={agc_report.busy_count}")
                print(f"blocked_count={agc_report.blocked_count}")
                print(f"failed_count={agc_report.failed_count}")
                print(f"quarantined_count={agc_report.quarantined_count}")
                print(f"replaced_count={agc_report.replaced_count}")
                print(f"released_count={agc_report.released_count}")
                return 0

            if args.command == "agent-dependency":
                tools: dict[str, str] = {}
                if args.tool:
                    for item in args.tool:
                        name, sep, version = item.partition("=")
                        if sep and name:
                            tools[name] = version
                environment: dict[str, str] = {}
                if args.environment:
                    for item in args.environment:
                        name, sep, value = item.partition("=")
                        if sep and name:
                            environment[name] = value
                agc_outcome = agc_engine.set_dependency(
                    args.agent,
                    args.dep_status,
                    agc_actor,
                    verified_at=getattr(args, "verified_at", None),
                    tool_dependencies=tools,
                    environment_dependencies=environment,
                )
                if agc_outcome.code == "UPDATED":
                    print(f"agent_id={args.agent}")
                    print(f"dep_status={args.dep_status}")
                    return 0
                _emit_pese_outcome(agc_outcome)
                return 2

            if args.command == "agent-heartbeat":
                agc_outcome = agc_engine.heartbeat(
                    args.agent, agc_actor, at=getattr(args, "at", None)
                )
                if agc_outcome.code == "UPDATED":
                    print(f"agent_id={args.agent}")
                    return 0
                _emit_pese_outcome(agc_outcome)
                return 2

            if args.command == "agent-checkpoint":
                agc_outcome = agc_engine.update_checkpoint(
                    args.agent, args.checkpoint_id, agc_actor
                )
                if agc_outcome.code == "UPDATED":
                    print(f"agent_id={args.agent}")
                    print(f"checkpoint_id={args.checkpoint_id}")
                    return 0
                _emit_pese_outcome(agc_outcome)
                return 2

            if args.command == "agent-claim":
                agc_outcome = agc_engine.claim(
                    args.agent, args.mission_id, args.assignment_id, agc_actor
                )
                if agc_outcome.code == "UPDATED":
                    print(f"agent_id={args.agent}")
                    print("status=BUSY")
                    return 0
                _emit_pese_outcome(agc_outcome)
                return 2

            agent_methods = {
                "agent-activate": lambda: agc_engine.activate(args.agent, agc_actor),
                "agent-ready": lambda: agc_engine.ready(args.agent, agc_actor),
                "agent-complete": lambda: agc_engine.complete(args.agent, agc_actor),
                "agent-block": lambda: agc_engine.block(
                    args.agent, agc_actor, args.reason
                ),
                "agent-unblock": lambda: agc_engine.unblock(args.agent, agc_actor),
                "agent-fail": lambda: agc_engine.fail(
                    args.agent, agc_actor, args.reason
                ),
                "agent-quarantine": lambda: agc_engine.quarantine(
                    args.agent, agc_actor, args.reason
                ),
                "agent-replace": lambda: agc_engine.replace(
                    args.agent, agc_actor, args.reason
                ),
                "agent-release": lambda: agc_engine.release(args.agent, agc_actor),
            }
            agc_outcome = agent_methods[args.command]()
            if agc_outcome.code == "UPDATED":
                print(f"agent_id={args.agent}")
                return 0
            _emit_pese_outcome(agc_outcome)
            return 2

        if args.command.startswith("recovery-"):
            from .recovery import RecoveryEngine

            rec_engine = RecoveryEngine(
                config.repository_root, audit_directory=config.audit_dir
            )
            rec_actor = getattr(args, "actor", "AGENT:orchestrator:local")

            if args.command == "recovery-diagnose":
                rec_diag = rec_engine.diagnose(args.agent, rec_actor)
                print(f"agent_id={rec_diag.agent_id}")
                print(f"agent_status={rec_diag.agent_status}")
                print(f"health_status={rec_diag.health_status or ''}")
                print(f"trigger={rec_diag.trigger or ''}")
                print(f"recoverable={'true' if rec_diag.recoverable else 'false'}")
                print(f"reason={rec_diag.reason}")
                print(f"mission_id={rec_diag.mission_id or ''}")
                print(f"assignment_id={rec_diag.assignment_id or ''}")
                print(f"acr_ref={rec_diag.acr_ref}")
                print(
                    f"suggested_replacement_id={rec_diag.suggested_replacement_id or ''}"
                )
                return 0

            if args.command == "recovery-run":
                rec_result = rec_engine.run(
                    args.agent,
                    rec_actor,
                    trigger=getattr(args, "trigger", None),
                    replacement_agent_id=getattr(args, "replacement", None),
                    mission_id=getattr(args, "mission_id", None),
                    assignment_id=getattr(args, "assignment_id", None),
                )
                print(f"recovery_id={rec_result.recovery_id}")
                print(f"status={rec_result.status}")
                print(f"replacement_agent_id={rec_result.replacement_agent_id}")
                print(f"actions={','.join(rec_result.actions)}")
                print(f"mission_id={rec_result.mission_id or ''}")
                print(f"assignment_id={rec_result.assignment_id or ''}")
                print(f"error={rec_result.error or ''}")
                return 0 if rec_result.status == "COMPLETED" else 2

            if args.command == "recovery-status":
                rec_record = rec_engine.status(args.recovery_id, actor=rec_actor)
                print(f"recovery_id={rec_record.recovery_id}")
                print(f"format={rec_record.format}")
                print(f"agent_id={rec_record.agent_id}")
                print(f"trigger={rec_record.trigger}")
                print(f"mission_id={rec_record.mission_id or ''}")
                print(f"assignment_id={rec_record.assignment_id or ''}")
                print(f"acr_ref={rec_record.acr_ref}")
                print(f"replacement_agent_id={rec_record.replacement_agent_id}")
                print(f"status={rec_record.status}")
                print(f"actions={','.join(rec_record.actions)}")
                print(f"created_at={rec_record.created_at}")
                print(f"updated_at={rec_record.updated_at or ''}")
                print(f"completed_at={rec_record.completed_at or ''}")
                print(f"error={rec_record.error or ''}")
                return 0

            if args.command == "recovery-list":
                rec_records = rec_engine.list(
                    mission_id=getattr(args, "mission_id", None),
                    agent_id=getattr(args, "agent_id", None),
                    status=getattr(args, "status", None),
                    actor=rec_actor,
                )
                print(f"recovery_count={len(rec_records)}")
                for rec_record in rec_records:
                    print(f"recovery_id={rec_record.recovery_id}")
                    print(f"agent_id={rec_record.agent_id}")
                    print(f"status={rec_record.status}")
                    print(f"mission_id={rec_record.mission_id or ''}")
                    print(f"replacement_agent_id={rec_record.replacement_agent_id}")
                return 0

            if args.command == "recovery-report":
                rec_report = rec_engine.report(actor=rec_actor)
                print(f"total={rec_report.total}")
                print(f"in_progress_count={rec_report.in_progress_count}")
                print(f"completed_count={rec_report.completed_count}")
                print(f"failed_count={rec_report.failed_count}")
                return 0
            # Unreachable but keeps type-checker happy.
            return 2  # pragma: no cover

        if args.command.startswith("etr-"):
            from pathlib import Path as _Path

            from .etr import EncryptedTransport

            etr_engine = EncryptedTransport(
                config.repository_root, audit_directory=config.audit_dir
            )
            etr_actor = getattr(args, "actor", "AGENT:orchestrator:local")

            if args.command == "etr-bind-channel":
                channel = etr_engine.bind_channel(
                    args.from_id, args.to_id, args.key_id, etr_actor
                )
                print(f"channel_id={channel.channel_id}")
                print(f"format={channel.format}")
                print(f"from_id={channel.from_id or ''}")
                print(f"to_id={channel.to_id or ''}")
                print(f"key_id={channel.key_id}")
                print(f"status={channel.status}")
                print(f"created_at={channel.created_at}")
                return 0

            if args.command == "etr-revoke-channel":
                channel = etr_engine.revoke_channel(args.channel_id, etr_actor)
                print(f"channel_id={channel.channel_id}")
                print(f"status={channel.status}")
                print(f"revoked_at={channel.revoked_at or ''}")
                return 0

            if args.command == "etr-channel":
                channel = etr_engine.channel(args.channel_id, etr_actor)
                print(f"channel_id={channel.channel_id}")
                print(f"format={channel.format}")
                print(f"from_id={channel.from_id or ''}")
                print(f"to_id={channel.to_id or ''}")
                print(f"key_id={channel.key_id}")
                print(f"status={channel.status}")
                print(f"created_at={channel.created_at}")
                print(f"updated_at={channel.updated_at or ''}")
                print(f"revoked_at={channel.revoked_at or ''}")
                return 0

            if args.command == "etr-list-channels":
                channels = etr_engine.list_channels(
                    from_id=getattr(args, "from_id", None),
                    to_id=getattr(args, "to_id", None),
                    status=getattr(args, "status", None),
                    actor=etr_actor,
                )
                print(f"channel_count={len(channels)}")
                for channel in channels:
                    print(f"channel_id={channel.channel_id}")
                    print(f"from_id={channel.from_id or ''}")
                    print(f"to_id={channel.to_id or ''}")
                    print(f"key_id={channel.key_id}")
                    print(f"status={channel.status}")
                return 0

            if args.command == "etr-seal":
                payload_path = _Path(args.file)
                if not payload_path.is_absolute():
                    payload_path = config.repository_root / payload_path
                if args.key_id is None and args.channel_id is None:
                    raise EtrError(
                        "KEY_REQUIRED",
                        "exactly one of --key-id or --channel-id is required",
                    )
                if args.output:
                    output_path = _Path(args.output)
                    if not output_path.is_absolute():
                        output_path = config.repository_root / output_path
                else:
                    output_path = _Path(str(payload_path) + ".etr")
                envelope = etr_engine.seal_file(
                    payload_path,
                    key_id=args.key_id,
                    channel_id=args.channel_id,
                    message_type=getattr(args, "message_type", None),
                    from_id=getattr(args, "from_id", None),
                    to_id=getattr(args, "to_id", None),
                    mission_id=getattr(args, "mission_id", None),
                    correlation_id=getattr(args, "correlation_id", None),
                    output=output_path,
                    actor=etr_actor,
                )
                print(f"envelope_id={envelope.envelope_id}")
                print(f"key_id={envelope.key_id}")
                print(f"status={envelope.status}")
                print(f"plaintext_sha256={envelope.plaintext_sha256}")
                print(f"envelope_path={output_path}")
                return 0

            if args.command == "etr-open":
                open_output: Path | None = None
                if args.output:
                    open_output = _Path(args.output)
                    if not open_output.is_absolute():
                        open_output = config.repository_root / open_output
                envelope_arg = args.envelope
                envelope_path = _Path(envelope_arg)
                if not envelope_path.is_absolute():
                    envelope_path = config.repository_root / envelope_path
                if envelope_path.exists():
                    import json as _json

                    record = _json.loads(envelope_path.read_text(encoding="utf-8"))
                    unsealed = etr_engine.open(record, actor=etr_actor)
                    print(f"envelope_id={unsealed.envelope_id}")
                else:
                    unsealed = etr_engine.open(envelope_arg, actor=etr_actor)
                    print(f"envelope_id={unsealed.envelope_id}")
                print(f"key_id={unsealed.key_id}")
                print("status=OPENED")
                print(f"plaintext_sha256={unsealed.plaintext_sha256}")
                if open_output:
                    open_output.write_bytes(unsealed.payload)
                    print(f"output_path={open_output}")
                return 0

            if args.command == "etr-list-envelopes":
                envelopes = etr_engine.list_envelopes(
                    key_id=getattr(args, "key_id", None),
                    message_type=getattr(args, "message_type", None),
                    status=getattr(args, "status", None),
                    actor=etr_actor,
                )
                print(f"envelope_count={len(envelopes)}")
                for envelope in envelopes:
                    print(f"envelope_id={envelope.envelope_id}")
                    print(f"key_id={envelope.key_id}")
                    print(f"message_type={envelope.message_type or ''}")
                    print(f"status={envelope.status}")
                return 0

            if args.command == "etr-report":
                transport_report = etr_engine.report(actor=etr_actor)
                print(f"channels_total={transport_report.channels_total}")
                print(f"channels_active={transport_report.channels_active}")
                print(f"channels_revoked={transport_report.channels_revoked}")
                print(f"envelopes_total={transport_report.envelopes_total}")
                print(f"envelopes_sealed={transport_report.envelopes_sealed}")
                print(f"envelopes_opened={transport_report.envelopes_opened}")
                print(f"envelopes_auth_failed={transport_report.envelopes_auth_failed}")
                return 0
            # Unreachable but keeps type-checker happy.
            return 2  # pragma: no cover

        if args.command.startswith("scheduler-"):
            from .aws import AutonomousScheduler

            scheduler = AutonomousScheduler(
                config.repository_root, audit_directory=config.audit_dir
            )
            sched_actor = getattr(args, "actor", "AGENT:orchestrator:local")

            if args.command == "scheduler-tick":
                cycle = scheduler.tick(actor=sched_actor)
                print(f"cycle_id={cycle.cycle_id}")
                print(f"status={cycle.status}")
                print(f"decision_type={cycle.decision_type}")
                print(f"priority={cycle.priority}")
                print(f"reason={cycle.reason}")
                print(f"action_code={cycle.action_code}")
                print(f"success={'true' if cycle.success else 'false'}")
                print(f"mission_id={cycle.mission_id or ''}")
                print(f"agent_id={cycle.agent_id or ''}")
                print(f"assignment_id={cycle.assignment_id or ''}")
                print(
                    "detail="
                    + json.dumps(cycle.detail, ensure_ascii=False, sort_keys=True)
                )
                return 0 if cycle.success else 2

            if args.command in {"scheduler-enable", "scheduler-disable"}:
                outcome = (
                    scheduler.enable(actor=sched_actor)
                    if args.command == "scheduler-enable"
                    else scheduler.disable(actor=sched_actor)
                )
                _emit_pese_outcome(outcome)
                return 0 if outcome.code in {"UPDATED", "NO_CHANGE"} else 2

            if args.command == "scheduler-status":
                sched_status = scheduler.status(actor=sched_actor)
                print(f"enabled={'true' if sched_status.enabled else 'false'}")
                print(f"active_mission_id={sched_status.active_mission_id or ''}")
                print(f"cycle_count={sched_status.cycle_count}")
                print(f"last_cycle_id={sched_status.last_cycle_id or ''}")
                print(f"last_decision_type={sched_status.last_decision_type or ''}")
                print(f"last_action_code={sched_status.last_action_code or ''}")
                print(f"reason={sched_status.reason}")
                return 0

            if args.command == "scheduler-cycle":
                cycle = scheduler.cycle(args.cycle_id, actor=sched_actor)
                print(f"cycle_id={cycle.cycle_id}")
                print(f"format={cycle.format}")
                print(f"status={cycle.status}")
                print(f"decision_type={cycle.decision_type}")
                print(f"priority={cycle.priority}")
                print(f"reason={cycle.reason}")
                print(f"action_code={cycle.action_code}")
                print(f"success={'true' if cycle.success else 'false'}")
                print(f"created_at={cycle.created_at}")
                print(f"completed_at={cycle.completed_at}")
                print(f"mission_id={cycle.mission_id or ''}")
                print(f"agent_id={cycle.agent_id or ''}")
                print(f"assignment_id={cycle.assignment_id or ''}")
                print(
                    "detail="
                    + json.dumps(cycle.detail, ensure_ascii=False, sort_keys=True)
                )
                return 0

            if args.command == "scheduler-list":
                cycles = scheduler.list_cycles(actor=sched_actor)
                print(f"cycle_count={len(cycles)}")
                for cycle in cycles:
                    print(f"cycle_id={cycle.cycle_id}")
                    print(f"status={cycle.status}")
                    print(f"decision_type={cycle.decision_type}")
                    print(f"action_code={cycle.action_code}")
                    print(f"success={'true' if cycle.success else 'false'}")
                return 0

            if args.command == "scheduler-report":
                sched_report = scheduler.report(actor=sched_actor)
                print(f"enabled={'true' if sched_report.enabled else 'false'}")
                print(f"total_cycles={sched_report.total_cycles}")
                print(f"completed_cycles={sched_report.completed_cycles}")
                print(f"failed_cycles={sched_report.failed_cycles}")
                print(
                    "decision_counts="
                    + json.dumps(sched_report.decision_counts, sort_keys=True)
                )
                print(
                    "action_counts="
                    + json.dumps(sched_report.action_counts, sort_keys=True)
                )
                print(f"last_cycle_id={sched_report.last_cycle_id or ''}")
                return 0
            # Unreachable but keeps type-checker happy.
            return 2  # pragma: no cover

        if args.command.startswith("key-"):
            from .keys import KeyStore

            key_store = KeyStore(config.repository_root)
            if args.command == "key-create":
                record = key_store.create_key(
                    args.actor, purpose=getattr(args, "purpose", None)
                )
                print(f"key_id={record.key_id}")
                return 0
            if args.command == "key-list":
                records = key_store.list_keys()
                print(f"key_count={len(records)}")
                for record in records:
                    print(record.key_id)
                return 0
            if args.command == "key-validate":
                valid = key_store.validate()
                print(f"outcome={'VALID' if valid else 'INVALID'}")
                return 0 if valid else 2
            if args.command == "key-sign":
                payload_path = Path(args.file)
                if not payload_path.is_absolute():
                    payload_path = config.repository_root / payload_path
                signature_record = key_store.sign(
                    args.key_id,
                    payload_path.read_bytes(),
                    args.actor,
                    purpose=getattr(args, "purpose", None),
                )
                print(f"signature={signature_record.signature_hex}")
                return 0
            if args.command == "key-verify":
                payload_path = Path(args.file)
                if not payload_path.is_absolute():
                    payload_path = config.repository_root / payload_path
                valid = key_store.verify(
                    args.key_id, payload_path.read_bytes(), args.signature
                )
                print(f"valid={'true' if valid else 'false'}")
                return 0
            if args.command == "key-rotate":
                record = key_store.rotate(
                    args.actor, args.key_id, purpose=getattr(args, "purpose", None)
                )
                print(f"new_key_id={record.key_id}")
                return 0
            key_store.revoke(
                args.actor,
                args.key_id,
                reason=getattr(args, "reason", "REVOCATION"),
            )
            print(f"key_id={args.key_id}")
            print("status=REVOKED")
            return 0

        from .registry import load_registry

        entries = load_registry(config.registry_dir)
        print(f"registry_entries={len(entries)}")
        for agent_id in sorted(entries):
            print(agent_id)
        return 0
    except (
        ConfigurationError,
        PESEError,
        EEFError,
        CKSError,
        AEXError,
        AHPError,
        VALError,
        RiskError,
        AGCError,
        RecoveryError,
        EtrError,
        AwsError,
        ValueError,
        OSError,
    ) as error:
        print(f"error: {error}")
        return 2
