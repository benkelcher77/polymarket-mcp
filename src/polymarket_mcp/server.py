"""FastMCP server exposing Polymarket data as tools."""

import asyncio
import json
import time
from datetime import datetime, timezone

import httpx
from mcp.server.fastmcp import FastMCP

from . import polymarket
from .polymarket import (
    INTERVAL_FIDELITY,
    RANGE_CLOB_INTERVALS,
    TIMEFRAME_SECONDS,
)

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


@mcp.tool()
async def get_market_probability(slug: str) -> str:
    """Get the current probability and metadata for a specific prediction market.

    Returns the market question, slug, probability_yes, full outcome
    probabilities, 24h volume, liquidity, end date, and resolution status.
    """
    try:
        market = await polymarket.get_market(slug)
    except httpx.HTTPError:
        return f"Unable to reach Polymarket while fetching '{slug}'."
    if market is None:
        return f"No market found with slug '{slug}'."
    summary = polymarket.summarize_market(market)
    summary["closed"] = bool(market.get("closed"))
    summary["last_updated"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return json.dumps(summary, indent=2)


@mcp.tool()
async def get_probability_timeseries(
    slug: str, range: str = "7d", interval: str = "1h"
) -> str:
    """Retrieve historical probability changes for a market over time.

    Points track the primary outcome (Yes when present) as {"t": unix_seconds,
    "p": probability}. Valid ranges: 24h, 7d, 30d, 90d, all.
    Valid intervals: 5m, 15m, 1h, 6h, 1d. Falls back to defaults when invalid.
    """
    if range not in RANGE_CLOB_INTERVALS:
        range = "7d"
    if interval not in INTERVAL_FIDELITY:
        interval = "1h"
    try:
        market = await polymarket.get_market(slug)
    except httpx.HTTPError:
        return f"Unable to reach Polymarket while fetching history for '{slug}'."
    if market is None:
        return f"No market found with slug '{slug}'."
    token_id = polymarket.primary_token_id(market)
    if token_id is None:
        return f"Market '{slug}' has no tradable outcomes to chart."
    try:
        history = await polymarket.price_history(
            token_id,
            interval=RANGE_CLOB_INTERVALS[range],
            fidelity=INTERVAL_FIDELITY[interval],
        )
    except httpx.HTTPError:
        return f"Unable to fetch price history for '{slug}'."
    result = {
        "question": market.get("question"),
        "slug": market.get("slug"),
        "range": range,
        "interval": interval,
        "current_probability_yes": next(
            (
                p
                for name, p in polymarket.outcome_probabilities(market)
                if name.lower() == "yes"
            ),
            None,
        ),
        "points": [{"t": point["t"], "p": point["p"]} for point in history],
    }
    return json.dumps(result, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
