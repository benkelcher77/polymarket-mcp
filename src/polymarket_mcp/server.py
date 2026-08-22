"""FastMCP server exposing Polymarket data as tools."""

from textwrap import dedent
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from . import polymarket
from .polymarket import GAMMA_API_BASE

mcp = FastMCP("polymarket")


@mcp.tool()
async def find_events(queries: list[str], limit: int | None = None) -> str:
    """Search Polymarket events relevant to the given query terms."""
    limit_per_type = limit if limit is not None else 5

    def format_event(event: dict[str, Any]) -> str:
        return dedent(f"""
        Title: {event['title']}
        Description: {event['description']}
        """)

    url = (
        f"{GAMMA_API_BASE}/public-search?q={'+'.join(queries)}"
        f"&limit_per_type={limit_per_type}&keep_closed_markets=0"
    )
    try:
        data = await polymarket.fetch_json(url)
    except httpx.HTTPError:
        return "Unable to search for events."

    if not isinstance(data, dict) or "events" not in data:
        return "Unable to search for events."

    if not data["events"]:
        return f"No events found for search terms {' '.join(queries)}."

    events = [format_event(event) for event in data["events"]]
    return "\n---\n".join(events)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
