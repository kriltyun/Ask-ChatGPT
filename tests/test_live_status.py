"""Only independently matched ESPN status fields can replace schedule status."""

import unittest

from server.verification import canonical_status, compare, parse_scoreboard


def espn_status(**type_fields):
    return {"type": type_fields}


def schedule_row(**updates):
    return {"game_id": "2026_05_BUF_LA", "season": "2026", "week": "5", "espn": "123",
            "gameday": "2026-10-12", "gametime": "20:15", "home_team": "LA", "away_team": "BUF",
            "stadium": "SoFi Stadium", **updates}


def scoreboard(event_status=None, competition_status=None, **event_fields):
    competition = {"venue": {"fullName": "SoFi Stadium"}, "competitors": [
        {"homeAway": "home", "team": {"abbreviation": "LAR"}},
        {"homeAway": "away", "team": {"abbreviation": "BUF"}},
    ]}
    if competition_status is not None:
        competition["status"] = competition_status
    event = {"id": "123", "date": "2026-10-13T00:15:00Z", "season": {"year": 2026, "type": 2}, "week": {"number": 5}, "competitions": [competition], **event_fields}
    if event_status is not None:
        event["status"] = event_status
    return {"events": [event]}


class CanonicalStatusChecks(unittest.TestCase):
    def test_explicit_pre_and_in_states(self):
        self.assertEqual(canonical_status(espn_status(state="pre", name="STATUS_SCHEDULED", completed=False)),
                         "upcoming")
        self.assertEqual(canonical_status(espn_status(state="in", name="STATUS_IN_PROGRESS", completed=False)),
                         "live")

    def test_completed_requires_explicit_post_state_or_boolean_completion(self):
        for fields in ({"state": "post", "name": "STATUS_FINAL", "completed": True},
                       {"state": "post", "name": "STATUS_FINAL", "completed": False},
                       {"name": "STATUS_FINAL", "completed": True}, {"state": "post"},
                       {"completed": True}, {"state": "post", "name": "STATUS_UNKNOWN"}):
            with self.subTest(fields=fields):
                self.assertEqual(canonical_status(espn_status(**fields)), "completed")
        for fields in ({"name": "STATUS_FINAL"}, {"completed": "true"}, {"completed": 1},
                       {"state": "unknown", "name": "STATUS_UNKNOWN", "completed": False}):
            with self.subTest(fields=fields):
                self.assertIsNone(canonical_status(espn_status(**fields)))

    def test_bare_type_dictionary_is_supported(self):
        self.assertEqual(canonical_status({"state": "in", "name": "STATUS_IN_PROGRESS"}), "live")

    def test_postponed_and_both_cancellation_spellings_override_generic_states(self):
        for name, expected in (("STATUS_POSTPONED", "postponed"), ("STATUS_CANCELED", "canceled"),
                               ("STATUS_CANCELLED", "canceled")):
            for state in ("pre", "post"):
                with self.subTest(name=name, state=state):
                    self.assertEqual(canonical_status(espn_status(name=name, state=state, completed=True)), expected)

    def test_missing_unsupported_or_malformed_status_is_unknown(self):
        for value in (None, {}, [], "Final", 0, {"type": None}, {"type": []},
                      espn_status(state="unknown", name="STATUS_UNKNOWN", completed=False)):
            with self.subTest(value=value):
                self.assertIsNone(canonical_status(value))

    def test_clock_period_and_detail_never_establish_completion(self):
        value = {"clock": 0, "displayClock": "0:00", "period": 4,
                 "type": {"description": "Final", "detail": "Final", "shortDetail": "Final"}}
        self.assertIsNone(canonical_status(value))

    def test_missing_event_status_can_use_explicit_competition_status(self):
        self.assertEqual(canonical_status(None, espn_status(state="in", name="STATUS_IN_PROGRESS")), "live")

    def test_unknown_event_status_falls_back_to_explicit_competition_status(self):
        self.assertEqual(canonical_status(espn_status(state="unknown"), espn_status(state="pre")), "upcoming")

    def test_valid_event_status_takes_precedence_over_competition_status(self):
        self.assertEqual(canonical_status(espn_status(state="in"), espn_status(state="pre")), "live")


class ParsedAndVerifiedStatusChecks(unittest.TestCase):
    def test_parser_preserves_explicit_event_status_without_inferring_from_date(self):
        payload = scoreboard(espn_status(state="pre", name="STATUS_SCHEDULED"), date="2000-01-01T00:00:00Z")
        self.assertEqual(parse_scoreboard(payload)[0]["status"], "upcoming")

    def test_parser_uses_competition_status_when_event_status_is_absent(self):
        payload = scoreboard(competition_status=espn_status(state="in", name="STATUS_IN_PROGRESS"))
        self.assertEqual(parse_scoreboard(payload)[0]["status"], "live")

    def test_parser_does_not_infer_status_from_elapsed_kickoff(self):
        self.assertIsNone(parse_scoreboard(scoreboard(date="2000-01-01T00:00:00Z"))[0]["status"])

    def test_fully_matched_schedule_exposes_independent_status_mapping(self):
        events = parse_scoreboard(scoreboard(espn_status(state="in", name="STATUS_IN_PROGRESS")))
        result = compare([schedule_row()], events)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["independent_status_by_game"], {"2026_05_BUF_LA": "live"})

    def test_venue_conflict_prevents_status_from_becoming_authoritative(self):
        events = parse_scoreboard(scoreboard(espn_status(state="in", name="STATUS_IN_PROGRESS")))
        result = compare([schedule_row(stadium="Different Stadium")], events)
        self.assertEqual(result["status"], "mismatch")
        self.assertNotIn("independent_status_by_game", result)

    def test_opponent_conflict_prevents_status_from_becoming_authoritative(self):
        payload = scoreboard(espn_status(state="post", name="STATUS_FINAL", completed=True))
        payload["events"][0]["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "WSH"
        result = compare([schedule_row()], parse_scoreboard(payload))
        self.assertEqual(result["status"], "mismatch")
        self.assertNotIn("independent_status_by_game", result)

    def test_missing_one_game_prevents_partial_independent_status_mapping(self):
        rows = [schedule_row(), schedule_row(game_id="2026_05_CHI_GB", espn="456", away_team="CHI",
                                            home_team="GB", gameday="2026-10-11", gametime="13:00",
                                            stadium="Lambeau Field")]
        result = compare(rows, parse_scoreboard(scoreboard(espn_status(state="in", name="STATUS_IN_PROGRESS"))))
        self.assertEqual(result["status"], "incomplete")
        self.assertNotIn("independent_status_by_game", result)


if __name__ == "__main__":
    unittest.main()
