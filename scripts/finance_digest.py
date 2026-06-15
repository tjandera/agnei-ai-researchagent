#!/usr/bin/env python3
"""
Agnes Finance Research - grounded digest orchestrator.

Fetches real market data (yfinance), runs research across Polymarket, web,
Reddit, and Hacker News, and synthesizes a structured JSON digest grounded in
actual numbers. Falls back to a deterministic, equally-grounded digest when the
Agnes API is unavailable, so the product works with no key at all.

The single entry point is build_digest(). It returns a dict matching
DIGEST_SCHEMA plus meta, history (OHLCV for the chart), and media URLs.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load .env from the project root if present, so any entry point (the web app,
# the demo cache builder, ad-hoc scripts) picks up the key the same way.
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from lib.agnes_client import AgnesClient
from lib.yahoo_finance import get_ticker_data, search_tickers
from lib.polymarket_search import search_polymarket
from lib.web_search import search_web
from lib.reddit_search import search_reddit
from lib.hackernews_search import search_hackernews


# ------------------------------------------------------------------ #
# Tool registry - finance only (yahoo_finance, polymarket, web, reddit, hn)
# ------------------------------------------------------------------ #

FINANCE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_ticker_data",
            "description": (
                "Pull live market data for a stock, ETF, or crypto symbol from Yahoo "
                "Finance: price, daily change, 52-week range, volume, and fundamentals. "
                "Use for the asset under study and for related or peer tickers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker, e.g. AAPL or BTC-USD."},
                    "days": {"type": "integer", "description": "History window in days.", "default": 90},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_polymarket",
            "description": (
                "Search Polymarket prediction markets for relevant odds. Returns markets "
                "with probability and volume. Real-money odds are high-signal evidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for recent news and editorial coverage about the asset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_reddit",
            "description": "Search Reddit for retail sentiment and discussion. Returns threads with upvotes and subreddits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 15},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hackernews",
            "description": "Search Hacker News for technical and investor discussion. Returns stories with points and comments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
]


def execute_finance_tool(name: str, args: dict, days: int = 30) -> str:
    """Run a finance tool and return its output as a JSON string."""
    try:
        if name == "get_ticker_data":
            data = get_ticker_data(args["symbol"], days=args.get("days", 90))
            trimmed = {k: v for k, v in data.items() if k != "history"}
            trimmed["history_points"] = len(data.get("history", []))
            return json.dumps(trimmed, ensure_ascii=False)
        if name == "search_polymarket":
            return json.dumps(search_polymarket(args["query"], limit=args.get("limit", 8)), ensure_ascii=False)
        if name == "search_web":
            return json.dumps(search_web(args["query"], limit=args.get("limit", 10), days=days), ensure_ascii=False)
        if name == "search_reddit":
            return json.dumps(search_reddit(args["query"], limit=args.get("limit", 15), days=days), ensure_ascii=False)
        if name == "search_hackernews":
            return json.dumps(search_hackernews(args["query"], limit=args.get("limit", 10), days=days), ensure_ascii=False)
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e), "tool": name})


# ------------------------------------------------------------------ #
# Output schema
# ------------------------------------------------------------------ #

SENTIMENTS = ("bullish", "bearish", "neutral", "mixed")

DIGEST_SCHEMA = {
    "type": "object",
    "required": ["headline", "snapshot", "themes", "markets", "sentiment_summary", "citations"],
    "properties": {
        "headline": {"type": "string"},
        "snapshot": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "name": {"type": "string"},
                "price": {"type": ["number", "null"]},
                "change_pct": {"type": ["number", "null"]},
                "key_levels": {
                    "type": "object",
                    "properties": {
                        "week52_high": {"type": ["number", "null"]},
                        "week52_low": {"type": ["number", "null"]},
                        "support": {"type": ["number", "null"]},
                        "resistance": {"type": ["number", "null"]},
                    },
                },
            },
        },
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "synthesis", "sentiment"],
                "properties": {
                    "title": {"type": "string"},
                    "synthesis": {"type": "string"},
                    "sentiment": {"type": "string", "enum": list(SENTIMENTS)},
                },
            },
        },
        "markets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "probability": {"type": ["number", "null"]},
                    "volume": {"type": ["number", "null"]},
                },
            },
        },
        "sentiment_summary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "sentiment": {"type": "string"},
                    "takeaway": {"type": "string"},
                },
            },
        },
        "citations": {"type": "array", "items": {"type": "string"}},
    },
}


SYNTHESIS_PROMPT = """You are a markets research synthesizer for a finance desk.
You receive verified live market numbers plus research data from Polymarket,
the web, Reddit, and Hacker News. Produce a grounded digest.

