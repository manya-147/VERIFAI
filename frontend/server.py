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
sys.path.insert(0, str(HERE))

try:  # the Streamlit app expected TINYFISH_API_KEY in the environment or a .env file
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import asyncio
import contextlib
import io
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from tinyfish import AsyncTinyFish, RunStatus, TinyFish

import resume_utils
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
    # discover -> advanced TinyFish().search.query filters (all optional)
    include_domains: str = ""
    exclude_domains: str = ""
    after_date: str = ""
    before_date: str = ""
    recency_minutes: int | None = None
    domain_type: str = ""          # "" (web) | news | research_paper
    language: str = ""
    # resume -> profile used to build searches and to rank the jobs found
    roles: list[str] = []
    skills: list[str] = []
    years: float = 0
    level: str = ""                # intern | entry | junior | mid | senior
    job_type: str = "both"         # internship | job | both


class ResumeParseRequest(BaseModel):
    text: str = ""                 # pasted resume text
    pdf_b64: str = ""              # uploaded PDF, base64 (a data: URL prefix is fine)


def _search_filters(req: "RunRequest") -> dict:
    """Optional search.query() arguments; anything left empty is simply not sent."""
    clean = lambda csv: ",".join(p.strip() for p in csv.split(",") if p.strip())  # noqa: E731
    filters = {
        "include_domains": clean(req.include_domains),
        "exclude_domains": clean(req.exclude_domains),
        "after_date": req.after_date.strip(),
        "before_date": req.before_date.strip(),
        "language": req.language.strip(),
        "domain_type": req.domain_type.strip() if req.domain_type in ("news", "research_paper") else "",
    }
    filters = {k: v for k, v in filters.items() if v}
    if req.recency_minutes:
        filters["recency_minutes"] = max(1, min(5256000, int(req.recency_minutes)))
    return filters


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
# Real TinyFish browser runs often take 1-4 minutes, so 120s skipped almost every page.
# Override without editing code:  PAGE_TIMEOUT=300 RUN_TIMEOUT=450 CONCURRENCY=5 python frontend/server.py
PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "240"))   # seconds allowed for one page's TinyFish run
RUN_TIMEOUT = int(os.getenv("RUN_TIMEOUT", "420"))     # then slow pages are skipped and the rest is returned (keep < 8 min, the browser cutoff in runner.js)
CONCURRENCY = int(os.getenv("CONCURRENCY", "5"))       # pages scraped at the same time (5 = the default search limit, so one wave)


def _find_items(result, collection: str) -> list[dict]:
    """extract_items() first; if the agent used a different key, fall back to the first list of objects it returned."""
    items = extract_items(result, collection)
    if items or not isinstance(result, dict):
        return items

    def walk(node, depth=0):
        if isinstance(node, list) and node and all(isinstance(x, dict) for x in node):
            return node
        if isinstance(node, dict) and depth < 3:
            for value in node.values():
                found = walk(value, depth + 1)
                if found:
                    return found
        return None

    return walk(result) or []


# Why pages produced nothing (shown on the Results page when a run comes back empty).
_DIAG: list[str] = []


async def _scrape_timed(pages: dict[str, str], goal: str, collection: str, schema: dict | None, progress, on_partial=None) -> list[dict]:
    """Same job as backend.models.scrape(), but with time limits and live per-page progress."""
    _DIAG.clear()
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
                _DIAG.append(f"{source}: no answer within {PAGE_TIMEOUT}s")
                progress(f"[{finished}/{total}] Skipped {source} — no answer within {PAGE_TIMEOUT}s")
                return
            except Exception as error:  # noqa: BLE001
                finished += 1
                _DIAG.append(f"{source}: {error.__class__.__name__}: {error}")
                progress(f"[{finished}/{total}] Skipped {source} — {error.__class__.__name__}: {error}")
                return
            finished += 1
            if run.status != RunStatus.COMPLETED:
                reason = getattr(getattr(run, "error", None), "message", "") or ""
                _DIAG.append(f"{source}: run ended as {run.status}{' — ' + reason if reason else ''}")
                progress(f"[{finished}/{total}] Skipped {source} — run ended as {run.status} {reason}".strip())
                return
            items = _find_items(run.result, collection)
            if not items:
                keys = list(run.result) if isinstance(run.result, dict) else type(run.result).__name__
                _DIAG.append(f"{source}: page scraped but nothing matched (result: {keys})")
            batch = [{"source": source, **item} for item in items]
            listings.extend(batch)
            progress(f"[{finished}/{total}] {source} — {len(items)} found")
            if batch and on_partial:
                on_partial(batch)   # lets the UI keep these even if a later page is too slow

    tasks = [asyncio.create_task(one(name, url)) for name, url in pages.items()]
    _, pending = await asyncio.wait(tasks, timeout=RUN_TIMEOUT)
    if pending:
        progress(f"Stopped waiting for {len(pending)} slow page(s) after {RUN_TIMEOUT}s — showing what was found.")
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return listings


