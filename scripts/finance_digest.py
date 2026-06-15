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
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

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
  "citations": ["Yahoo Finance", "Reuters", "r/stocks"]
}

The level_to_watch numbers are price levels in dollars. The bull level should
be above today's price (a target if things go well). The bear level should be
below today's price (a stop-out point if things go badly). If you cannot infer
a level from the data, set it to null."""


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

    # Citations
    citations = ["Yahoo Finance"]
    for item in (research.get("news") or [])[:4]:
        pub = (item.get("publisher") or "").strip()
        if pub and pub not in citations:
            citations.append(pub)
    for r in (research.get("reddit") or [])[:2]:
        if isinstance(r, dict):
            sub = (r.get("subreddit") or "").strip()
            if sub and sub not in citations:
                citations.append(sub)

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
# benefit from a reasoning trace, and skipping it cuts response time from
# ~60-100 s to ~10-15 s with no measurable quality loss on a grounded prompt.
SYNTHESIS_ATTEMPT_TIMEOUT_S = 45
SYNTHESIS_RETRY_TIMEOUT_S = 25
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

    return {
        "news": _slim_news(research.get("news")),
        "web": _slim_web(research.get("web")),
        "reddit": _slim_reddit(research.get("reddit")),
    }


def live_synthesis(client: AgnesClient, real: dict, research: dict, days: int, quick: bool = False) -> dict:
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
    slim_research = _trim_research_for_model(research, quick)
    user = (
        f"Asset: {real.get('name')} ({real.get('symbol')})\n"
        f"As of {datetime.now().strftime('%B %d, %Y')}, {days}-day window.\n\n"
        f"VERIFIED MARKET NUMBERS (use these exactly, do not change them):\n"
        f"{json.dumps(facts, ensure_ascii=False)}\n\n"
        f"RESEARCH DATA:\n{json.dumps(slim_research, ensure_ascii=False)}\n\n"
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
    """Fan out finance research in parallel.

    Returns: {news, events, web, reddit}. Polymarket is intentionally not
    pulled — it has no relevance for individual stocks.
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

    def _news():
        _emit({"type": "search_start", "tool": "yahoo_news", "query": sym})
        items = get_stock_news(sym, limit=8)
        _emit({"type": "search_done", "tool": "yahoo_news",
               "query": sym, "count": len(items), "error": False})
        return ("news", items)

    def _events():
        # No emit — this is fast and uninteresting to the progress UI.
        return ("events", get_upcoming_events(sym))

    def _web():
        q = f"{name} stock news"
        _emit({"type": "search_start", "tool": "search_web", "query": q})
        items = search_web(q, limit=6 if quick else 8, days=days)
        # The search_web fallback returns an [{"error":...}] sentinel; treat as empty.
        clean = [r for r in items if isinstance(r, dict) and not r.get("error")]
        _emit({"type": "search_done", "tool": "search_web",
               "query": q, "count": len(clean), "error": len(items) > 0 and not clean})
        return ("web", clean)

    def _reddit():
        q = f"{name} {sym}"
        _emit({"type": "search_start", "tool": "search_reddit", "query": q})
        items = search_reddit(q, limit=n, days=days)
        clean = [r for r in items if isinstance(r, dict) and not r.get("error")]
        _emit({"type": "search_done", "tool": "search_reddit",
               "query": q, "count": len(clean), "error": False})
        return ("reddit", clean)

    grouped = {"news": [], "events": {}, "web": [], "reddit": []}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fn) for fn in (_news, _events, _web, _reddit)]
        for fut in as_completed(futures):
            try:
                key, data = fut.result()
                grouped[key] = data
            except Exception:
                continue
    return grouped


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

def build_digest(symbol: str, days: int = 30, topic: str = None, quick: bool = False,
                 want_media: bool = True, client: AgnesClient = None, progress=None) -> dict:
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

    # Bring up the Agnes client now so we can kick off the image generation
    # in parallel with research + synthesis (the image is the longest-running
    # serial step otherwise, blocking the whole brief for ~30 s).
    if client is None and os.environ.get("AGNES_API_KEY"):
        try:
            client = AgnesClient()
        except Exception:
            client = None

    # Start hero image generation NOW (in the background) — it only needs
    # symbol + name, so it can run concurrently with research + synthesis.
    image_pool = None
    image_future = None
    if want_media and client is not None:
        try:
            from lib import media_gen
            image_pool = ThreadPoolExecutor(max_workers=1)
            image_future = image_pool.submit(
                media_gen.generate_hero_image,
                client, real.get("symbol", ""), real.get("name", ""),
                "",  # theme_hint not available yet; symbol/name is enough
            )
            emit({"type": "phase", "key": "image", "label": "Making your share card"})
        except Exception:
            image_pool = image_future = None

    # 2. Research - news, events, web, reddit.
    emit({"type": "phase", "key": "research", "label": "Reading the news"})
    research = run_research(real, topic, days, quick, progress=progress)

    # 3. Synthesis.
    emit({"type": "phase", "key": "synthesis", "label": "Writing your brief"})
    live = False
    fallback = False
    model = "offline"
    if client is not None:
        try:
            digest = live_synthesis(client, real, research, days, quick=quick)
            live = True
            model = "agnes-2.0-flash"
            if not digest.get("tldr"):
                raise ValueError("empty tldr")
        except Exception as e:
            emit({"type": "status", "message": f"Synthesis fell back to offline mode: {e}"})
            digest = offline_synthesis(real, research)
            fallback = True
    else:
        digest = offline_synthesis(real, research)

    # 4. Attach research outputs the UI will render directly.
    digest["news"] = research.get("news", [])
    digest["watch_this_week"] = _watch_list(research.get("events", {}), real)

    # 5. Media - collect the image result (likely already complete by now).
    media = {"image_url": None}
    if image_future is not None:
        try:
            # The image normally finishes during synthesis. Cap the wait at
            # 25 s so a stuck image call can't block the whole brief.
            media["image_url"] = image_future.result(timeout=25)
            if media["image_url"]:
                emit({"type": "image", "url": media["image_url"]})
        except Exception as e:
            emit({"type": "status", "message": f"Share card image skipped: {e}"})
        finally:
            if image_pool is not None:
                image_pool.shutdown(wait=False)

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
