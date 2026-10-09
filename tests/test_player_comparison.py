"""Prior-season production stays independent of the selected current-week sample."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import data
from server.main import app


NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def game(game_id, season, week, date, *, completed=True, game_type="REG"):
    return {"game_id": game_id, "season": str(season), "week": str(week), "game_type": game_type,
            "gameday": date, "gametime": "13:00", "home_team": "GB", "away_team": "CHI",
            "home_score": "24" if completed else "", "away_score": "17" if completed else ""}


def statistic(game_id, week, yards, *, player="one", season_type="REG"):
    return {"game_id": game_id, "week": str(week), "season_type": season_type,
            "player_id": player, "player_display_name": f"Recorded {player}", "position": "WR",
            "team": "CHI", "receiving_yards": str(yards), "receptions": "5"}


class PlayerComparisonChecks(unittest.TestCase):
    def setUp(self):
        self.schedule_rows = [game("current_before", 2026, 4, "2026-10-01"),
                              game("current_target", 2026, 5, "2026-10-08"),
                              game("prior_early", 2025, 1, "2025-09-07"),
                              game("prior_later", 2025, 6, "2025-10-12"),
                              game("prior_final", 2025, 18, "2026-01-04"),
                              game("prior_post", 2025, 19, "2026-01-11", game_type="WC"),
                              game("prior_uncompleted", 2025, 18, "2026-01-04", completed=False),
                              game("prior_future", 2025, 18, "2027-01-03")]
        self.dataset = {"rows": self.schedule_rows, "url": data.SCHEDULE_URL,
                        "retrieved_at": data.iso(NOW), "status": "source_confirmed"}
        self.current_stats = [statistic("current_before", 4, 100), statistic("current_target", 5, 999)]
        self.previous_stats = [statistic("prior_early", 1, 80), statistic("prior_later", 6, 120),
                               statistic("prior_final", 18, 200), statistic("prior_final", 18, 60, player="prior_only"),
                               statistic("prior_post", 19, 999), statistic("prior_uncompleted", 18, 999),
                               statistic("prior_future", 18, 999),
                               statistic("prior_early", 1, 999, season_type="POST")]
        self.rosters = {2026: [{"gsis_id": "one", "full_name": "Recorded one", "position": "WR",
                               "team": "CHI", "week": "4", "status": "ACT"}],
                        2025: [{"gsis_id": "one", "full_name": "Recorded one", "position": "WR",
                               "team": "CHI", "week": "1", "status": "ACT"},
                               {"gsis_id": "one", "full_name": "Recorded one", "position": "WR",
                                "team": "GB", "week": "18", "status": "ACT"},
                               {"gsis_id": "one", "full_name": "Future roster one", "position": "WR",
                                "team": "KC", "week": "19", "status": "ACT"}]}
        schedule = patch("server.main.schedule_dataset", return_value=(self.dataset, data.regular_rows(self.dataset)))
        schedule.start()
        self.addCleanup(schedule.stop)
        clock = patch("server.data.utc_now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        api_clock = patch("server.main.utc_now", return_value=NOW)
        api_clock.start()
        self.addCleanup(api_clock.stop)

    def csv(self, url, **kwargs):
        season = 2025 if "2025" in url else 2026
        rows = ((self.previous_stats if season == 2025 else self.current_stats) if "stats_player" in url
                else self.rosters[season])
        return {"url": url, "retrieved_at": data.iso(NOW), "status": "source_confirmed", "rows": rows}

    def request(self):
        return TestClient(app).get("/api/players?season=2026&week=5&include_previous=true")

    def test_prior_sample_covers_full_regular_season_without_current_week_truncation(self):
        with patch.object(data.store, "csv", side_effect=self.csv):
            response = self.request()
        self.assertEqual(response.status_code, 200)
        result = response.json()
        current = {player["id"]: player for player in result["players"]}
        previous = {player["id"]: player for player in result["previous_players"]}
        self.assertEqual(current["one"]["stats"]["receiving_yards"], 100)
        self.assertEqual(result["stats_through_week"], 4)
        self.assertEqual(previous["one"]["stats"]["receiving_yards"], 400)
        self.assertEqual(previous["one"]["sample_games"], 3)
        self.assertEqual(previous["one"]["team"], "GB")
        self.assertEqual(previous["prior_only"]["stats"]["receiving_yards"], 60)
        self.assertNotIn("prior_only", current)
        self.assertEqual(result["previous_season"], 2025)
        self.assertEqual(result["previous_stats_through_week"], 18)
        self.assertEqual(result["previous_status"], "available")
        self.assertIsNone(result["previous_error"])
        self.assertEqual(result["previous_source"]["cutoff_date"], data.iso(data.kickoff(self.schedule_rows[1])))
        self.assertIn("stats_player_week_2025.csv", result["previous_source"]["url"])

    def test_missing_prior_sources_preserves_current_statistics(self):
        def unavailable_previous(url, **kwargs):
            if "2025" in url:
                raise data.SourceError("Previous-season source could not be reached.")
            return self.csv(url, **kwargs)

        with patch.object(data.store, "csv", side_effect=unavailable_previous):
            result = self.request().json()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["players"][0]["stats"]["receiving_yards"], 100)
        self.assertEqual(result["previous_players"], [])
        self.assertEqual(result["previous_status"], "unavailable")
        self.assertEqual(result["previous_source"]["status"], "unavailable")
        self.assertIsNone(result["previous_stats_through_week"])
        self.assertIn("could not be reached", result["previous_error"])

    def test_prior_roster_alone_does_not_claim_statistical_availability(self):
        def unavailable_previous_statistics(url, **kwargs):
            if "stats_player_week_2025" in url:
                raise data.SourceError("Previous-season statistics are unavailable.")
            return self.csv(url, **kwargs)

        with patch.object(data.store, "csv", side_effect=unavailable_previous_statistics):
            result = self.request().json()
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["previous_players"])
        self.assertTrue(all(player["stats"] is None for player in result["previous_players"]))
        self.assertEqual(result["previous_status"], "unavailable")
        self.assertEqual(result["previous_source"]["status"], "unavailable")
        self.assertIn("stats_player_week_2025.csv", result["previous_source"]["url"])

    def test_default_endpoint_does_not_fetch_prior_season_or_add_fields(self):
        current = {"season": 2026, "players": [], "source": {}, "stats_through_week": None,
                   "status": "unavailable", "error": None}
        with patch("server.main.player_data", return_value=current.copy()) as call:
            response = TestClient(app).get("/api/players?season=2026")
        self.assertEqual(response.json(), current)
        call.assert_called_once_with(2026, self.dataset)

    def test_future_selected_week_uses_retrieval_time_for_comparison(self):
        future = game("future_current", 2026, 18, "2027-01-03", completed=False)
        rows = data.regular_rows(self.dataset) + [future]
        current = {"players": [], "source": {}, "status": "unavailable", "error": None}
        prior = {"players": [{"stats": {"receiving_yards": 400}, "sample_games": 3}],
                 "source": {}, "status": "available", "error": None, "stats_through_week": 18}
        with patch("server.main.schedule_dataset", return_value=(self.dataset, rows)), \
                patch("server.main.player_data", side_effect=[current, prior]) as call:
            response = TestClient(app).get("/api/players?season=2026&week=18&include_previous=true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(call.call_args_list[1].kwargs["cutoff_override"], NOW)
        self.assertEqual(call.call_args_list[1].kwargs["roster_week"], 18)

    def test_prior_season_can_precede_public_endpoint_lower_bound(self):
        row = game("current_2024", 2024, 5, "2024-10-03")
        dataset = {**self.dataset, "rows": [row]}
        current = {"players": [], "source": {}, "status": "unavailable", "error": None}
        with patch("server.main.schedule_dataset", return_value=(dataset, [row])), \
                patch("server.main.player_data", side_effect=[current.copy(), current.copy()]) as call:
            response = TestClient(app).get("/api/players?season=2024&week=5&include_previous=true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["previous_season"], 2023)
        self.assertEqual(call.call_args_list[1].args[0], 2023)

    def test_raised_prior_source_error_is_labeled_without_losing_current_response(self):
        current = {"players": [{"id": "current", "stats": {"receiving_yards": 100}}],
                   "source": {}, "status": "available", "error": None}
        with patch("server.main.player_data", side_effect=[current, data.SourceError("Prior source unavailable.")]):
            response = self.request()
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["players"][0]["id"], "current")
        self.assertEqual(result["previous_status"], "unavailable")
        self.assertEqual(result["previous_error"], "Prior source unavailable.")


if __name__ == "__main__":
    unittest.main()
