# Agnes Research Skill

Deep topic research across Reddit, Hacker News, Polymarket, and the web — orchestrated and synthesized by **Agnes 2.0 Flash** with Thinking mode. Optionally generates a visual report cover and animated brief via Agnes Image 2.1 Flash and Agnes Video V2.0.

Adapted from [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) (MIT) — same architecture, same connectors, Agnes AI as the AI layer.

---

## Terminal Preview

```
  Agnes Research  v1.0 · powered by Agnes 2.0 Flash

  Topic   AI coding assistants
  Window  30 days  ·  Sources  Reddit · HN · Polymarket · Web

 ──────────────────────────────────────────────────────────
   Source         Query                              Status
 ──────────────────────────────────────────────────────────
  🟠  Reddit       AI coding assistants               ✓ 18 results
  🟡  Hacker News  AI coding tools 2025               ✓ 12 results
  📊  Polymarket   AI developer tools                 ✓ 3 results
  🌐  Web          best AI coding assistant 2025       ✓ 9 results
  🟠  Reddit       Cursor vs Copilot vs Cody           ✓ 14 results
  🟡  Hacker News  AI pair programming                ✓ 8 results
 ──────────────────────────────────────────────────────────

 ─────────────────────────────────────────────────────────
 ## What I learned about AI coding assistants
 ...
```

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/agnes-research-skill
cd agnes-research-skill

# 2. Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Add your Agnes AI key to .env
cp .env.example .env
# then open .env and replace your_key_here with your actual key

# 4. Run
python3 scripts/agnes_research.py "AI coding assistants"
```

---

## Terminal Setup (run from anywhere)

Add an alias to your shell so you can call `agnes` from any directory:

```bash
# Open your shell config
open ~/.zshrc
```

Add this line (update the path if you cloned somewhere else):

```bash
alias agnes='AGNES_PROJECT=~/Documents/agnei-ai-researchagent && source "$AGNES_PROJECT/.venv/bin/activate" && python3 "$AGNES_PROJECT/scripts/agnes_research.py"'
```

Save the file, then reload:

```bash
source ~/.zshrc
```

Now you can run research from anywhere:

```bash
agnes "AI coding assistants"
agnes "OpenAI vs Anthropic" --days=7 --quick
agnes "crypto defi" --image
```

---

## Usage

```bash
# Basic research (30-day window, rich terminal UI)
python scripts/agnes_research.py "topic here"

# Shorter window, faster
python scripts/agnes_research.py "topic" --days=7 --quick

# Generate visual cover + animated brief
python scripts/agnes_research.py "topic" --image --video

# Plain output (no rich formatting)
python scripts/agnes_research.py "topic" --plain

# Agent mode (no TUI, machine-readable, pipe-friendly)
python scripts/agnes_research.py "topic" --agent

# Pipe a topic from stdin
echo "typescript vs rust" | python scripts/agnes_research.py --agent

# Save report to a custom directory
python scripts/agnes_research.py "topic" --save-dir=~/Desktop/research
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `AGNES_API_KEY` | **Yes** | Agnes AI API key from [apihub.agnes-ai.com](https://apihub.agnes-ai.com) |
| `BRAVE_API_KEY` | No | [Brave Search](https://brave.com/search/api/) — better web results (2,000 free/month) |
| `SCRAPECREATORS_API_KEY` | No | X/TikTok/Instagram connector |

---

## Architecture

```
agnes-research-skill/
├── SKILL.md                      ← Claude skill definition
├── requirements.txt
└── scripts/
    ├── agnes_research.py         ← Main orchestrator + CLI
    ├── tui.py                    ← Rich terminal UI (auto-detects TTY)
    └── lib/
        ├── agnes_client.py       ← Agnes AI wrapper (chat, image, video)
        ├── reddit_search.py      ← Reddit public JSON API (free, no auth)
        ├── hackernews_search.py  ← Algolia HN API (free, no auth)
        ├── polymarket_search.py  ← Polymarket Gamma API (free, no auth)
        └── web_search.py         ← Brave Search / DuckDuckGo fallback
```

### How it works

1. **Orchestration** — Agnes 2.0 Flash decides which sources to search and with what queries, using OpenAI-compatible tool calling.
2. **Data collection** — Each tool call hits a real connector (Reddit, HN, Polymarket, web). All connectors are free and require no auth by default.
3. **Synthesis** — Agnes 2.0 Flash with Thinking mode synthesizes all data into a grounded, cited brief.
4. **Visuals** (optional) — Agnes Image 2.1 Flash generates a report cover; Agnes Video V2.0 generates an animated brief using the cover as a starting frame.

### Agnes AI models used

| Model | Role |
|---|---|
| `agnes-2.0-flash` | Orchestrator + synthesizer (tool calling + Thinking mode) |
| `agnes-image-2.1-flash` | Visual report cover generation (`--image`) |
| `agnes-video-v2.0` | Animated brief generation (`--video`) |

---

## Connectors

| Source | API | Auth |
|---|---|---|
| Reddit | `reddit.com/search.json` | None (public) |
| Hacker News | Algolia HN API | None (public) |
| Polymarket | Gamma API | None (public) |
| Web | Brave Search API | `BRAVE_API_KEY` (or DDG fallback) |

---

## Terminal UI

The rich terminal UI auto-activates when stdout is a TTY. It shows:
- A startup panel with topic, window, and model info
- A live source table that updates as each search completes
- The final report rendered as formatted markdown
- Image and video URLs in styled panels

Pass `--plain` to disable rich formatting, or `--agent` for fully machine-readable output.

The UI degrades gracefully: if `rich` is not installed, it falls back to plain `print()` automatically.

---

## License

MIT — adapted from [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill).