Rules:
- Ground every claim in the data provided. Cite a real number or a named source in
  each theme. Do not invent prices, odds, or facts.
- Themes lead with what the data shows: price action versus the 52-week range,
  volume, prediction-market odds, fundamentals, and community sentiment.
- Sentiment per theme is exactly one of: bullish, bearish, neutral, mixed.
- For markets, use the Polymarket entries provided with their probability and volume.
- For sentiment_summary, summarize per subreddit or Hacker News, not generic claims.
- Citations are source names only (for example Polymarket, Hacker News, r/Bitcoin,
  CoinDesk). Never raw URLs or URL chains.
- Infer plausible support and resistance from the recent price history if visible.

Return a SINGLE JSON object and nothing else. No prose, no markdown, no code fences.
The object must match this shape exactly:

{
  "headline": "one-line takeaway",
  "snapshot": { "symbol": "", "name": "", "price": 0, "change_pct": 0,
    "key_levels": { "week52_high": 0, "week52_low": 0, "support": 0, "resistance": 0 } },
  "themes": [ { "title": "", "synthesis": "1-2 sentences citing a real number or source",
    "sentiment": "bullish|bearish|neutral|mixed" } ],
  "markets": [ { "question": "", "probability": 0, "volume": 0 } ],
  "sentiment_summary": [ { "source": "r/sub or HN", "sentiment": "", "takeaway": "" } ],
  "citations": [ "" ]
}

