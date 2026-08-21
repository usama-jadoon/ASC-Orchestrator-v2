"""Universal ASC v2.2.0 - Professional Terminal Operator Console.

Provides rich terminal rendering, interactive REPL console, diagnostic dashboards,
and real-time event displays following UI/UX Pro Max Developer Tool guidelines.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output encoding on Windows consoles
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .lock import ProjectLock
from .models import Task, TaskStatus
from .repo import Repository
from .spec import MissionSpecParser
from .state import State

VERSION = "2.2.0"
console = Console(safe_box=True)


def get_git_info(cwd: str | Path = ".") -> Dict[str, Any]:
    """Retrieve Git repository metadata."""
    repo = Repository(cwd)
    if not repo.is_git_repo():
        return {
            "is_git": False,
            "root": str(Path(cwd).resolve()),
            "name": Path(cwd).resolve().name,
            "branch": "N/A",
            "head": "N/A",
            "clean": True,
            "dirty_count": 0,
            "dirty_files": [],
        }
    status = repo.get_porcelain_status()
    return {
        "is_git": True,
        "root": str(repo.get_root_dir()),
        "name": repo.get_repo_name(),
        "branch": repo.get_current_branch() or "HEAD",
        "head": (repo.get_head_commit() or "")[:8],
        "clean": status.is_clean,
        "dirty_count": len(status.all_dirty),
        "dirty_files": status.all_dirty,
    }


def render_header(
    git_info: Dict[str, Any],
    state_name: str = "READY",
    elapsed: str = "00:00:00",
    model: Optional[str] = None,
    executor: str = "OMP",
) -> Panel:
    """Render top developer dashboard header."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right", ratio=1)

    status_style = (
        "bold green"
        if state_name in ("READY", "COMPLETE")
        else ("bold yellow" if state_name == "RUNNING" else "bold red")
    )
    status_icon = "*" if state_name in ("READY", "RUNNING") else "+"

    left_text = Text()
    left_text.append("ASC DevOS ", style="bold bright_white")
    left_text.append(f"v{VERSION}", style="dim cyan")

    right_text = Text()
    right_text.append(f"{status_icon} SYSTEM {state_name}", style=status_style)
    grid.add_row(left_text, right_text)

    # Sub-grid metadata
    info_table = Table.grid(expand=True, padding=(0, 2))
    info_table.add_column(style="dim white", width=10)
    info_table.add_column(style="bold white", ratio=1)
    info_table.add_column(style="dim white", width=10)
    info_table.add_column(style="bold white", ratio=1)

    git_badge = (
        "[bold green]CLEAN[/bold green]"
        if git_info.get("clean")
        else f"[bold red]DIRTY ({git_info.get('dirty_count')} files)[/bold red]"
    )
    branch_str = str(git_info.get("branch", "main"))
    if len(branch_str) > 22:
        branch_str = branch_str[:20] + "..."

    repo_str = str(git_info.get("name", "Project"))
    if len(repo_str) > 22:
        repo_str = repo_str[:20] + "..."

    model_display = model or "omniroute/auto (configured)"

    info_table.add_row("Project", repo_str, "Branch", branch_str)
    info_table.add_row(
        "Git", git_badge, "State", f"[{status_style}]{state_name}[/{status_style}]"
    )
    info_table.add_row("Executor", executor, "Route", model_display)
    info_table.add_row("Runtime", elapsed, "HEAD", git_info.get("head", "N/A"))

    main_grid = Table.grid(expand=True)
    main_grid.add_row(grid)
    main_grid.add_row(Text("-" * 70, style="dim #334155"))
    main_grid.add_row(info_table)

    return Panel(
        main_grid,
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_mission_panel(
    tasks: List[Task], mission_goal: str = "No active mission"
) -> Panel:
    """Render mission DAG and progress panel."""
    table = Table(box=None, expand=True, show_header=False, padding=(0, 1))
    table.add_column("Icon", width=3)
    table.add_column("ID", style="bold white", width=16)
    table.add_column("Status", width=12)
    table.add_column("Details", style="dim white")

    total_tasks = len(tasks)
    completed_tasks = 0

    if not tasks:
        table.add_row(
            "o", "No tasks", "[dim]IDLE[/dim]", "Load or run a mission to start"
        )
    else:
        for t in tasks:
            if t.status == TaskStatus.COMPLETED:
                icon = "[bold green]+[/bold green]"
                st = "[bold green]COMPLETE[/bold green]"
                completed_tasks += 1
            elif t.status == TaskStatus.RUNNING:
                icon = "[bold yellow]*[/bold yellow]"
                st = "[bold yellow]RUNNING[/bold yellow]"
            elif t.status == TaskStatus.FAILED:
                icon = "[bold red]X[/bold red]"
                st = "[bold red]FAILED[/bold red]"
            elif t.status == TaskStatus.BLOCKED:
                icon = "[bold red]![/bold red]"
                st = "[bold red]BLOCKED[/bold red]"
            else:
                icon = "[dim white]o[/dim white]"
                st = "[dim white]PENDING[/dim white]"

            task_title = t.title[:24] + "..." if len(t.title) > 25 else t.title
            table.add_row(icon, t.id, st, task_title)

    pct = int((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0
    filled = int(pct / 10)
    bar = "=" * filled + "-" * (10 - filled)
    progress_str = f"[bold green][{bar}][/bold green] {pct}% ({completed_tasks}/{total_tasks} tasks)"

    grid = Table.grid(expand=True)
    grid.add_row(Text(f"Goal: {mission_goal}", style="italic dim white"))
    grid.add_row(Text("-" * 36, style="dim #334155"))
    grid.add_row(table)
    grid.add_row(Text("-" * 36, style="dim #334155"))
    grid.add_row(Text(progress_str))

    return Panel(
        grid,
        title="[bold white]MISSION[/bold white]",
        border_style="blue",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_runtime_panel(
    executor_status: str = "READY",
    attempt: str = "1 / 1",
    lock_status: str = "FREE",
    changed_files: int = 0,
    elapsed: str = "00:00:00",
    exec_phase: str = "IDLE",
    verify_phase: str = "WAITING",
) -> Panel:
    """Render runtime telemetry panel."""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(style="dim white", width=14)
    table.add_column(style="bold white", justify="right")

    lock_badge = (
        "[bold green]HELD[/bold green]"
        if lock_status == "HELD"
        else "[dim white]FREE[/dim white]"
    )

    table.add_row("OMP Runtime", f"[bold green]{executor_status}[/bold green]")
    table.add_row("Attempt", attempt)
    table.add_row(
        "Execution",
        f"[bold yellow]{exec_phase}[/bold yellow]"
        if exec_phase == "RUNNING"
        else f"[dim white]{exec_phase}[/dim white]",
    )
    table.add_row(
        "Verification",
        f"[bold green]{verify_phase}[/bold green]"
        if verify_phase == "PASS"
        else f"[dim white]{verify_phase}[/dim white]",
    )
    table.add_row("Project Lock", lock_badge)
    table.add_row("Changed Files", f"{changed_files} delta")
    table.add_row("Elapsed", elapsed)

    return Panel(
        table,
        title="[bold white]RUNTIME[/bold white]",
        border_style="blue",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_activity_panel(events: List[Dict[str, Any]], max_events: int = 6) -> Panel:
    """Render recent activity log panel."""
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(style="dim #94A3B8", width=10)
    grid.add_column(style="bold white", width=22)
    grid.add_column(style="dim white", ratio=1)

    recent = events[-max_events:] if events else []
    if not recent:
        grid.add_row("--:--:--", "IDLE", "Awaiting operator commands...")
    else:
        for ev in recent:
            ts = time.strftime(
                "%H:%M:%S", time.localtime(ev.get("timestamp", time.time()))
            )
            ev_type = str(ev.get("event_type", "EVENT"))
            msg = ev.get("message") or str(ev.get("payload", ""))
            if len(msg) > 50:
                msg = msg[:47] + "..."
            grid.add_row(ts, f"[cyan]{ev_type}[/cyan]", msg)

    return Panel(
        grid,
        title="[bold white]ACTIVITY[/bold white]",
        border_style="#334155",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def run_doctor(cwd: str | Path = ".") -> None:
    """Run comprehensive ASC doctor diagnostics and print dashboard."""
    cwd_path = Path(cwd).resolve()
    git_info = get_git_info(cwd_path)
    state = State(cwd=cwd_path)

    # Check OMP
    omp_found = shutil.which("omp") or shutil.which("omp.exe")
    if not omp_found:
        home = Path.home()
        bun_omp = home / ".bun" / "bin" / "omp.exe"
        if bun_omp.exists():
            omp_found = str(bun_omp)

    omp_status = (
        f"[bold green]FOUND[/bold green] ({omp_found})"
        if omp_found
        else "[bold red]NOT FOUND[/bold red]"
    )

    # Lock check
    repo = Repository(cwd_path)
    lock_dir = (
        repo.get_root_dir() / ".git" / "asc"
        if repo.is_git_repo()
        else cwd_path / ".asc"
    )
    lock = ProjectLock(lock_dir)
    lock_info = lock.get_lock_info()
    lock_status_str = (
        f"[bold yellow]HELD[/bold yellow] (PID {lock_info.get('pid') if lock_info else 'unknown'})"
        if lock.is_locked()
        else "[bold green]FREE[/bold green]"
    )

    # Missions
    missions = state.get_all_missions(limit=5)
    last_mission = state.get_last_mission_id() or "None"

    table = Table(
        title=f"ASC DevOS v{VERSION} - System Diagnostics",
        box=box.ROUNDED,
        border_style="cyan",
    )
    table.add_column("Component", style="bold white", width=22)
    table.add_column("Status / Path", style="dim white")

    table.add_row("ASC Core Version", f"[bold green]{VERSION}[/bold green]")
    table.add_row("Python Runtime", f"{platform.python_version()} ({sys.executable})")
    table.add_row("Project Root", git_info["root"])
    table.add_row("Repository Name", git_info["name"])
    table.add_row("Git Branch / HEAD", f"{git_info['branch']} @ {git_info['head']}")
    table.add_row(
        "Git Working Tree",
        "[bold green]CLEAN[/bold green]"
        if git_info["clean"]
        else f"[bold red]DIRTY ({git_info['dirty_count']} files)[/bold red]",
    )
    table.add_row("ASC State Path", str(state.db_path))
    table.add_row("OMP Executable", omp_status)
    table.add_row("Execution Lock", lock_status_str)
    table.add_row(
        "Configured Route", os.environ.get("OMP_MODEL", "omniroute/auto (default)")
    )
    table.add_row("OmniRoute Gateway", "[dim yellow]UNKNOWN / NOT PROBED[/dim yellow]")
    table.add_row(
        "Total Missions", f"{len(missions)} recorded (Latest: {last_mission})"
    )

    console.print(table)


def run_status_view(cwd: str | Path = ".") -> None:
    """Print current repository and mission status snapshot."""
    cwd_path = Path(cwd).resolve()
    git_info = get_git_info(cwd_path)
    state = State(cwd=cwd_path)

    last_mission_id = state.get_last_mission_id()
    mission = state.get_mission(last_mission_id) if last_mission_id else None
    tasks = state.get_tasks(last_mission_id) if last_mission_id else []

    header = render_header(
        git_info=git_info,
        state_name=mission.status if mission else "READY",
        model=getattr(mission, "model", None) if mission else None,
        executor=getattr(mission, "executor", "OMP") if mission else "OMP",
    )
    mission_panel = render_mission_panel(
        tasks, mission_goal=mission.goal if mission else "No mission active"
    )
    runtime_panel = render_runtime_panel(
        executor_status="READY" if shutil.which("omp") else "UNAVAILABLE",
        attempt="1 / 1",
    )
    events = (
        state.get_events(mission_id=last_mission_id, limit=5) if last_mission_id else []
    )
    activity = render_activity_panel(events)

    body = Table.grid(expand=True)
    body.add_column(ratio=1)
    body.add_column(ratio=1)
    body.add_row(mission_panel, runtime_panel)

    console.print(header)
    console.print(body)
    console.print(activity)


def run_logs_view(
    mission_id: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 50,
    cwd: str | Path = ".",
) -> None:
    """Display formatted event logs."""
    state = State(cwd=cwd)
    mid = mission_id or state.get_last_mission_id()
    events = state.get_events(mission_id=mid, task_id=task_id, limit=limit)

    if not events:
        console.print(
            f"[dim yellow]No events found for mission '{mid or 'all'}'.[/dim yellow]"
        )
        return

    table = Table(
        title=f"ASC Mission Event Ledger (Mission: {mid or 'all'})",
        box=box.SIMPLE_HEAVY,
        border_style="cyan",
    )
    table.add_column("Time", style="dim #94A3B8", width=10)
    table.add_column("Task ID", style="bold white", width=14)
    table.add_column("Event Type", style="cyan", width=24)
    table.add_column("Payload / Details", style="dim white")

    for ev in events:
        ts = time.strftime("%H:%M:%S", time.localtime(ev.get("timestamp", time.time())))
        tid = ev.get("task_id") or "-"
        ev_type = ev.get("event_type", "EVENT")
        payload = ev.get("payload", {})
        payload_str = (
            ", ".join(f"{k}={v}" for k, v in payload.items())
            if isinstance(payload, dict)
            else str(payload)
        )
        table.add_row(ts, tid, ev_type, payload_str)

    console.print(table)


class InteractiveConsole:
    """Interactive REPL terminal operator console for ASC DevOS."""

    def __init__(self, cwd: str | Path = "."):
        self.cwd = Path(cwd).resolve()
        self.state = State(cwd=self.cwd)
        self.running = True

    def start(self) -> None:
        """Start interactive REPL session."""
        console.clear()
        git_info = get_git_info(self.cwd)
        last_mid = self.state.get_last_mission_id()
        mission = self.state.get_mission(last_mid) if last_mid else None
        tasks = self.state.get_tasks(last_mid) if last_mid else []

        header = render_header(
            git_info, state_name=mission.status if mission else "READY"
        )
        m_panel = render_mission_panel(
            tasks, mission_goal=mission.goal if mission else "No mission active"
        )
        r_panel = render_runtime_panel()
        act_panel = render_activity_panel(
            self.state.get_events(mission_id=last_mid, limit=4) if last_mid else []
        )

        body = Table.grid(expand=True)
        body.add_column(ratio=1)
        body.add_column(ratio=1)
        body.add_row(m_panel, r_panel)

        console.print(header)
        console.print(body)
        console.print(act_panel)
        console.print(
            "[dim]Type [bold white]help[/bold white] for commands, [bold white]doctor[/bold white] for diagnostics, or [bold white]exit[/bold white] to quit.[/dim]\n"
        )

        while self.running:
            try:
                cmd_line = console.input("[bold cyan]ASC>[/bold cyan] ").strip()
                if not cmd_line:
                    continue
                self.dispatch(cmd_line)
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Exiting ASC console...[/dim]")
                break

    def dispatch(self, cmd_line: str) -> None:
        """Execute interactive command."""
        parts = cmd_line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("exit", "quit", "q"):
            self.running = False
            console.print("[dim]Goodbye.[/dim]")
        elif cmd in ("help", "?"):
            self.show_help()
        elif cmd in ("doctor", "d"):
            run_doctor(self.cwd)
        elif cmd in ("status", "s"):
            run_status_view(self.cwd)
        elif cmd in ("logs", "l"):
            run_logs_view(cwd=self.cwd)
        elif cmd in ("clear", "cls"):
            console.clear()
        elif cmd == "project":
            git = get_git_info(self.cwd)
            console.print(f"[bold]Project Root:[/bold] {git['root']}")
            console.print(f"[bold]Branch:[/bold] {git['branch']} (HEAD: {git['head']})")
            console.print(
                f"[bold]Clean:[/bold] {git['clean']} (Dirty: {git['dirty_count']} files)"
            )
        elif cmd == "missions":
            missions = self.state.get_all_missions(limit=10)
            if not missions:
                console.print("[dim yellow]No missions recorded.[/dim yellow]")
            else:
                table = Table(title="Recorded Missions", box=box.SIMPLE)
                table.add_column("Mission ID", style="bold cyan")
                table.add_column("Goal", style="white")
                table.add_column("Status", style="bold green")
                for m in missions:
                    table.add_row(m.id, m.goal[:40], m.status)
                console.print(table)
        elif cmd == "run":
            if not args:
                console.print("[bold red]Usage:[/bold red] run <mission.yaml>")
            else:
                from .driver import MissionDriver

                spec_file = args[0]
                if not Path(spec_file).exists():
                    console.print(f"[bold red]File not found:[/bold red] {spec_file}")
                    return
                try:
                    spec = MissionSpecParser.from_file(spec_file)
                    driver = MissionDriver(spec=spec, working_directory=str(self.cwd))
                    console.print(
                        f"[bold green]Starting mission '{spec.id}'...[/bold green]"
                    )
                    res = driver.run()
                    console.print(
                        f"[bold cyan]Mission finished with status: {res['final_status']}[/bold cyan]"
                    )
                except Exception as exc:
                    console.print(f"[bold red]Error running mission:[/bold red] {exc}")
        elif cmd == "resume":
            from .driver import MissionDriver

            mid = args[0] if args else self.state.get_last_mission_id()
            if not mid:
                console.print("[bold red]No mission to resume.[/bold red]")
                return
            try:
                driver = MissionDriver(
                    self.state, mission_id=mid, working_directory=str(self.cwd)
                )
                console.print(f"[bold green]Resuming mission '{mid}'...[/bold green]")
                res = driver.run()
                console.print(
                    f"[bold cyan]Mission finished with status: {res['final_status']}[/bold cyan]"
                )
            except Exception as exc:
                console.print(f"[bold red]Error resuming mission:[/bold red] {exc}")
        else:
            console.print(
                f"[dim red]Unknown command '{cmd}'. Type [bold white]help[/bold white] for options.[/dim red]"
            )

    def show_help(self) -> None:
        """Display help sheet."""
        table = Table(
            title="ASC DevOS Interactive Commands", box=box.ROUNDED, border_style="cyan"
        )
        table.add_column("Command", style="bold cyan", width=18)
        table.add_column("Shortcut", style="bold yellow", width=10)
        table.add_column("Description", style="white")

        table.add_row(
            "status", "s", "Display live project, mission, and task dashboard"
        )
        table.add_row("doctor", "d", "Run full system diagnostic checks")
        table.add_row("run <file>", "r", "Execute a mission YAML specification")
        table.add_row("resume [id]", "r", "Resume the last or specified mission")
        table.add_row("logs", "l", "Inspect chronological mission event ledger")
        table.add_row(
            "project", "p", "Show repository root, branch, and porcelain status"
        )
        table.add_row("missions", "m", "List all past and active missions")
        table.add_row("clear", "cls", "Clear terminal screen")
        table.add_row("help", "?", "Display this help screen")
        table.add_row("exit / quit", "q", "Exit interactive console")

        console.print(table)
