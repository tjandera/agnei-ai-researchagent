---
name: agnes-research
version: "1.0.0"
description: "Deep research engine covering the last 30 days across Reddit, X, YouTube, HN, Polymarket, and the web — synthesized by Agnes 2.0 Flash with Thinking mode. Optionally generates visual briefs and animated summaries via Agnes Image and Video models."
argument-hint: 'agnes-research AI video tools, agnes-research best project management software'
allowed-tools: Bash, Read, Write, AskUserQuestion, WebSearch
homepage: https://github.com/mvanhorn/last30days-skill
repository: https://github.com/mvanhorn/last30days-skill
author: mvanhorn (adapted for Agnes AI)
license: MIT
user-invocable: true
metadata:
  openclaw:
    emoji: "🔍"
    requires:
      env:
        - AGNES_API_KEY
      optionalEnv:
        - SCRAPECREATORS_API_KEY
        - BRAVE_API_KEY
        - AUTH_TOKEN
        - CT0
        - BSKY_HANDLE
        - BSKY_APP_PASSWORD
      bins:
        - python3
    primaryEnv: AGNES_API_KEY
    files:
      - "scripts/*"
    tags:
      - research
      - deep-research
      - agnes-ai
      - reddit
      - hackernews
      - polymarket
      - web-search
      - synthesis
      - image-generation
      - video-generation
      - trends
      - recency
---

# Agnes Research Skill v1.0.0

Research ANY topic across Reddit, X, Hacker News, Polymarket, and the web.
Agnes 2.0 Flash acts as the orchestrator AND synthesizer — using tool calling to
run parallel searches and Thinking mode to produce grounded, cited reports.
Optionally generates a visual report cover (Agnes Image 2.1 Flash) and animated
brief (Agnes Video V2.0).

---

## CRITICAL: Parse User Intent

Before doing anything, parse the user's input for:

1. **TOPIC** — what they want to learn about
2. **QUERY_TYPE** — one of:
   - `RECOMMENDATIONS` — "best X", "top X", "what X should I use"
   - `NEWS` — "what's happening with X", "X news", "latest on X"
   - `COMPARISON` — "X vs Y", "compare X and Y"
   - `GENERAL` — anything else
3. **FLAGS** — check for:
   - `--image` → generate visual report cover via Agnes Image 2.1 Flash
   - `--video` → generate animated brief via Agnes Video V2.0 (requires --image)
   - `--days=N` → look back N days (default 30)
   - `--quick` → faster, fewer sources

**Before calling any tools, display:**

```
I'll research {TOPIC} across Reddit, HN, Polymarket, and the web using Agnes 2.0 Flash.

Parsed intent:
- TOPIC = {TOPIC}
- QUERY_TYPE = {QUERY_TYPE}
- FLAGS = {FLAGS or "none"}

Starting research now. Agnes will orchestrate searches in parallel.
```

---

## Research Execution

**Run the Agnes research script in the FOREGROUND with a 5-minute timeout:**

```bash
# Locate skill root
for dir in \
  "." \
  "${CLAUDE_PLUGIN_ROOT:-}" \
  "$HOME/.claude/plugins/marketplaces/agnes-research-skill" \
  "$HOME/.claude/skills/agnes-research" \
  "$HOME/.agents/skills/agnes-research"; do
  [ -n "$dir" ] && [ -f "$dir/scripts/agnes_research.py" ] && SKILL_ROOT="$dir" && break
done

if [ -z "${SKILL_ROOT:-}" ]; then
  echo "ERROR: Could not find scripts/agnes_research.py" >&2
  exit 1
fi

python3 "${SKILL_ROOT}/scripts/agnes_research.py" $ARGUMENTS \
  --save-dir=~/Documents/AgnesResearch
```

**Flags passed through from user input:**
- `--days=N` → look back N days
- `--quick` → fewer results per source
- `--image` → generate visual cover via Agnes Image 2.1 Flash
- `--video` → generate animated brief via Agnes Video V2.0

**Read the ENTIRE output.** It contains data from all sources plus the Agnes synthesis.

---

## If QUERY_TYPE = COMPARISON

Run the script twice in parallel, then a combined pass:

```bash
# Pass 1 + 2 in parallel:
python3 "${SKILL_ROOT}/scripts/agnes_research.py" {TOPIC_A} --emit=compact
python3 "${SKILL_ROOT}/scripts/agnes_research.py" {TOPIC_B} --emit=compact

# Pass 3 after both complete:
python3 "${SKILL_ROOT}/scripts/agnes_research.py" "{TOPIC_A} vs {TOPIC_B}" --emit=compact
```

Then synthesize into a side-by-side comparison table.

---

## WebSearch Supplement

