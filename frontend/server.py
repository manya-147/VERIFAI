"""HTTP server for the HTML frontend. Same logic as the old Streamlit app.

Run from the project root:   python frontend/server.py
Then open:                   http://localhost:8000
"""

import json
import os
import queue
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

try:  # the Streamlit app expected TINYFISH_API_KEY in the environment or a .env file
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.backend import collect_from_pages
from backend.models import DEFAULT_GOAL

app = FastAPI(title="Opportunity Finder")


class SearchRequest(BaseModel):
    links: list[str]
    goal: str = DEFAULT_GOAL
    limit: int = 10


def _is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _error(message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=400)


@app.get("/api/config")
def config():
    return {"default_goal": DEFAULT_GOAL}


@app.post("/api/search")
def search(req: SearchRequest):
    # Same checks, same order, same messages as the Streamlit form handler.
    links = list(dict.fromkeys(line.strip() for line in req.links if line.strip()))
    if not links:
        return _error("Enter at least one URL to search.")
    if any(not _is_valid_url(url) for url in links):
        return _error("Every link must be a complete URL beginning with http:// or https://.")
    if not os.getenv("TINYFISH_API_KEY"):
        return _error("Set TINYFISH_API_KEY in your environment or .env file before searching.")

    limit = max(1, min(100, int(req.limit)))
    pages = {url: url for url in links}
    events: queue.Queue = queue.Queue()

    def worker():
        try:
            listings = collect_from_pages(
                pages,
                req.goal,
                limit,
                on_progress=lambda message: events.put({"type": "progress", "message": str(message)}),
            )
            events.put({"type": "result", "listings": listings})
        except Exception as error:  # surfaced as "Could not complete the search: ..."
            events.put({"type": "error", "message": str(error)})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# Only the three frontend files are served (not server.py).
@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


@app.get("/style.css")
def style():
    return FileResponse(HERE / "style.css")


@app.get("/script.js")
def script():
    return FileResponse(HERE / "script.js")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
