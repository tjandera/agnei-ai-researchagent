"""
Price chart generator using matplotlib (dark terminal aesthetic).
Returns PNG bytes — used for PDF embedding.
"""

import io
from typing import List, Dict

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import FancyArrowPatch
    import pandas as pd
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def generate_price_chart(history: List[Dict], symbol: str, name: str = "") -> bytes:
    """
    Generate a dark-themed price + volume chart.

    Args:
        history: List of {date, open, high, low, close, volume} dicts
        symbol:  Ticker symbol
        name:    Company name

    Returns:
        PNG bytes
    """
    if not MATPLOTLIB_AVAILABLE:
        raise ImportError("matplotlib not installed")
    if not history:
        raise ValueError("No history data")

    import pandas as pd
    from datetime import datetime

    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")

    bg        = "#0c0c0c"
    panel_bg  = "#111111"
    green     = "#00e87a"
    red       = "#ff5555"
    cyan      = "#00d4ff"
    dim       = "#444444"
    text_col  = "#888888"

    start_price = df["close"].iloc[0]
    end_price   = df["close"].iloc[-1]
    is_up       = end_price >= start_price
    line_color  = green if is_up else red

    fig = plt.figure(figsize=(12, 5), facecolor=bg)
    gs  = fig.add_gridspec(3, 1, hspace=0, height_ratios=[3, 0, 1])

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[2], sharex=ax1)

    for ax in (ax1, ax2):
        ax.set_facecolor(panel_bg)
        ax.tick_params(colors=text_col, labelsize=8)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for spine in ax.spines.values():
            spine.set_color(dim)
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.grid(True, color=dim, linewidth=0.4, alpha=0.5, linestyle="--")

    # ── Price line ───────────────────────────────────────────────────────
    ax1.plot(df["date"], df["close"], color=line_color, linewidth=1.6, zorder=3)
    ax1.fill_between(df["date"], df["close"], df["close"].min(),
                     alpha=0.08, color=line_color)

    # Annotate start / end price
    ax1.annotate(f"${end_price:.2f}", xy=(df["date"].iloc[-1], end_price),
                 xytext=(5, 0), textcoords="offset points",
                 color=line_color, fontsize=9, fontweight="bold",
                 va="center")

    # ── Volume bars ──────────────────────────────────────────────────────
    vol_colors = [green if c >= o else red
                  for c, o in zip(df["close"], df["open"])]
    ax2.bar(df["date"], df["volume"], color=vol_colors, alpha=0.5, width=0.8)
    ax2.set_ylabel("VOL", color=text_col, fontsize=7, labelpad=6)

    # ── Title ────────────────────────────────────────────────────────────
    change     = end_price - start_price
    change_pct = (change / start_price * 100) if start_price else 0
    sign       = "▲" if change >= 0 else "▼"
    chg_color  = green if change >= 0 else red

    fig.text(0.02, 0.93, f"{symbol}",
             color="white", fontsize=13, fontweight="bold",
             transform=fig.transFigure)
    fig.text(0.10, 0.93, f"  {name}",
             color=text_col, fontsize=9,
             transform=fig.transFigure)
    fig.text(0.02, 0.86, f"${end_price:.2f}  {sign} {abs(change):.2f} ({abs(change_pct):.2f}%)",
             color=chg_color, fontsize=10,
             transform=fig.transFigure)

    # Date axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    plt.setp(ax1.get_xticklabels(), visible=False)
    plt.setp(ax2.get_xticklabels(), rotation=0, ha="center", color=text_col, fontsize=7)

    plt.tight_layout(rect=[0, 0, 1, 0.88])

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=bg, edgecolor="none")
    buf.seek(0)
    plt.close(fig)
    return buf.getvalue()
