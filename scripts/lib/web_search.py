"""
Web search connector.

Priority order (uses whichever key is set first):
  1. Brave Search  - BRAVE_API_KEY   - brave.com/search/api  (2,000/month free)
  2. Serper.dev    - SERPER_API_KEY  - serper.dev            (2,500 free on signup, no card)
  3. Tavily        - TAVILY_API_KEY  - tavily.com            (1,000/month free, AI-tuned)
"""

import os
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict

BRAVE_URL  = "https://api.search.brave.com/res/v1/web/search"
SERPER_URL = "https://google.serper.dev/search"
TAVILY_URL = "https://api.tavily.com/search"

SKIP_DOMAINS = {"reddit.com", "x.com", "twitter.com", "news.ycombinator.com"}


def search_web(query: str, limit: int = 10, days: int = 30) -> List[Dict]:
    brave_key  = os.environ.get("BRAVE_API_KEY",  "")
    serper_key = os.environ.get("SERPER_API_KEY", "")
    tavily_key = os.environ.get("TAVILY_API_KEY", "")

    if brave_key:
        return _brave_search(query, limit, days, brave_key)
    if serper_key:
        return _serper_search(query, limit, days, serper_key)
    if tavily_key:
        return _tavily_search(query, limit, days, tavily_key)
    return []   # no key configured - caller treats empty list as "no results"


def _brave_freshness(days: int) -> str:
    """Brave accepts pd/pw/pm/py or a custom YYYY-MM-DDtoYYYY-MM-DD range.

    The fixed shortcuts only cover day/week/month/year. For 14d, 30d, 90d we
    use a custom range so the user actually gets results from the chosen
    window instead of the next coarser bucket up.
    """
    if days <= 1:
        return "pd"
    if days <= 7:
        return "pw"
    # For everything else, ask for an explicit start-end window.
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    return f"{start.isoformat()}to{end.isoformat()}"


def _serper_tbs(days: int) -> str:
    """Serper / Google supports qdr:h/d/w/m/y or a custom cdr range."""
    if days <= 1:
        return "qdr:d"
    if days <= 7:
        return "qdr:w"
    if days <= 31:
        return "qdr:m"
    if days <= 365:
        # Custom date range: cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)
        return f"cdr:1,cd_min:{start.strftime('%m/%d/%Y')},cd_max:{end.strftime('%m/%d/%Y')}"
    return "qdr:y"


def _brave_search(query: str, limit: int, days: int, api_key: str) -> List[Dict]:
    """Brave Search API - 2,000 free queries/month."""
    headers = {
        "Accept":              "application/json",
        "Accept-Encoding":     "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {
        "q":           query,
        "count":       min(limit, 20),
        "freshness":   _brave_freshness(days),
        "search_lang": "en",
    }
    # Only add result_filter=web when not doing a site: search
    # (site: queries need to be unrestricted to return social/forum results)
    if "site:" not in query:
        params["result_filter"] = "web"

    try:
        resp = requests.get(BRAVE_URL, headers=headers, params=params, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": str(e), "source": "web_brave"}]

    # When doing a site: search, don't skip that domain
    site_query = next((p.split("site:")[-1].split()[0] for p in [query] if "site:" in p), None)
    skip = {d for d in SKIP_DOMAINS if d != site_query}

    results = []
    for r in data.get("web", {}).get("results", []):
        url = r.get("url", "")
        if any(d in url for d in skip):
            continue
        results.append({
            "source":      "web",
            "title":       r.get("title", ""),
            "url":         url,
            "description": r.get("description", "")[:300],
            "site_name":   r.get("meta_url", {}).get("hostname", "").replace("www.", ""),
            "age":         r.get("age", ""),
        })
    return results


def _serper_search(query: str, limit: int, days: int, api_key: str) -> List[Dict]:
    """Serper.dev - Google results via API. 2,500 free queries on signup."""
    try:
        resp = requests.post(
            SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={
                "q": query,
                "num": min(limit, 10),
                "gl": "us", "hl": "en",
                "tbs": _serper_tbs(days),
            },
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": str(e), "source": "web_serper"}]

    results = []
    for r in data.get("organic", []):
        url = r.get("link", "")
        if any(d in url for d in SKIP_DOMAINS):
            continue
        results.append({
            "source":      "web",
            "title":       r.get("title", ""),
            "url":         url,
            "description": r.get("snippet", "")[:300],
            "site_name":   r.get("displayLink", "").replace("www.", ""),
            "age":         r.get("date", ""),
        })
    return results[:limit]


def _tavily_search(query: str, limit: int, days: int, api_key: str) -> List[Dict]:
    """Tavily - AI-tuned search. 1,000 free queries/month."""
    try:
        resp = requests.post(
            TAVILY_URL,
            json={
                "api_key":      api_key,
                "query":        query,
                "max_results":  min(limit, 10),
                "search_depth": "basic",
                "include_answer": False,
                # Tavily honours `days` directly for the time window.
                "days": max(1, min(days, 365)),
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": str(e), "source": "web_tavily"}]

    results = []
    for r in data.get("results", []):
        url = r.get("url", "")
        if any(d in url for d in SKIP_DOMAINS):
            continue
        domain = url.split("/")[2].replace("www.", "") if "://" in url else ""
        results.append({
            "source":      "web",
            "title":       r.get("title", ""),
            "url":         url,
            "description": r.get("content", "")[:300],
            "site_name":   domain,
            "age":         r.get("published_date", ""),
        })
    return results[:limit]
