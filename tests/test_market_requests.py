"""Market selection must control provider requests and their cache scope."""

import os
import unittest
from unittest.mock import patch

import httpx

from server.odds import OddsClient, PROP_MARKETS


class SelectedMarketRequests(unittest.TestCase):
    def setUp(self):
        self.client = OddsClient()
        self.game = {"game_id": "2099_05_CHI_GB", "gameday": "2099-10-11",
                     "gametime": "13:00", "away_team": "CHI", "home_team": "GB"}
        self.event = {"id": "verified-event", "home_team": "Green Bay Packers",
                      "away_team": "Chicago Bears", "commence_time": "2099-10-11T17:00:00Z",
                      "bookmakers": [{"key": "fanduel", "title": "FanDuel",
                          "markets": [{"key": "h2h", "last_update": "2099-10-11T16:00:00Z",
                                       "outcomes": [{"name": "Green Bay Packers", "price": -120}]}]}]}

    def provider_response(self, url, *, params, timeout):
        if url.endswith("/events/verified-event/odds"):
            return httpx.Response(200, json={**self.event, "bookmakers": [{"key": "fanduel",
                "title": "FanDuel", "markets": [{"key": params["markets"],
                "last_update": "2099-10-11T16:00:00Z", "outcomes": [
                    {"name": "Over", "description": "Sourced Kicker", "point": 1.5, "price": -110}]}]}]})
        return httpx.Response(200, json=[self.event])

    def test_optional_market_requests_only_that_key_and_keeps_exact_quote(self):
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy-test-credential"}), \
                patch("server.odds.httpx.get", side_effect=self.provider_response) as request:
            quote = self.client.game(self.game, requested_markets=("player_field_goals",))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.kwargs["params"]["markets"], "player_field_goals")
        self.assertEqual(quote["props_max_request_cost"], 1)
        self.assertEqual(quote["props_status"], "connected")
        self.assertEqual(quote["props"][0]["market"], "player_field_goals")
        self.assertEqual(quote["props"][0]["outcomes"][0]["point"], 1.5)

    def test_same_market_reuses_cache_but_different_market_fetches_own_prices(self):
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy-test-credential"}), \
                patch("server.odds.httpx.get", side_effect=self.provider_response) as request:
            for key in ("player_field_goals", "player_field_goals", "player_pats"):
                quote = self.client.game(self.game, requested_markets=(key,))
                self.assertEqual(quote["props"][0]["market"], key)
        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.kwargs["params"]["markets"] for call in request.call_args_list],
                         ["h2h,spreads,totals", "player_field_goals", "player_pats"])

    def test_empty_market_selection_never_fetches_default_player_markets(self):
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy-test-credential"}), \
                patch("server.odds.httpx.get", side_effect=self.provider_response) as request:
            quote = self.client.game(self.game, requested_markets=())
        self.assertEqual(request.call_count, 1)
        self.assertEqual(quote["props_status"], "not_requested")
        self.assertEqual(quote["props_max_request_cost"], 0)
        self.assertEqual(quote["props"], [])

    def test_invalid_market_never_uses_provider(self):
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy-test-credential"}), \
                patch("server.odds.httpx.get") as request:
            quote = self.client.game(self.game, requested_markets=("unknown-market",))
        request.assert_not_called()
        self.assertEqual(quote["status"], "unavailable")

    def test_defaults_and_duplicate_selection_have_bounded_request_cost(self):
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy-test-credential"}), \
                patch.object(self.client, "request", return_value={"status": "connected",
                    "error": None, "retrieved_at": "2099-10-11T16:00:00Z", "payload": [self.event]}) as request:
            defaults = self.client.game(self.game)
            self.assertEqual(request.call_args.args[1], PROP_MARKETS)
            deduplicated = self.client.game(self.game,
                requested_markets=("player_field_goals", "player_field_goals", "player_pats"))
            self.assertEqual(request.call_args.args[1], ("player_field_goals", "player_pats"))
        self.assertEqual(defaults["props_max_request_cost"], 15)
        self.assertEqual(deduplicated["props_max_request_cost"], 2)


if __name__ == "__main__":
    unittest.main()
