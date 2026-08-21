"""Universal ASC v2.3.0 - Professional Terminal Operator Console.

Provides rich terminal rendering, interactive REPL console, diagnostic dashboards,
and real-time event displays following UI/UX Pro Max Developer Tool guidelines.
"""

from __future__ import annotations

import json
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

VERSION = "2.3.0"
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
            "full_head": "N/A",
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
        "full_head": repo.get_head_commit() or "N/A",
        "clean": status.is_clean,
        "dirty_count": len(status.all_dirty),
        "dirty_files": status.all_dirty,
    }


def render_header(
    git_info: Dict[str, Any],
    state_name: str = "READY",
    mission_status: str = "IDLE",
    elapsed: str = "00:00:00",
    model: Optional[str] = None,
    executor: str = "OMP",
) -> Panel:
    """Render top developer dashboard header."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right", ratio=1)

    sys_style = (
        "bold green"
        if state_name in ("READY", "COMPLETE")
        else ("bold yellow" if state_name == "RUNNING" else "bold red")
    )
    sys_icon = "*" if state_name in ("READY", "RUNNING") else "+"

    left_text = Text()
    left_text.append("ASC Orchestrator ", style="bold bright_white")
    left_text.append(f"v{VERSION}", style="dim cyan")

    right_text = Text()
    right_text.append(f"{sys_icon} SYSTEM {state_name}", style=sys_style)
    grid.add_row(left_text, right_text)

    # Sub-grid metadata
    info_table = Table.grid(expand=True, padding=(0, 2))
    info_table.add_column(style="dim #94A3B8", width=12)
    info_table.add_column(style="bold white", ratio=1)
    info_table.add_column(style="dim #94A3B8", width=12)
    info_table.add_column(style="bold white", ratio=1)

    git_badge = (
        Text.from_markup("[bold green]CLEAN[/bold green]")
        if git_info.get("clean")
        else Text.from_markup(
            f"[bold red]DIRTY ({git_info.get('dirty_count')} files)[/bold red]"
        )
    )

    branch_full = str(git_info.get("branch", "main"))
    branch_display = branch_full[:24] + "..." if len(branch_full) > 26 else branch_full

    repo_full = str(git_info.get("name", "Project"))
    repo_display = repo_full[:24] + "..." if len(repo_full) > 26 else repo_full

    model_display = model or (
        os.environ.get("OMP_MODEL") or "omniroute/auto (configured)"
    )

    m_style = (
        "bold green"
        if mission_status == "COMPLETE"
        else (
            "bold yellow"
            if mission_status == "RUNNING"
            else (
                "bold red" if mission_status in ("BLOCKED", "FAILED") else "dim white"
            )
        )
    )
    m_badge = Text.from_markup(f"[{m_style}]{mission_status}[/{m_style}]")

    info_table.add_row("Project", repo_display, "Branch", branch_display)
    info_table.add_row("Git Status", git_badge, "Mission", m_badge)
    info_table.add_row("Executor", executor, "Route", model_display)
    info_table.add_row("Runtime", elapsed, "HEAD", git_info.get("head", "N/A"))

    main_grid = Table.grid(expand=True)
    main_grid.add_row(grid)
    main_grid.add_row(Text("-" * 72, style="dim #334155"))
    main_grid.add_row(info_table)

    return Panel(
        main_grid,
        border_style="#334155",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _render_progress_bar(completed: int, total: int, width: int = 30) -> Text:
    """Render a styled Rich Text progress bar."""
    pct = int((completed / total) * 100) if total > 0 else 0
    filled = int((pct / 100) * width) if width > 0 else 0
    bar = Text()
    bar.append("[", style="dim #475569")
    bar.append("=" * filled, style="bold green")
    if filled < width:
        bar.append("-" * (width - filled), style="dim #334155")
    bar.append(f"] {pct}% ({completed}/{total} tasks)", style="bold white")
    return bar


def render_mission_panel(
    tasks: List[Task],
    mission_goal: str = "",
) -> Panel:
    """Render structured task table with progress bar."""
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)

    table = Table(
        box=box.SIMPLE_HEAD,
        border_style="#334155",
        header_style="bold #94A3B8",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Task ID", style="bold white", width=10)
    table.add_column("Title", style="white", ratio=1)
    table.add_column("Status", justify="right", width=14)

    status_styles = {
        TaskStatus.COMPLETED: ("[bold green]DONE[/bold green]", "COMPLETED"),
        TaskStatus.RUNNING: ("[bold yellow]RUNNING[/bold yellow]", "RUNNING"),
        TaskStatus.FAILED: ("[bold red]FAILED[/bold red]", "FAILED"),
        TaskStatus.BLOCKED: ("[bold red]BLOCKED[/bold red]", "BLOCKED"),
        TaskStatus.PENDING: ("[dim white]PENDING[/dim white]", "PENDING"),
        TaskStatus.CANCELLED: ("[dim red]CANCELLED[/dim red]", "CANCELLED"),
        TaskStatus.INTERRUPTED: (
            "[bold yellow]INTERRUPTED[/bold yellow]",
            "INTERRUPTED",
        ),
    }

    for task in tasks:
        markup, _ = status_styles.get(
            task.status, (f"[dim]{task.status.value}[/dim]", str(task.status))
        )
        table.add_row(task.id, task.title, Text.from_markup(markup))

    if not tasks:
        table.add_row(
            "-", "No active mission — run <mission-file> to start", "[dim]EMPTY[/dim]"
        )

    bar_text = _render_progress_bar(completed, total, width=30)

    layout = Table.grid(expand=True)
    if mission_goal:
        goal_text = Text(f"Goal: {mission_goal}", style="dim #94A3B8")
        layout.add_row(goal_text)
    layout.add_row(bar_text)
    layout.add_row(table)

    return Panel(
        layout,
        title="[bold white]MISSION PROGRESS[/bold white]",
        border_style="#334155",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_runtime_panel(
    executor_status: str = "READY",
    attempt: str = "— / —",
    exec_phase: str = "IDLE",
    verify_phase: str = "IDLE",
    last_action: str = "Idle",
    changed_files_count: int = 0,
    lock_status: str = "FREE",
    has_active_mission: bool = False,
    **kwargs: Any,
) -> Panel:
    """Render runtime & verification execution metrics."""
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(style="dim #94A3B8", width=18)
    grid.add_column(style="bold white", ratio=1)

    effective_exec_phase = (
        exec_phase
        if exec_phase != "IDLE"
        else ("RUNNING" if has_active_mission else "IDLE")
    )
    effective_verify_phase = (
        verify_phase
        if verify_phase != "IDLE"
        else ("PASSING" if has_active_mission else "IDLE")
    )

    grid.add_row("Executor Engine", executor_status)
    grid.add_row("Attempt", attempt if has_active_mission else "— / —")
    grid.add_row("Execution Phase", effective_exec_phase)
    grid.add_row("Verification", effective_verify_phase)
    grid.add_row(
        "Changed Files",
        f"{changed_files_count} changes" if changed_files_count > 0 else "0 changes",
    )
    grid.add_row("Lock Status", lock_status)
    grid.add_row("Last Action", last_action)

    return Panel(
        grid,
        title="[bold white]RUNTIME TELEMETRY[/bold white]",
        border_style="#334155",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def render_activity_panel(events: List[Dict[str, Any]]) -> Panel:
    """Render recent chronological events list."""
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(style="dim #64748B", width=10)
    grid.add_column(style="bold cyan", width=22)
    grid.add_column(style="white", ratio=1)

    if not events:
        grid.add_row("-", "NO RECENT EVENTS", "System ready for commands")
    else:
        for ev in events:
            ts = time.strftime(
                "%H:%M:%S", time.localtime(ev.get("timestamp", time.time()))
            )
            ev_type = ev.get("event_type", "EVENT")
            type_styled = (
                f"[bold green]{ev_type}[/bold green]"
                if "PASSED" in ev_type or "COMPLETED" in ev_type
                else (
                    f"[bold red]{ev_type}[/bold red]"
                    if "FAILED" in ev_type or "BLOCKED" in ev_type
                    else f"[bold cyan]{ev_type}[/bold cyan]"
                )
            )
            payload = ev.get("payload", {})
            if isinstance(payload, dict):
                msg = (
                    payload.get("message")
                    or payload.get("title")
                    or (", ".join(f"{k}={v}" for k, v in payload.items()))
                )
            else:
                msg = str(payload)

            if len(msg) > 55:
                msg = msg[:52] + "..."
            grid.add_row(ts, type_styled, msg)

    return Panel(
        grid,
        title="[bold white]ACTIVITY[/bold white]",
        border_style="#334155",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def get_doctor_snapshot(cwd: str | Path = ".") -> Dict[str, Any]:
    """Retrieve structured system diagnostic snapshot."""
    cwd_path = Path(cwd).resolve()
    git_info = get_git_info(cwd_path)
    state = State(cwd=cwd_path)

    omp_found = shutil.which("omp") or shutil.which("omp.exe")
    if not omp_found:
        home = Path.home()
        bun_omp = home / ".bun" / "bin" / "omp.exe"
        if bun_omp.exists():
            omp_found = str(bun_omp)

    repo = Repository(cwd_path)
    lock_dir = (
        repo.get_root_dir() / ".git" / "asc"
        if repo.is_git_repo()
        else cwd_path / ".asc"
    )
    lock = ProjectLock(lock_dir)
    lock_info = lock.get_lock_info()

    missions = state.get_all_missions(limit=5)
    last_mission = state.get_last_mission_id()

    return {
        "asc_version": VERSION,
        "python_version": f"{platform.python_version()} ({sys.executable})",
        "platform": platform.platform(),
        "git": git_info,
        "state_path": str(state.db_path),
        "omp": {
            "found": bool(omp_found),
            "path": str(omp_found) if omp_found else None,
        },
        "lock": {
            "is_locked": lock.is_locked(),
            "info": lock_info,
        },
        "model_route": os.environ.get("OMP_MODEL", "omniroute/auto (configured)"),
        "total_missions": len(missions),
        "last_mission_id": last_mission,
        "system_status": "READY",
    }


def run_doctor(cwd: str | Path = ".", as_json: bool = False) -> None:
    """Run comprehensive ASC doctor diagnostics."""
    snapshot = get_doctor_snapshot(cwd)
    if as_json:
        print(json.dumps(snapshot, indent=2))
        return

    table = Table(
        title=f"ASC Orchestrator v{VERSION} - System Diagnostics",
        box=box.ROUNDED,
        border_style="cyan",
        expand=True,
    )
    table.add_column("Component", style="bold white", width=22)
    table.add_column("Status / Full Path", style="dim white")

    table.add_row("ASC Core Version", f"[bold green]{VERSION}[/bold green]")
    table.add_row("Python Runtime", snapshot["python_version"])
    table.add_row("Project Root", snapshot["git"]["root"])
    table.add_row("Repository Name", snapshot["git"]["name"])
    table.add_row("Git Branch", snapshot["git"]["branch"])
    table.add_row(
        "Git HEAD Commit",
        str(snapshot["git"].get("full_head", snapshot["git"]["head"])),
    )
    table.add_row(
        "Git Working Tree",
        "[bold green]CLEAN[/bold green]"
        if snapshot["git"]["clean"]
        else f"[bold red]DIRTY ({snapshot['git']['dirty_count']} files)[/bold red]",
    )
    table.add_row("ASC State Path", snapshot["state_path"])
    table.add_row(
        "OMP Executable",
        f"[bold green]FOUND[/bold green] ({snapshot['omp']['path']})"
        if snapshot["omp"]["found"]
        else "[bold red]NOT FOUND[/bold red]",
    )
    table.add_row(
        "Execution Lock",
        f"[bold yellow]HELD[/bold yellow] (PID {snapshot['lock']['info'].get('pid') if snapshot['lock']['info'] else 'unknown'})"
        if snapshot["lock"]["is_locked"]
        else "[bold green]FREE[/bold green]",
    )
    table.add_row("Configured Route", snapshot["model_route"])
    table.add_row("OmniRoute Gateway", "[dim yellow]UNKNOWN / NOT PROBED[/dim yellow]")
    table.add_row(
        "Total Missions",
        f"{snapshot['total_missions']} recorded (Latest: {snapshot['last_mission_id'] or 'None'})",
    )

    console.print(table)


def get_status_snapshot(cwd: str | Path = ".") -> Dict[str, Any]:
    """Retrieve structured status snapshot for machine output."""
    cwd_path = Path(cwd).resolve()
    git_info = get_git_info(cwd_path)
    state = State(cwd=cwd_path)

    last_mission_id = state.get_last_mission_id()
    mission = state.get_mission(last_mission_id) if last_mission_id else None
    tasks = state.get_tasks(last_mission_id) if last_mission_id else []
    events = (
        state.get_events(mission_id=last_mission_id, limit=5) if last_mission_id else []
    )

    return {
        "asc_version": VERSION,
        "git": git_info,
        "mission": {
            "id": mission.id if mission else None,
            "goal": mission.goal if mission else None,
            "status": mission.status if mission else "IDLE",
            "executor": getattr(mission, "executor", "OMP") if mission else "OMP",
            "model": getattr(mission, "model", None) if mission else None,
            "working_directory": getattr(mission, "working_directory", str(cwd_path))
            if mission
            else str(cwd_path),
        }
        if mission
        else None,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value
                if hasattr(t.status, "value")
                else str(t.status),
                "depends_on": t.depends_on,
                "commit_sha": t.commit_sha,
            }
            for t in tasks
        ],
        "recent_events": events,
    }


def run_status_view(cwd: str | Path = ".", as_json: bool = False) -> None:
    """Print current repository and mission status snapshot."""
    if as_json:
        snapshot = get_status_snapshot(cwd)
        print(json.dumps(snapshot, indent=2))
        return

    cwd_path = Path(cwd).resolve()
    git_info = get_git_info(cwd_path)
    state = State(cwd=cwd_path)

    last_mission_id = state.get_last_mission_id()
    mission = state.get_mission(last_mission_id) if last_mission_id else None
    tasks = state.get_tasks(last_mission_id) if last_mission_id else []

    has_active = mission is not None and bool(tasks)

    header = render_header(
        git_info=git_info,
        state_name="READY"
        if not has_active
        else (mission.status if mission else "READY"),
        mission_status=mission.status if mission else "IDLE",
        model=getattr(mission, "model", None) if mission else None,
        executor=getattr(mission, "executor", "OMP") if mission else "OMP",
    )
    mission_panel = render_mission_panel(
        tasks, mission_goal=mission.goal if mission else "No active mission"
    )
    runtime_panel = render_runtime_panel(
        executor_status="READY"
        if (shutil.which("omp") or shutil.which("omp.exe"))
        else "UNAVAILABLE",
        attempt="1 / 1" if has_active else "— / —",
        has_active_mission=has_active,
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
    as_json: bool = False,
) -> None:
    """Display formatted event logs."""
    state = State(cwd=cwd)
    mid = mission_id or state.get_last_mission_id()
    events = state.get_events(mission_id=mid, task_id=task_id, limit=limit)

    if as_json:
        print(json.dumps(events, indent=2))
        return

    if not events:
        console.print(
            f"[dim yellow]No events found for mission '{mid or 'all'}'.[/dim yellow]"
        )
        return

    table = Table(
        title=f"ASC Mission Event Ledger (Mission: {mid or 'all'})",
        box=box.SIMPLE_HEAVY,
        border_style="cyan",
        expand=True,
    )
    table.add_column("Time", style="dim #64748B", width=10)
    table.add_column("Task ID", style="bold white", width=14)
    table.add_column("Event Type", style="bold cyan", width=26)
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
    """Interactive REPL terminal operator console for ASC Orchestrator."""

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
        has_active = mission is not None and bool(tasks)

        header = render_header(
            git_info,
            state_name="READY"
            if not has_active
            else (mission.status if mission else "READY"),
            mission_status=mission.status if mission else "IDLE",
        )
        m_panel = render_mission_panel(
            tasks, mission_goal=mission.goal if mission else "No active mission"
        )
        r_panel = render_runtime_panel(has_active_mission=has_active)
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
            console.print(f"[bold white]Project Root:[/bold white] {git['root']}")
            console.print(f"[bold white]Branch:[/bold white] {git['branch']}")
            console.print(
                f"[bold white]HEAD Commit:[/bold white] {git.get('full_head', git['head'])}"
            )
            clean_str = (
                "[bold green]CLEAN[/bold green]"
                if git["clean"]
                else f"[bold red]DIRTY ({git['dirty_count']} files)[/bold red]"
            )
            console.print(f"[bold white]Git Status:[/bold white] {clean_str}")
            if git["dirty_files"]:
                console.print(f"[dim]Dirty files: {git['dirty_files']}[/dim]")
        elif cmd == "missions":
            missions = self.state.get_all_missions(limit=10)
            if not missions:
                console.print("[dim yellow]No missions recorded.[/dim yellow]")
            else:
                table = Table(title="Recorded Missions", box=box.SIMPLE, expand=True)
                table.add_column("Mission ID", style="bold cyan", width=18)
                table.add_column("Goal", style="white", ratio=1)
                table.add_column("Status", style="bold green", width=12)
                for m in missions:
                    table.add_row(m.id, m.goal, m.status)
                console.print(table)
        elif cmd == "run":
            if not args:
                console.print("[bold red]Usage:[/bold red] run <mission.yaml>")
            else:
                spec_file = args[0]
                if not Path(spec_file).exists():
                    console.print(f"[bold red]File not found:[/bold red] {spec_file}")
                    return
                try:
                    spec = MissionSpecParser.from_file(spec_file)
                    from .driver import MissionDriver

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
            mid = args[0] if args else self.state.get_last_mission_id()
            if not mid:
                console.print("[bold red]No mission to resume.[/bold red]")
                return
            try:
                from .driver import MissionDriver

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
            title="ASC Orchestrator Interactive Commands",
            box=box.ROUNDED,
            border_style="cyan",
            expand=True,
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
