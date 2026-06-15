#!/usr/bin/env python3
"""
Agnes Research - main orchestrator.

Uses Agnes 2.0 Flash with tool calling to plan and execute research
across Reddit, Hacker News, Polymarket, and the web. Synthesizes
findings with Thinking mode. Optionally generates visual briefs
via Agnes Image 2.1 Flash and Agnes Video V2.0.

Usage:
  python agnes_research.py "AI coding assistants"
  python agnes_research.py "OpenAI vs Anthropic" --days=7 --image --video
  python agnes_research.py "crypto markets" --quick --agent
  python agnes_research.py "latest in LLMs" --emit=compact --plain
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# Load .env from project root if present
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Allow running from scripts/ directly
sys.path.insert(0, str(Path(__file__).parent))

from lib.agnes_client import AgnesClient
from lib.reddit_search import search_reddit
from lib.hackernews_search import search_hackernews
from lib.polymarket_search import search_polymarket
from lib.web_search import search_web
from lib.github_search import search_github
from lib.devto_search import search_devto
from lib.arxiv_search import search_arxiv
from tui import make_ui


# ------------------------------------------------------------------ #
# Tool definitions for Agnes 2.0 Flash
# ------------------------------------------------------------------ #

RESEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_reddit",
            "description": (
                "Search Reddit for posts and top comments about a topic. "
                "Returns threads with upvote counts, subreddit names, and top comments. "
                "Best for community opinions, hot takes, and unfiltered discussion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query. Be specific - use exact product/person names where possible.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max posts to return (default 20, max 50).",
                        "default": 20,
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["relevance", "hot", "top", "new", "comments"],
                        "description": "Sort order (default: relevance).",
                        "default": "relevance",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hackernews",
            "description": (
                "Search Hacker News for stories and technical discussions. "
                "Returns stories with point counts and top comments. "
                "Best for developer opinions, technical analysis, and startup news."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max stories (default 10).",
                        "default": 10,
                    },
                    "min_points": {
                        "type": "integer",
                        "description": "Minimum HN points (default 5, increase to filter noise).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_polymarket",
            "description": (
                "Search Polymarket prediction markets for relevant odds. "
                "Returns markets with probability % and volume. "
                "Best for quantified uncertainty - elections, releases, outcomes. "
                "Real money = high-signal data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max markets (default 8).",
                        "default": 8,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the web for recent articles, blog posts, and editorial coverage. "
                "Returns titles, URLs, and descriptions. "
                "Use for context and facts not covered by Reddit/HN."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10).",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_github",
            "description": (
                "Search GitHub for repositories related to a topic. "
                "Returns repos with star counts, descriptions, and languages. "
                "Best for tech topics, open-source tools, what developers are actively building."
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
            "name": "search_devto",
            "description": (
                "Search Dev.to for developer blog posts about a topic. "
                "Returns posts with reaction counts. "
                "Best for developer opinions, tutorials, and tool comparisons."
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
            "name": "search_arxiv",
            "description": (
                "Search ArXiv for academic papers and preprints. "
                "Returns papers with abstracts and authors. "
                "Best for AI/ML research, science, and technical deep-dives."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 6},
                },
                "required": ["query"],
            },
        },
    },
]


# ------------------------------------------------------------------ #
# System prompts
# ------------------------------------------------------------------ #

ORCHESTRATOR_PROMPT = """You are a research orchestrator powered by Agnes 2.0 Flash.
Your job: research the given topic thoroughly using the available tools, then synthesize
your findings into a grounded, cited brief.

RESEARCH STRATEGY:
1. Run 2-4 parallel searches across different platforms. Use specific query variations:
   - Exact topic name
   - Topic + "review" or "discussion" or the current year
   - For people: their handle or full name
   - For tools: "[tool] alternative" or "[tool] vs"

2. After collecting data, synthesize using these rules:
   - Weight by engagement: Reddit upvotes > HN points > web articles
   - Cross-platform signals (same story on Reddit + HN + Polymarket) = strongest evidence
   - Quote top Reddit comments and HN takes directly - they're the signal
   - Polymarket odds are hard evidence; cite the % and volume
   - NEVER paste raw URLs - use site/publication names only
   - Cite sparingly: "per @handle" or "per r/subreddit" - not chains