Provide 3 to 5 themes."""


# ------------------------------------------------------------------ #
# JSON helpers - tolerant parse + coercion to a safe, renderable shape
# ------------------------------------------------------------------ #

def _extract_json(text: str):
    """Best-effort extraction of a JSON object from a model response."""
    if not text:
        raise ValueError("empty response")
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(s[start:end + 1])
    raise ValueError("no JSON object found")


def _num(v):
    try:
        if v is None or v != v:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_sentiment(v) -> str:
    s = str(v or "").strip().lower()
    return s if s in SENTIMENTS else "neutral"


def _coerce_digest(raw: dict, snapshot: dict) -> dict:
    """Normalize any model JSON into a complete, renderable digest."""
    raw = raw if isinstance(raw, dict) else {}

    themes = []
    for t in (raw.get("themes") or [])[:5]:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title", "")).strip()
        synth = str(t.get("synthesis", t.get("body", ""))).strip()
        if title or synth:
            themes.append({
                "title": title or "Theme",
                "synthesis": synth,
                "sentiment": _norm_sentiment(t.get("sentiment")),
            })

    markets = []
    for m in (raw.get("markets") or [])[:6]:
        if not isinstance(m, dict):
            continue
        markets.append({
            "question": str(m.get("question", "")).strip(),
            "probability": _num(m.get("probability")),
            "volume": _num(m.get("volume")),
        })

    sentiment = []
    for s in (raw.get("sentiment_summary") or [])[:8]:
        if isinstance(s, dict):
            sentiment.append({
                "source": str(s.get("source", "")).strip(),
                "sentiment": _norm_sentiment(s.get("sentiment")),
                "takeaway": str(s.get("takeaway", s.get("quote", ""))).strip(),
            })
        elif isinstance(s, str):
            sentiment.append({"source": "", "sentiment": "neutral", "takeaway": s.strip()})

    citations = []
    for c in (raw.get("citations") or []):
        c = str(c).strip()
        if c and "http" not in c and c not in citations:
            citations.append(c)

    return {
        "headline": str(raw.get("headline", "")).strip() or _fallback_headline(snapshot),
        "snapshot": _grounded_snapshot(raw.get("snapshot"), snapshot),
        "themes": themes,
        "markets": markets,
        "sentiment_summary": sentiment,
        "citations": citations,
    }


# ------------------------------------------------------------------ #
# Grounding - real numbers always win over model output
# ------------------------------------------------------------------ #

def _infer_levels(history: list, week52_high, week52_low) -> dict:
    """Infer support and resistance from recent closes, falling back to 52w range."""
    closes = [h.get("close") for h in (history or []) if isinstance(h.get("close"), (int, float))]
    support = resistance = None
    if len(closes) >= 5:
        recent = closes[-min(len(closes), 60):]
        support = round(min(recent), 2)
        resistance = round(max(recent), 2)
    return {
        "week52_high": _num(week52_high),
        "week52_low": _num(week52_low),
        "support": support if support is not None else _num(week52_low),
        "resistance": resistance if resistance is not None else _num(week52_high),
    }


def _grounded_snapshot(model_snap, real: dict) -> dict:
    """Build the snapshot from real data; the model never sets a number here."""
    model_snap = model_snap if isinstance(model_snap, dict) else {}
    levels = _infer_levels(real.get("history"), real.get("52w_high"), real.get("52w_low"))
    # Let the model contribute inferred support/resistance only if real history was thin.
    ml = model_snap.get("key_levels") if isinstance(model_snap.get("key_levels"), dict) else {}
    if levels["support"] is None:
        levels["support"] = _num(ml.get("support"))
    if levels["resistance"] is None:
        levels["resistance"] = _num(ml.get("resistance"))
    return {
        "symbol": real.get("symbol", ""),
        "name": real.get("name", ""),
        "price": _num(real.get("price")),
        "change_pct": _num(real.get("change_pct")),
        "key_levels": levels,
    }


def _pct_in_range(price, low, high):
    price, low, high = _num(price), _num(low), _num(high)
    if None in (price, low, high) or high <= low:
        return None
    return max(0.0, min(100.0, (price - low) / (high - low) * 100))


def _fallback_headline(snapshot: dict) -> str:
    sym = snapshot.get("symbol", "")
    name = snapshot.get("name", "") or sym
    chg = snapshot.get("change_pct")
    price = snapshot.get("price")
    if price is None:
        return f"{name}: market snapshot"
    if chg is None:
        return f"{name} trades at ${price:,.2f}"
    direction = "up" if chg >= 0 else "down"
    return f"{name} {direction} {abs(chg):.2f}% at ${price:,.2f}"


def _clean_markets(raw_polymarket, limit: int = 6) -> list:
    """Prefer live, unresolved Polymarket entries over settled or extreme ones."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    for m in raw_polymarket or []:
        if not isinstance(m, dict) or m.get("error") or not m.get("question"):
            continue
        prob = _num(m.get("probability"))
        end = m.get("end_date") or ""
        rows.append({
            "question": str(m.get("question", "")).strip(),
            "probability": prob,
            "volume": _num(m.get("volume_usd")),
            "open": (not end or end >= today) and (prob is None or 1 < prob < 99),
        })
    live = [r for r in rows if r["open"]]
    pool = live if len(live) >= 2 else rows
    pool.sort(key=lambda r: (r["open"], r["volume"] or 0), reverse=True)
    return [{"question": r["question"], "probability": r["probability"], "volume": r["volume"]}
            for r in pool[:limit]]


# ------------------------------------------------------------------ #
# Offline fallback synthesis - deterministic, grounded in real numbers
# ------------------------------------------------------------------ #

