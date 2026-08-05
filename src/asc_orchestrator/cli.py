"""Command-line entry point for M006 runtime validation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .aex import AEXError
from .config import ConfigurationError, load_config
from .execution import EEFError
from .health import AHPError
from .keys import CKSError
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
        ValueError,
        OSError,
    ) as error:
        print(f"error: {error}")
        return 2
