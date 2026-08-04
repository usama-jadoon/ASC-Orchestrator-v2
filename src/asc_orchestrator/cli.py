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

        from .registry import load_registry

        entries = load_registry(config.registry_dir)
        print(f"registry_entries={len(entries)}")
        for agent_id in sorted(entries):
            print(agent_id)
        return 0
    except (ConfigurationError, PESEError, ValueError, OSError) as error:
        print(f"error: {error}")
        return 2
