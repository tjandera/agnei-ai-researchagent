"""
Rich terminal UI for Agnes Research.

Auto-activated when stdout is a TTY (interactive terminal).
Falls back gracefully when piped or in --agent mode.

Usage (internal — called by agnes_research.py):
    from tui import ResearchUI
    ui = ResearchUI(topic="AI coding tools", days=30)
    ui.start()
    executor = ui.wrap_executor(my_executor_fn)
    ...
    ui.stop_live()
    ui.print_report(report_text)
"""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

try:
    from rich.columns import Columns
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

BANNER = (
    "  [bold cyan]Agnes[/bold cyan] [bold white]Research[/bold white]  "
    "[dim]v1.0 · powered by Agnes 2.0 Flash[/dim]"
)

SOURCE_META: Dict[str, Tuple[str, str, str]] = {
    # tool_name  → (icon, label, color)
    "search_reddit":     ("🟠", "Reddit",       "orange1"),
    "search_hackernews": ("🟡", "Hacker News",  "yellow"),
    "search_polymarket": ("📊", "Polymarket",   "cyan"),
    "search_web":        ("🌐", "Web",          "blue"),
    "search_github":     ("🐙", "GitHub",       "white"),
    "search_devto":      ("👩‍💻", "Dev.to",       "magenta"),
    "search_arxiv":      ("📄", "ArXiv",        "green"),
}

STATUS_SEARCHING = "searching…"
STATUS_DONE      = "done"
STATUS_ERROR     = "error"


# ──────────────────────────────────────────────────────────────────────────────
# Search status tracker
# ──────────────────────────────────────────────────────────────────────────────

class _SearchEntry:
    __slots__ = ("icon", "label", "color", "query", "status", "count", "started_at")

    def __init__(self, icon: str, label: str, color: str, query: str):
        self.icon       = icon
        self.label      = label
        self.color      = color
        self.query      = query[:55]
        self.status     = STATUS_SEARCHING
        self.count      = 0
        self.started_at = time.time()

    @property
    def elapsed(self) -> str:
        secs = int(time.time() - self.started_at)
        return f"{secs}s"

    def render_status(self) -> str:
        if self.status == STATUS_DONE:
            if self.count == 0:
                return "[dim]— no results[/dim]"
            return f"[bold green]✓[/bold green] [green]{self.count} result{'s' if self.count != 1 else ''}[/green]"
        if self.status == STATUS_ERROR:
            return "[bold red]✗ error[/bold red]"
        return f"[yellow dim]{STATUS_SEARCHING}[/yellow dim] [dim]{self.elapsed}[/dim]"


class _SourceTracker:
    """Tracks all in-flight and completed searches for the live table."""

    def __init__(self):
        self._entries: List[_SearchEntry] = []
        self._lock = threading.Lock()

    def add(self, tool: str, query: str) -> int:
        icon, label, color = SOURCE_META.get(tool, ("🔍", tool, "white"))
        entry = _SearchEntry(icon, label, color, query)
        with self._lock:
            self._entries.append(entry)
            return len(self._entries) - 1

    def complete(self, idx: int, result_json: str):
        try:
            data = json.loads(result_json)
            if isinstance(data, list):
                count, is_error = len(data), False
            elif isinstance(data, dict) and "error" in data:
                count, is_error = 0, True
            else:
                count, is_error = 1, False
        except Exception:
            count, is_error = 0, True
        with self._lock:
            if 0 <= idx < len(self._entries):
                self._entries[idx].status = STATUS_ERROR if is_error else STATUS_DONE
                self._entries[idx].count  = count

    def render(self) -> Table:
        t = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold dim",
            padding=(0, 1),
            expand=True,
        )
        t.add_column("",       width=3,  no_wrap=True)
        t.add_column("Source", width=14, no_wrap=True)
        t.add_column("Query",  ratio=1)
        t.add_column("Status", width=22, no_wrap=True)

        with self._lock:
            entries = list(self._entries)
        for e in entries:
            t.add_row(
                e.icon,
                f"[{e.color}]{e.label}[/{e.color}]",
                f"[dim]{e.query}[/dim]",
                e.render_status(),
            )
        return t

    @property
    def is_empty(self) -> bool:
        return len(self._entries) == 0


# ──────────────────────────────────────────────────────────────────────────────
# Main UI class
# ──────────────────────────────────────────────────────────────────────────────

