#!/usr/bin/env python3
"""
Agnes Finance Research - grounded digest orchestrator.

Builds a plain-English finance digest for a single ticker:
  - One-paragraph TL;DR a non-investor can read
  - Direct action signal (HOLD / WATCH / TRIM / ACCUMULATE) with reasoning
  - What's driving the move today
  - Bull case / bear case with levels to watch
  - Latest news with clickable links
  - Upcoming events this week (earnings, ex-div)

Real numbers come from yfinance and always win over the model. The model only
shapes the language. Without an Agnes key, a deterministic offline synthesis
produces the same shape from the same data, so the product never breaks.
"""

import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from lib.agnes_client import AgnesClient
from lib.yahoo_finance import get_ticker_data, search_tickers
from lib.yahoo_news import get_stock_news, get_upcoming_events
from lib.web_search import search_web
from lib.reddit_search import search_reddit
from lib.google_news_search import search_google_news
from lib.stocktwits_search import search_stocktwits, stocktwits_sentiment
from lib.sec_edgar_search import search_sec_filings
from lib.finnhub_search import get_finnhub_analytics


# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

ACTION_SIGNALS = ("ACCUMULATE", "HOLD", "WATCH", "TRIM")

SYNTHESIS_PROMPT = """You are Agnes, a friendly finance brief writer.
You speak to someone who owns or is thinking about owning the stock and has
no finance background. Your job: explain what is going on with their stock
and what they should do about it, in plain English.

STYLE RULES (strict):
- Sixth-grade reading level. Short sentences. No hedging soup.
- No finance jargon. Forbidden phrases include "trades at", "P/E multiple",
  "elevated valuation", "tailwinds", "headwinds", "compression", "consolidation",
  "outperforms peers", "valuation re-rate". If you would write one of these,
  rewrite the sentence so a high-schooler understands it.
- Use dollar amounts, percentages, and dates the reader can picture.
- Never invent numbers. Use only the verified numbers and the research data
  given below.
- The research data may include StockTwits retail sentiment (bullish vs bearish
  counts) and recent SEC filings. When present and relevant, weave them into the
  brief in plain English (e.g. "most small investors posting today are bullish",
  or "the company just filed an 8-K about a major event").

ACTION SIGNAL — choose exactly one and back it with the data:
- ACCUMULATE: Buy more on dips. Use when fundamentals are healthy and the
  price is in a clear buy zone (near support, off the 52-week high).
- HOLD: Do nothing. Keep what you have. Use when there is no urgent reason
  to act, the news is mixed, and the price is mid-range.
- WATCH: Wait for a clearer signal before you act. Use when sentiment is
  unclear or the chart is at a key level that could break either way.
- TRIM: Sell some. Use when the price is near or above the 52-week high with
  weakening news, or when a clear risk is rising.

Return a SINGLE JSON object and nothing else. No prose. No markdown. No code
fences. The object must match this shape exactly:

{
  "headline": "one short line a reader can scan in 2 seconds",
  "tldr": "one paragraph (3 to 5 sentences), plain English, what is happening today and what it means for someone who owns the stock",
  "action": {
    "signal": "ACCUMULATE | HOLD | WATCH | TRIM",
    "reasoning": "2 to 3 sentences citing real numbers from the data"
  },
  "drivers": [
    "one short bullet (one sentence) on why the stock is moving",
    "one short bullet",
    "one short bullet"
  ],
  "bull_case": {
    "outlook": "1 to 2 sentences on what could go right",
    "level_to_watch": 0
  },
  "bear_case": {
    "outlook": "1 to 2 sentences on what could go wrong",
    "level_to_watch": 0
  },
  "sentiment_quote": "one short line from a real source (Reddit, news, etc.) that captures how people feel — keep it under 140 characters",
  "citations": ["Yahoo Finance", "Google News", "Reuters", "StockTwits", "SEC EDGAR", "r/stocks"]
}

The level_to_watch numbers are price levels in dollars. The bull level should
be above today's price (a target if things go well). The bear level should be
below today's price (a stop-out point if things go badly). If you cannot infer
a level from the data, set it to null."""


ESSAY_PROMPT = """You are Agnes, a plain-English finance writer. Write a thorough,
clear explanation of what is happening with this stock RIGHT NOW and why it matters
to someone who owns or is watching it.

STRUCTURE — write exactly 4 to 5 flowing paragraphs of prose. No headings, no
bullet points, no lists. Cover these angles in order:
  1. What is happening today — the price move, the main driver, the overall mood.
  2. Why it is happening — the business context, recent events, what changed and when.
  3. What the news and data are saying — weave in the headlines, any retail sentiment,
     and any official filings. What is the market focused on or worried about?
  4. What this means for someone who holds the stock — key levels to watch, risks
     on both sides, and what would need to happen for the picture to change.
  5. The bigger picture — where this moment fits in the company's longer story or
     what it signals about the sector.

RULES:
- Seventh-grade reading level. Clear sentences. No finance jargon whatsoever.
  Forbidden words: "headwinds", "tailwinds", "valuation", "compression",
  "consolidation", "multiple", "re-rate", "outperform", "underperform".
- Use real dollar amounts, percentages, and dates the reader can picture.
- Ground every claim in the verified numbers and research given below.
  Never invent or estimate numbers not in the data.
- If the reader owns the stock, speak directly to what their gain or loss
  means given what is happening right now.
- Be calm, thorough, and honest. Never hype. Never alarm unnecessarily.
- Output only the essay prose. No preamble, no JSON, no markdown."""


