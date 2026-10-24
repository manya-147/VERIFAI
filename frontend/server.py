"""HTTP adapter between the HTML frontend and backend/ (the backend itself is not modified).

Run from the project root:   python frontend/server.py
Then open:                   http://localhost:8000
"""

import json
import os
import queue
import re
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

import asyncio
import contextlib
import io

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from tinyfish import AsyncTinyFish, RunStatus, TinyFish

from backend.backend import collect_from_pages
from backend.models import (
    DEFAULT_GOAL,
    build_schema,
    extract_items,
    INTERNSHIP_GOAL,
    INTERNSHIP_SCHEMA,
    PAGES,
    scrape,
    scrape_one,
)

# Defaults of backend.parse_args() (the CLI options of backend/backend.py).
DEFAULT_QUERY = "software engineering internship apply 2026"
DEFAULT_COLLECTION = "internships"
DEFAULT_SEARCH_LIMIT = 5

app = FastAPI(title="Opportunity Finder")
_run_lock = threading.Lock()  # scrape()/scrape_one() print to stdout, so runs are serialised


class RunRequest(BaseModel):
    mode: str                      # links | single | sources | discover
    links: list[str] = []          # links      -> collect_from_pages
    url: str = ""                  # single     -> scrape_one
    query: str = ""                # discover   -> TinyFish().search.query
    goal: str = ""
    collection: str = DEFAULT_COLLECTION
    limit: int = 10
    category: str = "auto"         # discover   -> auto | shopping | jobs | events | general
    region: str = ""               # discover   -> optional country / city / market


def _is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _error(message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=400)


class _LineWriter(io.TextIOBase):
    """Turns the backend's print() output into progress messages."""

    def __init__(self, callback):
        self.callback, self.buffer = callback, ""

    def write(self, text):
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.callback(line.strip())
        return len(text)

    def flush(self):
        if self.buffer.strip():
            self.callback(self.buffer.strip())
        self.buffer = ""


def _remote_first(listings: list[dict]) -> list[dict]:
    """Same ordering backend.models.save() applies before writing results."""
    listings.sort(key=lambda item: item.get("remote") is not True)
    return listings



# Per-page limits (the SDK default is 10 min x 3 attempts per page, which can look like an endless "Working…").
PAGE_TIMEOUT = 120      # seconds allowed for one page's TinyFish run
RUN_TIMEOUT = 300       # seconds after which slow pages are skipped and the rest is returned
CONCURRENCY = 4         # pages scraped at the same time


async def _scrape_timed(pages: dict[str, str], goal: str, collection: str, schema: dict | None, progress) -> list[dict]:
    """Same job as backend.models.scrape(), but with time limits and live per-page progress."""
    client = AsyncTinyFish(timeout=PAGE_TIMEOUT, max_retries=0)
    output_schema = schema or build_schema(collection_key=collection)
    gate = asyncio.Semaphore(CONCURRENCY)
    listings: list[dict] = []
    total, finished = len(pages), 0

    async def one(source: str, url: str) -> None:
        nonlocal finished
        async with gate:
            try:
                run = await asyncio.wait_for(
                    client.agent.run(url=url, goal=goal, output_schema=output_schema), PAGE_TIMEOUT)
            except asyncio.TimeoutError:
                finished += 1
                progress(f"[{finished}/{total}] Skipped {source} — no answer within {PAGE_TIMEOUT}s")
                return
            except Exception as error:  # noqa: BLE001
                finished += 1
                progress(f"[{finished}/{total}] Skipped {source} — {error}")
                return
            finished += 1
            if run.status != RunStatus.COMPLETED:
                progress(f"[{finished}/{total}] Skipped {source} — run ended as {run.status}")
                return
            items = extract_items(run.result, collection)
            listings.extend({"source": source, **item} for item in items)
            progress(f"[{finished}/{total}] {source} — {len(items)} found")

    tasks = [asyncio.create_task(one(name, url)) for name, url in pages.items()]
    _, pending = await asyncio.wait(tasks, timeout=RUN_TIMEOUT)
    if pending:
        progress(f"Stopped waiting for {len(pending)} slow page(s) after {RUN_TIMEOUT}s — showing what was found.")
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return listings


# ───────── Find & scrape: general-purpose search (products, jobs, events, anything) ─────────
_SHOPPING_WORDS = {
    "price", "prices", "cheap", "cheapest", "cheaper", "buy", "deal", "deals", "discount", "offer", "offers",
    "sale", "under", "below", "best", "shop", "shopping", "order", "iphone", "samsung", "pixel", "phone",
    "laptop", "tv", "headphones", "earbuds", "shoes", "sneakers", "bag", "bags", "backpack", "watch",
    "shirt", "jeans", "dress", "camera", "tablet", "ipad", "macbook", "playstation", "xbox", "furniture",
}
_JOB_WORDS = {"internship", "internships", "intern", "job", "jobs", "hiring", "career", "careers",
              "vacancy", "vacancies", "recruitment", "fellowship", "apply", "openings"}
