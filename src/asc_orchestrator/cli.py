"""Command-line entry point for M006 runtime validation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .config import ConfigurationError, load_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asc-orchestrator")
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("config", help="validate and display resolved runtime configuration")
    commands.add_parser("registry", help="validate the configured ACR registry")
    acp = commands.add_parser("acp", help="validate an ACP v1.0 message file")
    acp.add_argument("--file", required=True, help="UTF-8 ACP message file")
    acp.add_argument("--direction", choices=("IN", "OUT"), help="append a verified audit record")
    return parser


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

        from .registry import load_registry

        entries = load_registry(config.registry_dir)
        print(f"registry_entries={len(entries)}")
        for agent_id in sorted(entries):
            print(agent_id)
        return 0
    except (ConfigurationError, ValueError, OSError) as error:
        print(f"error: {error}")
        return 2