# ------------------------------------------------------------------ #
# JSON helpers
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


def _norm_signal(v) -> str:
    s = str(v or "").strip().upper()
    return s if s in ACTION_SIGNALS else "HOLD"


def _coerce_digest(raw: dict, snapshot: dict) -> dict:
    """Normalize model JSON into a complete, renderable digest."""
    raw = raw if isinstance(raw, dict) else {}

    action = raw.get("action") if isinstance(raw.get("action"), dict) else {}
    bull = raw.get("bull_case") if isinstance(raw.get("bull_case"), dict) else {}
    bear = raw.get("bear_case") if isinstance(raw.get("bear_case"), dict) else {}

    drivers = []
    for d in (raw.get("drivers") or [])[:5]:
        d = str(d).strip()
        if d:
            drivers.append(d)

    citations = []
    for c in (raw.get("citations") or []):
        c = str(c).strip()
        if c and "http" not in c and c not in citations:
            citations.append(c)

    return {
        "headline": str(raw.get("headline", "")).strip() or _fallback_headline(snapshot),
        "tldr": str(raw.get("tldr", "")).strip(),
        "action": {
            "signal": _norm_signal(action.get("signal")),
            "reasoning": str(action.get("reasoning", "")).strip(),
        },
        "drivers": drivers,
        "bull_case": {
            "outlook": str(bull.get("outlook", "")).strip(),
            "level_to_watch": _num(bull.get("level_to_watch")),
        },
        "bear_case": {
            "outlook": str(bear.get("outlook", "")).strip(),
            "level_to_watch": _num(bear.get("level_to_watch")),
        },
        "sentiment_quote": str(raw.get("sentiment_quote", "")).strip()[:200],
        "snapshot": _grounded_snapshot(raw.get("snapshot"), snapshot),
        "citations": citations,
    }


# ------------------------------------------------------------------ #
# Grounding - real numbers always win
# ------------------------------------------------------------------ #

def _infer_levels(history: list, week52_high, week52_low) -> dict:
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
    model_snap = model_snap if isinstance(model_snap, dict) else {}
    levels = _infer_levels(real.get("history"), real.get("52w_high"), real.get("52w_low"))
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


def _quick_signal(price, low, high, change_pct) -> str:
    """Fast, deterministic action signal from price position + day move.

    Same rubric the offline synthesis uses, factored out so the portfolio
    overview can badge each holding without a model call.
    """
    pos = _pct_in_range(price, low, high)
    chg = _num(change_pct)
    if pos is not None and pos >= 85:
        return "TRIM"
    if pos is not None and pos <= 25:
        return "ACCUMULATE"
    if chg is not None and abs(chg) >= 4:
        return "WATCH"
    return "HOLD"


def _volatility(history: list) -> Optional[float]:
    """Annualized volatility (%) from daily closes, or None if too little data."""
    closes = [h.get("close") for h in (history or []) if isinstance(h.get("close"), (int, float))]
    if len(closes) < 10:
        return None
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1]]
    if len(rets) < 5:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return round((var ** 0.5) * (252 ** 0.5) * 100, 1)


# ------------------------------------------------------------------ #
# Holding-aware decision panels (position / risk / income)
# ------------------------------------------------------------------ #

def _build_position(real: dict, holding: dict) -> dict:
    """The user's P&L on this stock, from their saved shares + buy price."""
    shares = _num(holding.get("shares")) or 0
    cb = _num(holding.get("cost_basis"))
    price = _num(real.get("price"))
    pos = {
        "shares": shares,
        "cost_basis": cb,
        "value": round((price or 0) * shares, 2),
        "day_change_value": round((_num(real.get("change")) or 0) * shares, 2),
    }
    if cb and cb > 0:
        pos["cost"] = round(cb * shares, 2)
        pos["gain"] = round(pos["value"] - pos["cost"], 2)
        pos["gain_pct"] = round((price - cb) / cb * 100, 2) if price is not None else None
    else:
        pos["cost"] = pos["gain"] = pos["gain_pct"] = None
    return pos


def _build_risk(real: dict, history: list) -> dict:
    levels = _infer_levels(history, real.get("52w_high"), real.get("52w_low"))
    price = _num(real.get("price"))
    return {
        "beta": _num(real.get("beta")),
        "volatility": _volatility(history),
        "range_pos": _pct_in_range(price, real.get("52w_low"), real.get("52w_high")),
        "week52_low": _num(real.get("52w_low")),
        "week52_high": _num(real.get("52w_high")),
        "support": levels.get("support"),
        "resistance": levels.get("resistance"),
    }


def _build_income(real: dict, events: dict, position: Optional[dict]) -> dict:
    dy = _num(real.get("dividend_yield"))   # already a percentage, e.g. 0.38 == 0.38%
    price = _num(real.get("price"))
    annual = None
    if dy and price and position and position.get("shares"):
        annual = round((dy / 100.0) * price * position["shares"], 2)
    return {
        "dividend_yield": dy,
        "ex_dividend_date": (events or {}).get("ex_dividend_date"),
        "earnings_date": (events or {}).get("earnings_date"),
        "annual_income": annual,
    }


