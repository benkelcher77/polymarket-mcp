from mcp.server.fastmcp import FastMCP
from textwrap import dedent
from typing import Any

import httpx

mcp = FastMCP("polymarket")

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"
USER_AGENT = "polymarket-mcp/1.0"

async def make_request(url: str) -> dict[str, Any] | None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

@mcp.tool()
async def find_events(queries: list[str]) -> str:
    def format_event(event: dict) -> str:
        return dedent(f"""
        Title: {event['title']}
        Description: {event['description']}
        """)

    url = f"{GAMMA_API_BASE}/public-search?q={'+'.join(queries)}"
    data = await make_request(url)

    if not data or "events" not in data:
        return "Unable to search for events."

    if not data["events"]:
        return f"No events found for search terms {' '.join(queries)}."

    events = [format_event(event) for event in data["events"]]
    return "\n---\n".join(events)

def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
