"""Hermetic checks for data cutoffs, timezone correctness and price safety."""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from server import data
from server.main import app
from server.ai import AIProviderError
from server.odds import OddsClient, american_implied, normalize_markets


def row(game_id, date, time="13:00", week="1", away="CHI", home="GB", scores=(None, None)):
    return {"game_id": game_id, "season": "2026", "game_type": "REG", "week": week,
            "gameday": date, "gametime": time, "away_team": away, "home_team": home,
            "away_score": "" if scores[0] is None else str(scores[0]),
            "home_score": "" if scores[1] is None else str(scores[1]), "stadium": "Lambeau Field"}


class ScheduleChecks(unittest.TestCase):
    def test_eastern_daylight_and_standard_offsets(self):
        self.assertEqual(data.iso(data.kickoff(row("summer", "2026-10-11"))), "2026-10-11T17:00:00Z")
        self.assertEqual(data.iso(data.kickoff(row("winter", "2026-12-13"))), "2026-12-13T18:00:00Z")
        self.assertIsNone(data.kickoff(row("missing", "2026-10-11", time="")))

    def test_week_selection_uses_chicago_calendar_day(self):
        rows = [row("w4", "2026-10-01", week="4"), row("w5", "2026-10-08", week="5")]
        now = datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc)
        self.assertEqual(data.season_and_week(rows, now=now)[:2], (2026, 5))

    def test_metric_cutoff_excludes_target_and_future_scores(self):
        rows = [row("before", "2026-09-27", scores=(14, 21)),
                row("target", "2026-10-04", scores=(31, 7)),
                row("after", "2026-10-11", scores=(60, 0))]
        metrics = data.team_metrics(rows, "CHI", data.kickoff(rows[1]))
        self.assertEqual(metrics["sample_games"], 1)
        self.assertEqual(metrics["points_per_game"], 14)
        self.assertEqual(metrics["record"], "0-1")
        empty = data.team_metrics(rows, "NYJ", data.kickoff(rows[1]))
        self.assertIsNone(empty["points_per_game"])

    def test_schedule_derives_byes_from_selected_season(self):
        rows = [row("w4", "2026-10-01", week="4", away="KC", home="BUF"),
                row("w5", "2026-10-08", week="5")]
        dataset = {"url": data.SCHEDULE_URL, "retrieved_at": "2026-10-08T12:00:00Z", "rows": rows}
        with patch("server.main.schedule_dataset", return_value=(dataset, rows)), patch("server.main.verification_client.check", return_value={"status": "unavailable"}):
            result = TestClient(app).get("/api/schedule?season=2026&week=5").json()
        self.assertEqual(result["byes"], ["BUF", "KC"])
        self.assertIsNone(result["games"][0]["projections"])


class PlayerChecks(unittest.TestCase):
    def test_player_stats_require_completed_game_before_target(self):
        schedule_rows = [row("before", "2026-09-27", scores=(14, 21)),
                         row("target", "2026-10-04", scores=(31, 7)),
                         row("future", "2026-10-11")]
        stat_rows = [{"player_id": "one", "player_display_name": "Sourced Player", "position": "QB",
                      "team": "CHI", "season_type": "REG", "week": str(index + 1),
                      "game_id": game_id, "passing_yards": yards}
                     for index, (game_id, yards) in enumerate((("before", "200"), ("target", "400"), ("future", "999")))]
        roster_rows = [{"gsis_id": "two", "full_name": "Roster Player", "team": "GB",
                        "position": "WR", "week": "1"}]

        def fake_csv(url, **kwargs):
            return {"url": url, "retrieved_at": "2026-10-08T12:00:00Z", "status": "source_confirmed",
                    "rows": stat_rows if "stats_player" in url else roster_rows}

        with patch.object(data.store, "csv", side_effect=fake_csv):
            result = data.player_data(2026, {"rows": schedule_rows}, schedule_rows[1])
        players = {p["id"]: p for p in result["players"]}
        self.assertEqual(players["one"]["stats"]["passing_yards"], 200)
        self.assertEqual(players["one"]["sample_games"], 1)
        self.assertIsNone(players["two"]["stats"])
        self.assertIsNone(players["one"]["projections"])