def _fallback_headline(snapshot: dict) -> str:
    sym = snapshot.get("symbol", "")
    name = snapshot.get("name", "") or sym
    chg = snapshot.get("change_pct")
    price = snapshot.get("price")
    if price is None:
        return f"{name}: market snapshot"
    if chg is None:
        return f"{name} at ${price:,.2f}"
    word = "up" if chg >= 0 else "down"
    return f"{name} {word} {abs(chg):.1f}% to ${price:,.2f}"


# ------------------------------------------------------------------ #
# Offline synthesis - deterministic, grounded fallback
# ------------------------------------------------------------------ #

def offline_synthesis(real: dict, research: dict) -> dict:
    """Build a digest with no model call. Used when Agnes is unavailable."""
    snap = _grounded_snapshot(None, real)
    price = snap["price"]
    high = snap["key_levels"]["week52_high"]
    low = snap["key_levels"]["week52_low"]
    support = snap["key_levels"]["support"]
    resistance = snap["key_levels"]["resistance"]
    chg = snap["change_pct"]
    pos = _pct_in_range(price, low, high)
    name = snap["name"] or snap["symbol"]

    # Action rubric — same as the prompt, deterministic version.
    if pos is not None and pos >= 85:
        signal = "TRIM"
        reason = (f"{name} is sitting near its 12-month high. That's a strong run, "
                  f"but it also means there's less room before a pullback. Taking "
                  f"some profit here is reasonable.")
    elif pos is not None and pos <= 25:
        signal = "ACCUMULATE"
        reason = (f"{name} is in the lower part of its 12-month range. If the company "
                  f"fundamentals still look healthy to you, prices like these are "
                  f"usually where long-term buyers step in.")
    elif chg is not None and abs(chg) >= 4:
        signal = "WATCH"
        reason = (f"Today's move of {chg:+.1f}% is bigger than a normal day. "
                  f"Wait a session or two before reacting — big single-day moves "
                  f"often reverse partway.")
    else:
        signal = "HOLD"
        reason = (f"Nothing on the chart or the news demands an action today. "
                  f"{name} is trading in a normal range and the move is small.")

    # TL;DR
    parts = []
    if chg is not None:
        word = "up" if chg >= 0 else "down"
        parts.append(f"{name} is {word} {abs(chg):.1f}% today.")
    if pos is not None:
        if pos >= 75:
            parts.append("It's trading near the top of its 12-month range.")
        elif pos <= 25:
            parts.append("It's trading near the bottom of its 12-month range.")
        else:
            parts.append("It's sitting in the middle of its 12-month range.")
    news_count = len(research.get("news") or [])
    if news_count:
        parts.append(f"There are {news_count} fresh news stories about it today.")
    tldr = " ".join(parts)

    # Drivers - pulled from news headlines
    drivers = []
    for item in (research.get("news") or [])[:3]:
        title = item.get("title", "")
        publisher = item.get("publisher", "")
        if title:
            tag = f" — {publisher}" if publisher else ""
            drivers.append(f"{title}{tag}")
    if not drivers and chg is not None:
        drivers.append(
            f"Day-on-day move of {chg:+.2f}% with no major headlines tracked yet."
        )

    # Bull / bear levels
    bull_level = resistance if (resistance and price and resistance > price) else high
    bear_level = support if (support and price and support < price) else low

    bull_outlook = (
        f"If buyers keep pushing, the next level to watch is ${bull_level:,.2f}. "
        f"A clean break above that often opens room for more upside."
        if bull_level else
        "If buyers come back in, watch how the stock handles its recent highs."
    )
    bear_outlook = (
        f"If selling picks up, ${bear_level:,.2f} is the line to defend. "
        f"Losing it would suggest more downside from here."
        if bear_level else
        "If selling picks up, watch how the stock holds its recent lows."
    )

    # Citations - credit every platform that contributed.
    citations = ["Yahoo Finance"]
    for item in (research.get("news") or [])[:4]:
        pub = (item.get("publisher") or "").strip()
        if pub and pub not in citations:
            citations.append(pub)
    if research.get("google_news"):
        citations.append("Google News")
    for item in (research.get("google_news") or [])[:2]:
        pub = (item.get("publisher") or "").strip()
        if pub and pub not in citations:
            citations.append(pub)
    for r in (research.get("reddit") or [])[:2]:
        if isinstance(r, dict):
            sub = (r.get("subreddit") or "").strip()
            if sub and sub not in citations:
                citations.append(sub)
    if research.get("stocktwits"):
        citations.append("StockTwits")
    if research.get("sec"):
        citations.append("SEC EDGAR")

    # Sentiment quote
    sentiment_quote = ""
    reddit = [r for r in (research.get("reddit") or []) if isinstance(r, dict) and not r.get("error")]
    if reddit:
        top = max(reddit, key=lambda r: r.get("upvotes", 0))
        sentiment_quote = (top.get("title") or "")[:140]

    return {
        "headline": _fallback_headline(snap),
        "tldr": tldr,
        "action": {"signal": signal, "reasoning": reason},
        "drivers": drivers[:3],
        "bull_case": {"outlook": bull_outlook, "level_to_watch": bull_level},
        "bear_case": {"outlook": bear_outlook, "level_to_watch": bear_level},
        "sentiment_quote": sentiment_quote,
        "snapshot": snap,
        "citations": citations[:6],
    }


