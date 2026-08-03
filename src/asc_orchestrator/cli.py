"""Command-line entry point for M006 runtime validation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .config import ConfigurationError, load_config
from .pese import PESEError, PESEOutcome, PESEStore


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
        }
        else 2
    )


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

        if args.command in {"state", "resume", "checkpoint", "validate-state"}:
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
            else:
                outcome = store.validate()
            _emit_pese_outcome(outcome)
            return _pese_exit_code(outcome)

        from .registry import load_registry

        entries = load_registry(config.registry_dir)
        print(f"registry_entries={len(entries)}")
        for agent_id in sorted(entries):
            print(agent_id)
        return 0
    except (ConfigurationError, PESEError, ValueError, OSError) as error:
        print(f"error: {error}")
        return 2
