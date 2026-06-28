"""
StockTwits connector via the public symbol stream - no auth required, free.

Gives ticker-specific retail chatter and a bullish/bearish sentiment read that
none of the other sources provide. The endpoint is symbol-keyed (not free text)
and can rate-limit; on any block we degrade to an empty list like the other
connectors. Crypto-style symbols (e.g. BTC-USD) are not supported and return [].
"""

import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
HEADERS = {"User-Agent": "agnes-research-skill/1.0 (research tool)"}


def search_stocktwits(symbol: str, limit: int = 20) -> List[Dict]:
    """Fetch recent StockTwits messages for a ticker.

    Returns a list of dicts: {source, title, url, username, sentiment,
    created_at, age, age_days}. Returns [] for unsupported symbols (crypto) or
    when the endpoint blocks the request.
    """
    sym = (symbol or "").upper().strip()
    # StockTwits keys on bare equity symbols; the Yahoo "-USD" crypto form
    # does not resolve here.
    if not sym or "-" in sym:
        return []

    try:
        resp = requests.get(STREAM_URL.format(symbol=sym), headers=HEADERS, timeout=12)
        if resp.status_code in (403, 404, 429):
            return []
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": str(e), "source": "stocktwits"}]

    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for msg in data.get("messages", []):
        body = (msg.get("body") or "").strip()
        if not body:
            continue
        username = ((msg.get("user") or {}).get("username") or "").strip()
        sentiment = (((msg.get("entities") or {}).get("sentiment") or {}).get("basic")) or None
        created_at = _to_iso(msg.get("created_at"))
        age_days = _age_days(created_at, now)

        out.append({
            "source": "stocktwits",
            "title": body[:200],
            "url": f"https://stocktwits.com/{username}/message/{msg.get('id')}" if username else "https://stocktwits.com",
            "username": username,
            "sentiment": sentiment,            # "Bullish" | "Bearish" | None
            "created_at": created_at,
            "age": _relative_age(age_days),
            "age_days": round(age_days, 2) if age_days is not None else None,
        })
        if len(out) >= limit:
            break

    return out


def stocktwits_sentiment(items: List[Dict]) -> Dict[str, int]:
    """Aggregate bullish/bearish/neutral counts from a message list."""
    bullish = bearish = neutral = 0
    for m in items:
        if not isinstance(m, dict) or m.get("error"):
            continue
        s = (m.get("sentiment") or "").lower()
        if s == "bullish":
            bullish += 1
        elif s == "bearish":
            bearish += 1
        else:
            neutral += 1
    return {
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "total": bullish + bearish + neutral,
    }


def _to_iso(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _age_days(iso: Optional[str], now: datetime) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - dt).total_seconds() / 86400


def _relative_age(days: Optional[float]) -> str:
    if days is None:
        return ""
    seconds = days * 86400
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(days)}d ago"