# ------------------------------------------------------------------ #
# Live synthesis
# ------------------------------------------------------------------ #

# Token budget tuned to actual usage. The digest JSON is ~1k-1.5k tokens.
# We do not use thinking mode for synthesis: structured JSON output does not
# benefit from a reasoning trace, and skipping it cuts response time and keeps
# the model from wrapping the JSON in a reasoning preamble.
#
# Timeouts are sized for a locally served model. A 14B-class model on Apple
# Silicon produces the digest JSON in roughly 20-60 s; a cloud API returns in
# ~10-15 s and finishes well inside the same cap. The first call after model
# load is the slow one, which is why build_digest warms the model up first.
SYNTHESIS_ATTEMPT_TIMEOUT_S = 150
SYNTHESIS_RETRY_TIMEOUT_S = 100
SYNTHESIS_MAX_TOKENS = 2560         # plenty for the JSON
SYNTHESIS_MAX_TOKENS_QUICK = 2048


def _message_text(client: "AgnesClient", resp: dict) -> str:
    content = (client.get_message_content(resp) or "").strip()
    if content:
        return content
    try:
        msg = resp["choices"][0]["message"]
        psf = msg.get("provider_specific_fields") or {}
        return str(psf.get("reasoning_content") or psf.get("reasoning") or "").strip()
    except Exception:
        return ""


def _chat_with_deadline(
    client: "AgnesClient", messages: list, timeout_s: float,
    thinking: bool = True, max_tokens: int = SYNTHESIS_MAX_TOKENS,
) -> str:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(
            client.chat, messages=messages, thinking=thinking,
            max_tokens=max_tokens, temperature=0.3,
        )
        resp = fut.result(timeout=timeout_s)
        return _message_text(client, resp)
    finally:
        pool.shutdown(wait=False)


def _trim_research_for_model(research: dict, quick: bool) -> dict:
    """Keep only what the synthesizer actually uses.

    The full research payload can run 10-20 KB which forces the model to
    process irrelevant tokens. We keep the top headlines (the model only
    quotes 2-3 of them) and trim long fields.
    """
    news_limit = 4 if quick else 6
    web_limit = 3 if quick else 4
    reddit_limit = 3 if quick else 5

    def _slim_news(items):
        return [
            {"title": (n.get("title") or "")[:160],
             "publisher": n.get("publisher") or "",
             "age": n.get("age") or ""}
            for n in (items or [])[:news_limit]
            if n.get("title")
        ]

    def _slim_web(items):
        return [
            {"title": (w.get("title") or "")[:140],
             "description": (w.get("description") or "")[:240],
             "site_name": w.get("site_name") or ""}
            for w in (items or [])[:web_limit]
            if w.get("title")
        ]

    def _slim_reddit(items):
        return [
            {"title": (r.get("title") or "")[:140],
             "subreddit": r.get("subreddit") or "",
             "upvotes": r.get("upvotes", 0)}
            for r in (items or [])[:reddit_limit]
            if r.get("title")
        ]

    # Merge Yahoo + Google News so the model sees the broadest headline set,
    # de-duplicated by normalized title.
    merged_news = list(research.get("news") or [])
    seen = {_norm_title(n.get("title")) for n in merged_news}
    for g in (research.get("google_news") or []):
        if _norm_title(g.get("title")) not in seen:
            merged_news.append(g)
            seen.add(_norm_title(g.get("title")))

    st = research.get("stocktwits") or []
    sentiment = stocktwits_sentiment(st) if st else None
    filings = [f.get("title") for f in (research.get("sec") or [])[:4] if f.get("title")]

    # Finnhub analytics are already compact structured data — pass through directly.
    finnhub = research.get("finnhub") or {}

    return {
        "news": _slim_news(merged_news),
        "web": _slim_web(research.get("web")),
        "reddit": _slim_reddit(research.get("reddit")),
        "stocktwits_sentiment": sentiment,
        "sec_filings": filings,
        "analyst_consensus":   finnhub.get("analyst"),
        "price_target":        finnhub.get("price_target"),
        "earnings_history":    finnhub.get("earnings"),
        "insider_sentiment":   finnhub.get("insider"),
        "financial_ratios":    finnhub.get("ratios"),
    }