def _collect_parallel(links: list[str], goal: str, limit: int, progress, on_partial) -> list[dict]:
    """backend.collect_from_pages() is sequential, so run it once per link, in parallel.

    The backend function itself is untouched; this only changes how server.py calls it.
    """
    results: list[dict] = []
    lock = threading.Lock()

    def one(url: str) -> None:
        try:
            rows = collect_from_pages({url: url}, goal, limit, on_progress=progress)
        except Exception as error:  # noqa: BLE001
            progress(f"Could not collect results from {url}: {error}")
            return
        with lock:
            results.extend(rows)
        if rows:
            on_partial(rows)

    pool = ThreadPoolExecutor(max_workers=max(1, min(len(links), CONCURRENCY)))
    futures = [pool.submit(one, url) for url in links]
    _, pending = futures_wait(futures, timeout=RUN_TIMEOUT)
    if pending:
        progress(f"Stopped waiting for {len(pending)} slow page(s) after {RUN_TIMEOUT}s — showing what was found.")
    pool.shutdown(wait=False, cancel_futures=True)
    with lock:
        return results[:limit]


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


@app.post("/api/resume/parse")
def parse_resume(req: ResumeParseRequest):
    """Pasted text or an uploaded PDF -> editable profile (skills, experience, level, target roles, ...)."""
    text = req.text
    try:
        if req.pdf_b64:
            import base64
            raw = req.pdf_b64.split(",", 1)[-1]
            data = base64.b64decode(raw, validate=False)
            if len(data) > 10 * 1024 * 1024:
                return _error("That PDF is larger than 10 MB.")
            text = resume_utils.extract_pdf_text(data)
        if len(text.strip()) < 40:
            return _error("The resume is too short to analyse. Paste the full text or upload a PDF.")
        profile = resume_utils.analyze_resume(text[:60000])
    except RuntimeError as error:
        return _error(str(error))
    if not profile["skills"]:
        profile["warning"] = "No known technologies were found — add your skills below before searching."
    return {"profile": profile, "text": text[:60000]}


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
        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        if any(d and not date_re.match(d) for d in (req.after_date, req.before_date)):
            return _error("Dates must be in YYYY-MM-DD format.")
        if req.after_date and req.before_date and req.after_date > req.before_date:
            return _error("“Published after” must be earlier than “Published before”.")
    elif mode == "resume":
        if not (req.skills or req.roles):
            return _error("Add your resume first — there are no skills or target roles to search with.")
    elif mode != "sources":
        return _error(f"Unknown mode: {mode}")
    if not os.getenv("TINYFISH_API_KEY"):
        return _error("Set TINYFISH_API_KEY in your environment or .env file before searching.")

    events: queue.Queue = queue.Queue()
    progress = lambda message: events.put({"type": "progress", "message": str(message)})  # noqa: E731
    partial = lambda batch: events.put({"type": "partial", "listings": batch})  # noqa: E731

    def scrape_pages(pages: dict[str, str]) -> list[dict]:
        events.put({"type": "pages", "pages": list(pages.values())})
        return _remote_first(asyncio.run(_scrape_timed(
            pages, goal, collection, INTERNSHIP_SCHEMA if collection == "internships" else None, progress, partial,
        )))

    def worker():
        if _run_lock.locked():
            progress("Another run is still in progress — waiting for it to finish…")
        try:
            with _run_lock, contextlib.redirect_stdout(_LineWriter(progress)):
                if mode == "links":        # backend.collect_from_pages
                    events.put({"type": "pages", "pages": links})
                    listings = _collect_parallel(links, goal, limit, progress, partial)
                    events.put({"type": "result", "listings": listings})
                elif mode == "single":     # backend mode 1: scrape_one
                    events.put({"type": "pages", "pages": [url]})
                    raw = scrape_one(url, goal)
                    events.put({"type": "result", "raw": raw, "completed": raw is not None})
                elif mode == "sources":    # backend mode 2: scrape configured PAGES
                    progress(f"Scraping {len(PAGES)} saved sources…")
                    rows = scrape_pages(PAGES)
                    events.put({"type": "result", "listings": rows,
                                "note": "" if rows or not _DIAG else "No listings found. " + " | ".join(_DIAG[:6])})
                elif mode == "resume":     # resume -> search queries -> TinyFish search -> scrape -> rank by fit
                    roles = [r.strip() for r in req.roles if r.strip()]
                    skills = [x.strip() for x in req.skills if x.strip()]
                    queries = resume_utils.build_queries(roles, skills, req.level, req.job_type, req.region)
                    filters = _search_filters(req)
                    per_query: list[list[str]] = []
                    for q in queries:
                        progress(f"Searching the web for: {q}")
                        try:
                            found = TinyFish().search.query(query=q, **filters)
                            per_query.append([r.url for r in found.results])
                        except Exception as error:  # noqa: BLE001
                            progress(f"Search failed for “{q}”: {error.__class__.__name__}: {error}")
                    urls: list[str] = []
                    for rank in range(max((len(u) for u in per_query), default=0)):   # round-robin so every role gets pages
                        for urls_for_q in per_query:
                            if rank < len(urls_for_q) and urls_for_q[rank] not in urls:
                                urls.append(urls_for_q[rank])
                    pages = {u: u for u in urls[:limit]}
                    if not pages:
                        events.put({"type": "result", "listings": [], "note": "The web search returned no pages" + (" — try loosening the filters." if filters else ".")})
                    else:
                        progress(f"Found {len(pages)} pages. Scraping up to {CONCURRENCY} at a time (max {PAGE_TIMEOUT}s each)…")
                        events.put({"type": "pages", "pages": list(pages.values())})
                        goal_text = resume_utils.resume_goal(roles, skills, req.level, req.years, req.job_type, req.region)
                        schema = build_schema({**{k: {"type": "string"} for k in ("title", "organization", "location", "deadline", "apply_link", "category", "required_skills", "experience_required")},
                                               "remote": {"type": "boolean", "nullable": True}}, "internships", max_items=8)
                        rows = asyncio.run(_scrape_timed(pages, goal_text, "internships", schema, progress, partial))
                        rows = _dedupe([r for r in rows if r.get("title")], ("apply_link",))
                        rows = [resume_utils.score_listing(r, skills, roles, req.level) for r in rows]
                        rows.sort(key=lambda r: (-r["match_score"], r.get("remote") is not True))
                        note = "ranked by how well each fits your resume"
                        if not rows and _DIAG:
                            note = "No listings found. " + " | ".join(_DIAG[:6])
                        events.put({"type": "result", "listings": rows, "note": note})
                else:                      # backend mode 3, generalised: search anything, then scrape the top pages
                    plan = _discover_plan(req)
                    progress(f"Searching the web for: {req.query.strip()} ({plan['category']})")
                    filters = _search_filters(req)
                    if filters:
                        progress("Search filters: " + ", ".join(f"{k}={v}" for k, v in filters.items()))
                    found = TinyFish().search.query(query=plan["search"], **filters)
                    pages = {r.url: r.url for r in found.results[: max(limit, 0)]}
                    if not pages:
                        progress("No pages found for that search.")
                        events.put({"type": "result", "listings": [], "note": "The web search returned no pages" + (" — try loosening the filters." if filters else ".")})
                    else:
                        progress(f"Found {len(pages)} pages. Scraping up to {CONCURRENCY} at a time (max {PAGE_TIMEOUT}s each)…")
                        events.put({"type": "pages", "pages": list(pages.values())})
                        rows = asyncio.run(_scrape_timed(
                            pages, plan["goal"], plan["collection"], plan["schema"], progress, partial,
                        ))
                        rows = plan["finish"](rows)
                        note = plan["note"]
                        if not rows and _DIAG:
                            note = "No listings found. " + " | ".join(_DIAG[:6])
                        events.put({"type": "result", "listings": rows, "note": note})
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
    "results.html", "activity.html", "resume.html", "resume.js", "style.css",
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