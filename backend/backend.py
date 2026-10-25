"""Command-line backend for scraping and saving structured listings.

Examples:
    python backend/backend.py 1                 # scrape one configured source
    python backend/backend.py 2                 # scrape all configured sources
    python backend/backend.py 3                 # search for sources, then scrape
"""

import argparse
import asyncio
from collections.abc import Callable

from tinyfish import RunStatus, TinyFish
from dotenv import load_dotenv
load_dotenv()
try:  # Support both `python backend/backend.py` and `python -m backend.backend`.
    from .models import (
        INTERNSHIP_GOAL,
        INTERNSHIP_SCHEMA,
        PAGES,
        build_schema,
        extract_items,
        require_api_key,
        save,
        scrape,
        scrape_one,
    )
except ImportError:
    from models import (
        INTERNSHIP_GOAL,
        INTERNSHIP_SCHEMA,
        PAGES,
        build_schema,
        extract_items,
        require_api_key,
        save,
        scrape,
        scrape_one,
    )


def collect_from_pages(
    pages: dict[str, str],
    goal: str = INTERNSHIP_GOAL,
    limit: int = 10,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Stream over supplied pages until the requested number of listings is reached."""
    if not pages or limit <= 0:
        return []

    client = TinyFish()
    listings: list[dict] = []
    for source, url in pages.items():
        remaining = limit - len(listings)
        if remaining <= 0:
            break
        if on_progress:
            on_progress(f"Searching {url}")

        result = None
        try:
            with client.agent.stream(
                url=url,
                goal=goal,
                output_schema=build_schema(collection_key="listings", max_items=remaining),
            ) as events:
                for event in events:
                    event_type = getattr(event.type, "value", event.type)
                    if event_type == "PROGRESS" and on_progress:
                        on_progress(f"{url}: {event.purpose}")
                    elif event_type == "COMPLETE":
                        if event.status == RunStatus.COMPLETED:
                            result = event.result_json
                        elif on_progress:
                            on_progress(f"Could not collect results from {url}: {event.status}")
        except Exception as error:
            if on_progress:
                on_progress(f"Could not collect results from {url}: {error}")
            continue

        items = extract_items(result, "listings")
        listings.extend(
            {"source": source, **item}
            for item in items
        )
    return listings[:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and save opportunity listings.")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("1", "2", "3"),
        default="1",
        help="1: scrape one source, 2: scrape configured sources, 3: search then scrape",
    )
    parser.add_argument("--url", help="URL to scrape in mode 1")
    parser.add_argument("--query", default="software engineering internship apply 2026")
    parser.add_argument("--goal", default=INTERNSHIP_GOAL, help="What listings to collect")
    parser.add_argument("--collection", default="internships", help="Collection key returned by TinyFish")
    parser.add_argument("--output", default="internships.json", help="JSON output path for modes 2 and 3")
    parser.add_argument("--limit", type=int, default=5, help="Maximum search results to scrape in mode 3")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_api_key()

    if args.mode == "1":
        url = args.url or next(iter(PAGES.values()))
        scrape_one(url, args.goal)
        return

    if args.mode == "2":
        pages = PAGES
    else:
        search_results = TinyFish().search.query(query=args.query)
        pages = {result.url: result.url for result in search_results.results[: max(args.limit, 0)]}
        if not pages:
            print("No pages found for that search.")
            save([], args.output)
            return

    records = asyncio.run(
        scrape(
            pages,
            goal=args.goal,
            collection_key=args.collection,
            schema=INTERNSHIP_SCHEMA if args.collection == "internships" else None,
        )
    )
    save(records, args.output)


if __name__ == "__main__":
    main()
