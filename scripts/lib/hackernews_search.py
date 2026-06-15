"""
Hacker News search via Algolia HN API — no auth required, free.
Returns stories + top comments with point counts.
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict

ALGOLIA_URL   = "https://hn.algolia.com/api/v1/search"
COMMENTS_URL  = "https://hn.algolia.com/api/v1/search"
HN_ITEM_URL   = "https://news.ycombinator.com/item?id={id}"


def search_hackernews(
    query: str,
    limit: int = 15,
    days: int = 30,
    min_points: int = 5,
) -> List[Dict]:
    """
    Search Hacker News stories.

    Args:
        query:      Search terms
        limit:      Max stories to return
        days:       Look-back window
        min_points: Minimum story points (filters noise)
    Returns:
        List of story dicts with keys:
          title, url, hn_url, points, num_comments, created_at, top_comments
    """
    since_ts = int((datetime.utcnow() - timedelta(days=days)).timestamp())

    params = {
        "query":       query,
        "tags":        "story",
        "numericFilters": f"created_at_i>{since_ts},points>{min_points}",
        "hitsPerPage": min(limit, 50),
        "attributesToRetrieve": "objectID,title,url,points,num_comments,created_at_i,author",
    }

    try:
        resp = requests.get(ALGOLIA_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": str(e), "source": "hackernews"}]

    stories = []
    for hit in data.get("hits", []):
        story_id = hit.get("objectID")
        story = {
            "source":       "hackernews",
            "title":        hit.get("title", ""),
            "url":          hit.get("url", ""),
            "hn_url":       HN_ITEM_URL.format(id=story_id),
            "points":       hit.get("points", 0),
            "num_comments": hit.get("num_comments", 0),
            "author":       hit.get("author", ""),
            "created_at":   hit.get("created_at_i", 0),
            "top_comments": _fetch_top_comments(story_id) if story_id else [],
        }
        stories.append(story)

    return stories


def _fetch_top_comments(story_id: str, limit: int = 3) -> List[Dict]:
    """Fetch top-level comments for a story, sorted by points."""
    params = {
        "tags":        f"comment,story_{story_id}",
        "hitsPerPage": 20,
        "attributesToRetrieve": "objectID,comment_text,points,author",
    }
    try:
        resp = requests.get(COMMENTS_URL, params=params, timeout=8)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        # Sort by points desc, take top N
        hits.sort(key=lambda x: x.get("points", 0), reverse=True)
        return [
            {
                "text":    (h.get("comment_text", "") or "")[:300],
                "points":  h.get("points", 0),
                "author":  h.get("author", ""),
            }
            for h in hits[:limit]
            if h.get("comment_text")
        ]
    except Exception:
        return []
