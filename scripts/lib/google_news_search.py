"""
Google News connector via the public RSS feed - no auth required, free.

Broadens headline coverage well beyond Yahoo Finance: Google News aggregates
hundreds of outlets. The feed is RSS/XML, parsed with the stdlib. Items come
back in the same shape as yahoo_news.get_stock_news so the two merge cleanly.
"""

import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "agnes-research-skill/1.0 (research tool)"}

_TAG_RE = re.compile(r"<[^>]+>")


def search_google_news(query: str, limit: int = 10, days: int = 30) -> List[Dict]:
    """Search Google News for a query within the last `days` days.

    Returns a list of dicts: {source, title, url, publisher, published_at, age,
    age_days, summary}. Items missing a title or link are dropped.
    """
    params = {
        "q": f"{query} when:{max(1, days)}d",
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    try:
        resp = requests.get(GOOGLE_NEWS_RSS, params=params, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        return [{"error": str(e), "source": "google_news"}]

    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or not url:
            continue

        # Google News appends " - Publisher" to titles; the <source> tag is the
        # authoritative publisher name.
        source_el = item.find("source")
        publisher = (source_el.text or "").strip() if source_el is not None else ""
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -(len(publisher) + 3)].strip()

        published_at = _to_iso(item.findtext("pubDate"))
        age_days = _age_days(published_at, now)
        # Honour the window even though when: should already filter.
        if age_days is not None and age_days > days + 1:
            continue

        summary = _TAG_RE.sub("", item.findtext("description") or "").strip()

        out.append({
            "source": "google_news",
            "title": title,
            "url": url,
            "publisher": publisher,
            "published_at": published_at,
            "age": _relative_age(published_at, now),
            "age_days": round(age_days, 2) if age_days is not None else None,
            "summary": summary[:240],
        })
        if len(out) >= limit:
            break

    return out


def _to_iso(pubdate: Optional[str]) -> Optional[str]:
    """Parse an RFC 822 RSS date into an ISO 8601 string, or None."""
    if not pubdate:
        return None
    try:
        return parsedate_to_datetime(pubdate).astimezone(timezone.utc).isoformat()
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


def _relative_age(iso: Optional[str], now: datetime) -> str:
    d = _age_days(iso, now)
    if d is None:
        return ""
    seconds = d * 86400
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(d)}d ago"
