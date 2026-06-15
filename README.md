# Agnes Finance Research

A grounded, tri-modal finance digest for a single stock, ETF, or crypto symbol.
You enter a ticker and the app returns one coherent briefing in three forms:
structured data, designed cards, and a pair of generated visuals.

1. Structured JSON: a headline, a price snapshot with key levels, three to five
   themes with per theme sentiment, prediction markets, community sentiment, and
   source citations.
2. Designed cards: the same digest rendered as a clean HTML page with a price
   chart, served from the built in web app. There is no PDF.
3. Media: one abstract hero image and a short silent recap video that set the
   mood for the asset.

Every number you see comes from live market data (yfinance) and the chart. The
image and video models are never asked to draw text, numbers, tickers, or
readable charts. They produce atmosphere only.

The product works with no API key at all. When the Agnes key is absent it builds
the exact same grounded digest using a deterministic offline synthesis and a
locally drawn poster for the hero visual.

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running the web app (do change the port number if it's already been used to a different number at web/app.py)
```

```bash
python web/app.py
```

Then open http://localhost:8765 in your browser. Enter a symbol such as `AAPL`,
`BTC-USD`, or `NVDA` and the digest streams in as it is built: the price
snapshot first, then research, then the synthesized themes, then the hero image
and recap video when a key is present.

---

## Environment variables

Copy the template and fill in what you have:

```bash
cp .env.example .env
```

| Variable | Required | Purpose |
|---|---|---|
| `AGNES_API_KEY` | Yes for live mode | Prerequisite for live synthesis, the hero image, and the recap video. Without it the app still runs with grounded offline synthesis and a locally drawn poster. |
| `BRAVE_API_KEY` | Optional | Improves web and Reddit results. Falls back to keyless sources when empty. |

The web app reads `.env` from the project root on startup. The key is injected
only into the running app process.

---

## Demo mode

Three digests ship pre built and cached so the product is instant with no live
API call:

- `BTC-USD` over 30 days
- `AAPL` over 90 days
- `ETH-USD` over 30 days

They live in `web/static/demo/` as `<key>.json` (the full digest) and
`<key>.png` (the locally drawn poster), with `index.json` listing them. The UI
reads `index.json` and shows one demo chip per seed. Clicking a chip loads the
cached digest straight from disk through `/api/demo/{key}`, so it renders
immediately and uses no quota.

These seeds are grounded real data digests built offline. Rebuild them anytime:

```bash
.venv/bin/python scripts/cache_demo.py
```

That writes the three JSON digests, the three posters, and `index.json`. It runs
fully offline with no key, which is expected.

When a key is present in the running app, the live build route can regenerate a
seed with real Agnes media (hero image plus recap video) and cache the result in
the same `web/static/demo/` folder.

---

## A note on the visuals

The hero image and recap video are mood pieces, never data. The prompts
explicitly forbid text, words, numbers, tickers, logos, and readable charts. All
figures in the digest are sourced from yfinance and drawn into the price chart,
so nothing financial is ever hallucinated by an image or video model. The
offline poster shows only the symbol and asset name as typographic labels and a
trend up or trend down tag, never a price.

---

## Architecture

```
agnei-ai-researchagent/
├── requirements.txt
├── .env.example
├── web/
│   ├── app.py                 FastAPI app, SSE streaming, demo routes
│   └── static/
│       ├── index.html         Single page UI: input, chart, cards, media
│       └── demo/              Cached seed digests, posters, and index.json
└── scripts/
    ├── finance_digest.py      Orchestrator: build_digest end to end
    ├── cache_demo.py          Builds and caches the demo seeds
    └── lib/
        ├── agnes_client.py    Agnes wrapper: chat, image, video
        ├── media_gen.py       Hero image, recap video, offline poster
        ├── yahoo_finance.py   Live prices, fundamentals, OHLCV history
        ├── polymarket_search.py
        ├── web_search.py
        ├── reddit_search.py
        ├── hackernews_search.py
        └── chart_gen.py       PNG price chart for the cards
```

### How it works

1. Snapshot. `finance_digest.build_digest` pulls live market data for the symbol
   from the `yahoo_finance` tool: price, daily change, 52 week range, volume, and
   fundamentals.
2. Research. It fans out in parallel across the Polymarket, web, Reddit, and
   Hacker News connectors for odds, news, and community sentiment.
3. Synthesis. With a key, Agnes synthesizes a structured JSON digest grounded in
   the verified numbers. With no key, a deterministic offline synthesis produces
   the same shape from the same real data. Real numbers always win over model
   output.
4. Media. With a key, Agnes generates one abstract hero image, then a short
   silent recap video seeded by that image. With no key, a locally drawn poster
   stands in. Media is best effort and never blocks the digest.

### Agnes models used

| Model | Role |
|---|---|
| `agnes-2.0-flash` | Synthesizer with Thinking mode |
| `agnes-image-2.1-flash` | Abstract hero image |
| `agnes-video-v2.0` | Short silent recap video |

### Connectors

| Source | Auth |
|---|---|
| Yahoo Finance | None |
| Polymarket | None |
| Hacker News | None |
| Reddit | None, better with `BRAVE_API_KEY` |
| Web | `BRAVE_API_KEY` optional, keyless fallback |
