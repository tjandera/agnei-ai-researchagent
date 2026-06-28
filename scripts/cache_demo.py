#!/usr/bin/env python3
"""
Build and cache the demo finance digests.

Run offline with no key: it produces real-data digests from yfinance and the
keyless connectors via build_digest's deterministic offline synthesis, draws a
local branded poster for the hero image, and writes JSON plus PNG into
web/static/demo/. These cached seeds are the demo that ships and they load with
no live API call. Live Agnes media is produced later, in app, when build_and_cache
is called with a client and with_media=True.

    .venv/bin/python scripts/cache_demo.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from finance_digest import build_digest
from lib.media_gen import offline_hero_poster

DEMO_DIR = Path(__file__).parent.parent / "web" / "static" / "demo"

DEMO_SEEDS = [
    ("BTC-USD", 30, "btc-usd-30"),
    ("AAPL", 90, "aapl-90"),
    ("ETH-USD", 30, "eth-usd-30"),
]


def build_and_cache(symbol, days, key=None, client=None, with_media=False):
    """Build one digest and cache it under web/static/demo/{key}.json.

    Offline (client None) uses a locally drawn poster for the hero image. When a
    client is supplied with with_media, live Agnes URLs are kept as is.
    """
    key = key or f"{symbol.lower()}-{days}"
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    digest = build_digest(
        symbol,
        days=days,
        client=client,
    )

    media = digest.setdefault("media", {"image_url": None, "video_url": None})
    snap = digest.get("snapshot", {}) or {}

    live_image = bool(with_media and client and media.get("image_url"))
    if not live_image:
        up = (snap.get("change_pct") or 0) >= 0
        poster = offline_hero_poster(snap.get("symbol", symbol), snap.get("name", ""), up)
        (DEMO_DIR / f"{key}.png").write_bytes(poster)
        media["image_url"] = f"/static/demo/{key}.png"

    (DEMO_DIR / f"{key}.json").write_text(
        json.dumps(digest, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "key": key,
        "symbol": symbol,
        "days": days,
        "live": bool(digest.get("meta", {}).get("live")),
        "image": media.get("image_url"),
        "video": media.get("video_url"),
    }


def main():
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    ok = 0
    for symbol, days, key in DEMO_SEEDS:
        try:
            build_and_cache(symbol, days, key=key, client=None, with_media=False)
            digest = json.loads((DEMO_DIR / f"{key}.json").read_text(encoding="utf-8"))
            snap = digest.get("snapshot", {}) or {}
            index.append({
                "key": key,
                "symbol": symbol,
                "days": days,
                "name": snap.get("name", symbol),
                "headline": digest.get("headline", ""),
            })
            ok += 1
        except Exception as exc:
            sys.stderr.write(f"demo build failed for {key}: {exc}\n")

    (DEMO_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8"
    )
    sys.stderr.write(f"cache_demo: built {ok}/{len(DEMO_SEEDS)} seeds, index entries {len(index)}\n")


if __name__ == "__main__":
    main()
