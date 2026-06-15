#!/usr/bin/env python3
"""Agnes Research — interactive prompt. Run with: agnes"""

import json
import os
import sys
from pathlib import Path

# ── .env loader ───────────────────────────────────────────────────────────────
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.rule import Rule
from rich.text import Text

from agnes_research import run_research, run_parallel_research

console = Console()


def ask_days() -> int:
    console.print("[dim]  Look-back window:[/dim]")
    console.print("    [bold]1[/bold] · 7 days   [dim](last week)[/dim]")
    console.print("    [bold]2[/bold] · 30 days  [dim](last month)[/dim]")
    console.print("    [bold]3[/bold] · 90 days  [dim](last 3 months)[/dim]")
    choice = Prompt.ask("  Choose", choices=["1", "2", "3"], default="2")
    return {"1": 7, "2": 30, "3": 90}[choice]


def main():
    console.print()
    console.print(Panel(
        "[bold cyan]Agnes[/bold cyan] [bold white]Research[/bold white]\n"
        "[dim]Powered by Agnes 2.0 Flash · Reddit · HN · Polymarket · Web[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))

    while True:
        console.print()
        topic = Prompt.ask("[bold cyan]  What do you want to research?[/bold cyan]").strip()
        if not topic:
            continue

        console.print()
        days = ask_days()

        console.print()
        quick = Confirm.ask("  Quick mode? [dim](fewer results, faster)[/dim]", default=False)

        console.print()
        parallel = Confirm.ask(
            "  Parallel mode? [dim](all searches run at once — ~2-3x faster)[/dim]",
            default=True,
        )

        console.print()

        try:
            fn = run_parallel_research if parallel else run_research
            fn(
                topic=topic,
                days=days,
                quick=quick,
                save_dir="~/Documents/AgnesResearch",
            )
        except KeyboardInterrupt:
            console.print("\n[dim]  Interrupted.[/dim]")
        except Exception as e:
            console.print(f"\n[bold red]  Error:[/bold red] {e}")

        console.print()
        again = Confirm.ask("[bold cyan]  Research another topic?[/bold cyan]", default=True)
        if not again:
            console.print("\n[dim]  Goodbye.[/dim]\n")
            break


if __name__ == "__main__":
    main()
