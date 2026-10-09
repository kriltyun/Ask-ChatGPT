"""Market queries validate documented identifiers before any sportsbook request."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import odds
from server.main import app


class MarketRouteChecks(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.row = {"game_id": "2026_05_CHI_GB", "season": "2026", "week": "5"}
        self.quote = {"markets": [], "props": [], "status": "disconnected", "error": None}
        for target, result in (("server.main.find_game", (self.row, {}, [self.row])),
                               ("server.main.sourced_game", {"status": "upcoming"})):
            stub = patch(target, return_value=result)
            stub.start()
            self.addCleanup(stub.stop)

    def test_default_market_request_preserves_documented_core_selection(self):
        with patch("server.main.odds_client.game", return_value=self.quote) as request:
            response = self.client.get("/api/odds/2026_05_CHI_GB?season=2026")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.quote)
        self.assertIsNone(request.call_args.kwargs.get("requested_markets"))

    def test_specific_market_request_deduplicates_without_featured_keys_in_props(self):
        with patch("server.main.odds_client.game", return_value=self.quote) as request:
            response = self.client.get("/api/odds/2026_05_CHI_GB",
                                       params={"markets": " h2h,player_reception_yds,player_pass_tds,player_reception_yds,totals "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.call_args.kwargs["requested_markets"],
                         ("player_reception_yds", "player_pass_tds"))

    def test_featured_only_request_does_not_request_event_props(self):
        with patch("server.main.odds_client.game", return_value=self.quote) as request:
            response = self.client.get("/api/odds/2026_05_CHI_GB?markets=h2h,spreads,totals")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.call_args.kwargs["requested_markets"], ())

    def test_unsupported_and_empty_market_queries_do_not_reach_schedule_or_provider(self):
        for markets in ("", " ", ",", "player_receptions,", "player_receptions,,player_pass_yds",
                        "unrecognized_market", "PLAYER_RECEPTIONS", "player_receptions,unrecognized_market"):
            with self.subTest(markets=markets), patch("server.main.find_game") as schedule, \
                    patch("server.main.odds_client.game") as request:
                response = self.client.get("/api/odds/2026_05_CHI_GB", params={"markets": markets})
                self.assertEqual(response.status_code, 400)
                schedule.assert_not_called()
                request.assert_not_called()

    def test_all_configured_prop_markets_are_accepted(self):
        for key in odds.SUPPORTED_PROP_MARKETS:
            with self.subTest(market=key), patch("server.main.odds_client.game", return_value=self.quote) as request:
                response = self.client.get("/api/odds/2026_05_CHI_GB", params={"markets": key})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(request.call_args.kwargs["requested_markets"], (key,))

    def test_market_catalog_exposes_configuration_without_provider_or_credentials(self):
        with patch("server.main.odds_client.game") as request:
            response = self.client.get("/api/markets")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), odds.MARKET_CATALOG)
        request.assert_not_called()
        self.assertNotIn("apiKey", response.text)
        self.assertNotIn("ODDS_API_KEY", response.text)


if __name__ == "__main__":
    unittest.main()
