#!/usr/bin/env python3
"""Agnes Finance Research - web backend."""

import asyncio
import json
import os
import queue
import re
import sys
import threading
from pathlib import Path

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from finance_digest import build_digest
from lib.yahoo_finance import get_ticker_data, search_tickers

STATIC_DIR = Path(__file__).parent / "static"
DEMO_DIR = STATIC_DIR / "demo"

app = FastAPI(title="Agnes Finance Research")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _make_client():
    """Construct an AgnesClient if a key is present in this process, else None."""
    if not os.environ.get("AGNES_API_KEY"):
        return None
    try:
        from lib.agnes_client import AgnesClient
        return AgnesClient()
    except Exception:
        return None


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    has_agnes = bool(os.environ.get("AGNES_API_KEY"))
    web_key = next((k for k in ["BRAVE_API_KEY", "SERPER_API_KEY", "TAVILY_API_KEY"] if os.environ.get(k)), None)
    return {"agnes": has_agnes, "web_search": web_key or False}


@app.get("/api/ticker/{symbol}")
def ticker(symbol: str, days: int = 90):
    """Return price, fundamentals, and historical OHLCV for a ticker."""
    try:
        return get_ticker_data(symbol, days=days)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ticker/{symbol}/chart")
def ticker_chart(symbol: str, days: int = 90):
    """Return a PNG price chart for embedding."""
    try:
        from lib.chart_gen import generate_price_chart
        data = get_ticker_data(symbol, days=days)
        png = generate_price_chart(data["history"], symbol, data.get("name", ""))
        return Response(content=png, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/search")
def ticker_search(q: str):
    """Search for ticker symbols."""
    return search_tickers(q)


# -- Digest stream (SSE) --------------------------------------------------------

@app.get("/api/generate")
async def generate_stream(
    symbol: str,
    days: int = 30,
    topic: str = None,
    quick: bool = False,
    media: bool = True,
):
    """Stream a grounded finance digest build as Server-Sent Events."""
    event_queue: queue.Queue = queue.Queue()
    client = _make_client()

    def _cb(ev: dict):
        event_queue.put(ev)

    def _run():
        try:
            build_digest(symbol, days=days, topic=topic, quick=quick,
                         want_media=media, client=client, progress=_cb)
        except Exception as exc:
            event_queue.put({"type": "error", "message": str(exc), "fatal": True})
        finally:
            event_queue.put(None)

    threading.Thread(target=_run, daemon=True).start()

    async def _stream():
        yield "data: " + json.dumps({"type": "start", "symbol": symbol, "days": days, "topic": topic}) + "\n\n"
        while True:
            try:
                event = event_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if event is None:
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                break
            yield "data: " + json.dumps(event) + "\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- Demo (cached assets, no live call) -----------------------------------------

def _safe_key(key: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", (key or "").lower())


@app.get("/api/demo")
def demo_index():
    """List cached demo digests, or an empty list if none exist."""
    path = DEMO_DIR / "index.json"
    if not path.exists():
        return []
    try:
        return JSONResponse(content=json.loads(path.read_text()))
    except Exception:
        return []


@app.get("/api/demo/{key}")
def demo_get(key: str):
    """Return a single cached demo digest by key."""
    safe = _safe_key(key)
    path = DEMO_DIR / f"{safe}.json"
    if not safe or not path.exists():
        raise HTTPException(status_code=404, detail="demo not found")
    try:
        return JSONResponse(content=json.loads(path.read_text()))
    except Exception:
        raise HTTPException(status_code=404, detail="demo not found")


@app.post("/api/demo/build")
def demo_build(symbol: str, days: int = 30, key: str = None):
    """Run an in-app live build and cache it as a demo asset. Best effort."""
    safe = _safe_key(key) if key else _safe_key(symbol)
    client = _make_client()
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import cache_demo
        if hasattr(cache_demo, "build_and_cache"):
            result = cache_demo.build_and_cache(symbol, days, key=safe, client=client, with_media=True)
            return {"status": "ok", "key": safe, "cached": True, "detail": result if isinstance(result, (str, dict)) else None}
    except Exception:
        pass

    try:
        digest = build_digest(symbol, days=days, want_media=True, client=client)
        (DEMO_DIR / f"{safe}.json").write_text(json.dumps(digest, ensure_ascii=False))
        return {"status": "ok", "key": safe, "cached": True,
                "live": bool(digest.get("meta", {}).get("live"))}
    except Exception as e:
        return {"status": "error", "key": safe, "cached": False, "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    try:
        sys.stderr.write("Agnes Finance Research on http://localhost:8765\n")
    except Exception:
        pass
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
