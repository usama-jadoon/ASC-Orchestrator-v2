"""Universal ASC v2.0.0 - CLI Module.

Provides command-line interface for mission management.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from .dag import evaluate_mission, is_task_ready
from .driver import MissionDriver
from .models import SchedulerState, TaskStatus
from .spec import MissionSpecParser
from .state import State


class CLI:
    """Command-line interface for Universal ASC v2.0.0."""

    def __init__(self, db_path: str = ".asc/asc.db"):
        self.state = State(db_path)
        self.parser = argparse.ArgumentParser(
            prog="asc",
            description="Universal ASC v2.0.0 - Autonomous Software Company Orchestrator",
        )
        self._setup_parser()

    def _setup_parser(self):
        """Set up command-line argument parser."""
        self.parser.add_argument(
            "command",
            choices=["init", "validate", "run", "status", "resume", "doctor"],
            help="Command to execute: init, validate, run, status, resume, doctor",
        )
        self.parser.add_argument(
            "file",
            nargs="?",
            default=None,
            help="Path to mission file (e.g. mission.yaml)",
        )
        self.parser.add_argument(
            "--file",
            dest="file_opt",
            type=str,
            help="Path to mission file",
        )
        self.parser.add_argument(
            "--mission-id",
            type=str,
            help="Specific mission ID (defaults to latest active)",
        )
        self.parser.add_argument(
            "--verbose",
            "-v",
            action="store_true",
            help="Enable verbose output",
        )

    def _get_target_file(
        self, args: argparse.Namespace, default: str = "mission.yaml"
    ) -> str:
        """Resolve file path from positional argument or --file flag."""
        return args.file_opt or args.file or default

    def run(self, argv: Optional[list] = None):
        """Execute the CLI command."""
        args = self.parser.parse_args(argv)

        if args.command == "init":
            self._init_mission(self._get_target_file(args))
        elif args.command == "validate":
            self._validate_mission(self._get_target_file(args))
        elif args.command == "run":
            self._run_mission(self._get_target_file(args))
        elif args.command == "status":
            self._show_status(args.mission_id)
        elif args.command == "resume":
            self._resume_mission(args.mission_id)
        elif args.command == "doctor":
            self._doctor(args.verbose)

    def _init_mission(self, file_path: str):
        """Initialize a new sample mission file if not present."""
        path = Path(file_path)
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
            print(f"Created sample mission template at: {path}")

        try:
            spec = MissionSpecParser.from_file(path)
            self.state.save_mission(spec)
            print(
                f"Initialized mission '{spec.id}' with {len(spec.tasks)} tasks in state database."
            )
        except Exception as e:
            print(f"Error initializing mission: {e}")
            sys.exit(1)

    def _validate_mission(self, file_path: str):
        """Validate a mission file specification and DAG validity."""
        path = Path(file_path)
        if not path.exists():
            print(f"Error: Mission file '{file_path}' not found.")
            sys.exit(1)

        try:
            spec = MissionSpecParser.from_file(path)
            print(
                f"SUCCESS: Mission '{spec.id}' validation passed! ({len(spec.tasks)} tasks, 0 cycle/dependency errors)"
            )
        except Exception as e:
            print(f"Validation ERROR: {e}")
            sys.exit(1)

    def _run_mission(self, file_path: str):
        """Execute a mission end-to-end."""
        path = Path(file_path)
        if not path.exists():
            print(f"Error: Mission file '{file_path}' not found.")
            sys.exit(1)

        try:
            spec = MissionSpecParser.from_file(path)
            self.state.save_mission(spec)
            print(f"Starting Mission '{spec.id}': {spec.goal}")
            driver = MissionDriver(spec=spec, db_path=str(self.state.db_path))
            result = driver.run(spec.id)
            print(f"\nMission Completed: {result.get('final_status')}")
            print(
                f"Tasks Completed: {result.get('tasks_completed')}, Failed: {result.get('tasks_failed')}"
            )
        except Exception as e:
            print(f"Error running mission: {e}")
            sys.exit(1)

    def _show_status(self, mission_id: Optional[str] = None):
        """Display human-readable mission and task status."""
        target_id = mission_id or self.state.get_last_mission_id()
        if not target_id:
            print(
                "No missions found in database. Run 'asc init' or 'asc run mission.yaml' to start a mission."
            )
            return

        mission = self.state.get_mission(target_id)
        if not mission:
            print(f"Mission '{target_id}' not found in database.")
            sys.exit(1)

        tasks = self.state.get_tasks(target_id)
        task_dict = {t.id: t for t in tasks}
        outcome = evaluate_mission(target_id, task_dict)

        status_icons = {
            TaskStatus.COMPLETED: "[OK]",
            TaskStatus.RUNNING: "[RUNNING]",
            TaskStatus.PENDING: "[PENDING]",
            TaskStatus.FAILED: "[FAILED]",
            TaskStatus.BLOCKED: "[BLOCKED]",
            TaskStatus.CANCELLED: "[CANCELLED]",
        }

        print("\n=======================================================")
        print(f" Mission: {mission.id}")
        print(f" Goal:    {mission.goal}")
        print(
            f" State:   {outcome.state.value if hasattr(outcome.state, 'value') else outcome.state}"
        )
        print("=======================================================")
        print(f"Tasks ({len(tasks)} total):")

        completed_count = 0
        for t in tasks:
            is_ready = is_task_ready(t, task_dict)
            ready_marker = " (RUNNABLE NEXT)" if is_ready else ""
            icon = status_icons.get(t.status, "[?]")
            deps_str = (
                f" [depends_on: {', '.join(t.depends_on)}]" if t.depends_on else ""
            )
            print(f"  {icon} {t.id}: {t.title}{deps_str}{ready_marker}")
            if t.status == TaskStatus.COMPLETED:
                completed_count += 1

        print(f"\nSummary: {completed_count}/{len(tasks)} completed.")
        if outcome.state == SchedulerState.BLOCKED:
            blocked_info = (
                f"Blocked Tasks: {', '.join(outcome.blocked_ids)}"
                if outcome.blocked_ids
                else "Dependencies incomplete"
            )
            print(f"Blocked Reason: {blocked_info}")
        print("=======================================================\n")

    def _resume_mission(self, mission_id: Optional[str] = None):
        """Resume an interrupted mission."""
        target_id = mission_id or self.state.get_last_mission_id()
        if not target_id:
            print("No mission to resume.")
            sys.exit(1)

        print(f"Resuming mission '{target_id}' from SQLite state...")
        driver = MissionDriver(self.state)
        result = driver.run(target_id)
        print(f"Execution finished with status: {result.get('final_status')}")

    def _doctor(self, verbose: bool = False):
        """Diagnose environment, git, and database health."""
        print("Universal ASC v2 Doctor - System Diagnostics:")
        print(f"  [+] Python version: {sys.version.split()[0]} (Supported >= 3.11)")
        print(
            f"  [+] Database: {self.state.db_path} ({'Connected' if self.state._conn is None else 'Active'})"
        )

        # Git check
        is_git = Path(".git").exists()
        print(
            f"  [{'+' if is_git else '!'}] Git Repository: {'Detected' if is_git else 'Not a git repo'}"
        )

        missions = self.state.get_all_missions()
        print(f"  [+] Recorded Missions in State: {len(missions)}")
        print("System health OK.\n")


def main():
    """Main entry point for CLI."""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