def live_synthesis(client: AgnesClient, real: dict, research: dict, days: int,
                   quick: bool = False, position: Optional[dict] = None) -> dict:
    snap = _grounded_snapshot(None, real)
    facts = {
        "symbol": real.get("symbol"),
        "name": real.get("name"),
        "asset_type": real.get("asset_type"),
        "price": real.get("price"),
        "change_pct": real.get("change_pct"),
        "week52_high": real.get("52w_high"),
        "week52_low": real.get("52w_low"),
        "support": snap["key_levels"]["support"],
        "resistance": snap["key_levels"]["resistance"],
        "volume": real.get("volume"),
        "avg_volume": real.get("avg_volume"),
        "market_cap": real.get("market_cap"),
        "pe_ratio": real.get("pe_ratio"),
        "forward_pe": real.get("forward_pe"),
        "sector": real.get("sector"),
        "recent_closes": [h.get("close") for h in (real.get("history") or [])[-30:]],
    }
    if position:
        facts["your_position"] = {
            "shares": position.get("shares"),
            "avg_buy_price": position.get("cost_basis"),
            "current_value": position.get("value"),
            "gain_pct": position.get("gain_pct"),
        }
    finnhub = research.get("finnhub") or {}
    if finnhub.get("analyst"):
        facts["analyst_consensus"] = finnhub["analyst"]
    if finnhub.get("price_target"):
        facts["analyst_price_target"] = finnhub["price_target"]
    if finnhub.get("earnings"):
        facts["earnings_beat_rate_pct"] = finnhub["earnings"].get("beat_rate")
        facts["earnings_quarters"] = finnhub["earnings"].get("quarters")
    if finnhub.get("insider"):
        facts["insider_activity"] = finnhub["insider"]
    if finnhub.get("ratios"):
        facts["financial_ratios"] = finnhub["ratios"]

    slim_research = _trim_research_for_model(research, quick)
    pos_note = (
        "\nThe reader OWNS this stock (see your_position). Make the action and "
        "reasoning speak to their actual position and gain/loss.\n"
        if position else "\n"
    )
    user = (
        f"Asset: {real.get('name')} ({real.get('symbol')})\n"
        f"As of {datetime.now().strftime('%B %d, %Y')}, {days}-day window.\n\n"
        f"VERIFIED MARKET NUMBERS (use these exactly, do not change them):\n"
        f"{json.dumps(facts, ensure_ascii=False)}\n\n"
        f"RESEARCH DATA:\n{json.dumps(slim_research, ensure_ascii=False)}\n"
        f"{pos_note}\n"
        "Write the JSON digest now. Plain English. Short sentences. "
        "Real numbers only."
    )
    messages = [
        {"role": "system", "content": SYNTHESIS_PROMPT},
        {"role": "user", "content": user},
    ]
    # Thinking mode adds ~50-90 s with no measurable quality gain on grounded
    # JSON synthesis. We keep it off and use a tight token budget.
    token_budget = SYNTHESIS_MAX_TOKENS_QUICK if quick else SYNTHESIS_MAX_TOKENS

    last_err = None
    for attempt in range(2):
        deadline = SYNTHESIS_ATTEMPT_TIMEOUT_S if attempt == 0 else SYNTHESIS_RETRY_TIMEOUT_S
        content = _chat_with_deadline(
            client, messages, deadline,
            thinking=False, max_tokens=token_budget,
        )
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
# Research fan-out (news, web context, retail sentiment)
# ------------------------------------------------------------------ #

def run_research(real: dict, topic: str, days: int, quick: bool, progress=None) -> dict:
    """Fan out finance research in parallel across every source.

    Returns: {news, events, web, reddit, google_news, stocktwits, sec}. Each
    list source is cleaned of the [{"error"}] sentinel before it is returned.
    Polymarket is intentionally not pulled — it has no relevance for individual
    stocks.
    """
    sym = real.get("symbol", "")
    name = real.get("name", "") or sym
    n = 6 if quick else 10

    def _emit(ev):
        if progress:
            try:
                progress(ev)
            except Exception:
                pass

    def _clean(items):
        """Drop the [{"error"}] sentinel; return (clean_list, had_error)."""
        clean = [r for r in items if isinstance(r, dict) and not r.get("error")]
        return clean, (len(items) > 0 and not clean)

    def _news():
        _emit({"type": "search_start", "tool": "yahoo_news", "query": sym})
        items = get_stock_news(sym, limit=8, max_age_days=days)
        _emit({"type": "search_done", "tool": "yahoo_news",
               "query": sym, "count": len(items), "error": False})
        return ("news", items)

    def _events():
        # No emit — this is fast and uninteresting to the progress UI.
        return ("events", get_upcoming_events(sym))

    def _web():
        q = f"{name} stock news"
        _emit({"type": "search_start", "tool": "search_web", "query": q})
        clean, err = _clean(search_web(q, limit=6 if quick else 8, days=days))
        _emit({"type": "search_done", "tool": "search_web",
               "query": q, "count": len(clean), "error": err})
        return ("web", clean)

    def _reddit():
        q = f"{name} {sym}"
        _emit({"type": "search_start", "tool": "search_reddit", "query": q})
        clean, _ = _clean(search_reddit(q, limit=n, days=days))
        _emit({"type": "search_done", "tool": "search_reddit",
               "query": q, "count": len(clean), "error": False})
        return ("reddit", clean)

    def _google_news():
        q = f"{name} stock"
        _emit({"type": "search_start", "tool": "google_news", "query": q})
        clean, err = _clean(search_google_news(q, limit=6 if quick else 10, days=days))
        _emit({"type": "search_done", "tool": "google_news",
               "query": q, "count": len(clean), "error": err})
        return ("google_news", clean)

    def _stocktwits():
        _emit({"type": "search_start", "tool": "stocktwits", "query": sym})
        clean, _ = _clean(search_stocktwits(sym, limit=30))
        _emit({"type": "search_done", "tool": "stocktwits",
               "query": sym, "count": len(clean), "error": False})
        return ("stocktwits", clean)

    def _sec():
        _emit({"type": "search_start", "tool": "sec", "query": sym})
        clean, _ = _clean(search_sec_filings(sym, limit=6, days=max(days, 90)))
        _emit({"type": "search_done", "tool": "sec",
               "query": sym, "count": len(clean), "error": False})
        return ("sec", clean)

    def _finnhub():
        _emit({"type": "search_start", "tool": "finnhub", "query": sym})
        data = get_finnhub_analytics(sym, current_price=real.get("price"))
        _emit({"type": "search_done", "tool": "finnhub",
               "query": sym, "count": len(data), "error": False})
        return ("finnhub", data)

    grouped = {"news": [], "events": {}, "web": [], "reddit": [],
               "google_news": [], "stocktwits": [], "sec": [], "finnhub": {}}
    tasks = (_news, _events, _web, _reddit, _google_news, _stocktwits, _sec, _finnhub)
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [pool.submit(fn) for fn in tasks]
        for fut in as_completed(futures):
            try:
                key, data = fut.result()
                grouped[key] = data
            except Exception:
                continue
    return grouped


