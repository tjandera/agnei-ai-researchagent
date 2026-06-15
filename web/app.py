#!/usr/bin/env python3
"""Agnes Finance Research — web backend."""

import asyncio
import base64
import json
import os
import queue
import sys
import threading
import time
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
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agnes_research import run_research, run_parallel_research
from lib.yahoo_finance import get_ticker_data, search_tickers, fmt_large

app = FastAPI(title="Agnes Finance Research")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/health")
def health():
    has_agnes = bool(os.environ.get("AGNES_API_KEY"))
    web_key   = next((k for k in ["BRAVE_API_KEY", "SERPER_API_KEY", "TAVILY_API_KEY"] if os.environ.get(k)), None)
    return {"agnes": has_agnes, "web_search": web_key or False}


@app.get("/api/ticker/{symbol}")
def ticker(symbol: str, days: int = 90):
    """Return price, fundamentals, and historical OHLCV for a ticker."""
    try:
        data = get_ticker_data(symbol, days=days)
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ticker/{symbol}/chart")
def ticker_chart(symbol: str, days: int = 90):
    """Return a PNG price chart for embedding."""
    try:
        from lib.yahoo_finance import get_ticker_data
        from lib.chart_gen import generate_price_chart
        data = get_ticker_data(symbol, days=days)
        png  = generate_price_chart(data["history"], symbol, data.get("name", ""))
        return Response(content=png, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/search")
def ticker_search(q: str):
    """Search for ticker symbols."""
    return search_tickers(q)


@app.get("/api/export/pdf")
def export_pdf(symbol: str, report: str = "", days: int = 90):
    """Generate and return a PDF finance report."""
    try:
        from lib.yahoo_finance import get_ticker_data
        from lib.chart_gen import generate_price_chart
        from lib.pdf_report import generate_pdf

        data      = get_ticker_data(symbol, days=days)
        chart_png = None
        try:
            chart_png = generate_price_chart(data["history"], symbol, data.get("name", ""))
        except Exception:
            pass

        pdf_bytes = generate_pdf(symbol, data, report, chart_png)
        filename  = f"agnes-{symbol.lower()}-{time.strftime('%Y%m%d')}.pdf"
        return Response(
            content=bytes(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── SSE research stream ───────────────────────────────────────────────────────

class _QueueUI:
    def __init__(self, topic: str, days: int, q: queue.Queue):
        self._q     = q
        self._start = time.time()
        self.topic  = topic
        self.days   = days

    def start(self):
        self._q.put({"type": "start", "topic": self.topic, "days": self.days})

    def stop_live(self):
        pass

    def wrap_executor(self, executor):
        q = self._q
        def _tracked(name: str, args: dict) -> str:
            query = args.get("query", "")
            q.put({"type": "search_start", "tool": name, "query": query})
            result = executor(name, args)
            try:
                data = json.loads(result)
                count = len(data) if isinstance(data, list) else (0 if isinstance(data, dict) and "error" in data else 1)
                error = isinstance(data, dict) and "error" in data
            except Exception:
                count, error = 0, True
            q.put({"type": "search_done", "tool": name, "query": query, "count": count, "error": error})
            return result
        return _tracked

    def print_report(self, report: str):
        self._q.put({"type": "report", "content": report, "elapsed": round(time.time() - self._start, 1)})

    def print_status(self, msg: str):
        self._q.put({"type": "status", "message": msg})

    def print_error(self, msg: str):
        self._q.put({"type": "error", "message": msg})

    def print_image_url(self, url: str):
        self._q.put({"type": "image", "url": url})

    def print_video_url(self, url: str):
        self._q.put({"type": "video", "url": url})


@app.get("/api/research")
async def research_stream(
    topic: str,
    days: int = 30,
    quick: bool = False,
    parallel: bool = True,
):
    event_queue: queue.Queue = queue.Queue()

    def _run():
        try:
            ui = _QueueUI(topic, days, event_queue)
            fn = run_parallel_research if parallel else run_research
            fn(topic=topic, days=days, quick=quick,
               save_dir="~/Documents/AgnesResearch", ui=ui)
        except Exception as exc:
            event_queue.put({"type": "error", "message": str(exc)})
        finally:
            event_queue.put(None)

    threading.Thread(target=_run, daemon=True).start()

    async def _stream():
        while True:
            try:
                event = event_queue.get_nowait()
                if event is None:
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    break
                yield "data: " + json.dumps(event) + "\n\n"
            except queue.Empty:
                await asyncio.sleep(0.05)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    print("\n  Agnes Finance Research → http://localhost:8765\n")
    webbrowser.open("http://localhost:8765")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
