"""Tests for the market discovery tools, with Polymarket HTTP mocked out."""

import asyncio
import json

import httpx
import pytest

from polymarket_mcp import polymarket
from polymarket_mcp import server


def run(coro):
    return asyncio.run(coro)


def fake_fetch(routes):
    """Build a fetch_json replacement dispatching on URL substring."""

    async def _fetch(url: str):
        for fragment, payload in routes.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"unexpected URL: {url}")

    return _fetch


FAKE_MARKET = {
    "question": "Will the Fed cut rates in September 2026?",
    "slug": "fed-cut-september-2026",
    "outcomes": '["Yes", "No"]',
    "outcomePrices": '["0.62", "0.38"]',
    "clobTokenIds": '["111", "222"]',
    "volume24hr": 137768.39,
    "liquidityNum": 704685.38,
    "endDate": "2026-09-16T00:00:00Z",
}

FAKE_EVENT = {
    "title": "Fed Decision",
    "slug": "fed-decision",
    "markets": [dict(FAKE_MARKET)],
}


class TestSearchMarkets:
    def test_returns_normalized_summaries(self, monkeypatch):
        monkeypatch.setattr(
            polymarket,
            "fetch_json",
            fake_fetch({"public-search": {"events": [FAKE_EVENT]}}),
        )
        result = run(server.search_markets("fed rate", 10))
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["question"] == FAKE_MARKET["question"]
        assert data[0]["slug"] == "fed-cut-september-2026"
        assert data[0]["probability_yes"] == 0.62
        assert data[0]["outcomes"] == [
            {"name": "Yes", "probability": 0.62},
            {"name": "No", "probability": 0.38},
        ]
        assert data[0]["volume_24h"] == pytest.approx(137768.39)
        assert data[0]["end_date"] == "2026-09-16"

    def test_no_results_message(self, monkeypatch):
        monkeypatch.setattr(
            polymarket, "fetch_json", fake_fetch({"public-search": {"events": []}})
        )
        result = run(server.search_markets("nothing matches this", 5))
        assert result == "No markets found for 'nothing matches this'."

    def test_http_error_message(self, monkeypatch):
        monkeypatch.setattr(
            polymarket,
            "fetch_json",
            fake_fetch({"public-search": httpx.ConnectError("boom")}),
        )
        result = run(server.search_markets("fed rate", 5))
        assert result.startswith("Unable to reach Polymarket")


class TestTrendingMarkets:
    def test_annotates_price_change(self, monkeypatch):
        routes = {
            "/events?closed=false": [FAKE_EVENT],
            "prices-history": {"history": [{"t": 1, "p": 0.5}, {"t": 2, "p": 0.65}]},
        }
        monkeypatch.setattr(polymarket, "fetch_json", fake_fetch(routes))
        result = run(server.get_trending_markets(5, "24h"))
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["price_change_24h"] == pytest.approx(0.15)

    def test_missing_history_omits_change(self, monkeypatch):
        routes = {
            "/events?closed=false": [FAKE_EVENT],
            "prices-history": {"history": []},
        }
        monkeypatch.setattr(polymarket, "fetch_json", fake_fetch(routes))
        result = run(server.get_trending_markets(5, "7d"))
        data = json.loads(result)
        assert "price_change_7d" not in data[0]

    def test_invalid_timeframe_defaults_to_24h(self, monkeypatch):
        routes = {
            "/events?closed=false": [FAKE_EVENT],
            "prices-history": {"history": [{"t": 1, "p": 0.4}, {"t": 2, "p": 0.4}]},
        }
        monkeypatch.setattr(polymarket, "fetch_json", fake_fetch(routes))
        result = run(server.get_trending_markets(5, "fortnight"))
        data = json.loads(result)
        assert "price_change_24h" in data[0]


class TestGetMarketProbability:
    def test_returns_summary_with_status(self, monkeypatch):
        monkeypatch.setattr(
            polymarket,
            "fetch_json",
            fake_fetch({"/markets?slug=": [FAKE_MARKET]}),
        )
        result = run(server.get_market_probability("fed-cut-september-2026"))
        data = json.loads(result)
        assert data["probability_yes"] == 0.62
        assert data["closed"] is False
        assert "last_updated" in data
        assert data["end_date"] == "2026-09-16"

    def test_unknown_slug_message(self, monkeypatch):
        monkeypatch.setattr(
            polymarket, "fetch_json", fake_fetch({"/markets?slug=": []})
        )
        result = run(server.get_market_probability("missing-slug"))
        assert result == "No market found with slug 'missing-slug'."

    def test_http_error_message(self, monkeypatch):
        monkeypatch.setattr(
            polymarket,
            "fetch_json",
            fake_fetch({"/markets?slug=": httpx.ConnectError("boom")}),
        )
        result = run(server.get_market_probability("fed-cut-september-2026"))
        assert result.startswith("Unable to reach Polymarket")


