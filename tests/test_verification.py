"""Independent-source comparisons and blocked-network retry behavior."""

import unittest
from unittest.mock import patch

import httpx

from server.verification import VerificationClient, compare, parse_scoreboard, verification_label


def schedule_row(**updates):
    return {"game_id": "2026_05_BUF_LA", "season": "2026", "week": "5", "espn": "123",
            "gameday": "2026-10-12", "gametime": "20:15", "home_team": "LA", "away_team": "BUF",
            "stadium": "SoFi Stadium", **updates}


def scoreboard(**updates):
    event = {"id": "123", "date": "2026-10-13T00:15:00Z", "season": {"year": 2026, "type": 2}, "week": {"number": 5}, "competitions": [{
        "venue": {"fullName": "SoFi Stadium"}, "competitors": [
            {"homeAway": "home", "team": {"abbreviation": "LAR"}},
            {"homeAway": "away", "team": {"abbreviation": "BUF"}},
        ]}], **updates}
    return {"events": [event]}


class VerificationChecks(unittest.TestCase):
    def test_season_and_week_must_match_even_when_teams_and_kickoff_match(self):
        result = compare([schedule_row()], parse_scoreboard(scoreboard(season={"year": 2025, "type": 2}, week={"number": 6})))
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["mismatches"][0]["fields"], ["season", "week"])
        self.assertTrue(result["material_mismatch"])

    def test_missing_season_or_week_metadata_cannot_establish_verification(self):
        for changes in ({"season": None}, {"week": None}, {"week": {"number": True}}):
            with self.subTest(changes=changes):
                result = compare([schedule_row()], parse_scoreboard(scoreboard(**changes)))
                self.assertEqual(result["status"], "incomplete")
                self.assertNotIn("independent_status_by_game", result)

    def test_all_required_fields_and_normalized_venue_confirm_schedule(self):
        events = parse_scoreboard(scoreboard())
        result = compare([schedule_row(stadium="Sofi—Stadium")], events)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["checked_games"], 1)
        self.assertEqual(result["venue_checks"], 1)

    def test_explicit_id_opponent_and_kickoff_mismatch_is_material(self):
        payload = scoreboard(date="2026-10-13T01:15:00Z")
        payload["events"][0]["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "WSH"
        result = compare([schedule_row()], parse_scoreboard(payload))
        self.assertEqual(result["status"], "mismatch")
        self.assertTrue(result["material_mismatch"])
        self.assertEqual(result["mismatches"][0]["fields"], ["opponents", "kickoff"])
        self.assertEqual(result["mismatches"][0]["independent"]["home"], "WAS")

    def test_kickoff_tolerance_is_exactly_sixty_seconds(self):
        allowed = compare([schedule_row()], parse_scoreboard(scoreboard(date="2026-10-13T00:16:00Z")))
        changed = compare([schedule_row()], parse_scoreboard(scoreboard(date="2026-10-13T00:16:01Z")))
        self.assertEqual(allowed["status"], "verified")
        self.assertEqual(changed["status"], "mismatch")
        self.assertTrue(changed["material_mismatch"])

    def test_venue_conflict_is_warning_without_material_opponent_conflict(self):
        result = compare([schedule_row(stadium="Another Stadium")], parse_scoreboard(scoreboard()))
        self.assertEqual(result["status"], "mismatch")
        self.assertFalse(result["material_mismatch"])
        self.assertIn("warning", verification_label(result).lower())

    def test_missing_or_unparseable_fields_cannot_establish_verification(self):
        self.assertIsNone(parse_scoreboard({"unexpected": []}))
        malformed = scoreboard(date="2026-10-13T00:15:00")  # No timezone.
        result = compare([schedule_row()], parse_scoreboard(malformed))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["missing_games"], ["2026_05_BUF_LA"])

    def test_one_cached_request_covers_multiple_games_and_recompares_current_source(self):
        client = VerificationClient()
        with patch("server.verification.httpx.get", return_value=httpx.Response(200, json=scoreboard())) as request:
            first = client.check([schedule_row()], 2026, 5)
            second = client.check([schedule_row(gametime="21:15")], 2026, 5)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(first["status"], "verified")
        self.assertEqual(second["status"], "mismatch")

    def test_blocked_access_backoff_never_claims_verified_and_force_retry_recovers(self):
        client = VerificationClient()
        with patch("server.verification.httpx.get", return_value=httpx.Response(403, text="Blocked")) as request:
            for _ in range(15):
                result = client.check([schedule_row()], 2026, 5)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["detail"], "Independent ESPN cross-check unavailable")
        self.assertNotIn("Blocked", str(result))
        with patch("server.verification.httpx.get", return_value=httpx.Response(200, json=scoreboard())) as request:
            refreshed = client.check([schedule_row()], 2026, 5, force=True)
        request.assert_called_once()
        self.assertEqual(refreshed["status"], "verified")

    def test_distinct_single_dates_and_duplicate_event_ids_use_one_week_cache(self):
        client = VerificationClient()
        rows = [schedule_row(), schedule_row(game_id="other", gameday="2026-10-11"),
                schedule_row(game_id="same-day", gameday="2026-10-11")]
        with patch("server.verification.httpx.get", return_value=httpx.Response(200, json=scoreboard())) as request:
            client.check(rows, 2026, 5)
            client.check(rows, 2026, 5)
        self.assertEqual(request.call_count, 2)
        self.assertEqual([call.kwargs["params"]["dates"] for call in request.call_args_list], ["20261011", "20261012"])
        self.assertEqual(len(next(iter(client.cache.values()))["events"]), 1)

    def test_blocked_first_day_short_circuits_remaining_distinct_dates(self):
        client = VerificationClient()
        rows = [schedule_row(), schedule_row(game_id="other", gameday="2026-10-11")]
        with patch("server.verification.httpx.get", return_value=httpx.Response(403)) as request:
            result = client.check(rows, 2026, 5)
        request.assert_called_once()
        self.assertEqual(result["status"], "unavailable")

    def test_failed_later_day_does_not_verify_partial_success(self):
        client = VerificationClient()
        rows = [schedule_row(), schedule_row(game_id="other", gameday="2026-10-11")]
        responses = [httpx.Response(200, json=scoreboard()), httpx.Response(400)]
        with patch("server.verification.httpx.get", side_effect=responses):
            result = client.check(rows, 2026, 5)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["checked_games"], 0)


if __name__ == "__main__":
    unittest.main()