_EVENT_WORDS = {"event", "events", "hackathon", "hackathons", "conference", "workshop", "meetup",
                "webinar", "concert", "festival", "tickets", "competition"}

_CATEGORY_FIELDS = {
    "shopping": ("products", {
        "product_name": {"type": "string"},
        "price": {"type": "string"},
        "currency": {"type": "string"},
        "store": {"type": "string"},
        "rating": {"type": "string"},
        "availability": {"type": "string"},
        "product_link": {"type": "string"},
    }),
    "events": ("events", {
        "title": {"type": "string"},
        "date": {"type": "string"},
        "location": {"type": "string"},
        "price": {"type": "string"},
        "organizer": {"type": "string"},
        "link": {"type": "string"},
    }),
    "general": ("results", {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "price": {"type": "string"},
        "location": {"type": "string"},
        "date": {"type": "string"},
        "link": {"type": "string"},
    }),
}


def _detect_category(query: str) -> str:
    words = set(re.findall(r"[a-z0-9]+", query.lower()))
    if words & _JOB_WORDS:
        return "jobs"
    if words & _EVENT_WORDS:
        return "events"
    if words & _SHOPPING_WORDS or re.search(r"[\u20b9$\u20ac\u00a3]|\b(rs|inr|usd)\b", query.lower()):
        return "shopping"
    return "general"