3. Output format:
```
## What I learned about {TOPIC}

**{Finding 1}** - [1-2 sentences with data, per source]
**{Finding 2}** - [1-2 sentences, per source]
**{Finding 3}** - [1-2 sentences, per source]

KEY PATTERNS:
1. [Pattern] - per r/subreddit or HN
2. [Pattern] - per source
3. [Pattern] - per source

---
 Agnes research complete!
├─  Reddit: {N} threads │ {N} total upvotes
├─  HN: {N} stories │ {N} total points
├─  Polymarket: {N} markets │ {top odds summary}
├─  Web: {N} pages - Source, Source, Source
└─  Top signal: {highest-engagement finding}
---
```

Be grounded. Only cite what the data actually says. Do not invent facts or fill
gaps with your training data. If evidence is thin, say so.
"""

SYNTHESIS_ONLY_PROMPT = """You are a world-class research synthesizer.
You receive raw research data from Reddit, HN, Polymarket, and the web.
Synthesize it into a grounded, cited brief.

Rules:
- Ground every claim in the actual research data (upvote counts, point counts, odds)
- Lead with what PEOPLE are saying, not what editors wrote
- Cross-platform signals are the strongest evidence
- Quote the best Reddit/HN takes directly
- Polymarket: cite specific % and volume
- No raw URLs - use publication/site names only
- Cite sparingly: one source per pattern
"""


# ------------------------------------------------------------------ #
# Tool executor
# ------------------------------------------------------------------ #

def execute_tool(name: str, args: dict, days: int = 30) -> str:
    """Run a research tool and return its output as a JSON string."""
    try:
        if name == "search_reddit":
            results = search_reddit(
                args["query"],
                limit=args.get("limit", 20),
                days=days,
                sort=args.get("sort", "relevance"),
            )
        elif name == "search_hackernews":
            results = search_hackernews(
                args["query"],
                limit=args.get("limit", 10),
                days=days,
                min_points=args.get("min_points", 5),
            )
        elif name == "search_polymarket":
            results = search_polymarket(
                args["query"],
                limit=args.get("limit", 8),
            )
        elif name == "search_web":
            results = search_web(
                args["query"],
                limit=args.get("limit", 10),
                days=days,
            )
        elif name == "search_github":
            results = search_github(
                args["query"],
                limit=args.get("limit", 8),
                days=days,
            )
        elif name == "search_devto":
            results = search_devto(
                args["query"],
                limit=args.get("limit", 8),
                days=days,
            )
        elif name == "search_arxiv":
            results = search_arxiv(
                args["query"],
                limit=args.get("limit", 6),
                days=days,
            )
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

        return json.dumps(results, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e), "tool": name})


# ------------------------------------------------------------------ #
# Parallel research (fans out all searches at once, then synthesizes)
# ------------------------------------------------------------------ #

def run_parallel_research(
    topic: str,
    days: int = 30,
    quick: bool = False,
    save_dir: str = None,
    agent_mode: bool = False,
    plain: bool = False,
    ui=None,
) -> str:
    """
    Parallel mode: fire all searches simultaneously across every source,
    then run one synthesis call. Typically 2-3x faster than the agent loop.
    """
    client = AgnesClient()
    if ui is None:
        use_plain = plain or agent_mode
        ui = make_ui(topic, days, force_plain=use_plain)
    ui.start()

    # Pre-planned search queries (Agnes decides in normal mode; here we fan out)
    n    = 5 if quick else 15
    year = datetime.now().year
    searches = [
        ("search_reddit",     {"query": topic,                              "limit": n}),
        ("search_reddit",     {"query": f"{topic} review discussion",       "limit": n}),
        ("search_hackernews", {"query": topic,                              "limit": 5 if quick else 10}),
        ("search_hackernews", {"query": f"{topic} {year}",                  "limit": 5 if quick else 10}),
        ("search_polymarket", {"query": topic,                              "limit": 8}),
        ("search_web",        {"query": f"{topic} {year}",                  "limit": 5 if quick else 10}),
        ("search_web",        {"query": f"{topic} latest news",             "limit": 5 if quick else 10}),
        ("search_github",     {"query": topic,                              "limit": 5 if quick else 8}),
        ("search_devto",      {"query": topic,                              "limit": 5 if quick else 8}),
        ("search_arxiv",      {"query": topic,                              "limit": 3 if quick else 6}),
    ]

    tracked = ui.wrap_executor(lambda name, args: execute_tool(name, args, days))

    # Run all searches simultaneously
    raw: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(searches)) as pool:
        futures = {
            pool.submit(tracked, tool, args): f"{tool}:{args['query'][:30]}"
            for tool, args in searches
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                raw[key] = future.result()
            except Exception as e:
                raw[key] = json.dumps({"error": str(e)})

    ui.stop_live()

    # Build synthesis prompt from all raw results
    sections = []
    for key, result in raw.items():
        try:
            data = json.loads(result)
            if isinstance(data, list) and data:
                sections.append(f"### {key}\n{json.dumps(data, indent=2)}")
        except Exception:
            pass

    synthesis_input = (
        f"Topic: **{topic}**\n"
        f"Today: {datetime.now().strftime('%B %d, %Y')} · Look-back: {days} days\n\n"
        + "\n\n".join(sections)
        + "\n\nSynthesize the above into a grounded research brief. "
        "Only cite what is in the data above. Do not fill gaps with training knowledge from prior years."
    )

    report = client.get_message_content(
        client.chat(
            messages=[
                {"role": "system", "content": SYNTHESIS_ONLY_PROMPT},
                {"role": "user",   "content": synthesis_input},
            ],
            thinking=True,
            max_tokens=8192,
        )
    )

    ui.print_report(report)

    if save_dir:
        _save_report(report, topic, save_dir)

    return report


# ------------------------------------------------------------------ #
# Main research function
# ------------------------------------------------------------------ #

def run_research(
    topic: str,
    days: int = 30,
    quick: bool = False,
    emit: str = "full",
    generate_image: bool = False,
    generate_video: bool = False,
    save_dir: str = None,
    agent_mode: bool = False,
    plain: bool = False,
    ui=None,
) -> str:
    client = AgnesClient()

    if ui is None:
        use_plain = plain or agent_mode
        ui = make_ui(topic, days, force_plain=use_plain)
    ui.start()

    # Build user message for orchestrator
    year = datetime.now().year
    user_message = (
        f"Research this topic thoroughly: **{topic}**\n\n"
        f"Today is {datetime.now().strftime('%B %d, %Y')}. Look back {days} days only - focus on recent content from {year}, not older years. "
        f"{'Run quick searches with fewer results.' if quick else 'Run comprehensive searches.'}\n\n"
        f"Use all available tools. Run multiple query variations to get broad coverage. "
        f"When adding a year to queries, use {year} - not any prior year. "
        f"Then synthesize everything into a grounded report following the output format in your instructions."
    )

    # Wrap executor so the TUI can track progress
    tracked_executor = ui.wrap_executor(
        lambda name, args: execute_tool(name, args, days=days)
    )

    # Run the agentic research loop
    report = client.run_agent(
        system_prompt=ORCHESTRATOR_PROMPT.replace("{TOPIC}", topic),
        user_message=user_message,
        tools=RESEARCH_TOOLS,
        tool_executor=tracked_executor,
        thinking=True,
        max_iterations=25,
    )

    # Stop live display before printing results
    ui.stop_live()

    # Optional: generate visual outputs
    image_url = None
    video_url = None

    if generate_image:
        ui.print_status("Generating visual cover (Agnes Image 2.1 Flash)...")
        image_prompt = (
            f"A sophisticated research intelligence brief cover for the topic '{topic}'. "
            "Dark editorial aesthetic, abstract data visualization, cinematic lighting, "
            "professional broadcast design, high contrast, no text."
        )
        try:
            image_url = client.generate_image(image_prompt, size="1024x768")
            report += f"\n\n Visual Brief: {image_url}"
            ui.print_image_url(image_url)
        except Exception as e:
            msg = f"Image generation failed: {e}"
            report += f"\n\n {msg}"
            ui.print_error(msg)

    if generate_video and image_url:
        ui.print_status("Generating animated brief (Agnes Video V2.0)...")
        video_prompt = (
            f"Cinematic slow reveal of research intelligence findings about '{topic}'. "
            "Atmospheric, professional broadcast aesthetic, slow camera push-in, "
            "dark editorial background, atmospheric particle effects."
        )
        try:
            video_url = client.generate_video(
                prompt=video_prompt,
                image_url=image_url,
                num_frames=121,
                frame_rate=24,
            )
            report += f"\n Animated Brief: {video_url}"
            ui.print_video_url(video_url)
        except Exception as e:
            msg = f"Video generation failed: {e}"
            report += f"\n {msg}"
            ui.print_error(msg)

    # Print the report through the TUI
    ui.print_report(report)

    # Save to disk if requested
    if save_dir:
        _save_report(report, topic, save_dir)

    return report


def _save_report(content: str, topic: str, save_dir: str) -> None:
    """Save research report to a markdown file."""
    path = Path(save_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    safe_topic = "".join(c if c.isalnum() or c in "-_ " else "_" for c in topic)[:60]
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    filename = path / f"{safe_topic}-{ts}.md"
    try:
        filename.write_text(
            f"# Agnes Research: {topic}\n"
            f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · Model: Agnes 2.0 Flash_\n\n"
            + content
        )
        print(f"\n Report saved to: {filename}", file=sys.stderr)
    except Exception as e:
        print(f"\n Could not save report: {e}", file=sys.stderr)


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(
        description="Agnes Research - deep topic research powered by Agnes AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agnes_research.py "AI coding assistants"
  python agnes_research.py "OpenAI vs Anthropic" --days=7 --image --video
  python agnes_research.py "crypto defi protocols" --quick --save-dir=~/Desktop
  python agnes_research.py "best mechanical keyboards" --plain
  echo "typescript vs rust" | python agnes_research.py --agent
        """,
    )
    parser.add_argument("topic",     nargs="?",             help="Topic to research")
    parser.add_argument("--days",    type=int, default=30,  help="Look-back window in days (default: 30)")
    parser.add_argument("--quick",    action="store_true",   help="Fewer results, faster run")
    parser.add_argument("--parallel", action="store_true",   help="Parallel mode - all searches run at once, ~2-3x faster")
    parser.add_argument("--image",    action="store_true",   help="Generate visual cover (Agnes Image 2.1 Flash)")
    parser.add_argument("--video",    action="store_true",   help="Generate animated brief (Agnes Video V2.0, requires --image)")
    parser.add_argument("--agent",    action="store_true",   help="Agent mode - no interactive pauses, no TUI")
    parser.add_argument("--plain",    action="store_true",   help="Force plain text output (no rich formatting)")
    parser.add_argument("--emit",     default="full",        help="Output format: full | compact")
    parser.add_argument("--save-dir", default="~/Documents/AgnesResearch",
                        help="Directory to save report (default: ~/Documents/AgnesResearch)")

    args = parser.parse_args()

    if not args.topic:
        if not sys.stdin.isatty():
            args.topic = sys.stdin.read().strip()
        else:
            parser.print_help()
            sys.exit(1)

    if not os.environ.get("AGNES_API_KEY"):
        print(" AGNES_API_KEY is not set.", file=sys.stderr)
        print("   Export it: export AGNES_API_KEY=your_key_here", file=sys.stderr)
        sys.exit(1)

    if args.parallel:
        run_parallel_research(
            topic=args.topic,
            days=args.days,
            quick=args.quick,
            save_dir=args.save_dir,
            agent_mode=args.agent,
            plain=args.plain,
        )
    else:
        run_research(
            topic=args.topic,
            days=args.days,
            quick=args.quick,
            emit=args.emit,
            generate_image=args.image,
            generate_video=args.video,
            save_dir=args.save_dir,
            agent_mode=args.agent,
            plain=args.plain,
        )


if __name__ == "__main__":
    main()