# ------------------------------------------------------------------ #
# Unified feed + source attribution
# ------------------------------------------------------------------ #

# label + kind per platform; kind drives the badge colour in the UI.
PLATFORM_META = {
    "yahoo":       ("Yahoo Finance", "news"),
    "google_news": ("Google News", "news"),
    "web":         ("Web", "web"),
    "reddit":      ("Reddit", "social"),
    "stocktwits":  ("StockTwits", "social"),
    "sec":         ("SEC EDGAR", "filing"),
}


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:60]


def _build_feed(research: dict) -> list:
    """Merge every source into one de-duplicated, badged, source-diverse feed.

    Each item carries its platform so the UI can attribute it. Items are pulled
    into per-platform lanes (each already recency-ordered by its connector), then
    interleaved round-robin so the top of the feed shows the freshest item from
    every source — not 18 items from whichever source happened to be dated.
    """
    seen_titles, seen_urls = set(), set()

    def _lane(platform, rows):
        """rows: iterable of (title, url, label, age, age_days). Deduped."""
        out = []
        for title, url, label, age, age_days in rows:
            title = (title or "").strip()
            url = (url or "").strip()
            if not title or not url:
                continue
            nt = _norm_title(title)
            if (nt and nt in seen_titles) or url in seen_urls:
                continue
            seen_titles.add(nt)
            seen_urls.add(url)
            out.append({
                "platform": platform,
                "label": label or PLATFORM_META[platform][0],
                "kind": PLATFORM_META[platform][1],
                "title": title,
                "url": url,
                "age": age or "",
                "age_days": age_days,
            })
        return out

    def _st_label(m):
        user = m.get("username") or ""
        sent = m.get("sentiment")
        return ("@" + user if user else "StockTwits") + (f" · {sent}" if sent else "")

    lanes = [
        _lane("yahoo", ((n.get("title"), n.get("url"), n.get("publisher"), n.get("age"), n.get("age_days"))
                        for n in (research.get("news") or [])[:6])),
        _lane("google_news", ((n.get("title"), n.get("url"), n.get("publisher"), n.get("age"), n.get("age_days"))
                              for n in (research.get("google_news") or [])[:6])),
        _lane("sec", ((f.get("title"), f.get("url"), f.get("form"), f.get("age"), f.get("age_days"))
                      for f in (research.get("sec") or [])[:3])),
        _lane("stocktwits", ((m.get("title"), m.get("url"), _st_label(m), m.get("age"), m.get("age_days"))
                             for m in (research.get("stocktwits") or [])[:3])),
        _lane("reddit", ((r.get("title"), r.get("url"), r.get("subreddit"), r.get("age"), r.get("age_days"))
                         for r in (research.get("reddit") or [])[:3])),
        _lane("web", ((w.get("title"), w.get("url"), w.get("site_name"), w.get("age"), None)
                      for w in (research.get("web") or [])[:4])),
    ]

    feed, depth = [], 0
    while len(feed) < 18 and any(depth < len(lane) for lane in lanes):
        for lane in lanes:
            if depth < len(lane):
                feed.append(lane[depth])
                if len(feed) >= 18:
                    break
        depth += 1
    return feed


def _build_sources_summary(research: dict) -> list:
    """One row per platform consulted, with counts, for the UI sources strip."""
    st = research.get("stocktwits") or []
    sent = stocktwits_sentiment(st) if st else {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0}
    return [
        {"platform": "yahoo", "label": "Yahoo Finance", "count": len(research.get("news") or []), "note": "news"},
        {"platform": "google_news", "label": "Google News", "count": len(research.get("google_news") or []), "note": "news"},
        {"platform": "web", "label": "Web · Brave", "count": len(research.get("web") or []), "note": "search"},
        {"platform": "reddit", "label": "Reddit", "count": len(research.get("reddit") or []), "note": "threads"},
        {"platform": "stocktwits", "label": "StockTwits", "count": sent["total"],
         "note": (f"{sent['bullish']}▲ / {sent['bearish']}▼" if sent["total"] else "no posts")},
        {"platform": "sec", "label": "SEC EDGAR", "count": len(research.get("sec") or []), "note": "filings"},
        {"platform": "finnhub", "label": "Finnhub", "count": len(research.get("finnhub") or {}),
         "note": "analytics"},
    ]


# ------------------------------------------------------------------ #
# Backend selection
# ------------------------------------------------------------------ #