class CacheChecks(unittest.TestCase):
    def test_failed_early_manual_refresh_stays_stale_during_cached_reuse(self):
        url = "https://example.invalid/source.csv"
        with tempfile.TemporaryDirectory() as directory:
            cache = data.DataStore(Path(directory))
            with patch("server.data.httpx.get", return_value=httpx.Response(200, text="season,value\n2026,real\n")):
                cache.csv(url)
            with patch("server.data.httpx.get", side_effect=httpx.ConnectError("offline")) as request:
                cache.csv(url, force=True)
                result = cache.csv(url)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(result["status"], "stale")
            self.assertEqual(cache.memory[url]["status"], "stale")
            self.assertIsNotNone(cache.memory[url]["error"])

    def test_failure_uses_labeled_source_cache_without_examples(self):
        url = "https://example.invalid/source.csv"
        with tempfile.TemporaryDirectory() as directory:
            cache = data.DataStore(Path(directory))
            good = httpx.Response(200, text="season,value\n2026,real\n")
            with patch("server.data.httpx.get", return_value=good):
                first = cache.csv(url, ttl=0)
            with patch("server.data.httpx.get", side_effect=httpx.ConnectError("source unavailable")):
                second = cache.csv(url, ttl=0)
            self.assertEqual(second["status"], "stale")
            self.assertEqual(second["rows"], first["rows"])
            self.assertIsNotNone(second["error"])
            with patch("server.data.httpx.get", side_effect=httpx.ConnectError("offline")):
                with self.assertRaises(data.SourceError):
                    cache.csv("https://example.invalid/other.csv", ttl=0)


