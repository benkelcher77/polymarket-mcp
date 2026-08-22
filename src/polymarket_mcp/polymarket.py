"""HTTP access to Polymarket's public Gamma and CLOB APIs."""

import json
from typing import Any
from urllib.parse import quote

import httpx

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

_HEADERS = {
    "User-Agent": "polymarket-mcp/0.1",
    "Accept": "application/json",
}

# Supported trend-annotation windows mapped to seconds.
TIMEFRAME_SECONDS = {
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 604800,
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
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    if isinstance(value, list):
        return value
    return []


def outcome_probabilities(market: dict[str, Any]) -> list[tuple[str, float]]:
    """Pair each outcome name with its current probability from a Gamma market."""
    outcomes = parse_json_list(market.get("outcomes"))
    prices = parse_json_list(market.get("outcomePrices"))
    pairs: list[tuple[str, float]] = []
    for name, price in zip(outcomes, prices):
        try:
            pairs.append((str(name), float(price)))
        except (TypeError, ValueError):
            continue
    return pairs


def summarize_market(market: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw Gamma market into the compact context schema."""
    outcomes = [
        {"name": name, "probability": probability}
        for name, probability in outcome_probabilities(market)
    ]
    probability_yes = next(
        (
            probability
            for name, probability in outcome_probabilities(market)
            if name.lower() == "yes"
        ),
        None,
    )
    liquidity = market.get("liquidityNum")
    if liquidity is None:
        try:
            liquidity = float(market.get("liquidity"))
        except (TypeError, ValueError):
            liquidity = None
    end_date = market.get("endDate")
    return {
        "question": market.get("question"),
        "slug": market.get("slug"),
        "probability_yes": probability_yes,
        "outcomes": outcomes,
        "volume_24h": market.get("volume24hr"),
        "liquidity": liquidity,
        "end_date": end_date[:10] if isinstance(end_date, str) and end_date else None,
    }


def primary_token_id(market: dict[str, Any]) -> str | None:
    """CLOB token id whose history best represents this market.

    Prefers the ``Yes`` outcome when present, otherwise the first token.
    """
    tokens = parse_json_list(market.get("clobTokenIds"))
    if not tokens:
        return None
    index = 0
    for position, name in enumerate(parse_json_list(market.get("outcomes"))):
        if str(name).lower() == "yes":
            index = position
            break
    return str(tokens[index]) if index < len(tokens) else None


async def search_markets(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search Gamma for active markets relevant to a query, ranked by 24h volume."""
    url = (
        f"{GAMMA_API_BASE}/public-search?q={quote(query)}"
        f"&limit_per_type={max(limit, 5)}&keep_closed_markets=0"
    )
    data = await fetch_json(url)
    events = data.get("events", []) if isinstance(data, dict) else []
    markets = [
        market
        for event in events
        for market in event.get("markets", [])
        if not market.get("closed")
    ]
    markets.sort(key=lambda market: market.get("volume24hr") or 0, reverse=True)
    return markets[:limit]


async def trending_markets(limit: int = 10) -> list[dict[str, Any]]:
    """Flatten currently trending events into their markets, ranked by 24h volume."""
    url = (
        f"{GAMMA_API_BASE}/events?closed=false&order=volume24hr&ascending=false"
        f"&limit={min(limit * 3, 100)}"
    )
    events = await fetch_json(url)
    if not isinstance(events, list):
        return []
    markets = [
        market for event in events for market in event.get("markets", [])
    ]
    markets.sort(key=lambda market: market.get("volume24hr") or 0, reverse=True)
    return markets[:limit]


async def price_history(
    token_id: str,
    *,
    start_ts: int | None = None,
    interval: str | None = None,
    fidelity: int,
) -> list[dict[str, Any]]:
    """Fetch CLOB price history points ``[{"t": ..., "p": ...}, ...]``."""
    params = [f"market={token_id}", f"fidelity={fidelity}"]
    if start_ts is not None:
        params.append(f"startTs={start_ts}")
    if interval is not None:
        params.append(f"interval={interval}")
    data = await fetch_json(f"{CLOB_API_BASE}/prices-history?{'&'.join(params)}")
    history = data.get("history", []) if isinstance(data, dict) else []
    return [point for point in history if "t" in point and "p" in point]