def offline_synthesis(real: dict, research: dict) -> dict:
    """Build a grounded digest with no model call. Used when Agnes is unavailable."""
    snap = _grounded_snapshot(None, real)
    price = snap["price"]
    high = snap["key_levels"]["week52_high"]
    low = snap["key_levels"]["week52_low"]
    chg = snap["change_pct"]
    pos = _pct_in_range(price, low, high)

    themes = []
    citations = []

    # Theme 1: price action vs 52-week range
    if price is not None:
        if pos is not None:
            sent = "bullish" if pos >= 66 else "bearish" if pos <= 33 else "neutral"
            line = (f"At ${price:,.2f}, {snap['symbol']} sits about {pos:.0f}% up its 52-week "
                    f"range (${low:,.2f} to ${high:,.2f}).")
        else:
            sent = "neutral"
            line = f"{snap['symbol']} trades at ${price:,.2f}."
        if chg is not None:
            line += f" Last session moved {chg:+.2f}%."
            if abs(chg) >= 3:
                sent = "bullish" if chg > 0 else "bearish"
        themes.append({"title": "Price action", "synthesis": line, "sentiment": sent})
        citations.append("Yahoo Finance")

    # Theme 2: volume and liquidity
    vol = _num(real.get("volume"))
    avg = _num(real.get("avg_volume"))
    if vol is not None:
        if avg and avg > 0:
            ratio = vol / avg
            sent = "bullish" if ratio >= 1.3 else "bearish" if ratio <= 0.7 else "neutral"
            line = (f"Volume of {vol:,.0f} is {ratio:.1f}x the {avg:,.0f} average, "
                    f"{'above' if ratio >= 1 else 'below'} typical participation.")
        else:
            sent = "neutral"
            line = f"Latest volume is {vol:,.0f}."
        themes.append({"title": "Volume and liquidity", "synthesis": line, "sentiment": sent})

    # Theme 3: fundamentals (equities)
    pe = _num(real.get("pe_ratio"))
    mcap = _num(real.get("market_cap"))
    if pe is not None or mcap is not None:
        bits = []
        if mcap is not None:
            bits.append(f"market cap near ${mcap/1e9:,.1f}B" if mcap >= 1e9 else f"market cap ${mcap:,.0f}")
        if pe is not None:
            bits.append(f"trailing P/E of {pe:.1f}")
        line = f"{snap['name']} carries " + " and ".join(bits) + "."
        sent = "neutral"
        if pe is not None:
            sent = "bearish" if pe > 40 else "bullish" if 0 < pe < 15 else "neutral"
        themes.append({"title": "Fundamentals", "synthesis": line, "sentiment": sent})

    # Theme 4: prediction markets
    markets = _clean_markets(research.get("polymarket", []))
    if markets:
        top = markets[0]
        prob = top["probability"]
        line = f"Polymarket prices '{top['question']}'"
        if prob is not None:
            line += f" at {prob:.0f}%"
        if top["volume"]:
            line += f" on ${top['volume']:,.0f} volume"
        line += "."
        sent = "bullish" if (prob or 0) >= 60 else "bearish" if (prob or 100) <= 40 else "mixed"
        themes.append({"title": "Prediction markets", "synthesis": line, "sentiment": sent})
        citations.append("Polymarket")

    # Theme 5: community sentiment
    sentiment_summary = []
    reddit = [r for r in research.get("reddit", []) if isinstance(r, dict) and not r.get("error")]
    hn = [h for h in research.get("hackernews", []) if isinstance(h, dict) and not h.get("error")]
    if reddit:
        top = max(reddit, key=lambda r: r.get("upvotes", 0))
        sub = top.get("subreddit", "Reddit") or "Reddit"
        sentiment_summary.append({
            "source": sub, "sentiment": "mixed",
            "takeaway": (top.get("title", "") or "")[:160],
        })
        citations.append(sub)
    if hn:
        top = max(hn, key=lambda h: h.get("points", 0))
        sentiment_summary.append({
            "source": "Hacker News", "sentiment": "mixed",
            "takeaway": f"{(top.get('title','') or '')[:140]} ({top.get('points',0)} points)",
        })
        citations.append("Hacker News")
    if reddit or hn:
        n = len(reddit) + len(hn)
        themes.append({
            "title": "Community sentiment",
            "synthesis": f"{n} recent threads across Reddit and Hacker News reference the asset; engagement is the signal here.",
            "sentiment": "mixed",
        })

    for w in research.get("web", [])[:4]:
        if isinstance(w, dict) and w.get("site_name") and w["site_name"] not in citations:
            citations.append(w["site_name"])

    return {
        "headline": _fallback_headline(snap),
        "snapshot": snap,
        "themes": themes[:5],
        "markets": markets,
        "sentiment_summary": sentiment_summary,
        "citations": list(dict.fromkeys([c for c in citations if c]))[:8],
    }


