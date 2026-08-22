"""FastMCP server exposing Polymarket data as tools."""

import asyncio
import json
import time

import httpx
from mcp.server.fastmcp import FastMCP

from . import polymarket
from .polymarket import TIMEFRAME_SECONDS

mcp = FastMCP("polymarket")

DEFAULT_LIMIT = 10
MAX_LIMIT = 50


def clamp_limit(value: int) -> int:
    return max(1, min(value, MAX_LIMIT))


def _fidelity_for(seconds: int) -> int:
    """History resolution in minutes, coarse enough for one window."""
    if seconds <= 3600:
        return 5
    if seconds <= 21600:
        return 15
    if seconds <= 86400:
        return 60
    return 360


async def _price_change(market: dict, seconds: int) -> float | None:
    token_id = polymarket.primary_token_id(market)
    if token_id is None:
        return None
    start_ts = int(time.time()) - seconds
    history = await polymarket.price_history(
        token_id, start_ts=start_ts, fidelity=_fidelity_for(seconds)
    )
    if len(history) < 2:
        return None
    start_price = float(history[0]["p"])
    end_price = float(history[-1]["p"])
    if start_price <= 0:
        return None
    return round(end_price - start_price, 4)


@mcp.tool()
async def search_markets(query: str, limit: int = DEFAULT_LIMIT) -> str:
    """Search Polymarket prediction markets relevant to a topic or question.

    Returns normalized market summaries: question, slug, current probability_yes,
    full outcome probabilities, 24h volume, liquidity, and end date.
    """
    limit = clamp_limit(limit)
    try:
        markets = await polymarket.search_markets(query, limit)
    except httpx.HTTPError:
        return f"Unable to reach Polymarket while searching for '{query}'."
    if not markets:
        return f"No markets found for '{query}'."
    summaries = [polymarket.summarize_market(market) for market in markets]
    return json.dumps(summaries, indent=2)


@mcp.tool()
async def get_trending_markets(
    limit: int = DEFAULT_LIMIT, timeframe: str = "24h"
) -> str:
    """Return markets currently seeing high trading activity, ranked by 24h volume.

    Each market is annotated with its price change over the chosen timeframe.
    """
    limit = clamp_limit(limit)
    if timeframe not in TIMEFRAME_SECONDS:
        timeframe = "24h"
    seconds = TIMEFRAME_SECONDS[timeframe]
    change_key = f"price_change_{timeframe}"
    try:
        markets = await polymarket.trending_markets(limit)
    except httpx.HTTPError:
        return "Unable to reach Polymarket while fetching trending markets."
    if not markets:
        return "No trending markets found."

    changes = await asyncio.gather(
        *(_price_change(market, seconds) for market in markets),
        return_exceptions=True,
    )
    summaries = []
    for market, change in zip(markets, changes):
        summary = polymarket.summarize_market(market)
        if isinstance(change, (int, float)):
            summary[change_key] = change
        summaries.append(summary)
    return json.dumps(summaries, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