class TestProbabilityTimeseries:
    def test_returns_points(self, monkeypatch):
        routes = {
            "/markets?slug=": [FAKE_MARKET],
            "prices-history": {
                "history": [
                    {"t": 1787324419, "p": 0.575},
                    {"t": 1787364014, "p": 0.63},
                ]
            },
        }
        monkeypatch.setattr(polymarket, "fetch_json", fake_fetch(routes))
        result = run(server.get_probability_timeseries("fed-cut-september-2026"))
        data = json.loads(result)
        assert data["range"] == "7d"
        assert data["interval"] == "1h"
        assert data["current_probability_yes"] == 0.62
        assert len(data["points"]) == 2

    def test_invalid_params_fall_back(self, monkeypatch):
        urls = []

        async def capture(url: str):
            urls.append(url)
            if "prices-history" in url:
                return {"history": [{"t": 1, "p": 0.5}]}
            return [FAKE_MARKET]

        monkeypatch.setattr(polymarket, "fetch_json", capture)
        result = run(
            server.get_probability_timeseries(
                "fed-cut-september-2026", range="decade", interval="3s"
            )
        )
        data = json.loads(result)
        assert data["range"] == "7d"
        assert data["interval"] == "1h"
        assert any("fidelity=60" in url and "interval=1w" in url for url in urls)

    def test_no_token_message(self, monkeypatch):
        market = dict(FAKE_MARKET, clobTokenIds='[]')
        monkeypatch.setattr(
            polymarket, "fetch_json", fake_fetch({"/markets?slug=": [market]})
        )
        result = run(server.get_probability_timeseries("fed-cut-september-2026"))
        assert result == "Market 'fed-cut-september-2026' has no tradable outcomes to chart."


class TestHelpers:
    def test_parse_json_list_variants(self):
        assert polymarket.parse_json_list('["a", "b"]') == ["a", "b"]
        assert polymarket.parse_json_list(["a"]) == ["a"]
        assert polymarket.parse_json_list("not json") == []
        assert polymarket.parse_json_list(None) == []
        assert polymarket.parse_json_list('{"x": 1}') == []

    def test_primary_token_id_prefers_yes(self):
        market = dict(FAKE_MARKET, outcomes='["No", "Yes"]', clobTokenIds='["1", "2"]')
        assert polymarket.primary_token_id(market) == "2"
        multi = {
            "outcomes": '["Alice", "Bob", "Carol"]',
            "clobTokenIds": '["9", "8", "7"]',
        }
        assert polymarket.primary_token_id(multi) == "9"
        assert polymarket.primary_token_id({"outcomes": "[]"}) is None

    def test_multi_outcome_market_has_null_probability_yes(self):
        market = dict(
            FAKE_MARKET,
            outcomes='["Alice", "Bob"]',
            outcomePrices='["0.7", "0.3"]',
        )
        summary = polymarket.summarize_market(market)
        assert summary["probability_yes"] is None
        assert len(summary["outcomes"]) == 2


class TestGetRelatedMarkets:
    TAGGED_EVENT = {
        "title": "Fed Decision",
        "slug": "fed-decision",
        "tags": [{"slug": "fed-rates"}, {"slug": "politics"}],
    }

    def market_with_event(self):
        return dict(FAKE_MARKET, slug="fed-cut", events=[{"slug": "fed-decision"}])

    def test_via_shared_tags(self, monkeypatch):
        related = {
            "title": "Other Fed Event",
            "slug": "other-fed-event",
            "markets": [
                dict(FAKE_MARKET, question="Will the Fed pause?", slug="fed-pause")
            ],
        }
        routes = {
            "/markets?slug=fed-cut": [self.market_with_event()],
            "/events?slug=fed-decision": [self.TAGGED_EVENT],
            "tag_slug=fed-rates": [related],
            "tag_slug=politics": [],
        }
        monkeypatch.setattr(polymarket, "fetch_json", fake_fetch(routes))
        result = run(server.get_related_markets("fed-cut", 5))
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["slug"] == "fed-pause"

    def test_excludes_source_market(self, monkeypatch):
        related = {
            "title": "E",
            "slug": "e2",
            "markets": [
                dict(FAKE_MARKET, slug="fed-pause"),
                dict(FAKE_MARKET, slug="fed-cut"),
            ],
        }
        routes = {
            "/markets?slug=fed-cut": [self.market_with_event()],
            "/events?slug=fed-decision": [self.TAGGED_EVENT],
            "tag_slug=fed-rates": [related],
            "tag_slug=politics": [],
        }
        monkeypatch.setattr(polymarket, "fetch_json", fake_fetch(routes))
        result = run(server.get_related_markets("fed-cut", 5))
        slugs = [m["slug"] for m in json.loads(result)]
        assert slugs == ["fed-pause"]

    def test_keyword_fallback_without_results(self, monkeypatch):
        market = dict(FAKE_MARKET, events=[], question="Will the Fed cut rates?")
        monkeypatch.setattr(
            polymarket,
            "fetch_json",
            fake_fetch(
                {"/markets?slug=": [market], "public-search": {"events": []}}
            ),
        )
        result = run(server.get_related_markets("fed-cut", 3))
        assert result == "No related markets found for 'fed-cut'."

    def test_unknown_slug_message(self, monkeypatch):
        monkeypatch.setattr(
            polymarket, "fetch_json", fake_fetch({"/markets?slug=": []})
        )
        result = run(server.get_related_markets("missing"))
        assert result == "No market found with slug 'missing'."