# ------------------------------------------------------------------ #
# Live synthesis - Agnes returns JSON, one retry on parse failure
# ------------------------------------------------------------------ #

# Per-attempt wall-clock budget so a slow or hung Agnes call cannot stall the
# request. A timeout counts as a failed attempt; after both attempts fail the
# function raises and build_digest falls back to the grounded offline digest.
# Thinking-mode synthesis on a full research payload runs ~60-150s depending on
# API latency, so the first window is generous; a parse-only retry uses a shorter one.
SYNTHESIS_ATTEMPT_TIMEOUT_S = 150
SYNTHESIS_RETRY_TIMEOUT_S = 60
SYNTHESIS_MAX_TOKENS = 8192


def _message_text(client: "AgnesClient", resp: dict) -> str:
    """Pull the answer text, recovering from the reasoning field if content is empty.

    With thinking enabled the model can emit its JSON inside the reasoning trace
    and leave content empty; recover it so a valid response is not discarded.
    """
    content = (client.get_message_content(resp) or "").strip()
    if content:
        return content
    try:
        msg = resp["choices"][0]["message"]
        psf = msg.get("provider_specific_fields") or {}
        return str(psf.get("reasoning_content") or psf.get("reasoning") or "").strip()
    except Exception:
        return ""


def _chat_with_deadline(client: "AgnesClient", messages: list, timeout_s: float) -> str:
    """Run one Agnes chat call bounded by a wall-clock deadline."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(
            client.chat, messages=messages, thinking=True,
            max_tokens=SYNTHESIS_MAX_TOKENS, temperature=0.4,
        )
        resp = fut.result(timeout=timeout_s)
        return _message_text(client, resp)
    finally:
        # Do not block on a hung request; its own socket timeout reaps it.
        pool.shutdown(wait=False)


def live_synthesis(client: AgnesClient, real: dict, research: dict, days: int) -> dict:
    """Call Agnes for a structured JSON digest. Raises on hard failure."""
    snap = _grounded_snapshot(None, real)
    facts = {
        "symbol": real.get("symbol"),
        "name": real.get("name"),
        "asset_type": real.get("asset_type"),
        "price": real.get("price"),
        "change_pct": real.get("change_pct"),
        "week52_high": real.get("52w_high"),
        "week52_low": real.get("52w_low"),
        "volume": real.get("volume"),
        "avg_volume": real.get("avg_volume"),
        "market_cap": real.get("market_cap"),
        "pe_ratio": real.get("pe_ratio"),
        "forward_pe": real.get("forward_pe"),
        "eps": real.get("eps"),
        "dividend_yield": real.get("dividend_yield"),
        "beta": real.get("beta"),
        "sector": real.get("sector"),
        "recent_closes": [h.get("close") for h in (real.get("history") or [])[-30:]],
    }
    user = (
        f"Asset: {real.get('name')} ({real.get('symbol')})\n"
        f"As of {datetime.now().strftime('%B %d, %Y')}, {days}-day window.\n\n"
        f"VERIFIED MARKET NUMBERS (use these, do not change them):\n{json.dumps(facts, ensure_ascii=False)}\n\n"
        f"RESEARCH DATA:\n{json.dumps(research, ensure_ascii=False)[:14000]}\n\n"
        "Synthesize the grounded JSON digest now."
    )
    messages = [
        {"role": "system", "content": SYNTHESIS_PROMPT},
        {"role": "user", "content": user},
    ]
    last_err = None
    for attempt in range(2):
        deadline = SYNTHESIS_ATTEMPT_TIMEOUT_S if attempt == 0 else SYNTHESIS_RETRY_TIMEOUT_S
        # A timeout or transport error will not improve on a same-deadline retry,
        # so surface it and let build_digest fall back to the grounded offline path.
        content = _chat_with_deadline(client, messages, deadline)
        try:
            return _coerce_digest(_extract_json(content), real)
        except Exception as e:
            last_err = e
            messages.append({"role": "user", "content": (
                "That was not valid. Return ONLY a single JSON object matching the schema, "
                "no prose and no code fences."
            )})
            time.sleep(0.8)
    raise RuntimeError(f"synthesis returned unparseable JSON: {last_err}")


# ------------------------------------------------------------------ #
# Research fan-out
# ------------------------------------------------------------------ #

def _related_symbol(real: dict) -> str:
    """Pick one peer or related ticker to exercise yahoo_finance during research."""
    sym = (real.get("symbol") or "").upper()
    crypto = {"BTC-USD": "ETH-USD", "ETH-USD": "BTC-USD", "SOL-USD": "BTC-USD"}
    if sym in crypto:
        return crypto[sym]
    try:
        for q in search_tickers(real.get("name") or sym, limit=5):
            cand = (q.get("symbol") or "").upper()
            if cand and cand != sym and "error" not in q:
                return cand
    except Exception:
        pass
    return ""


def run_research(real: dict, topic: str, days: int, quick: bool, progress=None) -> dict:
    """Fan out finance searches in parallel and return grouped raw results."""
    sym = real.get("symbol", "")
    name = real.get("name", "") or sym
    n = 8 if quick else 15
    related = _related_symbol(real)

    # Core asset name for prediction-market matching, without quote-currency or
    # corporate suffixes that match unrelated markets (USD/JPY, "Inc" substrings).
    market_query = name
    for suffix in (" USD", " USDT", " USDC", ", Inc.", " Inc.", " Inc", " Corporation", " Corp.", " Corp"):
        if market_query.endswith(suffix):
            market_query = market_query[: -len(suffix)].strip()
            break

    plan = [
        ("search_polymarket", {"query": market_query, "limit": 8}),
        ("search_web", {"query": f"{name} stock price news", "limit": 6 if quick else 10}),
        ("search_reddit", {"query": f"{name} {sym}", "limit": n}),
        ("search_hackernews", {"query": name, "limit": 6 if quick else 10}),
    ]
    if related:
        plan.append(("get_ticker_data", {"symbol": related, "days": 30}))

    def _run(tool, args):
        if progress:
            progress({"type": "search_start", "tool": tool, "query": args.get("query", args.get("symbol", ""))})
        out = execute_finance_tool(tool, args, days=days)
        count, error = 0, False
        try:
            data = json.loads(out)
            if isinstance(data, list):
                count = len(data)
                error = bool(data and isinstance(data[0], dict) and data[0].get("error"))
            elif isinstance(data, dict):
                error = "error" in data
                count = 0 if error else 1
        except Exception:
            error = True
        if progress:
            progress({"type": "search_done", "tool": tool,
                      "query": args.get("query", args.get("symbol", "")), "count": count, "error": error})
        return tool, out

    grouped = {"polymarket": [], "web": [], "reddit": [], "hackernews": [], "related": {}}
    name_map = {"search_polymarket": "polymarket", "search_web": "web",
                "search_reddit": "reddit", "search_hackernews": "hackernews"}
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:
        futures = [pool.submit(_run, tool, args) for tool, args in plan]
        for fut in as_completed(futures):
            try:
                tool, out = fut.result()
                data = json.loads(out)
                if tool == "get_ticker_data":
                    grouped["related"] = data if isinstance(data, dict) else {}
                elif tool in name_map and isinstance(data, list):
                    grouped[name_map[tool]] = data
            except Exception:
                continue
    return grouped


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

def build_digest(symbol: str, days: int = 30, topic: str = None, quick: bool = False,
                 want_media: bool = True, client: AgnesClient = None, progress=None) -> dict:
    """
    Build a grounded finance digest end to end.

    progress(event: dict) is an optional callback the SSE route maps to frames.
    Returns the full digest dict: schema fields + meta + history + media.
    """
    def emit(ev):
        if progress:
            try:
                progress(ev)
            except Exception:
                pass

    symbol = (symbol or "").upper().strip()
    topic = topic or symbol
    started = time.time()

    # 1. Snapshot - real market data, emitted early for progressive render.
    emit({"type": "phase", "key": "snapshot", "label": "Fetching market data"})
    try:
        real = get_ticker_data(symbol, days=max(days, 90))
    except Exception as e:
        emit({"type": "error", "message": f"Could not load {symbol}: {e}", "fatal": True})
        raise
    history = real.get("history", [])
    emit({"type": "snapshot", "data": {**{k: v for k, v in real.items() if k != "history"},
                                       "history": history}})

    # 2. Research fan-out across finance sources.
    emit({"type": "phase", "key": "research", "label": "Researching sources"})
    research = run_research(real, topic, days, quick, progress=progress)

    # 3. Synthesis - live JSON if a key is available, else grounded offline.
    emit({"type": "phase", "key": "synthesis", "label": "Synthesizing digest"})
    live = False
    fallback = False
    model = "offline"
    if client is None and os.environ.get("AGNES_API_KEY"):
        try:
            client = AgnesClient()
        except Exception:
            client = None
    if client is not None:
        try:
            digest = live_synthesis(client, real, research, days)
            live = True
            model = "agnes-2.0-flash"
            if not digest.get("themes"):
                raise ValueError("empty themes")
        except Exception as e:
            emit({"type": "status", "message": f"Synthesis fell back to offline mode: {e}"})
            digest = offline_synthesis(real, research)
            fallback = True
    else:
        digest = offline_synthesis(real, research)

    # Markets come straight from cleaned Polymarket data so the odds strip never
    # shows settled or extreme entries, regardless of what the model returned.
    cleaned_markets = _clean_markets(research.get("polymarket", []))
    if cleaned_markets:
        digest["markets"] = cleaned_markets

    # 4. Media - best effort, never blocks the digest.
    media = {"image_url": None, "video_url": None}
    if want_media:
        try:
            from lib import media_gen
        except Exception:
            media_gen = None
        if media_gen is not None and client is not None:
            up = (real.get("change_pct") or 0) >= 0
            emit({"type": "phase", "key": "image", "label": "Generating hero image"})
            try:
                media["image_url"] = media_gen.generate_hero_image(
                    client, real.get("symbol", ""), real.get("name", ""),
                    theme_hint=digest.get("headline", ""))
                if media["image_url"]:
                    emit({"type": "image", "url": media["image_url"]})
            except Exception as e:
                emit({"type": "status", "message": f"Hero image skipped: {e}"})
            if media["image_url"]:
                emit({"type": "phase", "key": "video", "label": "Generating recap video"})
                try:
                    media["video_url"] = media_gen.generate_recap_video(
                        client, media["image_url"], real.get("symbol", ""), real.get("name", ""))
                    if media["video_url"]:
                        emit({"type": "video", "url": media["video_url"]})
                except Exception as e:
                    emit({"type": "status", "message": f"Recap video skipped: {e}"})

    digest["history"] = history
    digest["media"] = media
    digest["meta"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "live": live,
        "grounded": True,
        "fallback": fallback,
        "days": days,
        "asset_type": real.get("asset_type", "EQUITY"),
        "elapsed_s": round(time.time() - started, 1),
    }
    emit({"type": "digest", "data": digest})
    return digest
