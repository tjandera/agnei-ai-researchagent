"""
Yahoo Finance news connector.

Pulls stock-specific news headlines (with links + publisher + timestamp) and
upcoming calendar events (earnings date, ex-dividend date) for a ticker. Both
are free via yfinance, no API key required.

yfinance has shipped two news payload shapes; we normalize both.
"""

from __future__ import annotations

import io
import logging
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)


@contextmanager
def _silent():
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        yield


def _to_iso(ts: Any) -> Optional[str]:
    """Accept ISO strings or unix timestamps; return ISO 8601 or None."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (OSError, ValueError):
            return None
    if isinstance(ts, str):
        return ts
    return None


def _relative_age(iso: Optional[str]) -> str:
    """Render '2h ago' / '3d ago' / '' from an ISO timestamp."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    now = datetime.now(timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def get_stock_news(
    symbol: str,
    limit: int = 8,
    max_age_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fetch the latest news articles for a ticker.

    Args:
        symbol: Ticker.
        limit: Max in-window items to return.
        max_age_days: Drop articles older than this many days. None = no cap.

    Returns a list of dicts: {title, url, publisher, published_at, age, summary,
    age_days, in_window}. Items missing a title or URL are dropped so the UI
    never renders a dead link.
    """
    if not symbol or not symbol.strip():
        return []

    with _silent():
        try:
            raw = yf.Ticker(symbol.upper()).news or []
        except Exception:
            return []

    now = datetime.now(timezone.utc)
    # Pull a generous slice so the window filter still has options to choose from.
    out: List[Dict[str, Any]] = []
    for item in raw[: max(limit * 3, limit + 10)]:
        if not isinstance(item, dict):
            continue

        body = item.get("content") if isinstance(item.get("content"), dict) else item

        title = (body.get("title") or "").strip()
        url = (
            (body.get("canonicalUrl") or {}).get("url")
            if isinstance(body.get("canonicalUrl"), dict)
            else body.get("link") or body.get("url")
        )
        url = (url or "").strip()
        if not title or not url:
            continue

        publisher = (
            (body.get("provider") or {}).get("displayName")
            if isinstance(body.get("provider"), dict)
            else body.get("publisher")
        ) or ""

        published_at = _to_iso(
            body.get("pubDate")
            or body.get("displayTime")
            or body.get("providerPublishTime")
        )

        # Compute exact age in days so the UI can verify the window honestly.
        age_days: Optional[float] = None
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                age_days = (now - dt).total_seconds() / 86400
            except ValueError:
                age_days = None

        in_window = (
            max_age_days is None
            or age_days is None  # unknown age: keep, mark as not-verified
            or age_days <= max_age_days
        )
        # Drop hard-out-of-window items so the synthesizer never sees them.
        if max_age_days is not None and age_days is not None and age_days > max_age_days:
            continue

        summary = (body.get("summary") or body.get("description") or "").strip()

        out.append({
            "title": title,
            "url": url,
            "publisher": publisher.strip(),
            "published_at": published_at,
            "age": _relative_age(published_at),
            "age_days": round(age_days, 2) if age_days is not None else None,
            "in_window": in_window,
            "summary": summary[:240],
        })

        if len(out) >= limit:
            break

    return out


def get_upcoming_events(symbol: str) -> Dict[str, Any]:
    """Fetch next earnings date and ex-dividend date for a ticker.

    Returns {} when the data is unavailable. Dates are ISO strings.
    """
    if not symbol or not symbol.strip():
        return {}

    with _silent():
        try:
            cal = yf.Ticker(symbol.upper()).calendar
        except Exception:
            return {}

    if cal is None:
        return {}

    # yfinance returns either a DataFrame (older) or a dict (newer).
    events: Dict[str, Any] = {}

    if isinstance(cal, dict):
        earnings = cal.get("Earnings Date") or cal.get("earnings_date")
        ex_div = cal.get("Ex-Dividend Date") or cal.get("ex_dividend_date")
        events["earnings_date"] = _coerce_date(earnings)
        events["ex_dividend_date"] = _coerce_date(ex_div)
        return {k: v for k, v in events.items() if v}

    # DataFrame path: pull the first column.
    try:
        if "Earnings Date" in cal.index:
            events["earnings_date"] = _coerce_date(cal.loc["Earnings Date"].iloc[0])
        if "Ex-Dividend Date" in cal.index:
            events["ex_dividend_date"] = _coerce_date(cal.loc["Ex-Dividend Date"].iloc[0])
    except Exception:
        pass

    return {k: v for k, v in events.items() if v}


def _coerce_date(v: Any) -> Optional[str]:
    """Turn whatever yfinance hands back into 'YYYY-MM-DD' or None."""
    if v is None:
        return None
    if isinstance(v, list) and v:
        v = v[0]
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%Y-%m-%d")
        except Exception:
            return None
    if isinstance(v, str):
        return v[:10]
    return None
