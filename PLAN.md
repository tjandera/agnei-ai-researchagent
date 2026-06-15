# PLAN.md - Agnes Finance Research: the delta

A teammate moved this repo toward finance (live `yahoo_finance.py`, `chart_gen.py`,
ticker dashboard, AI brief over web/Reddit/HN/Polymarket). This plan ships a
grounded, designed, tri-modal HTML digest. No CLI workflow is a deliverable.

## What is changing

1. **Grounding.** Real market numbers (price, change, 52w range, volume, fundamentals)
   are fetched up front and fused into the synthesis so the brief cites actual numbers.
2. **Structured output.** The brief returns JSON only (schema below), rendered as
   designed digest cards. No markdown blob, no `marked.js`, no PDF.
3. **Tri-modal.** A hero image (Agnes Image 2.1 Flash) and a short silent recap video
   (Agnes Video V2.0) are wired into the web product.
4. **Tool set.** Register `yahoo_finance` as an orchestrator tool. Finance tools only:
   yahoo_finance, polymarket, web_search, reddit, hackernews. Drop github/devto/arxiv.
5. **Bug fix.** `requirements.txt` now lists every imported dependency.

## Environment reality (verified)

- Only Python 3.14 is present and externally managed -> use a `.venv`. `pip install -r
  requirements.txt` succeeds there (numpy 2.4, pandas 3.0, matplotlib 3.11, fastapi,
  yfinance, Pillow).
- `AGNES_API_KEY` / `BRAVE_API_KEY` are injected **only into the running `web/app.py`
  process** by a session security hook. Standalone scripts and probes do NOT see the key.
  Consequence: all live Agnes calls (synthesis JSON, image, video) and live demo-asset
  generation must run **through the app**. Demo mode also ships an **offline fallback**
  (real yfinance + keyless connectors + deterministic synthesis + local poster) so the
  product is usable with no key at all.

## File ownership (parallel Phase 1, zero edit overlap)

- **Phase 0 (done by lead):** `requirements.txt`, `PLAN.md`, `scripts/finance_digest.py`
  (schema + tools + offline fallback + live synthesis + `build_digest` orchestration).
- **Subagent A (backend/routes):** `web/app.py` + hardening `scripts/finance_digest.py`
  (live synthesis prompt quality, retry/backoff/timeouts/fallbacks). Routes: page,
  health, ticker, chart, `/api/generate` (SSE: progress + final structured JSON),
  demo list/serve/build. **Remove** `/api/export/pdf`.
- **Subagent B (frontend):** `web/static/index.html` only. Structured digest consuming
  SSE + JSON. Keep ticker hero + Chart.js. Add theme cards, odds strip, recap-video slot,
  hero-image slot, citations, disclaimer. Remove PDF + Copy-Markdown buttons; add
  copy-summary. Progressive SSE loading states.
- **Subagent C (media/demo/docs):** `scripts/lib/media_gen.py`, `scripts/cache_demo.py`,
  `web/static/demo/`, `README.md`, `.env.example`. Hero image then recap video as final
  optional steps; offline poster fallback; cache builder; finance README; no PDF framing.

## Shared contract

### Output JSON schema (final synthesis returns THIS, JSON only)

```json
{
  "headline": "one-line takeaway",
  "snapshot": {
    "symbol": "BTC-USD", "name": "Bitcoin USD",
    "price": 65741.99, "change_pct": 0.05,
    "key_levels": { "week52_high": 126198.07, "week52_low": 59108.92,
                    "support": 62000, "resistance": 70000 }
  },
  "themes": [
    { "title": "...", "synthesis": "1-2 sentences citing a real number/source",
      "sentiment": "bullish|bearish|neutral|mixed" }
  ],
  "markets": [ { "question": "...", "probability": 63.0, "volume": 1200000.0 } ],
  "sentiment_summary": [ { "source": "r/Bitcoin", "sentiment": "...", "takeaway": "..." } ],
  "citations": [ "Polymarket", "Hacker News", "r/Bitcoin", "CoinDesk" ]
}
```

- `themes`: 3-5 items. `sentiment` is one of bullish/bearish/neutral/mixed.
- Numbers in `snapshot` are **overwritten in code** with real yfinance values before
  emit -> the page never shows a hallucinated number.
- `citations`: source names only, never raw URL chains.
- Code adds a `meta` block (not from the model): `{ generated_at, model, live, grounded,
  fallback, days, asset_type }`, plus `history` (OHLCV for the chart) and `media`
  `{ image_url, video_url }`.

### `build_digest(...)` - single entry point (finance_digest.py)

```python
build_digest(symbol, days=30, topic=None, want_media=True, progress=None) -> dict
# progress(event: dict) is an optional callback the SSE route maps to SSE frames.
# Returns the full digest dict: schema fields + meta + history + media.
```

Orchestration: fetch ticker snapshot (emit early) -> run finance research tools ->
synthesis JSON (live Agnes, 1 retry on parse failure, else offline fallback) ->
overwrite snapshot numbers with real data -> hero image -> recap video (best-effort).
Every external call has timeout + fallback; media failures degrade to `None`.

### media_gen interface (media_gen.py, called by build_digest)

```python
generate_hero_image(client, symbol, name, theme_hint, size="1024x768") -> str | None
generate_recap_video(client, image_url, symbol, name) -> str | None   # 121-241 frames, silent
offline_hero_poster(symbol, name, up: bool) -> bytes                    # Pillow, no text/numbers
```

Never ask the image/video model to render numbers or text. All numbers come from
yfinance/the chart.

### SSE frames over `/api/generate` (A emits, B consumes)

`start` -> `snapshot{data}` -> `search_start`/`search_done{tool,query,count,error}` ->
`phase{key,label}` (snapshot|research|synthesis|image|video) -> `image{url}` ->
`video{url}` -> `digest{data}` (final JSON+meta+history+media) -> `error{message,fatal}`
-> `done`.

### Demo cache layout (`web/static/demo/`)

`index.json` = `[ {key,symbol,days,name,headline} ]`; `<key>.json` = full digest;
`<key>.png` = poster; optional `<key>.mp4`. Seeds: `btc-usd-30`, `aapl-90`, `eth-usd-30`.

## Priority (ship even if time runs out)

1. Install + run (AC1) - done.
2. Grounded structured JSON digest + designed HTML (AC2/AC3/AC5).
3. Hero image (AC3/AC4).
4. Recap video (AC3/AC4).
Demo, graceful degradation, disclaimer, secrets hygiene, no PDF/emoji, README throughout.

## Hard constraints

No emojis in code/UI/copy. No em dashes in copy. Minimal comments, no stray debug prints
(progress via SSE or server-side only). Secrets only from env; update `.env.example`.
Disclaimer "informational only, not investment advice" visible on output.
