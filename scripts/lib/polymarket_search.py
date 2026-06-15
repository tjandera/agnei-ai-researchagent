"""
Polymarket search via Gamma API - no auth required, free.
Returns prediction markets with odds and volume.
"""

import re
import requests
from typing import List, Dict, Optional

GAMMA_URL = "https://gamma-api.polymarket.com/markets"


def search_polymarket(query: str, limit: int = 8) -> List[Dict]:
    """
    Search Polymarket prediction markets relevant to a query.

    Args:
        query: Search terms
        limit: Max markets to return
    Returns:
        List of market dicts with keys:
          question, probability, volume_usd, category, end_date, url
    """
    # Fetch a large batch and filter client-side - the API's `q` param
    # does not reliably filter by topic, so we pull top markets by volume
    # and keyword-match locally.
    query_words = set(re.sub(r"[^\w\s]", "", query.lower()).split())
    # Only keep words longer than 2 chars for matching
    match_words = [w for w in query_words if len(w) > 2]

    params = {
        "active":    "true",
        "closed":    "false",
        "limit":     200,
        "order":     "volume",
        "ascending": "false",
    }

    try:
        resp = requests.get(GAMMA_URL, params=params, timeout=10)
        resp.raise_for_status()
        markets = resp.json()
    except Exception as e:
        return [{"error": str(e), "source": "polymarket"}]

    if not isinstance(markets, list):
        markets = markets.get("markets", [])

    results = []
    for m in markets:
        question = m.get("question", "") or m.get("title", "")
        if not question:
            continue

        # Require at least one query word to appear in the market question
        q_lower = question.lower()
        if match_words and not any(w in q_lower for w in match_words):
            continue

        # Extract probability (may be in outcomePrices or probability field)
        prob = _extract_probability(m)
        volume = float(m.get("volume", 0) or 0)
        end_date = m.get("endDateIso") or m.get("end_date_iso") or ""

        results.append({
            "source":      "polymarket",
            "question":    question,
            "probability": prob,
            "volume_usd":  round(volume, 2),
            "category":    m.get("category", ""),
            "end_date":    end_date[:10] if end_date else "",
            "url":         f"https://polymarket.com/event/{m.get('slug', '')}",
            "active":      m.get("active", False),
        })

        if len(results) >= limit:
            break

    # Sort by volume desc
    results.sort(key=lambda x: x["volume_usd"], reverse=True)
    return results


def _extract_probability(market: Dict) -> Optional[float]:
    """Extract Yes probability from a market dict."""
    # Direct probability field
    if "probability" in market:
        try:
            return round(float(market["probability"]) * 100, 1)
        except (TypeError, ValueError):
            pass

    # outcomePrices is a stringified list like '["0.74", "0.26"]'
    prices = market.get("outcomePrices")
    if prices:
        try:
            if isinstance(prices, str):
                import json
                prices = json.loads(prices)
            if prices:
                return round(float(prices[0]) * 100, 1)
        except Exception:
            pass

    return None


