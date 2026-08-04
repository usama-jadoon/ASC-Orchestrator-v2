"""Command-line entry point for M006 runtime validation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .config import ConfigurationError, load_config
from .execution import EEFError
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

        from .registry import load_registry

        entries = load_registry(config.registry_dir)
        print(f"registry_entries={len(entries)}")
        for agent_id in sorted(entries):
            print(agent_id)
        return 0
    except (ConfigurationError, PESEError, EEFError, ValueError, OSError) as error:
        print(f"error: {error}")
        return 2
