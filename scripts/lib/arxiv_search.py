"""
ArXiv search connector — free, no API key required.
Returns academic papers and preprints.
Best for: AI/ML research, science, technical deep-dives.
"""

import re
import requests
from datetime import datetime, timedelta
from typing import List, Dict

ARXIV_URL = "https://export.arxiv.org/api/query"


def search_arxiv(query: str, limit: int = 8, days: int = 90) -> List[Dict]:
    """
    Search ArXiv for papers related to a topic.

    Args:
        query:  Search terms
        limit:  Max papers to return
        days:   Look-back window (ArXiv is slower-moving; default 90d)
    Returns:
        List of paper dicts with title, authors, abstract, url, published
    """
    params = {
        "search_query": f"all:{query}",
        "start":        0,
        "max_results":  min(limit * 2, 30),
        "sortBy":       "submittedDate",
        "sortOrder":    "descending",
    }

    try:
        resp = requests.get(ARXIV_URL, params=params, timeout=15)
        resp.raise_for_status()
        xml = resp.text
    except Exception as e:
        return [{"error": str(e), "source": "arxiv"}]

    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
    cutoff  = datetime.utcnow() - timedelta(days=days)

    results = []
    for entry in entries:
        def _tag(tag: str) -> str:
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", entry, re.DOTALL)
            return m.group(1).strip() if m else ""

        published_str = _tag("published")[:10]
        try:
            published = datetime.strptime(published_str, "%Y-%m-%d")
            if published < cutoff:
                continue
        except Exception:
            pass

        # Collect authors
        authors = re.findall(r"<author>.*?<name>(.*?)</name>.*?</author>", entry, re.DOTALL)

        link_m = re.search(r'<link[^>]+href="(https://arxiv\.org/abs/[^"]+)"', entry)
        url = link_m.group(1) if link_m else ""

        abstract = re.sub(r"\s+", " ", _tag("summary")).strip()

        results.append({
            "source":    "arxiv",
            "title":     re.sub(r"\s+", " ", _tag("title")).strip(),
            "url":       url,
            "authors":   authors[:3],
            "abstract":  abstract[:400],
            "published": published_str,
        })

        if len(results) >= limit:
            break

    return results
