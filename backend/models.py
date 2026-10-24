"""Reusable models and helpers for collecting structured opportunity listings."""

import asyncio
import json
import os
from dotenv import load_dotenv
import sys
from dataclasses import dataclass, field
from typing import Any

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
    "deadline, application or information link, and category."
)
DEFAULT_FIELDS: dict[str, dict[str, str]] = {
    "title": {"type": "string"},
    "organization": {"type": "string"},
    "location": {"type": "string"},
    "remote": {"type": "boolean"},
    "deadline": {"type": "string"},
    "apply_link": {"type": "string"},
    "category": {"type": "string"},
}


def build_schema(
    fields: dict[str, dict[str, str]] | None = None,
    collection_key: str = "listings",
) -> dict[str, Any]:
    """Build a TinyFish JSON schema for a collection of listing records."""
    return {
        "type": "object",
        "properties": {
            collection_key: {
                "type": "array",
                "items": {"type": "object", "properties": fields or DEFAULT_FIELDS},
            }
        },
    }


def require_api_key() -> None:
    if not os.getenv("TINYFISH_API_KEY"):
        sys.exit("Set TINYFISH_API_KEY first (see the setup guide).")


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
) -> list[dict[str, Any]]:
    """Scrape multiple named sources concurrently and attach each source name."""
    agents = AsyncTinyFish()
    output_schema = schema or build_schema(collection_key=collection_key)
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
        result = run.result
        items = result.get(collection_key, []) if isinstance(result, dict) else []
        listings.extend({"source": source, **item} for item in items if isinstance(item, dict))
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