class APIIntegrationChecks(unittest.TestCase):
    def setUp(self):
        self.row = row("selected", "2026-10-11", week="5")
        self.dataset = {"rows": [self.row], "url": data.SCHEDULE_URL,
                        "retrieved_at": "2026-10-08T12:00:00Z", "status": "source_confirmed"}
        self.players = {"players": [], "source": {"name": "nflverse", "url": "https://example.invalid/stats"},
                        "status": "available", "error": None}
        self.odds = {"markets": [], "props": [], "source": {"name": "The Odds API"},
                     "status": "disconnected", "error": "No credential configured."}
        verifier = patch("server.main.verification_client.check", return_value={"status": "unavailable"})
        verifier.start()
        self.addCleanup(verifier.stop)

    def test_week_player_endpoint_uses_first_kickoff_cutoff(self):
        second = row("later", "2026-10-12", week="5")
        with patch("server.main.schedule_dataset", return_value=(self.dataset, [self.row, second])), patch("server.main.player_data", return_value=dict(self.players)) as call:
            response = TestClient(app).get("/api/players?season=2026&week=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(call.call_args.kwargs["cutoff_override"], data.kickoff(self.row))
        self.assertEqual(call.call_args.kwargs["roster_week"], 5)

    def test_analysis_provider_failure_keeps_factual_template(self):
        with patch("server.main.find_game", return_value=(self.row, self.dataset, [self.row])), patch("server.main.player_data", return_value=self.players), patch("server.main.odds_client.game", return_value=self.odds), patch("server.main.generate_ai_report", side_effect=AIProviderError("authentication")):
            response = TestClient(app).post("/api/analysis", json={"game_id": "selected", "season": 2026})
        report = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(report["kind"], "template")
        self.assertEqual(report["ai_status"], "unavailable")
        self.assertEqual(report["model"]["status"], "unavailable")
        self.assertTrue(any(section["heading"] == "Parlay dependencies" for section in report["sections"]))

    def test_ai_narration_never_changes_prediction_model_status(self):
        generated = {"kind": "ai", "sections": [], "ai_status": "connected"}
        with patch("server.main.find_game", return_value=(self.row, self.dataset, [self.row])), patch("server.main.player_data", return_value=self.players), patch("server.main.odds_client.game", return_value=self.odds), patch("server.main.generate_ai_report", return_value=generated) as call:
            response = TestClient(app).post("/api/analysis", json={"game_id": "selected", "season": 2026})
        report = response.json()
        self.assertEqual(report["kind"], "ai")
        self.assertEqual(report["model"]["status"], "unavailable")
        self.assertIsNone(call.call_args.args[0]["weather"])
        self.assertIsNone(call.call_args.args[0]["injuries"])

    def test_status_reports_initial_source_failure_as_unavailable(self):
        with patch.object(data.store, "memory", {}), patch.object(data.store, "failures", {data.SCHEDULE_URL: {"error": "Source unavailable"}}):
            response = TestClient(app).get("/api/status")
        connection = next(connection for connection in response.json()["connections"] if connection["id"] == "schedule")
        self.assertEqual(connection["status"], "unavailable")
        self.assertEqual(connection["detail"], "Source unavailable")


class OddsChecks(unittest.TestCase):
    def test_401_known_quota_error_is_sanitized_and_uses_quota_backoff(self):
        client = OddsClient()
        response = httpx.Response(401, json={"error_code": "OUT_OF_USAGE_CREDITS", "message": "dummy-test-credential"})
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy-test-credential"}), patch("server.odds.httpx.get", return_value=response), patch("server.odds.time.time", return_value=1000):
            result = client.request("/odds", ("h2h",))
        self.assertIn("credits are exhausted", result["error"])
        self.assertNotIn("dummy-test-credential", str(result))
        self.assertEqual(client.retry_after, 1300)

    def test_expired_provider_event_has_precise_safe_message(self):
        client = OddsClient()
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy"}), patch("server.odds.httpx.get", return_value=httpx.Response(404)):
            result = client.request("/events/missing/odds", ("player_anytime_td",))
        self.assertEqual(result["error"], "This sportsbook event is missing or has expired.")

    def test_past_kickoff_prices_require_explicit_independently_verified_live_status(self):
        event = {"id": "provider-a", "home_team": "Green Bay Packers", "away_team": "Chicago Bears",
                 "commence_time": "2020-10-11T17:00:00Z", "bookmakers": []}
        client = OddsClient()
        game = row("past", "2020-10-11")
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy"}), patch("server.odds.httpx.get", return_value=httpx.Response(200, json=[event])) as request:
            unknown = client.game(game, include_props=False)
            request.assert_not_called()
            live = client.game(game, include_props=False, verified_status="live")
        self.assertIsNone(unknown["event_id"])
        self.assertEqual(live["event_id"], "provider-a")

    def test_same_team_provider_event_requires_kickoff_within_sixty_seconds(self):
        event = {"id": "provider-a", "home_team": "Green Bay Packers", "away_team": "Chicago Bears",
                 "commence_time": "2099-10-11T17:01:01Z", "bookmakers": []}
        client = OddsClient()
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy"}), patch("server.odds.httpx.get", return_value=httpx.Response(200, json=[event])):
            result = client.game(row("a", "2099-10-11"), include_props=False)
        self.assertIsNone(result["event_id"])
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["markets"], [])

    def test_implied_probability_is_exact_american_conversion(self):
        self.assertAlmostEqual(american_implied(-110), 0.52381, places=6)
        self.assertEqual(american_implied(150), 0.4)
        self.assertIsNone(american_implied(0))

    def test_market_preserves_player_threshold_book_and_timestamp(self):
        event = {"bookmakers": [{"key": "draftkings", "title": "DraftKings", "last_update": "2026-10-08T12:00:00Z",
                  "markets": [{"key": "player_pass_yds", "last_update": "2026-10-08T12:01:00Z",
                    "outcomes": [{"name": "Over", "description": "Real Player", "point": 249.5, "price": -110}]}]},
                 {"key": "other", "markets": [{"key": "h2h", "outcomes": []}]}]}
        normalized = normalize_markets(event, "2026-10-08T12:02:00Z")
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["updated_at"], "2026-10-08T12:01:00Z")
        self.assertEqual(normalized[0]["outcomes"][0]["point"], 249.5)
        self.assertEqual(normalized[0]["outcomes"][0]["description"], "Real Player")

    def test_provider_errors_never_return_secret_url_or_body(self):
        client = OddsClient()
        marker = "dummy-test-credential"
        response = httpx.Response(401, text=f"apiKey={marker}")
        with patch.dict(os.environ, {"ODDS_API_KEY": marker}), patch("server.odds.httpx.get", return_value=response):
            result = client.request("/odds", ("h2h",))
        self.assertNotIn(marker, str(result))
        self.assertNotIn("apiKey", str(result))
        self.assertEqual(result["status"], "unavailable")

    def test_missing_credential_never_calls_network(self):
        client = OddsClient()
        with patch.dict(os.environ, {}, clear=True), patch("server.odds.httpx.get") as request:
            result = client.game(row("upcoming", "2099-10-11"))
        request.assert_not_called()
        self.assertEqual(result["status"], "disconnected")
        self.assertEqual(result["markets"], [])

    def test_featured_prices_reuse_one_provider_request_without_props(self):
        client = OddsClient()
        future_rows = [row("a", "2099-10-11"), row("b", "2099-10-11", away="KC", home="BUF")]
        payload = [{"id": "provider-a", "home_team": "Green Bay Packers", "away_team": "Chicago Bears",
                    "commence_time": "2099-10-11T17:00:00Z", "bookmakers": []},
                   {"id": "provider-b", "home_team": "Buffalo Bills", "away_team": "Kansas City Chiefs",
                    "commence_time": "2099-10-11T17:00:00Z", "bookmakers": []}]
        response = httpx.Response(200, json=payload)
        with patch.dict(os.environ, {"ODDS_API_KEY": "dummy"}), patch("server.odds.httpx.get", return_value=response) as request:
            quotes = [client.game(game, include_props=False) for game in future_rows]
        self.assertEqual(request.call_count, 1)
        self.assertEqual([q["event_id"] for q in quotes], ["provider-a", "provider-b"])
        self.assertTrue(all(q["props_status"] == "not_requested" for q in quotes))


if __name__ == "__main__":
    unittest.main()
