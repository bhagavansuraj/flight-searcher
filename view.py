#!/usr/bin/env python3
"""Flight-searcher live TUI.

Usage:
    uv run python view.py           # one-shot
    uv run python view.py --watch   # refresh every 30 s (Ctrl-C to quit)
    uv run python view.py --watch 60

Reads FLIGHT_WORKER_URL and FLIGHT_WORKER_TOKEN from env or .env file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _get_config() -> tuple[str, str]:
    _load_dotenv()
    url = os.environ.get("FLIGHT_WORKER_URL", "").rstrip("/")
    token = os.environ.get("FLIGHT_WORKER_TOKEN", "")
    if not url or not token:
        console.print("[red]Set FLIGHT_WORKER_URL and FLIGHT_WORKER_TOKEN in env or .env[/red]")
        sys.exit(1)
    return url, token


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_state(url: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{url}/state",
        headers={
            "authorization": f"Bearer {token}",
            "user-agent": "flight-searcher-view/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

ROUTE_FLAGS = {"LHR-BLR": "🇬🇧→🇮🇳", "LHR-ATL": "🇬🇧→🇺🇸", "LHR-LAX": "🇬🇧→🇺🇸"}
ROUTE_NAMES = {"LHR-BLR": "London → Bangalore", "LHR-ATL": "London → Atlanta", "LHR-LAX": "London → Los Angeles"}


def _route_panel(route: str, summary: str | None) -> Panel:
    flag = ROUTE_FLAGS.get(route, "")
    name = ROUTE_NAMES.get(route, route)
    if not summary:
        body = Text("no data yet", style="dim")
    else:
        # "$1489 | 1st | 16h45m | IndiGo via DEL | 8:10PM→5:25PM | 2026-08-26/2026-09-09"
        parts = [p.strip() for p in summary.split("|")]
        body = Text()
        if parts:
            body.append(parts[0], style="bold green")  # price
        for p in parts[1:]:
            body.append(f"  {p}", style="white")
    return Panel(body, title=f"{flag}  [bold]{route}[/bold]  [dim]{name}[/dim]", border_style="cyan", padding=(0, 1))


def _state_panel(state: dict) -> Panel:
    fire = state.get("fire_count", 0)
    mean = state.get("best_mean")
    streak = state.get("no_improve_streak", 0)
    stopped = state.get("stopped", False)
    running = state.get("running", False)

    t = Text()
    if running:
        t.append("🔄 FIRE IN PROGRESS   ", style="bold cyan")
    t.append(f"fires: {fire}", style="bold")
    t.append("   ")
    mean_str = f"{mean:.4f}" if mean is not None else "n/a"
    t.append(f"best mean: {mean_str}", style="bold yellow")
    t.append("   ")
    t.append(f"no-improve streak: {streak}", style="red" if streak >= 3 else "white")
    if stopped:
        t.append("   [bold red]STOPPED[/bold red]")

    ts_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    border = "cyan" if running else ("red" if stopped else "bright_blue")
    return Panel(t, title=f"[bold]flight-searcher[/bold]  [dim]as of {ts_str}[/dim]",
                 border_style=border, padding=(0, 1))


def _log_table(log: list[dict]) -> Table:
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim",
                  expand=True, padding=(0, 1))
    table.add_column("#", style="dim", width=4)
    table.add_column("time (UTC)", width=16)
    table.add_column("kept", width=5, justify="center")
    table.add_column("mean", width=7, justify="right")
    table.add_column("srch", width=5, justify="right", style="dim")
    table.add_column("note", ratio=1)

    for entry in reversed(log[-15:]):
        fire_n = str(entry.get("fire", "?"))
        ts_raw = entry.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).strftime("%m-%d  %H:%M")
        except Exception:
            ts = ts_raw[:16]
        kept = "✓" if entry.get("kept") else "✗"
        kept_style = "green" if entry.get("kept") else "red"
        mean = entry.get("mean")
        mean_str = f"{mean:.4f}" if mean is not None else "n/a"
        searches = str(entry.get("agent_searches", ""))
        note = (entry.get("llm_note") or "")[:120]
        table.add_row(fire_n, ts, f"[{kept_style}]{kept}[/{kept_style}]", mean_str, searches, note)

    return table


def _agent_notes_panel(notes: str) -> Panel:
    body = Text(notes.strip() or "(none)", style="dim" if not notes.strip() else "white")
    return Panel(body, title="[dim]agent notes for this fire[/dim]",
                 border_style="dim", padding=(0, 1))


def build_renderable(data: dict):
    from rich.console import Group
    state = data.get("state", {})
    best = state.get("best_summary_per_route", {})
    log = data.get("run_log", [])
    agent_notes = data.get("agent_notes", "")

    route_panels = Columns(
        [_route_panel(r, best.get(r)) for r in ["LHR-BLR", "LHR-ATL", "LHR-LAX"]],
        equal=True,
        expand=True,
    )
    log_panel = Panel(_log_table(log), title="[dim]run log (latest first)[/dim]",
                      border_style="dim", padding=(0, 0))

    return Group(
        _state_panel(state),
        route_panels,
        _agent_notes_panel(agent_notes),
        log_panel,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Flight-searcher live TUI")
    parser.add_argument(
        "--watch", nargs="?", const=30, type=int, metavar="SECS",
        help="Auto-refresh every N seconds (default 30). Ctrl-C to quit.",
    )
    args = parser.parse_args()

    url, token = _get_config()

    if args.watch:
        interval = args.watch
        with Live(console=console, refresh_per_second=1, screen=True) as live:
            while True:
                try:
                    data = fetch_state(url, token)
                    live.update(build_renderable(data))
                except Exception as e:
                    live.update(Panel(f"[red]fetch error: {e}[/red]"))
                time.sleep(interval)
    else:
        try:
            data = fetch_state(url, token)
        except Exception as e:
            console.print(f"[red]fetch error: {e}[/red]")
            sys.exit(1)
        console.print(build_renderable(data))


if __name__ == "__main__":
    main()
