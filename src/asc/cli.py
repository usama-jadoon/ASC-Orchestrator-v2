"""Universal ASC v2.2.0 - Command-Line Interface.

Provides rich CLI subcommands and launches the interactive Operator Console.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from .console import (
    InteractiveConsole,
    console,
    get_git_info,
    run_doctor,
    run_logs_view,
    run_status_view,
)
from .driver import MissionDriver, build_adapter
from .models import SchedulerState, TaskStatus
from .repo import Repository
from .spec import MissionSpecParser
from .state import State

VERSION = "2.2.0"


class CLI:
    """Command-line interface for Universal ASC DevOS v2.2.0."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.parser = argparse.ArgumentParser(
            prog="asc",
            description=f"ASC DevOS v{VERSION} — Autonomous Software Company Operator Console",
        )
        self._setup_parser()

    def _setup_parser(self):
        """Set up command-line argument parser."""
        self.parser.add_argument(
            "--version",
            action="version",
            version=f"ASC DevOS v{VERSION}",
        )
        self.parser.add_argument(
            "--cwd",
            type=str,
            default=".",
            help="Target repository working directory (defaults to current directory)",
        )
        self.parser.add_argument(
            "--model",
            type=str,
            help="Configured model or provider route (e.g. omniroute/auto/best-free)",
        )
        self.parser.add_argument(
            "--executor",
            type=str,
            help="Executor engine (omp, shell, mock)",
        )
        self.parser.add_argument(
            "--execution-timeout",
            type=int,
            default=600,
            help="Timeout in seconds for coding executor process",
        )
        self.parser.add_argument(
            "--verification-timeout",
            type=int,
            default=300,
            help="Timeout in seconds for verification commands",
        )
        self.parser.add_argument(
            "--mission-id",
            type=str,
            help="Specific mission ID (defaults to latest active)",
        )

        subparsers = self.parser.add_subparsers(dest="command", help="Available subcommands")

        # init
        init_p = subparsers.add_parser("init", help="Initialize a sample mission specification")
        init_p.add_argument("file", nargs="?", default="mission.yaml", help="Path to mission file")

        # validate
        val_p = subparsers.add_parser("validate", help="Validate mission syntax and DAG structure")
        val_p.add_argument("file", nargs="?", default="mission.yaml", help="Path to mission file")

        # run
        run_p = subparsers.add_parser("run", help="Execute a mission end-to-end")
        run_p.add_argument("file", nargs="?", default="mission.yaml", help="Path to mission file")

        # status
        stat_p = subparsers.add_parser("status", help="Show current mission and task status")
        stat_p.add_argument("--watch", action="store_true", help="Continuously watch status")

        # resume
        res_p = subparsers.add_parser("resume", help="Resume interrupted mission")
        res_p.add_argument("mission_id", nargs="?", default=None, help="Mission ID to resume")

        # doctor
        doc_p = subparsers.add_parser("doctor", help="Run comprehensive system diagnostics")
        doc_p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

        # logs
        log_p = subparsers.add_parser("logs", help="Inspect mission event ledger")
        log_p.add_argument("--task", type=str, help="Filter events by task ID")
        log_p.add_argument("--limit", type=int, default=50, help="Max events to display")

    def run(self, argv: Optional[list] = None) -> None:
        """Execute the CLI command or launch interactive console if no subcommand."""
        args = self.parser.parse_args(argv)
        cwd = Path(args.cwd).resolve()

        if not args.command:
            # Primary launch experience: Open interactive terminal operator console
            InteractiveConsole(cwd=cwd).start()
            return

        state = State(self.db_path, cwd=cwd)

        if args.command == "init":
            self._init_mission(args.file, cwd)
        elif args.command == "validate":
            self._validate_mission(args.file, cwd)
        elif args.command == "run":
            self._run_mission(args, cwd)
        elif args.command == "status":
            self._show_status(args, cwd)
        elif args.command == "resume":
            self._resume_mission(args, cwd)
        elif args.command == "doctor":
            run_doctor(cwd=cwd)
        elif args.command == "logs":
            run_logs_view(mission_id=args.mission_id, task_id=args.task, limit=args.limit, cwd=cwd)

    def _init_mission(self, file_path: str, cwd: Path) -> None:
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
            console.print(f"[bold green]Created sample mission template at:[/bold green] {path}")

        try:
            spec = MissionSpecParser.from_file(path)
            state = State(self.db_path, cwd=cwd)
            state.create_mission(spec)
            console.print(
                f"[bold green]Initialized mission '{spec.id}' with {len(spec.tasks)} tasks in state database.[/bold green]"
            )
        except Exception as e:
            console.print(f"[bold red]Error initializing mission:[/bold red] {e}")
            sys.exit(1)

    def _validate_mission(self, file_path: str, cwd: Path) -> None:
        """Validate a mission file specification and DAG validity."""
        path = cwd / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if not path.exists():
            console.print(f"[bold red]Error: Mission file '{path}' not found.[/bold red]")
            sys.exit(1)

        try:
            spec = MissionSpecParser.from_file(path)
            console.print(
                f"[bold green]SUCCESS: Mission '{spec.id}' validation passed![/bold green] "
                f"({len(spec.tasks)} tasks, 0 cycle/dependency errors)"
            )
        except Exception as e:
            console.print(f"[bold red]Validation ERROR:[/bold red] {e}")
            sys.exit(1)

    def _run_mission(self, args: argparse.Namespace, cwd: Path) -> None:
        """Execute a mission end-to-end with dirty-state safety check."""
        path = cwd / args.file if not Path(args.file).is_absolute() else Path(args.file)
        if not path.exists():
            console.print(f"[bold red]Error: Mission file '{path}' not found.[/bold red]")
            sys.exit(1)

        repo = Repository(cwd)
        # Pre-execution clean check
        if repo.is_git_repo() and not repo.is_clean():
            dirty = repo.get_dirty_files()
            console.print(
                f"[bold red]PRE-EXECUTION SAFETY ERROR: Target repository is DIRTY ({len(dirty)} files).[/bold red]\n"
                f"Offending paths: {dirty[:5]}\n"
                "Commit, stash, or clean your working tree before running autonomous missions."
            )
            sys.exit(1)

        try:
            spec = MissionSpecParser.from_file(path)
            if args.model:
                spec.model = args.model
            if args.executor:
                spec.executor = args.executor
            if args.execution_timeout:
                spec.execution_timeout = args.execution_timeout
            if args.verification_timeout:
                spec.verification_timeout = args.verification_timeout

            console.print(f"[bold cyan]Starting Mission '{spec.id}':[/bold cyan] {spec.goal}")
            driver = MissionDriver(
                spec=spec,
                db_path=self.db_path,
                working_directory=str(cwd),
                model=args.model,
                executor=args.executor,
                execution_timeout=args.execution_timeout,
                verification_timeout=args.verification_timeout,
            )
            result = driver.run(spec.id)
            status_color = "green" if result.get("final_status") == "COMPLETE" else "red"
            console.print(f"\n[bold {status_color}]Mission Finished: {result.get('final_status')}[/bold {status_color}]")
            console.print(
                f"Tasks Completed: [bold green]{result.get('tasks_completed')}[/bold green], "
                f"Failed: [bold red]{result.get('tasks_failed')}[/bold red], "
                f"Blocked: [bold yellow]{result.get('tasks_blocked')}[/bold yellow]"
            )
            if result.get("git_commits"):
                console.print(f"Verified Git Commits: {result.get('git_commits')}")
        except Exception as e:
            console.print(f"[bold red]Error running mission:[/bold red] {e}")
            sys.exit(1)

    def _show_status(self, args: argparse.Namespace, cwd: Path) -> None:
        """Display status view."""
        if getattr(args, "watch", False):
            try:
                while True:
                    console.clear()
                    run_status_view(cwd=cwd)
                    time.sleep(2)
            except KeyboardInterrupt:
                pass
        else:
            run_status_view(cwd=cwd)

    def _resume_mission(self, args: argparse.Namespace, cwd: Path) -> None:
        """Resume an interrupted mission."""
        state = State(self.db_path, cwd=cwd)
        target_id = args.mission_id or getattr(args, "mission_id", None) or state.get_last_mission_id()
        if not target_id:
            console.print("[bold red]No mission to resume.[/bold red]")
            sys.exit(1)

        console.print(f"[bold green]Resuming mission '{target_id}'...[/bold green]")
        driver = MissionDriver(state, mission_id=target_id, working_directory=str(cwd))
        result = driver.run(target_id)
        console.print(f"[bold cyan]Execution finished with status: {result.get('final_status')}[/bold cyan]")


def main():
    """Main entry point for CLI."""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