class ResearchUI:
    """
    Rich live terminal UI for a single Agnes research session.

    Usage:
        ui = ResearchUI(topic, days)
        ui.start()                              # prints banner, starts Live
        executor = ui.wrap_executor(raw_fn)     # intercept tool calls
        ...                                     # run agentic loop
        report = client.run_agent(..., tool_executor=executor)
        ui.stop_live()                          # freeze the live display
        ui.print_report(report)                 # render markdown
    """

    def __init__(
        self,
        topic: str,
        days: int,
        model: str = "Agnes 2.0 Flash",
        force_plain: bool = False,
    ):
        self.topic       = topic
        self.days        = days
        self.model       = model
        self._tracker    = _SourceTracker()
        self._live: Optional["Live"] = None
        self._start      = time.time()
        self._use_rich   = RICH_AVAILABLE and sys.stdout.isatty() and not force_plain
        self._console    = Console() if self._use_rich else None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self):
        """Print the header and begin the live display."""
        if self._use_rich:
            self._console.print()
            self._console.print(Panel(
                f"{BANNER}\n\n"
                f"  Topic   [bold white]{self.topic}[/bold white]\n"
                f"  Window  [dim]{self.days} days[/dim]  ·  "
                f"Sources  [dim]Reddit · HN · Polymarket · Web[/dim]",
                border_style="cyan",
                padding=(0, 2),
            ))
            self._console.print()
            self._live = Live(
                self._render_live(),
                console=self._console,
                refresh_per_second=6,
                transient=False,
            )
            self._live.__enter__()
        else:
            print(f"\n🔍 Agnes Research: {self.topic}", flush=True)
            print(f"   Look-back: {self.days} days · Model: {self.model}\n", flush=True)

    def stop_live(self):
        """Stop the live area (call before printing the final report)."""
        if self._live:
            self._live.update(self._render_live())   # final refresh
            self._live.__exit__(None, None, None)
            self._live = None
            if self._console:
                self._console.print()

    # ── rendering ─────────────────────────────────────────────────────────

    def _render_live(self):
        if self._tracker.is_empty:
            return Text("  Initializing Agnes 2.0 Flash orchestrator…", style="dim italic")
        return self._tracker.render()

    def _refresh(self):
        if self._live:
            self._live.update(self._render_live())

    # ── tool call hooks ───────────────────────────────────────────────────

    def on_tool_start(self, tool: str, args: dict) -> int:
        """Register a new search. Returns its index."""
        query = args.get("query", "")
        idx = self._tracker.add(tool, query)
        if not self._use_rich:
            icon, label, _ = SOURCE_META.get(tool, ("🔍", tool, ""))
            print(f"  {icon} Searching {label}: {query[:60]}", flush=True)
        self._refresh()
        return idx

    def on_tool_done(self, idx: int, result_json: str):
        """Mark a search as complete with its result JSON."""
        self._tracker.complete(idx, result_json)
        self._refresh()

    def wrap_executor(self, executor: Callable[[str, dict], str]) -> Callable[[str, dict], str]:
        """
        Wraps a raw tool_executor function so every call automatically
        updates the live terminal display.
        """
        ui = self

        def _tracked(tool_name: str, args: dict) -> str:
            idx    = ui.on_tool_start(tool_name, args)
            result = executor(tool_name, args)
            ui.on_tool_done(idx, result)
            return result

        return _tracked

    # ── final output ──────────────────────────────────────────────────────

    def print_report(self, report: str):
        """Render the synthesis as formatted markdown."""
        elapsed = time.time() - self._start

        if self._use_rich and self._console:
            self._console.print(Rule(style="dim"))
            self._console.print(Markdown(report))
            self._console.print(Rule(style="dim"))
            self._console.print(
                f"[dim]  Completed in {elapsed:.0f}s · "
                f"Agnes 2.0 Flash + Thinking mode[/dim]\n"
            )
        else:
            print(report, flush=True)
            print(f"\n✅ Completed in {elapsed:.0f}s", flush=True)

    def print_status(self, msg: str):
        """Print a one-line status update (outside the live area)."""
        if self._use_rich and self._console:
            self._console.log(f"[dim]{msg}[/dim]")
        else:
            print(f"  {msg}", flush=True)

    def print_error(self, msg: str):
        if self._use_rich and self._console:
            self._console.print(f"[bold red]✗[/bold red] {msg}")
        else:
            print(f"✗ {msg}", file=sys.stderr, flush=True)

    def print_image_url(self, url: str):
        if self._use_rich and self._console:
            self._console.print(
                Panel(
                    f"[bold]📸 Visual Brief[/bold]\n[link={url}]{url}[/link]",
                    border_style="magenta",
                    padding=(0, 2),
                )
            )
        else:
            print(f"\n📸 Visual Brief: {url}", flush=True)

    def print_video_url(self, url: str):
        if self._use_rich and self._console:
            self._console.print(
                Panel(
                    f"[bold]🎬 Animated Brief[/bold]\n[link={url}]{url}[/link]",
                    border_style="blue",
                    padding=(0, 2),
                )
            )
        else:
            print(f"🎬 Animated Brief: {url}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# Plain fallback (when rich is not installed)
# ──────────────────────────────────────────────────────────────────────────────

class PlainUI:
    """No-dep fallback used when rich is not installed."""

    def __init__(self, topic: str, days: int, **_):
        self.topic = topic
        self.days  = days
        self._start = time.time()

    def start(self):
        print(f"\n🔍 Agnes Research: {self.topic}", flush=True)
        print(f"   Look-back: {self.days} days · Model: Agnes 2.0 Flash\n", flush=True)

    def stop_live(self): pass

    def wrap_executor(self, executor):
        def _plain(name, args):
            icon, label, _ = SOURCE_META.get(name, ("🔍", name, ""))
            print(f"  {icon} {label}: {args.get('query','')}", flush=True)
            result = executor(name, args)
            try:
                count = len(json.loads(result))
            except Exception:
                count = 0
            print(f"       → {count} results", flush=True)
            return result
        return _plain

    def print_report(self, report: str):
        elapsed = time.time() - self._start
        print(report, flush=True)
        print(f"\n✅ Done in {elapsed:.0f}s", flush=True)

    def print_status(self, msg: str):    print(f"  {msg}", flush=True)
    def print_error(self, msg: str):     print(f"✗ {msg}", file=sys.stderr, flush=True)
    def print_image_url(self, url: str): print(f"\n📸 Visual Brief: {url}", flush=True)
    def print_video_url(self, url: str): print(f"🎬 Animated Brief: {url}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

def make_ui(topic: str, days: int, force_plain: bool = False):
    """Return the best available UI for this environment."""
    if RICH_AVAILABLE and sys.stdout.isatty() and not force_plain:
        return ResearchUI(topic, days)
    return PlainUI(topic, days)