def make_client():
    """Pick the synthesis backend.

    Order of preference:
      1. Gemini cloud API if GEMINI_API_KEY is set.
      2. The Agnes cloud API if AGNES_API_KEY is set.
      3. None -> deterministic offline synthesis.

    Set GEMINI_API_KEY in .env for the hosted web version.
    Override with LLM_BACKEND=gemini|agnes.
    """
    backend = os.environ.get("LLM_BACKEND", "").strip().lower()

    from lib.gemini_client import GeminiClient
    if backend != "agnes" and GeminiClient.is_available():
        try:
            return GeminiClient()
        except Exception:
            pass

    if backend != "gemini" and os.environ.get("AGNES_API_KEY"):
        try:
            return AgnesClient()
        except Exception:
            pass

    return None


def _model_label(client) -> str:
    """Human-readable model name for the digest meta block."""
    model = getattr(client, "model", None)
    if model:
        return str(model)
    return "offline"


# ------------------------------------------------------------------ #
# "The full story" essay (streamed narrative)
# ------------------------------------------------------------------ #

def _offline_essay(real: dict, digest: dict, research: dict) -> str:
    """Deterministic 2-paragraph narrative from already-computed digest fields."""
    snap = digest.get("snapshot") or {}
    name = snap.get("name") or real.get("name") or real.get("symbol", "")
    tldr = (digest.get("tldr") or "").strip()
    action = digest.get("action") or {}
    reason = (action.get("reasoning") or "").strip()
    bull = (digest.get("bull_case") or {}).get("outlook", "").strip()
    bear = (digest.get("bear_case") or {}).get("outlook", "").strip()
    news_n = len(research.get("news") or [])

    p1 = tldr or f"Here is where {name} stands today."
    if news_n:
        p1 += f" Across the sources we checked, {news_n} recent news items are shaping the story."
    p2_bits = []
    if bull:
        p2_bits.append(bull)
    if bear:
        p2_bits.append(bear)
    if reason:
        p2_bits.append(f"For now, the read is {action.get('signal', 'HOLD')}: {reason}")
    p2 = " ".join(p2_bits)
    return (p1 + "\n\n" + p2).strip()


def stream_essay(client, real: dict, digest: dict, research: dict, progress=None) -> str:
    """Stream a plain-English narrative of the current situation.

    Emits essay_start / essay_chunk / essay_done progress events as text arrives,
    and returns the full essay. Falls back to a deterministic essay when the
    client cannot stream or the call fails.
    """
    def emit(ev):
        if progress:
            try:
                progress(ev)
            except Exception:
                pass

    sentiment = (stocktwits_sentiment(research.get("stocktwits") or [])
                 if research.get("stocktwits") else None)
    position = digest.get("position")
    facts = {
        "name": real.get("name"), "symbol": real.get("symbol"),
        "price": real.get("price"), "change_pct": real.get("change_pct"),
        "week52_high": real.get("52w_high"), "week52_low": real.get("52w_low"),
        "tldr": digest.get("tldr"),
        "signal": (digest.get("action") or {}).get("signal"),
        "drivers": digest.get("drivers"),
        "news": [n.get("title") for n in (research.get("news") or [])[:10] if n.get("title")],
        "retail_sentiment": sentiment,
        "filings": [f.get("title") for f in (research.get("sec") or [])[:5] if f.get("title")],
        "analyst_consensus": (research.get("finnhub") or {}).get("analyst"),
        "analyst_price_target": (research.get("finnhub") or {}).get("price_target"),
        "earnings_beat_rate": ((research.get("finnhub") or {}).get("earnings") or {}).get("beat_rate"),
        "insider_activity": (research.get("finnhub") or {}).get("insider"),
        "financial_ratios": (research.get("finnhub") or {}).get("ratios"),
        "your_position": ({"shares": position.get("shares"),
                           "avg_buy_price": position.get("cost_basis"),
                           "gain_pct": position.get("gain_pct")} if position else None),
    }
    pos_line = ("The reader OWNS this stock (see your_position) — speak directly to "
                "what their gain/loss and the news mean for them. "
                if position else "")
    messages = [
        {"role": "system", "content": ESSAY_PROMPT},
        {"role": "user", "content": (
            f"As of {datetime.now().strftime('%B %d, %Y')}, write the essay for "
            f"{real.get('name')} ({real.get('symbol')}). {pos_line}\n\n"
            f"VERIFIED DATA (use only these numbers):\n{json.dumps(facts, ensure_ascii=False)}"
        )},
    ]

    emit({"type": "essay_start"})
    chunks = []
    if client is not None and hasattr(client, "chat_stream"):
        deadline = time.time() + 60
        try:
            for piece in client.chat_stream(messages, max_tokens=1200, temperature=0.4):
                chunks.append(piece)
                emit({"type": "essay_chunk", "text": piece})
                if time.time() > deadline:
                    break
        except Exception:
            chunks = []

    full = "".join(chunks).strip()
    if not full:
        full = _offline_essay(real, digest, research)
        emit({"type": "essay_chunk", "text": full})
    emit({"type": "essay_done", "text": full})
    return full


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

