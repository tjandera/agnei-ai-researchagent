#!/usr/bin/env python3
"""
Agnes stock brief - terminal version.

Feature parity with the web UI: TL;DR, action signal, drivers, bull/bear,
news with links, watch list. Calls the same build_digest() pipeline, so
real numbers and plain-English language are identical.

Usage:
    agnes stock AAPL
    agnes stock BTC-USD --days 7
    agnes stock NVDA --quick
    agnes stock TSLA --save ~/Documents
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Load .env from the project root.
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent))

from finance_digest import build_digest

try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
    from rich.columns import Columns
    from rich import box
    RICH = True
except ImportError:
    RICH = False


SIGNAL_STYLE = {
    "ACCUMULATE": ("bold green",  "Buy more on weakness"),
    "HOLD":       ("bold white",  "Do nothing — keep what you have"),
    "WATCH":      ("bold yellow", "Wait for a clearer signal"),
    "TRIM":       ("bold red",    "Take some profit off the table"),
}


def _fmt_price(n) -> str:
    if n is None:
        return "N/A"
    a = abs(n)
    if a >= 1000:
        return f"${n:,.0f}"
    if a >= 1:
        return f"${n:,.2f}"
    return f"${n:.4f}"


def _fmt_pct(n) -> str:
    if n is None:
        return "N/A"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.2f}%"


def render_brief(digest: dict, console: "Console") -> None:
    snap = digest.get("snapshot", {}) or {}
    levels = snap.get("key_levels", {}) or {}
    action = digest.get("action", {}) or {}
    bull = digest.get("bull_case", {}) or {}
    bear = digest.get("bear_case", {}) or {}
    meta = digest.get("meta", {}) or {}

    sym = snap.get("symbol", "")
    name = snap.get("name", "") or sym
    price = snap.get("price")
    chg = snap.get("change_pct")

    # ── Headline ────────────────────────────────────────────────────────
    chg_color = "green" if (chg or 0) >= 0 else "red"
    chg_text = _fmt_pct(chg) if chg is not None else ""
    header = Text()
    header.append(f"{sym}  ", style="bold white on default")
    header.append(name, style="dim")
    header.append("\n")
    header.append(_fmt_price(price), style="bold white")
    if chg_text:
        header.append(f"   {chg_text}", style=chg_color)
    console.print(Panel(header, border_style="yellow", padding=(0, 2)))
    console.print()

    # ── TL;DR ───────────────────────────────────────────────────────────
    tldr = digest.get("tldr", "").strip()
    if tldr:
        console.print(Panel(
            Text(tldr, style="italic"),
            title="[bold yellow]What's going on[/bold yellow]",
            border_style="dim", padding=(1, 2),
        ))
        console.print()

    # ── Action signal ───────────────────────────────────────────────────
    sig = (action.get("signal") or "HOLD").upper()
    style, hint = SIGNAL_STYLE.get(sig, ("bold white", ""))
    reason = action.get("reasoning", "").strip()
    signal_body = Text()
    signal_body.append(sig, style=style)
    signal_body.append(f"   {hint}\n\n", style="dim")
    if reason:
        signal_body.append(reason, style="white")
    console.print(Panel(
        signal_body,
        title="[bold]Signal[/bold]",
        border_style=style.split()[-1],
        padding=(1, 2),
    ))
    console.print()

    # ── Drivers ─────────────────────────────────────────────────────────
    drivers = digest.get("drivers") or []
    if drivers:
        console.print("[bold yellow]What's driving the move[/bold yellow]")
        for i, d in enumerate(drivers, 1):
            console.print(f"  [yellow]{i:>2}.[/yellow] {d}")
        console.print()

    # ── Bull / bear ─────────────────────────────────────────────────────
    bull_text = bull.get("outlook", "").strip()
    bear_text = bear.get("outlook", "").strip()
    if bull_text or bear_text:
        bull_lvl = bull.get("level_to_watch")
        bear_lvl = bear.get("level_to_watch")
        bull_panel = Panel(
            Text(
                (bull_text or "—") +
                (f"\n\n[level to watch: {_fmt_price(bull_lvl)}]" if bull_lvl else ""),
                style="white",
            ),
            title="[green]If things go well[/green]",
            border_style="green", padding=(1, 2),
        )
        bear_panel = Panel(
            Text(
                (bear_text or "—") +
                (f"\n\n[level to watch: {_fmt_price(bear_lvl)}]" if bear_lvl else ""),
                style="white",
            ),
            title="[red]If things go badly[/red]",
            border_style="red", padding=(1, 2),
        )
        console.print(Columns([bull_panel, bear_panel], equal=True, expand=True))
        console.print()

    # ── News ────────────────────────────────────────────────────────────
    news = digest.get("news") or []
    if news:
        console.print("[bold yellow]Latest news[/bold yellow]")
        for n in news[:6]:
            title = (n.get("title") or "").strip()
            pub = (n.get("publisher") or "").strip()
            age = (n.get("age") or "").strip()
            url = (n.get("url") or "").strip()
            meta_bits = " · ".join(x for x in (pub, age) if x)
            console.print(f"  [white]•[/white] [bold]{title}[/bold]")
            if meta_bits:
                console.print(f"      [dim]{meta_bits}[/dim]")
            if url:
                console.print(f"      [yellow][link={url}]{url}[/link][/yellow]")
        console.print()

    # ── Watch this week ─────────────────────────────────────────────────
    watch = digest.get("watch_this_week") or []
    if watch:
        console.print("[bold yellow]Things to watch this week[/bold yellow]")
        for w in watch:
            console.print(f"  [yellow]→[/yellow] {w}")
        console.print()

    # ── Footer ──────────────────────────────────────────────────────────
    cites = digest.get("citations") or []
    if cites:
        console.print(Text("Sources: ", style="dim") + Text(", ".join(cites), style="dim cyan"))
    elapsed = meta.get("elapsed_s")
    mode = "live" if meta.get("live") else "offline"
    if elapsed is not None:
        console.print(f"[dim]Built in {elapsed}s · {mode} mode[/dim]")
    console.print()
    console.print("[yellow dim]This is information, not financial advice.[/yellow dim]")
    console.print()


def render_plain(digest: dict) -> None:
    """No-color fallback for non-TTY or --plain."""
    snap = digest.get("snapshot", {}) or {}
    action = digest.get("action", {}) or {}
    bull = digest.get("bull_case", {}) or {}
    bear = digest.get("bear_case", {}) or {}

    sym = snap.get("symbol", "")
    name = snap.get("name", "")
    price = snap.get("price")
    chg = snap.get("change_pct")

    print(f"\n{sym}  {name}")
    print(f"{_fmt_price(price)}   {_fmt_pct(chg) if chg is not None else ''}")
    print()

    if digest.get("tldr"):
        print("WHAT'S GOING ON")
        print(digest["tldr"])
        print()

    sig = (action.get("signal") or "HOLD").upper()
    hint = SIGNAL_STYLE.get(sig, ("", ""))[1]
    print(f"SIGNAL: {sig}   {hint}")
    if action.get("reasoning"):
        print(action["reasoning"])
    print()

    drivers = digest.get("drivers") or []
    if drivers:
        print("WHAT'S DRIVING THE MOVE")
        for i, d in enumerate(drivers, 1):
            print(f"  {i}. {d}")
        print()

    if bull.get("outlook") or bear.get("outlook"):
        print("IF THINGS GO WELL")
        print(f"  {bull.get('outlook', '—')}")
        if bull.get("level_to_watch"):
            print(f"  Level to watch: {_fmt_price(bull['level_to_watch'])}")
        print()
        print("IF THINGS GO BADLY")
        print(f"  {bear.get('outlook', '—')}")
        if bear.get("level_to_watch"):
            print(f"  Level to watch: {_fmt_price(bear['level_to_watch'])}")
        print()

    news = digest.get("news") or []
    if news:
        print("LATEST NEWS")
        for n in news[:6]:
            print(f"  - {n.get('title', '')}")
            meta_bits = " · ".join(x for x in (n.get("publisher", ""), n.get("age", "")) if x)
            if meta_bits:
                print(f"    {meta_bits}")
            if n.get("url"):
                print(f"    {n['url']}")
        print()

    watch = digest.get("watch_this_week") or []
    if watch:
        print("THINGS TO WATCH THIS WEEK")
        for w in watch:
            print(f"  - {w}")
        print()

    cites = digest.get("citations") or []
    if cites:
        print(f"Sources: {', '.join(cites)}")
    print("\nThis is information, not financial advice.\n")


def save_markdown(digest: dict, save_dir: str) -> None:
    snap = digest.get("snapshot", {}) or {}
    sym = snap.get("symbol", "STOCK")
    name = snap.get("name", "")
    action = digest.get("action", {}) or {}
    bull = digest.get("bull_case", {}) or {}
    bear = digest.get("bear_case", {}) or {}

    md_lines = [
        f"# {sym} — {name}",
        f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        f"**Price:** {_fmt_price(snap.get('price'))}  ",
        f"**Change:** {_fmt_pct(snap.get('change_pct'))}  ",
        f"**Signal:** **{(action.get('signal') or 'HOLD').upper()}**  ",
        "",
        "## What's going on",
        digest.get("tldr", "—"),
        "",
        "## Signal reasoning",
        action.get("reasoning", "—"),
        "",
        "## What's driving the move",
    ]
    for d in (digest.get("drivers") or []):
        md_lines.append(f"- {d}")
    md_lines += [
        "",
        "## If things go well",
        bull.get("outlook", "—"),
        f"_Level to watch: {_fmt_price(bull.get('level_to_watch'))}_" if bull.get("level_to_watch") else "",
        "",
        "## If things go badly",
        bear.get("outlook", "—"),
        f"_Level to watch: {_fmt_price(bear.get('level_to_watch'))}_" if bear.get("level_to_watch") else "",
        "",
        "## Latest news",
    ]
    for n in (digest.get("news") or [])[:8]:
        title = n.get("title", "")
        url = n.get("url", "")
        pub = n.get("publisher", "")
        md_lines.append(f"- [{title}]({url}) — _{pub}_" if url else f"- {title} — _{pub}_")
    if digest.get("watch_this_week"):
        md_lines += ["", "## Things to watch this week"]
        for w in digest["watch_this_week"]:
            md_lines.append(f"- {w}")
    if digest.get("citations"):
        md_lines += ["", "**Sources:** " + ", ".join(digest["citations"])]
    md_lines += ["", "_This is information, not financial advice._"]

    out_dir = Path(save_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = out_dir / f"{sym}-{ts}.md"
    path.write_text("\n".join(md_lines))
    print(f"\nSaved brief to: {path}\n", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="agnes stock",
        description="Get a plain-English brief on a stock, ETF, or crypto.",
    )
    parser.add_argument("symbol", help="Ticker, e.g. AAPL, BTC-USD, TSLA")
    parser.add_argument("--days", type=int, default=30,
                        help="Look-back window in days (default: 30)")
    parser.add_argument("--quick", action="store_true",
                        help="Faster mode, fewer search results")
    parser.add_argument("--plain", action="store_true",
                        help="Plain text output, no colors")
    parser.add_argument("--save", metavar="DIR",
                        help="Save the brief as Markdown to DIR")
    args = parser.parse_args(argv)

    use_rich = RICH and sys.stdout.isatty() and not args.plain
    console = Console() if use_rich else None

    if use_rich:
        console.print()
        console.print(f"[dim]Building brief for [/dim][bold yellow]{args.symbol.upper()}[/bold yellow][dim]...[/dim]")
        console.print()
    else:
        print(f"\nBuilding brief for {args.symbol.upper()}...\n", file=sys.stderr)

    # Build the digest — no media for terminal output.
    started = time.time()
    digest = build_digest(
        symbol=args.symbol,
        days=args.days,
        quick=args.quick,
    )

    if use_rich:
        render_brief(digest, console)
    else:
        render_plain(digest)

    if args.save:
        save_markdown(digest, args.save)


if __name__ == "__main__":
    main()
