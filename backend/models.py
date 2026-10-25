"""Reusable models and helpers for collecting structured opportunity listings."""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from tinyfish import AsyncTinyFish, RunStatus

load_dotenv()


@dataclass
class Listing:
    """A flexible job, internship, event, or other opportunity listing."""

    title: str
    organization: str = ""
    location: str = ""
    remote: bool | None = None
    deadline: str = ""
    apply_link: str = ""
    category: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "title": self.title,
            "organization": self.organization,
            "location": self.location,
            "remote": self.remote,
            "deadline": self.deadline,
            "apply_link": self.apply_link,
            "category": self.category,
        }
        return {**result, **self.details}


DEFAULT_GOAL = (
    "Find current opportunities relevant to the requested audience and category. "
    "For each one return its title, organization, location, whether it is remote, "
    "deadline, application or information link, and category. Use an empty string "
    "for unavailable text fields and null when the remote status is unknown."
)
DEFAULT_FIELDS: dict[str, dict[str, str]] = {
    "title": {"type": "string"},
    "organization": {"type": "string"},
    "location": {"type": "string"},
    "remote": {"type": "boolean", "nullable": True},
    "deadline": {"type": "string"},
    "apply_link": {"type": "string"},
    "category": {"type": "string"},
}


def build_schema(
    fields: dict[str, dict[str, str]] | None = None,
    collection_key: str = "listings",
    max_items: int | None = None,
) -> dict[str, Any]:
    """Build a TinyFish-supported schema for a collection of listing records."""
    item_fields = DEFAULT_FIELDS if fields is None else fields
    item_schema: dict[str, Any] = {
        "type": "object",
        "properties": item_fields,
        "required": list(item_fields),
    }
    array_schema: dict[str, Any] = {"type": "array", "items": item_schema}
    if max_items is not None:
        array_schema["maxItems"] = max_items
    return {
        "type": "object",
        "properties": {collection_key: array_schema},
        "required": [collection_key],
    }


def require_api_key() -> None:
    if not os.getenv("TINYFISH_API_KEY"):
        sys.exit("Set TINYFISH_API_KEY first (see the setup guide).")


def extract_items(result: Any, collection_key: str = "listings") -> list[dict[str, Any]]:
    """Read structured collection data from either documented result shape."""
    if not isinstance(result, dict):
        return []
    items = result.get(collection_key)
    if not isinstance(items, list) and isinstance(result.get("result"), dict):
        items = result["result"].get(collection_key)
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def scrape_one(url: str, goal: str = DEFAULT_GOAL) -> Any:
    """Run a synchronous scrape against one URL."""
    from tinyfish import TinyFish

    run = TinyFish().agent.run(url=url, goal=goal)
    print(run.status)
    if run.status == RunStatus.COMPLETED:
        print(json.dumps(run.result, indent=2))
    return run.result if run.status == RunStatus.COMPLETED else None


async def scrape(
    pages: dict[str, str],
    goal: str = DEFAULT_GOAL,
    collection_key: str = "listings",
    schema: dict[str, Any] | None = None,
    max_listings: int | None = None,
) -> list[dict[str, Any]]:
    """Scrape sources and attach each source name to its returned listings.

    When ``max_listings`` is provided, sources are visited in order and scraping
    stops once that many records have been collected.
    """
    agents = AsyncTinyFish()
    output_schema = schema or build_schema(collection_key=collection_key)

    if max_listings is not None:
        if max_listings <= 0:
            return []
        listings: list[dict[str, Any]] = []
        for source, url in pages.items():
            try:
                page_schema = schema or build_schema(
                    collection_key=collection_key,
                    max_items=max_listings - len(listings),
                )
                run = await agents.agent.run(url=url, goal=goal, output_schema=page_schema)
            except Exception as error:
                print(f"! {source}: no result ({error})")
                continue
            if run.status != RunStatus.COMPLETED:
                print(f"! {source}: no result ({run.status})")
                continue
            items = extract_items(run.result, collection_key)
            listings.extend(
                {"source": source, **item}
                for item in items
            )
            if len(listings) >= max_listings:
                return listings[:max_listings]
        return listings

    runs = await asyncio.gather(
        *(agents.agent.run(url=url, goal=goal, output_schema=output_schema) for url in pages.values()),
        return_exceptions=True,
    )

    listings: list[dict[str, Any]] = []
    for source, run in zip(pages, runs):
        if isinstance(run, Exception) or run.status != RunStatus.COMPLETED:
            status = run if isinstance(run, Exception) else run.status
            print(f"! {source}: no result ({status})")
            continue
        items = extract_items(run.result, collection_key)
        listings.extend({"source": source, **item} for item in items)
    return listings


def save(
    listings: list[dict[str, Any]],
    output_path: str = "listings.json",
    limit: int = 15,
) -> None:
    """Save listing records and print a concise preview."""
    listings.sort(key=lambda item: item.get("remote") is not True)
    with open(output_path, "w", encoding="utf-8") as output:
        json.dump(listings, output, indent=2)
    for item in listings[:limit]:
        remote_tag = "REMOTE" if item.get("remote") else "      "
        source = item.get("source", "")
        print(
            f"{remote_tag} {source:<12} {item.get('title', '?')} | "
            f"{item.get('location', '?')} | {item.get('deadline', '-')}"
        )
    print(f"-> {output_path} written ({len(listings)} listings)")


# Existing internship workflow, now configured through the generic helpers above.
INTERNSHIP_GOAL = (
    "Find internships open to students (software, AI, or data roles preferred). "
    "For each one return title, organization, location, remote (true/false), "
    "deadline, apply_link, and category."
)
INTERNSHIP_SCHEMA = build_schema(collection_key="internships")
PAGES = {
    "Jane Street": "https://www.janestreet.com/join-jane-street/open-roles/",
    "Google": "https://www.google.com/about/careers/applications/jobs/results/?q=intern",
    "Microsoft": "https://jobs.careers.microsoft.com/global/en/search?q=intern",
    "Razorpay": "https://razorpay.com/jobs/",
}
