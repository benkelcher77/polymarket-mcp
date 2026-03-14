## Tools

- search_markets(query, limit)
- get_market_probability(slug)
- get_trending_markets(limit, range)
- get_probability_timeseries(slug, range, interval)
- get_related_markets(slug, limit)
- summarize_prediction_markets(topic, limit)
- world_state_from_markets(domains)

## Schema

```json
{
  "tools": [
    {
      "name": "search_markets",
      "description": "Search Polymarket prediction markets relevant to a topic or question.",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Natural language query describing an event or topic."
          },
          "limit": {
            "type": "integer",
            "description": "Maximum number of markets to return.",
            "default": 10,
            "minimum": 1,
            "maximum": 50
          }
        },
        "required": ["query"]
      }
    },
    {
      "name": "get_market_probability",
      "description": "Get the current probability and metadata for a specific prediction market.",
      "input_schema": {
        "type": "object",
        "properties": {
          "slug": {
            "type": "string",
            "description": "Unique market slug identifier."
          }
        },
        "required": ["slug"]
      }
    },
    {
      "name": "get_trending_markets",
      "description": "Return markets currently experiencing high trading activity, price movement, or volume.",
      "input_schema": {
        "type": "object",
        "properties": {
          "limit": {
            "type": "integer",
            "description": "Maximum number of markets to return.",
            "default": 10,
            "minimum": 1,
            "maximum": 50
          },
          "timeframe": {
            "type": "string",
            "description": "Time window for trend detection.",
            "enum": ["1h", "6h", "24h", "7d"],
            "default": "24h"
          }
        }
      }
    },
    {
      "name": "get_probability_timeseries",
      "description": "Retrieve historical probability changes for a market over time.",
      "input_schema": {
        "type": "object",
        "properties": {
          "slug": {
            "type": "string",
            "description": "Market slug identifier."
          },
          "range": {
            "type": "string",
            "description": "Time range to fetch.",
            "enum": ["24h", "7d", "30d", "90d", "all"],
            "default": "7d"
          },
          "interval": {
            "type": "string",
            "description": "Granularity of data points.",
            "enum": ["5m", "15m", "1h", "6h", "1d"],
            "default": "1h"
          }
        },
        "required": ["slug"]
      }
    },
    {
      "name": "get_related_markets",
      "description": "Find prediction markets related to a given market based on topic similarity or correlation.",
      "input_schema": {
        "type": "object",
        "properties": {
          "slug": {
            "type": "string",
            "description": "Market slug identifier."
          },
          "limit": {
            "type": "integer",
            "description": "Maximum number of related markets to return.",
            "default": 5,
            "minimum": 1,
            "maximum": 20
          }
        },
        "required": ["slug"]
      }
    },
    {
      "name": "summarize_prediction_markets",
      "description": "Generate a high-level summary of prediction market probabilities for a given topic.",
      "input_schema": {
        "type": "object",
        "properties": {
          "topic": {
            "type": "string",
            "description": "Topic to summarize (e.g., US election, AI development, crypto markets)."
          },
          "limit": {
            "type": "integer",
            "description": "Maximum number of markets to include in the summary.",
            "default": 10,
            "minimum": 1,
            "maximum": 50
          }
        },
        "required": ["topic"]
      }
    },
    {
      "name": "world_state_from_markets",
      "description": "Return a structured snapshot of the world's probabilistic state derived from major prediction markets across politics, economics, technology, and global events.",
      "input_schema": {
        "type": "object",
        "properties": {
          "categories": {
            "type": "array",
            "description": "Optional list of domains to include.",
            "items": {
              "type": "string",
              "enum": [
                "politics",
                "economics",
                "technology",
                "crypto",
                "geopolitics",
                "science",
                "sports"
              ]
            }
          },
          "limit_per_category": {
            "type": "integer",
            "description": "Maximum markets per category.",
            "default": 5,
            "minimum": 1,
            "maximum": 20
          }
        }
      }
    }
  ]
}
```

## Notes
- Output in a JSON format, e.g. (for `get_market_probability`)
```json
{
  "question": "Will Bitcoin exceed $100,000 by Dec 31, 2026?",
  "slug": "bitcoin-above-100k-2026",
  "outcomes": [
    { "name": "Yes", "probability": 0.42 },
  ],
  "volume_24h": 182340,
  "liquidity": 1200000,
  "end_date": "2026-12-31",
  "last_updated": "2026-03-14T18:40:00Z"
}
```
- Use normalized probability (e.g., `probability_yes` rather than providing
both yes and no)
