"""FastMCP server exposing Polymarket data as tools."""

import asyncio
import json
import time
from datetime import datetime, timezone
from textwrap import dedent

import httpx
from mcp.server.fastmcp import FastMCP

from . import polymarket
from .polymarket import (
    CATEGORY_TAGS,
    INTERVAL_FIDELITY,
    RANGE_CLOB_INTERVALS,
    TIMEFRAME_SECONDS,
)

INSTRUCTIONS = dedent("""\
    Polymarket prediction markets as a real-world context source. Market
    prices are crowd-implied probabilities, not ground truth.

    Typical flows:
    - Current events: get_trending_markets for what is actively trading now,
      or world_state_from_markets for a broad snapshot across domains.
    - Specific topic or question: search_markets (or
      summarize_prediction_markets for a grouped overview), then
      get_market_probability on promising slugs.
    - How sentiment shifted: get_probability_timeseries on a market slug.
    - Broader angle on one market: get_related_markets.
    - Multi-outcome questions (elections, awards, sports): use
      get_event_probabilities with any member market's slug to roll the
      sibling markets up into one distribution.

    Slugs returned by one tool are valid inputs everywhere a slug is asked
    for. probability_yes is null for non-binary markets; read their outcomes
    list instead.
""")

mcp = FastMCP("polymarket", instructions=INSTRUCTIONS)

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


_STOPWORDS = {
    "will", "the", "be", "by", "after", "before", "during", "than", "more",
    "less", "this", "that", "with", "from", "into", "over", "under", "when",
    "what", "which", "who", "how", "does", "did", "have", "has", "and",
}


def _keywords(question: str, max_words: int = 6) -> str:
    words = [w.strip(".,?!\"'").lower() for w in question.split()]
    significant = [w for w in words if len(w) > 3 and w not in _STOPWORDS]
    return "+".join(significant[:max_words])


def _event_context(event: dict, max_markets: int) -> dict | None:
    """Compact event digest with its top markets by 24h volume."""
    markets = sorted(
        (m for m in event.get("markets", []) if not m.get("closed")),
        key=lambda m: m.get("volume24hr") or 0,
        reverse=True,
    )[:max_markets]
    if not markets:
        return None
    description = (event.get("description") or "").strip()
    if len(description) > 300:
        description = description[:297] + "..."
    context = {
        "event": event.get("title"),
        "event_slug": event.get("slug"),
        "markets": [polymarket.summarize_market(m) for m in markets],
    }
    if description:
        context["description"] = description
    return context


@mcp.tool()
async def get_related_markets(slug: str, limit: int = DEFAULT_LIMIT) -> str:
    """Find prediction markets related to a given market via shared category tags.

    Falls back to keyword search when the market has no taggable parent event.
    """
    limit = clamp_limit(limit)
    try:
        market = await polymarket.get_market(slug)
    except httpx.HTTPError:
        return f"Unable to reach Polymarket while fetching '{slug}'."
    if market is None:
        return f"No market found with slug '{slug}'."

    candidates: list[dict] = []
    source_event_slug = None
    events = market.get("events") or []
    if events and isinstance(events[0], dict):
        source_event_slug = events[0].get("slug")
    if source_event_slug:
        try:
            event = await polymarket.get_event(source_event_slug)
            tags = polymarket.event_tag_slugs(event) if event else []
        except httpx.HTTPError:
            tags = []
        for tag in tags[:2]:
            try:
                related_events = await polymarket.events_by_tag(tag, limit * 3)
            except httpx.HTTPError:
                continue
            candidates.extend(
                m
                for e in related_events
                if e.get("slug") != source_event_slug
                for m in e.get("markets", [])
            )
    if not candidates:
        query = _keywords(market.get("question") or "")
        if not query:
            return f"No related markets found for '{slug}'."
        try:
            candidates = await polymarket.search_markets(query, limit + 1)
        except httpx.HTTPError:
            return f"Unable to reach Polymarket while searching for related markets."

    candidates = [
        m for m in candidates
        if m.get("slug") and m.get("slug") != slug and not m.get("closed")
    ]
    seen = set()
    unique = []
    for m in sorted(candidates, key=lambda x: x.get("volume24hr") or 0, reverse=True):
        if m["slug"] not in seen:
            seen.add(m["slug"])
            unique.append(m)
    if not unique:
        return f"No related markets found for '{slug}'."
    summaries = [polymarket.summarize_market(m) for m in unique[:limit]]
    return json.dumps(summaries, indent=2)


@mcp.tool()
async def summarize_prediction_markets(topic: str, limit: int = DEFAULT_LIMIT) -> str:
    """Generate a high-level summary of prediction market probabilities for a topic.

    Groups related markets under their parent events with trimmed descriptions,
    giving a compact probabilistic overview of the topic.
    """
    limit = clamp_limit(limit)
    try:
        events = await polymarket.search_events(topic, limit)
    except httpx.HTTPError:
        return f"Unable to reach Polymarket while searching for '{topic}'."
    contexts = []
    remaining = limit
    for event in events:
        if remaining <= 0:
            break
        context = _event_context(event, remaining)
        if context is None:
            continue
        contexts.append(context)
        remaining -= len(context["markets"])
    if not contexts:
        return f"No prediction markets found for '{topic}'."
    return json.dumps({"topic": topic, "events": contexts}, indent=2)


@mcp.tool()
async def world_state_from_markets(
    categories: list[str] | None = None, limit_per_category: int = 5
) -> str:
    """Return a structured snapshot of the world's probabilistic state.

    Aggregates the highest-volume active markets across major prediction
    market domains. Valid categories: politics, economics, technology, crypto,
    geopolitics, science, sports. Defaults to all categories.
    """
    limit_per_category = max(1, min(limit_per_category, MAX_LIMIT))
    selected = list(CATEGORY_TAGS)
    if categories:
        unknown = [c for c in categories if c not in CATEGORY_TAGS]
        if unknown:
            valid = ", ".join(sorted(CATEGORY_TAGS))
            return f"Unknown categories: {', '.join(unknown)}. Valid categories: {valid}."
        selected = list(dict.fromkeys(categories))

    async def top_for_category(category: str) -> list[dict]:
        events = await polymarket.events_by_tag(
            CATEGORY_TAGS[category], limit_per_category * 2
        )
        markets = [
            m
            for e in events
            for m in e.get("markets", [])
            if not m.get("closed") and m.get("slug")
        ]
        markets.sort(key=lambda m: m.get("volume24hr") or 0, reverse=True)
        return [polymarket.summarize_market(m) for m in markets[:limit_per_category]]

    results = await asyncio.gather(
        *(top_for_category(c) for c in selected), return_exceptions=True
    )
    snapshot: dict = {"generated_at": datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"), "categories": {}}
    failures = 0
    for category, result in zip(selected, results):
        if isinstance(result, BaseException):
            failures += 1
            continue
        snapshot["categories"][category] = result
    if failures == len(selected):
        return "Unable to reach Polymarket while building the world state."
    return json.dumps(snapshot, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
