"""Universal ASC v2.3.0 - Command-Line Interface.

Provides rich CLI subcommands, machine-readable JSON output,
and launches the interactive Operator Console.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

from .console import (
    InteractiveConsole,
    console,
    run_doctor,
    run_logs_view,
    run_status_view,
)
from .driver import MissionDriver
from .spec import MissionSpecParser
from .state import State

VERSION = "2.3.0"


class CLI:
    """Command-line interface for Universal ASC Orchestrator v2.3.0."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._setup_parser()

    def _setup_parser(self):
        """Set up command-line argument parser with shared parent options."""
        common = argparse.ArgumentParser(add_help=False)
        common.add_argument(
            "--cwd",
            type=str,
            default=None,
            help="Target repository working directory (defaults to current directory)",
        )
        common.add_argument(
            "--model",
            type=str,
            default=None,
            help="Configured model or provider route (e.g. omniroute/auto/best-free)",
        )
        common.add_argument(
            "--executor",
            type=str,
            default=None,
            help="Executor engine (omp, shell, mock)",
        )
        common.add_argument(
            "--execution-timeout",
            type=int,
            default=None,
            help="Timeout in seconds for coding executor process",
        )
        common.add_argument(
            "--verification-timeout",
            type=int,
            default=None,
            help="Timeout in seconds for verification commands",
        )
        common.add_argument(
            "--mission-id",
            type=str,
            default=None,
            help="Specific mission ID (defaults to latest active)",
        )
        common.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Output structured machine-readable JSON",
        )

        self.parser = argparse.ArgumentParser(
            prog="asc",
            description=f"ASC Orchestrator v{VERSION} — Autonomous Software Company Mission Authority",
            parents=[common],
        )
        self.parser.add_argument(
            "--version",
            action="version",
            version=f"ASC Orchestrator v{VERSION}",
        )

        subparsers = self.parser.add_subparsers(
            dest="command", help="Available subcommands"
        )

        # init
        init_p = subparsers.add_parser(
            "init", help="Initialize a sample mission specification", parents=[common]
        )
        init_p.add_argument(
            "file", nargs="?", default="mission.yaml", help="Path to mission file"
        )

        # validate
        val_p = subparsers.add_parser(
            "validate",
            help="Validate mission syntax and DAG structure",
            parents=[common],
        )
        val_p.add_argument(
            "file", nargs="?", default="mission.yaml", help="Path to mission file"
        )

        # run
        run_p = subparsers.add_parser(
            "run", help="Execute a mission end-to-end", parents=[common]
        )
        run_p.add_argument(
            "file", nargs="?", default="mission.yaml", help="Path to mission file"
        )

        # status
        stat_p = subparsers.add_parser(
            "status", help="Show current mission and task status", parents=[common]
        )
        stat_p.add_argument(
            "--watch", action="store_true", help="Continuously watch status"
        )

        # resume
        res_p = subparsers.add_parser(
            "resume", help="Resume interrupted mission", parents=[common]
        )
        res_p.add_argument(
            "res_mission_id", nargs="?", default=None, help="Mission ID to resume"
        )

        # doctor
        doc_p = subparsers.add_parser(
            "doctor", help="Run comprehensive system diagnostics", parents=[common]
        )
        doc_p.add_argument(
            "--verbose", "-v", action="store_true", help="Verbose output"
        )

        # logs
        log_p = subparsers.add_parser(
            "logs", help="Inspect mission event ledger", parents=[common]
        )
        log_p.add_argument("--task", type=str, help="Filter events by task ID")
        log_p.add_argument(
            "--limit", type=int, default=50, help="Max events to display"
        )

    def run(self, argv: Optional[list] = None) -> None:
        """Execute the CLI command or launch interactive console if no subcommand."""
        args = self.parser.parse_args(argv)
        cwd = Path(args.cwd).resolve() if args.cwd else Path(".").resolve()

        if not args.command:
            # Primary launch experience: Open interactive terminal operator console
            InteractiveConsole(cwd=cwd).start()
            return

        if args.command == "init":
            self._init_mission(args.file, cwd, as_json=args.json)
        elif args.command == "validate":
            self._validate_mission(args.file, cwd, as_json=args.json)
        elif args.command == "run":
            self._run_mission(args, cwd, as_json=args.json)
        elif args.command == "status":
            self._show_status(args, cwd, as_json=args.json)
        elif args.command == "resume":
            self._resume_mission(args, cwd, as_json=args.json)
        elif args.command == "doctor":
            run_doctor(cwd=cwd, as_json=args.json)
        elif args.command == "logs":
            run_logs_view(
                mission_id=args.mission_id,
                task_id=args.task,
                limit=args.limit,
                cwd=cwd,
                as_json=args.json,
            )

    def _init_mission(self, file_path: str, cwd: Path, as_json: bool = False) -> None:
        """Initialize a new sample mission file if not present."""
        path = cwd / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if not path.exists():
            sample_content = (
                "id: sample-mission\n"
                'goal: "Build sample feature set"\n'
                "tasks:\n"
                "  - id: T1\n"
                '    title: "Project Setup"\n'
                '    prompt: "Initialize project structure and configuration"\n'
                "    verify:\n"
                "      - echo 'Verifying setup'\n"
                "  - id: T2\n"
                '    title: "Core Implementation"\n'
                '    prompt: "Implement core business logic"\n'
                "    depends_on:\n"
                "      - T1\n"
                "    verify:\n"
                "      - echo 'Verifying core logic'\n"
            )
            path.write_text(sample_content, encoding="utf-8")

        try:
            spec = MissionSpecParser.from_file(path)
            state = State(self.db_path, cwd=cwd)
            state.save_mission(spec)
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "ok",
                            "mission_id": spec.id,
                            "tasks": len(spec.tasks),
                        },
                        indent=2,
                    )
                )
            else:
                console.print(
                    f"[bold green]Initialized mission '{spec.id}' with {len(spec.tasks)} tasks in state database.[/bold green]"
                )
        except Exception as e:
            if as_json:
                print(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                console.print(f"[bold red]Error initializing mission:[/bold red] {e}")
            sys.exit(1)

    def _validate_mission(
        self, file_path: str, cwd: Path, as_json: bool = False
    ) -> None:
        """Validate a mission file specification and DAG validity."""
        path = cwd / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if not path.exists():
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "error": f"Mission file '{path}' not found",
                        },
                        indent=2,
                    )
                )
            else:
                console.print(
                    f"[bold red]Error: Mission file '{path}' not found.[/bold red]"
                )
            sys.exit(1)

        try:
            spec = MissionSpecParser.from_file(path)
            warnings = MissionSpecParser.validate(spec)
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "valid" if not warnings else "warning",
                            "mission_id": spec.id,
                            "tasks_count": len(spec.tasks),
                            "warnings": warnings,
                        },
                        indent=2,
                    )
                )
            else:
                console.print(
                    f"[bold green]SUCCESS: Mission '{spec.id}' validation passed![/bold green] "
                    f"({len(spec.tasks)} tasks, 0 cycle/dependency errors)"
                )
        except Exception as e:
            if as_json:
                print(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                console.print(f"[bold red]Validation ERROR:[/bold red] {e}")
            sys.exit(1)

    def _run_mission(
        self, args: argparse.Namespace, cwd: Path, as_json: bool = False
    ) -> None:
        """Execute a mission end-to-end with centralized driver preflight."""
        path = cwd / args.file if not Path(args.file).is_absolute() else Path(args.file)
        if not path.exists():
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "error": f"Mission file '{path}' not found",
                        },
                        indent=2,
                    )
                )
            else:
                console.print(
                    f"[bold red]Error: Mission file '{path}' not found.[/bold red]"
                )
            sys.exit(1)

        try:
            spec = MissionSpecParser.from_file(path)
            if args.model is not None:
                spec.model = args.model
            if args.executor is not None:
                spec.executor = args.executor
            if args.execution_timeout is not None:
                spec.execution_timeout = args.execution_timeout
            if args.verification_timeout is not None:
                spec.verification_timeout = args.verification_timeout

            if not as_json:
                console.print(
                    f"[bold cyan]Starting Mission '{spec.id}':[/bold cyan] {spec.goal}"
                )

            driver = MissionDriver(
                spec=spec,
                db_path=self.db_path,
                working_directory=str(cwd) if args.cwd else None,
                model=args.model,
                executor=args.executor,
                execution_timeout=args.execution_timeout,
                verification_timeout=args.verification_timeout,
            )
            result = driver.run(spec.id)

            if as_json:
                print(json.dumps(result, indent=2))
                return

            status_color = (
                "green" if result.get("final_status") == "COMPLETE" else "red"
            )
            console.print(
                f"\n[bold {status_color}]Mission Finished: {result.get('final_status')}[/bold {status_color}]"
            )
            console.print(
                f"Tasks Completed: [bold green]{result.get('tasks_completed')}[/bold green], "
                f"Failed: [bold red]{result.get('tasks_failed')}[/bold red], "
                f"Blocked: [bold yellow]{result.get('tasks_blocked')}[/bold yellow]"
            )
            if result.get("git_commits"):
                console.print(f"Verified Git Commits: {result.get('git_commits')}")
        except Exception as e:
            if as_json:
                print(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                console.print(f"[bold red]Error running mission:[/bold red] {e}")
            sys.exit(1)

    def _show_status(
        self, args: argparse.Namespace, cwd: Path, as_json: bool = False
    ) -> None:
        """Display status view."""
        if getattr(args, "watch", False) and not as_json:
            try:
                while True:
                    console.clear()
                    run_status_view(cwd=cwd, as_json=False)
                    time.sleep(2)
            except KeyboardInterrupt:
                pass
        else:
            run_status_view(cwd=cwd, as_json=as_json)

    def _resume_mission(
        self, args: argparse.Namespace, cwd: Path, as_json: bool = False
    ) -> None:
        """Resume an interrupted mission."""
        state = State(self.db_path, cwd=cwd)
        target_id = (
            getattr(args, "res_mission_id", None)
            or args.mission_id
            or state.get_last_mission_id()
        )
        if not target_id:
            if as_json:
                print(
                    json.dumps(
                        {"status": "error", "error": "No mission to resume"}, indent=2
                    )
                )
            else:
                console.print("[bold red]No mission to resume.[/bold red]")
            sys.exit(1)

        if not as_json:
            console.print(f"[bold green]Resuming mission '{target_id}'...[/bold green]")
        driver = MissionDriver(
            state,
            mission_id=target_id,
            working_directory=str(cwd) if args.cwd else None,
        )
        result = driver.run(target_id)
        if as_json:
            print(json.dumps(result, indent=2))
        else:
            console.print(
                f"[bold cyan]Execution finished with status: {result.get('final_status')}[/bold cyan]"
            )


def main():
    """Main entry point for CLI."""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
