"""
GitHub search connector - free, no API key required.
Searches repositories and discussions relevant to a topic.
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
HEADERS = {"Accept": "application/vnd.github.v3+json"}


def search_github(query: str, limit: int = 10, days: int = 30) -> List[Dict]:
    """
    Search GitHub for repositories related to a topic.

    Returns repos with stars, description, language, and recent activity.
    Best for: tech topics, open-source tools, what developers are building.
    """
    since = (datetime.utcnow() - timedelta(days=max(days, 90))).strftime("%Y-%m-%d")

    params = {
        "q":        f"{query} pushed:>{since}",
        "sort":     "stars",
        "order":    "desc",
        "per_page": min(limit, 30),
    }

    try:
        resp = requests.get(GITHUB_SEARCH_URL, headers=HEADERS, params=params, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [{"error": str(e), "source": "github"}]

    results = []
    for item in data.get("items", []):
        pushed = item.get("pushed_at", "")[:10]
        results.append({
            "source":      "github",
            "title":       item.get("full_name", ""),
            "description": (item.get("description") or "")[:300],
            "url":         item.get("html_url", ""),
            "stars":       item.get("stargazers_count", 0),
            "language":    item.get("language") or "",
            "topics":      item.get("topics", [])[:5],
            "pushed_at":   pushed,
            "forks":       item.get("forks_count", 0),
        })

    return results