def _price_value(text) -> float | None:
    """First number in a price string, handling 1,29,900 / 1.299,00 / $1,299.00 style text."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(text or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _dedupe(listings: list[dict], link_keys: tuple[str, ...]) -> list[dict]:
    seen, unique = set(), []
    for item in listings:
        link = next((str(item[k]) for k in link_keys if item.get(k)), "")
        key = link or json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _discover_plan(req: "RunRequest") -> dict:
    """Turn a free-text request into: web-search query, TinyFish goal, output schema, and a finisher."""
    query = req.query.strip()
    region = req.region.strip()
    category = req.category if req.category in {"shopping", "jobs", "events", "general"} else _detect_category(query)
    where = f" in {region}" if region else ""
    extra = req.goal.strip()
    extra_text = f" Additional instructions: {extra}" if extra else ""

    if category == "jobs":
        return {
            "category": category,
            "search": f"{query}{where}",
            "goal": (extra or INTERNSHIP_GOAL) + (f" Focus on {region}." if region else ""),
            "collection": "internships",
            "schema": INTERNSHIP_SCHEMA,
            "finish": lambda rows: _remote_first(_dedupe(rows, ("apply_link",))),
            "note": "",
        }

    collection, fields = _CATEGORY_FIELDS[category]
    if category == "shopping":
        goal = (
            f"Find products for the search: '{query}'{where}. Use only this page (do not browse to other sites) and finish quickly. "
            "Return up to 5 real products that match it, preferring the cheapest. For each give product_name, price (exactly as shown, with its currency "
            "symbol), currency, store (seller or website name), rating, availability (for example in stock), and "
            "product_link (the full URL of that product). Use an empty string for anything unavailable. "
            "Ignore ads, accessories and unrelated items." + extra_text
        )
        search = f"{query} price buy online{where}"

        def finish(rows: list[dict]) -> list[dict]:
            rows = _dedupe(rows, ("product_link",))
            rows = [r for r in rows if r.get("product_name")]
            rows.sort(key=lambda r: (_price_value(r.get("price")) is None, _price_value(r.get("price")) or 0))
            return rows

        note = "sorted by lowest price (prices in different currencies are not converted)"
    elif category == "events":
        goal = (
            f"Find events matching: '{query}'{where}. For each give title, date, location, price (or 'free'), "
            "organizer, and link (full URL). Use an empty string for anything unavailable." + extra_text
        )
        search, finish, note = f"{query}{where}", (lambda rows: _dedupe(rows, ("link",))), ""
    else:
        goal = (
            f"Find information matching: '{query}'{where}. Return up to 10 relevant items from this page. For each give "
            "title, a one-sentence summary, price (if any), location (if any), date (if any), and link (full URL). "
            "Use an empty string for anything unavailable." + extra_text
        )
        search, finish, note = f"{query}{where}", (lambda rows: _dedupe(rows, ("link",))), ""

    return {
        "category": category,
        "search": search,
        "goal": goal,
        "collection": collection,
        "schema": build_schema(fields, collection),
        "finish": finish,
        "note": note,
    }


@app.get("/api/config")
def config():
    return {
        "default_goal": DEFAULT_GOAL,
        "internship_goal": INTERNSHIP_GOAL,
        "pages": PAGES,
        "default_query": DEFAULT_QUERY,
        "default_collection": DEFAULT_COLLECTION,
        "default_search_limit": DEFAULT_SEARCH_LIMIT,
    }


@app.post("/api/run")
def run(req: RunRequest):
    mode = req.mode
    goal = req.goal if mode == "links" else (req.goal.strip() or INTERNSHIP_GOAL)
    collection = req.collection.strip() or DEFAULT_COLLECTION
    limit = max(1, min(100, int(req.limit)))

    # Validation: same checks/messages as the Streamlit form handler, then the API-key check.
    if mode == "links":
        links = list(dict.fromkeys(line.strip() for line in req.links if line.strip()))
        if not links:
            return _error("Enter at least one URL to search.")
        if any(not _is_valid_url(url) for url in links):
            return _error("Every link must be a complete URL beginning with http:// or https://.")
    elif mode == "single":
        url = req.url.strip()
        if not url:
            return _error("Enter a URL to scrape.")
        if not _is_valid_url(url):
            return _error("The link must be a complete URL beginning with http:// or https://.")
    elif mode == "discover":
        if not req.query.strip():
            return _error("Enter a search query.")
    elif mode != "sources":
        return _error(f"Unknown mode: {mode}")
    if not os.getenv("TINYFISH_API_KEY"):
        return _error("Set TINYFISH_API_KEY in your environment or .env file before searching.")

    events: queue.Queue = queue.Queue()
    progress = lambda message: events.put({"type": "progress", "message": str(message)})  # noqa: E731

    def scrape_pages(pages: dict[str, str]) -> list[dict]:
        events.put({"type": "pages", "pages": list(pages.values())})
        return _remote_first(asyncio.run(_scrape_timed(
            pages, goal, collection, INTERNSHIP_SCHEMA if collection == "internships" else None, progress,
        )))

    def worker():
        if _run_lock.locked():
            progress("Another run is still in progress — waiting for it to finish…")
        try:
            with _run_lock, contextlib.redirect_stdout(_LineWriter(progress)):
                if mode == "links":        # backend.collect_from_pages
                    events.put({"type": "pages", "pages": links})
                    listings = collect_from_pages({u: u for u in links}, goal, limit, on_progress=progress)
                    events.put({"type": "result", "listings": listings})
                elif mode == "single":     # backend mode 1: scrape_one
                    events.put({"type": "pages", "pages": [url]})
                    raw = scrape_one(url, goal)
                    events.put({"type": "result", "raw": raw, "completed": raw is not None})
                elif mode == "sources":    # backend mode 2: scrape configured PAGES
                    progress(f"Scraping {len(PAGES)} saved sources…")
                    events.put({"type": "result", "listings": scrape_pages(PAGES)})
                else:                      # backend mode 3, generalised: search anything, then scrape the top pages
                    plan = _discover_plan(req)
                    progress(f"Searching the web for: {req.query.strip()} ({plan['category']})")
                    found = TinyFish().search.query(query=plan["search"])
                    pages = {r.url: r.url for r in found.results[: max(limit, 0)]}
                    if not pages:
                        progress("No pages found for that search.")
                        events.put({"type": "result", "listings": [], "note": ""})
                    else:
                        progress(f"Found {len(pages)} pages. Scraping up to {CONCURRENCY} at a time (max {PAGE_TIMEOUT}s each)…")
                        events.put({"type": "pages", "pages": list(pages.values())})
                        rows = asyncio.run(_scrape_timed(
                            pages, plan["goal"], plan["collection"], plan["schema"], progress,
                        ))
                        rows = plan["finish"](rows)
                        events.put({"type": "result", "listings": rows, "note": plan["note"]})
        except BaseException as error:  # incl. SystemExit; shown as "Could not complete the search: ..."
            events.put({"type": "error", "message": str(error) or error.__class__.__name__})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# Only the frontend files below are served (never server.py or the backend).
STATIC = {
    "index.html", "search.html", "single.html", "sources.html", "discover.html",
    "results.html", "activity.html", "style.css",
    "shared.js", "dashboard.js", "runner.js", "results.js", "activity.js",
}


_NO_CACHE = {"Cache-Control": "no-store, max-age=0"}


@app.get("/")
def index():
    return FileResponse(HERE / "index.html", headers=_NO_CACHE)


@app.get("/{name}")
def static_file(name: str):
    if name not in STATIC:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return FileResponse(HERE / name, headers=_NO_CACHE)


def _check_files() -> None:
    missing = sorted(name for name in STATIC if not (HERE / name).exists())
    leftovers = sorted(p.name for p in HERE.glob("*") if p.name in {"script.js", "config.js"})
    if missing:
        print(f"\n!! Missing frontend files in {HERE}:\n   " + ", ".join(missing))
        print("   Copy ALL files from the latest delivery into this folder (names must be exactly as listed).\n")
    if leftovers:
        print(f"!! Old files from earlier versions can be deleted: {', '.join(leftovers)}\n")
    if not missing:
        print(f"Frontend OK: {len(STATIC)} files found in {HERE}")


if __name__ == "__main__":
    import uvicorn
    _check_files()
    uvicorn.run(app, host="127.0.0.1", port=8000)