def build_digest(symbol: str, days: int = 30, topic: str = None, quick: bool = False,
                 want_essay: bool = True, client=None, progress=None, holding: dict = None) -> dict:
    """Build a grounded finance digest end to end.

    Returns the full digest dict: schema fields + history + media + meta.
    """
    def emit(ev):
        if progress:
            try:
                progress(ev)
            except Exception:
                pass

    symbol = (symbol or "").upper().strip()
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

    if client is None:
        client = make_client()

    # 2. Research - news, events, web, reddit.
    emit({"type": "phase", "key": "research", "label": "Reading the news"})
    research = run_research(real, topic, days, quick, progress=progress)

    # The user's position on this stock (if it's in their portfolio) — feeds the
    # synthesis so the action + essay speak to their actual holding.
    position = _build_position(real, holding) if holding else None

    # 3. Synthesis.
    emit({"type": "phase", "key": "synthesis", "label": "Writing your brief"})
    live = False
    fallback = False
    model = "offline"
    if client is not None:
        try:
            digest = live_synthesis(client, real, research, days, quick=quick, position=position)
            live = True
            model = _model_label(client)
            if not digest.get("tldr"):
                raise ValueError("empty tldr")
        except Exception as e:
            emit({"type": "status", "message": f"Synthesis fell back to offline mode: {e}"})
            digest = offline_synthesis(real, research)
            fallback = True
    else:
        digest = offline_synthesis(real, research)

    # 4. Attach research outputs + decision panels the UI renders directly. The
    #    unified feed merges every source with per-item platform attribution;
    #    `news` is kept (Yahoo) for back-compat.
    digest["news"] = research.get("news", [])
    digest["feed"] = _build_feed(research)
    digest["watch_this_week"] = _watch_list(research.get("events", {}), real)
    if position:
        digest["position"] = position
    digest["risk"] = _build_risk(real, history)
    digest["income"] = _build_income(real, research.get("events", {}), position)
    digest["finnhub"] = research.get("finnhub") or {}

    digest["history"] = history
    digest["meta"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "live": live,
        "grounded": True,
        "fallback": fallback,
        "days": days,
        "window": _build_window_report(days, research, history),
        "asset_type": real.get("asset_type", "EQUITY"),
        "elapsed_s": round(time.time() - started, 1),
    }
    emit({"type": "digest", "data": digest})

    # 6. "The full story" — a streamed plain-English essay. Runs AFTER the digest
    #    is emitted so the brief renders immediately and the essay types in below.
    if want_essay:
        try:
            digest["essay"] = stream_essay(client, real, digest, research, progress=progress)
        except Exception as e:
            emit({"type": "status", "message": f"Essay skipped: {e}"})

    return digest


def _build_window_report(days: int, research: dict, history: list) -> dict:
    """Honest accounting of what each source contributed within the window.

    Lets the UI render badges like "5 articles from the past 7 days" so the
    user can verify the brief actually reflects the timeframe they picked.
    """
    news = research.get("news") or []
    web = research.get("web") or []
    reddit = research.get("reddit") or []

    # News is the only source that returns precise age_days per item.
    news_with_age = [n for n in news if n.get("age_days") is not None]
    if news_with_age:
        newest = min(n["age_days"] for n in news_with_age)
        oldest = max(n["age_days"] for n in news_with_age)
    else:
        newest = oldest = None

    chart_days = len(history) if history else 0

    return {
        "requested_days": days,
        "label": _window_label(days),
        "sources": _build_sources_summary(research),
        "news": {
            "count": len(news),
            "newest_age_days": round(newest, 2) if newest is not None else None,
            "oldest_age_days": round(oldest, 2) if oldest is not None else None,
            "source": "Yahoo Finance",
            "filter": f"<= {days} days",
        },
        "web": {
            "count": len(web),
            "source": "Brave / Serper / Tavily",
            "filter": _window_label(days),
        },
        "reddit": {
            "count": len(reddit),
            "source": "Reddit",
            "filter": _reddit_filter_label(days),
        },
        "chart": {
            "points": chart_days,
            "source": "Yahoo Finance OHLCV",
            "note": "Chart always loads >=90 days for context, independent of brief window",
        },
    }


def _window_label(days: int) -> str:
    if days <= 1:
        return "past 24 hours"
    if days <= 7:
        return "past 7 days"
    if days <= 15:
        return "past 15 days"
    if days <= 31:
        return "past 30 days"
    if days <= 92:
        return "past 90 days"
    if days <= 365:
        return f"past {days} days"
    return "past year"


def _reddit_filter_label(days: int) -> str:
    if days <= 1:
        return "past day"
    if days <= 7:
        return "past week"
    if days <= 30:
        return "past month"
    if days <= 365:
        return "past year"
    return "all time"


def _watch_list(events: dict, real: dict) -> list:
    """Build the 'things to watch this week' bullets from yfinance events."""
    out = []
    earnings = events.get("earnings_date")
    if earnings:
        out.append(f"Next earnings report: {earnings}")
    ex_div = events.get("ex_dividend_date")
    if ex_div:
        out.append(f"Ex-dividend date: {ex_div}")
    high = real.get("52w_high")
    low = real.get("52w_low")
    price = real.get("price")
    if price and high and price >= 0.95 * high:
        out.append(f"Price is within 5% of the 12-month high (${high:,.2f}) — watch for resistance.")
    elif price and low and price <= 1.05 * low:
        out.append(f"Price is within 5% of the 12-month low (${low:,.2f}) — watch for support.")
    return out
