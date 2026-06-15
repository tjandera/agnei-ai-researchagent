"""
Reddit search via public JSON API — no auth required.
Returns threads + top comments with upvote counts.
"""

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
    """
    Search Reddit for posts matching a query.

    Args:
        query:  Search terms
        limit:  Max posts to return (capped at 100)
        days:   Look-back window in days (maps to Reddit time filters)
        sort:   "relevance" | "hot" | "top" | "new" | "comments"
    Returns:
        List of post dicts with keys:
          title, url, subreddit, upvotes, num_comments,
          created_utc, top_comment (text + upvotes)
    """
    time_filter = _days_to_time_filter(days)
    params = {
        "q":       query,
        "sort":    sort,
        "t":       time_filter,
        "limit":   min(limit, 100),
        "type":    "link",
    }

    try:
        resp = requests.get(
            REDDIT_SEARCH_URL,
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
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

        # Fetch top comment if post has enough engagement
        if post["upvotes"] >= 50 and post["num_comments"] >= 3:
            post["top_comment"] = _fetch_top_comment(p.get("permalink", ""))
            time.sleep(0.5)  # Rate limit

        posts.append(post)

    return posts


def _fetch_top_comment(permalink: str) -> Optional[Dict]:
    """Fetch the top comment from a Reddit thread."""
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
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 30:
        return "month"
    if days <= 365:
        return "year"
    return "all"
