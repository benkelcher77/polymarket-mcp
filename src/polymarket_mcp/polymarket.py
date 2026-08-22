"""HTTP access to Polymarket's public Gamma and CLOB APIs."""

from typing import Any

import httpx

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

_HEADERS = {
    "User-Agent": "polymarket-mcp/0.1",
    "Accept": "application/json",
}


async def fetch_json(url: str) -> Any:
    """GET a URL and return the parsed JSON body.

    Raises httpx.HTTPError subclasses on network or HTTP failure.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_HEADERS, timeout=30.0)
        response.raise_for_status()
        return response.json()


def parse_json_list(value: Any) -> list:
    """Parse Polymarket fields that are JSON arrays encoded as strings.

    Gamma API returns fields like ``outcomes`` and ``outcomePrices`` as
    strings such as ``'["Yes", "No"]'``. Real lists are passed through.
    """
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    if isinstance(value, list):
        return value
    return []
