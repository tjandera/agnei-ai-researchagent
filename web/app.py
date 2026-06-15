#!/usr/bin/env python3
"""Agnes Research — web UI backend. Run with: agnes-web"""

import asyncio
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

# .env loader
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agnes_research import run_research, run_parallel_research

app = FastAPI(title="Agnes Research")
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


class _QueueUI:
    """Bridges the research functions to an SSE event queue."""

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
                if isinstance(data, list):
                    count, error = len(data), False
                elif isinstance(data, dict) and "error" in data:
                    count, error = 0, True
                else:
                    count, error = 1, False
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
            if parallel:
                run_parallel_research(topic=topic, days=days, quick=quick,
                                      save_dir="~/Documents/AgnesResearch", ui=ui)
            else:
                run_research(topic=topic, days=days, quick=quick,
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
    print("\n  Agnes Research UI → http://localhost:8765\n")
    webbrowser.open("http://localhost:8765")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