class TestSummarizeMarkets:
    def test_groups_by_event_and_trims_description(self, monkeypatch):
        event = {
            "title": "Fed Decision in September?",
            "slug": "fed-september",
            "description": "Resolution details. " * 100,
            "markets": [
                FAKE_MARKET,
                dict(FAKE_MARKET, question="Cut 50bps?", slug="cut-50"),
            ],
        }
        monkeypatch.setattr(
            polymarket,
            "fetch_json",
            fake_fetch({"public-search": {"events": [event]}}),
        )
        result = run(server.summarize_prediction_markets("fed rates", 10))
        data = json.loads(result)
        assert data["topic"] == "fed rates"
        ctx = data["events"][0]
        assert ctx["event"] == "Fed Decision in September?"
        assert len(ctx["markets"]) == 2
        assert ctx["description"].endswith("...")
        assert len(ctx["description"]) <= 300

    def test_respects_total_limit(self, monkeypatch):
        event = {
            "title": "Big Event",
            "slug": "big-event",
            "description": "",
            "markets": [
                dict(FAKE_MARKET, slug=f"m{i}", question=f"Question {i}?")
                for i in range(6)
            ],
        }
        monkeypatch.setattr(
            polymarket,
            "fetch_json",
            fake_fetch({"public-search": {"events": [event]}}),
        )
        result = run(server.summarize_prediction_markets("topic", 4))
        total = sum(
            len(e["markets"]) for e in json.loads(result)["events"]
        )
        assert total == 4

    def test_no_results_message(self, monkeypatch):
        monkeypatch.setattr(
            polymarket, "fetch_json", fake_fetch({"public-search": {"events": []}})
        )
        result = run(server.summarize_prediction_markets("nothing", 5))
        assert result == "No prediction markets found for 'nothing'."


class TestWorldState:
    def test_snapshot_across_categories(self, monkeypatch):
        routes = {}
        for cat in ["politics", "crypto"]:
            routes[f"tag_slug={cat}"] = [
                {
                    "title": f"{cat} ev",
                    "slug": f"{cat}-ev",
                    "markets": [dict(FAKE_MARKET, slug=f"{cat}-m1")],
                }
            ]
        monkeypatch.setattr(polymarket, "fetch_json", fake_fetch(routes))
        result = run(server.world_state_from_markets(["politics", "crypto"], 5))
        data = json.loads(result)
        assert set(data["categories"]) == {"politics", "crypto"}
        assert data["categories"]["politics"][0]["slug"] == "politics-m1"
        assert "generated_at" in data

    def test_rejects_unknown_categories(self):
        result = run(server.world_state_from_markets(["cuisine"], 3))
        assert result.startswith("Unknown categories: cuisine.")
        assert "sports" in result

    def test_defaults_to_all_categories(self, monkeypatch):
        seen = []

        async def capture(url):
            if "tag_slug=" in url:
                seen.append(url.split("tag_slug=")[1].split("&")[0])
                return []
            raise AssertionError(url)

        monkeypatch.setattr(polymarket, "fetch_json", capture)
        data = json.loads(run(server.world_state_from_markets(None, 2)))
        assert set(data["categories"]) == set(polymarket.CATEGORY_TAGS)
        assert len(seen) == len(polymarket.CATEGORY_TAGS)

    def test_all_categories_fail(self, monkeypatch):
        monkeypatch.setattr(
            polymarket,
            "fetch_json",
            fake_fetch({"tag_slug=": httpx.ConnectError("down")}),
        )
        result = run(server.world_state_from_markets(["politics"], 2))
        assert result == "Unable to reach Polymarket while building the world state."
