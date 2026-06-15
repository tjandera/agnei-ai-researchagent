"""
Dev.to search connector — free, no API key required.
Returns developer blog posts and articles.
Best for: programming, tools, tutorials, developer opinions.
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict

DEVTO_URL = "https://dev.to/api/articles"


def search_devto(query: str, limit: int = 10, days: int = 30) -> List[Dict]:
    """
    Search Dev.to articles for a given topic.

    Args:
        query:  Search terms
        limit:  Max articles to return
        days:   Look-back window
    Returns:
        List of article dicts with title, url, reactions, comments, tags
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    tag = query.lower().split()[0].replace("-", "")  # use first word as tag hint

    results = []

    # Search by query string
    for endpoint_params in [
        {"q": query, "per_page": min(limit * 2, 30)},
        {"tag": tag,  "per_page": min(limit * 2, 30), "top": min(days, 365)},
    ]:
        try:
            resp = requests.get(DEVTO_URL, params=endpoint_params, timeout=10)
            resp.raise_for_status()
            articles = resp.json()
        except Exception as e:
            return [{"error": str(e), "source": "devto"}]

        for a in articles:
            pub_str = a.get("published_at", "") or ""
            try:
                pub_date = datetime.fromisoformat(pub_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if pub_date < cutoff:
                    continue
            except Exception:
                pass

            url = a.get("url") or f"https://dev.to{a.get('path','')}"
            if any(r["url"] == url for r in results):
                continue

            results.append({
                "source":       "devto",
                "title":        a.get("title", ""),
                "url":          url,
                "description":  (a.get("description") or "")[:300],
                "tags":         a.get("tag_list", [])[:5],
                "reactions":    a.get("public_reactions_count", 0),
                "comments":     a.get("comments_count", 0),
                "published_at": pub_str[:10],
                "author":       a.get("user", {}).get("username", ""),
            })

        if len(results) >= limit:
            break

    results.sort(key=lambda x: x["reactions"], reverse=True)
    return results[:limit]
