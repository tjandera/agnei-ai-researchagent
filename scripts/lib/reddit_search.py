"""
Reddit search connector.
Primary:  Reddit public JSON API (no auth)
Fallback: site:reddit.com search via Brave/Serper/Tavily (Reddit now blocks most API requests)
"""

import re
import time
import requests
from typing import List, Dict, Optional

REDDIT_SEARCH_URL = "https://www.reddit.com/search.json"
HEADERS = {"User-Agent": "agnes-research-skill/1.0 (research tool)"}


def search_reddit(
    query: str,
    limit: int = 20,
    days: int = 30,
    sort: str = "relevance",
) -> List[Dict]:
    # Try native API first
    result = _try_native_api(query, limit, days, sort)
    if result is not None:
        return result
    # Fallback: search via web (site:reddit.com)
    return _search_via_web(query, limit, days)


def _try_native_api(query: str, limit: int, days: int, sort: str) -> Optional[List[Dict]]:
    """Returns None if blocked, list of posts otherwise."""
    params = {
        "q":     query,
        "sort":  sort,
        "t":     _days_to_time_filter(days),
        "limit": min(limit, 100),
        "type":  "link",
    }
    try:
        resp = requests.get(REDDIT_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 403:
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        if "403" in str(e):
            return None
        return [{"error": str(e), "source": "reddit"}]

    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        post = {
            "source":       "reddit",
            "title":        p.get("title", ""),
            "url":          f"https://reddit.com{p.get('permalink', '')}",
            "subreddit":    p.get("subreddit_name_prefixed", ""),
            "upvotes":      p.get("ups", 0),
            "upvote_ratio": p.get("upvote_ratio", 0),
            "num_comments": p.get("num_comments", 0),
            "created_utc":  p.get("created_utc", 0),
            "selftext":     (p.get("selftext", "") or "")[:500],
            "top_comment":  None,
        }
        if post["upvotes"] >= 50 and post["num_comments"] >= 3:
            post["top_comment"] = _fetch_top_comment(p.get("permalink", ""))
            time.sleep(0.5)
        posts.append(post)
    return posts


def _search_via_web(query: str, limit: int, days: int) -> List[Dict]:
    """Search Reddit via Brave/Serper/Tavily using site:reddit.com."""
    from lib.web_search import search_web
    web_results = search_web(f"site:reddit.com {query}", limit=limit, days=days)

    posts = []
    for r in web_results:
        url = r.get("url", "")
        if "reddit.com" not in url:
            continue
        # Extract subreddit from URL e.g. /r/Python/comments/...
        subreddit_match = re.search(r'reddit\.com/r/([^/]+)', url)
        subreddit = f"r/{subreddit_match.group(1)}" if subreddit_match else ""
        posts.append({
            "source":       "reddit",
            "title":        r.get("title", ""),
            "url":          url,
            "subreddit":    subreddit,
            "upvotes":      0,
            "upvote_ratio": 0,
            "num_comments": 0,
            "created_utc":  0,
            "selftext":     r.get("description", "")[:500],
            "top_comment":  None,
            "age":          r.get("age", ""),
        })
    return posts


def _fetch_top_comment(permalink: str) -> Optional[Dict]:
    url = f"https://www.reddit.com{permalink}.json?limit=1&sort=top"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        comments = data[1]["data"]["children"]
        if not comments:
            return None
        c = comments[0]["data"]
        return {
            "body":    (c.get("body", "") or "")[:400],
            "upvotes": c.get("ups", 0),
            "author":  c.get("author", ""),
        }
    except Exception:
        return None


def _days_to_time_filter(days: int) -> str:
    if days <= 1:   return "day"
    if days <= 7:   return "week"
    if days <= 30:  return "month"
    if days <= 365: return "year"
    return "all"