After the script completes, run 2 WebSearches to catch blog/editorial coverage:

- **RECOMMENDATIONS:** `best {TOPIC} 2025`, `{TOPIC} recommendations list`
- **NEWS:** `{TOPIC} news 2025`, `{TOPIC} latest update`
- **COMPARISON:** `{TOPIC_A} vs {TOPIC_B} 2025`
- **GENERAL:** `{TOPIC} 2025 discussion`, `{TOPIC} community`

Exclude reddit.com, x.com (already covered by script). Cite web sources by name only — no raw URLs.

---

## Synthesis Rules

Agnes 2.0 Flash handles synthesis internally (Thinking mode on). When displaying results:

1. **Ground every claim in data** — upvote counts, view counts, @handles, subreddits
2. **Lead with people** — what Reddit/X/HN users are saying, not what editors wrote
3. **Cross-platform signals are strongest** — same story on Reddit + HN + Polymarket = lead finding
4. **Polymarket odds are hard evidence** — cite specific % and movement: "74% ceasefire by Dec 31 (up 8%)"
5. **Quote the best takes directly** — top Reddit comments, YouTube transcript highlights
6. **Cite sparingly:** "per @handle" or "per r/subreddit" — not chains of citations
7. **No raw URLs ever** — use publication names only

---

## Output Format

**Display in this exact sequence:**

### 1. What I learned

```
## What I learned about {TOPIC}

**{Key finding 1}** — [1-2 sentences with specific data, per @handle or r/sub]

**{Key finding 2}** — [1-2 sentences, per source]

**{Key finding 3}** — [1-2 sentences, per source]

KEY PATTERNS:
1. [Pattern] — per @handle
2. [Pattern] — per r/subreddit
3. [Pattern] — per HN
```

### 2. Stats block

```
---
✅ Agnes research complete!
├─ 🟠 Reddit: {N} threads │ {N} upvotes │ {N} comments
├─ 🟡 HN: {N} stories │ {N} points │ {N} comments
├─ 📊 Polymarket: {N} markets │ {summary of top odds}
├─ 🌐 Web: {N} pages — Source Name, Source Name
└─ 🗣️ Top voices: @{handle1} ({N} likes) │ r/{sub1}, r/{sub2}
---
```

Omit any line that returned 0 results.

### 3. Visual outputs (if --image or --video flagged)

If `--image` was set:
```
📸 Visual Brief: [Agnes Image 2.1 Flash generated cover URL]
```

If `--video` was set:
```
🎬 Animated Brief: [Agnes Video V2.0 generated clip URL]
```

### 4. Invitation

```
---
I'm now an expert on {TOPIC}. Some things I can help with:
- [Specific follow-up based on biggest finding]
- [Question about implications of a key trend]
- [Deeper dive into a pattern or debate]
```

Suggestions must be grounded in what was actually found — not generic.

---

## WAIT FOR USER RESPONSE

Stop after displaying the invitation. Do not run more tools until the user replies.

---

## When User Responds

- **Question about topic** → Answer from research (no new searches)
- **Different topic** → Start fresh research pass
- **"go deeper on X"** → Elaborate from existing findings
- **"write a prompt / draft / summary"** → Produce it using your research expertise

---

## Agent Mode (--agent flag)

If `--agent` appears in arguments:

1. Skip the intro display block
2. Skip all `AskUserQuestion` calls
3. Run research and output the complete report
4. Stop — do not wait for user input

Agent mode report format:
```
## Agnes Research Report: {TOPIC}
Generated: {date} | Sources: Reddit, HN, Polymarket, Web | Model: Agnes 2.0 Flash

### Key Findings
[3-5 bullet points with citations]

### Full Synthesis
{synthesis}

### Stats
{stats block}
```

---

## Security & Permissions

**What this skill does:**
- Calls Agnes AI API (`apihub.agnes-ai.com`) for orchestration and synthesis using `AGNES_API_KEY`
- Searches Reddit via public JSON API (no auth, free)
- Searches Hacker News via Algolia API (no auth, free)
- Searches Polymarket via Gamma API (no auth, free)
- Optionally calls Brave Search API for web results (`BRAVE_API_KEY`)
- Optionally uses ScrapeCreators for X/TikTok/Instagram (`SCRAPECREATORS_API_KEY`)
- Optionally generates images via Agnes Image 2.1 Flash (`AGNES_API_KEY`)
- Optionally generates video via Agnes Video V2.0 (`AGNES_API_KEY`)
- Saves research briefings as .md files to `~/Documents/AgnesResearch/`

**What this skill does NOT do:**
- Does not post, like, or modify content on any platform
- Does not access your accounts
- Does not share your API key with any endpoint except `apihub.agnes-ai.com`
- Does not log or cache API keys
