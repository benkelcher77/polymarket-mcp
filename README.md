# polymarket-mcp

An MCP server that turns [Polymarket](https://polymarket.com) prediction
markets into a source of real-world context for LLMs: what events are being
traded, what the crowd thinks will happen, and how those probabilities are
moving.

## Tools

| Tool | Description |
|------|-------------|
| `search_markets(query, limit=10)` | Search active markets relevant to a topic or question |
| `get_trending_markets(limit=10, timeframe="24h")` | Highest-volume markets, annotated with price change over the timeframe (`1h`, `6h`, `24h`, `7d`) |
| `get_market_probability(slug)` | Current probability and metadata for one market (normalized `probability_yes`) |
| `get_probability_timeseries(slug, range="7d", interval="1h")` | Historical probability points; ranges `24h/7d/30d/90d/all`, intervals `5m/15m/1h/6h/1d` |
| `get_related_markets(slug, limit=5)` | Markets related via shared event tags, with keyword-search fallback |
| `summarize_prediction_markets(topic, limit=10)` | Events with their top markets and probabilities for a topic |
| `world_state_from_markets(categories=None, limit_per_category=5)` | Snapshot across domains: politics, economics, technology, crypto, geopolitics, science, sports |

All market outputs are normalized JSON: `probability_yes` plus per-outcome
probabilities, 24h volume, liquidity, and end date. Multi-outcome markets
(e.g. sports) return all outcomes and a null `probability_yes`.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14+.

```sh
uv sync          # install dependencies
uv run pytest    # run tests
```

Run the server over stdio:

```sh
uv run polymarket-mcp
```

## MCP client configuration

```json
{
  "mcpServers": {
    "polymarket": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/polymarket-mcp", "polymarket-mcp"]
    }
  }
}
```

## Example

```
> get_market_probability("will-the-fed-decrease-interest-rates-by-25-bps-after-the-september-2026-meeting-586")

{
  "question": "Will the Fed decrease interest rates by 25 bps after the September 2026 meeting?",
  "slug": "...",
  "probability_yes": 0.0105,
  "outcomes": [
    {"name": "Yes", "probability": 0.0105},
    {"name": "No", "probability": 0.9895}
  ],
  "volume_24h": 1408244.13,
  "liquidity": 898608.17,
  "end_date": "2026-09-16",
  ...
}
```

## Architecture

- `src/polymarket_mcp/polymarket.py` — Gamma API (search/markets/events/tags)
  and CLOB API (price history) clients, plus normalization of Polymarket's
  string-encoded fields into plain data.
- `src/polymarket_mcp/server.py` — FastMCP tool definitions.

No API key required; both APIs are public read-only endpoints.
