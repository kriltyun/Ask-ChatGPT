import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from server import data


class ExtendedStatisticsChecks(unittest.TestCase):
    def aggregate(self, stats, roster=None):
        games = []
        for week in (1, 2, 5):
            games.append({"game_id": f"g{week}", "season": "2026", "week": str(week),
                          "game_type": "REG", "gameday": {1: "2026-09-10", 2: "2026-09-17", 5: "2026-10-11"}[week],
                          "gametime": "13:00", "home_team": "SEA", "away_team": "ARI",
                          "home_score": "20", "away_score": "10"})
        schedule = {"rows": games, "url": data.SCHEDULE_URL, "retrieved_at": "2026-10-08T12:00:00Z", "status": "source_confirmed"}
        def source(url, **kwargs):
            return {"rows": stats if "stats_player" in url else roster or [], "url": url,
                    "retrieved_at": "2026-10-08T12:00:00Z", "status": "source_confirmed"}
        with patch("server.data.store.csv", side_effect=source), patch("server.data.utc_now", return_value=datetime(2026, 10, 9, tzinfo=timezone.utc)):
            return data.player_data(2026, schedule, cutoff_override=datetime(2026, 10, 8, tzinfo=timezone.utc), roster_week=5)

    def stat(self, pid, position, week, **values):
        return {"player_id": pid, "player_display_name": pid, "team": "SEA", "position": position,
                "game_id": f"g{week}", "season_type": "REG", "week": str(week), **values}

    def test_kicker_counts_sum_completed_games_and_preserve_actual_sample(self):
        payload = self.aggregate([self.stat("Kicker", "K", 1, fg_made="3", fg_att="4", pat_made="2", pat_att="2"),
                                  self.stat("Kicker", "K", 2, fg_made="2", fg_att="2", pat_made="1", pat_att="1"),
                                  self.stat("Kicker", "K", 5, fg_made="99", fg_att="99")])
        kicker = payload["players"][0]
        self.assertEqual(kicker["position"], "K")
        self.assertEqual(kicker["stats"]["fg_made"], 5)
        self.assertEqual(kicker["stats"]["fg_att"], 6)
        self.assertEqual(kicker["stats"]["pat_made"], 3)
        self.assertEqual(kicker["sample_games"], 2)

    def test_defensive_counts_and_fractional_sacks_remain_distinct(self):
        payload = self.aggregate([self.stat("Defender", "DE", 1, def_sacks="0.5", def_tackles_solo="5", def_tackles_with_assist="1", def_tackle_assists="2", def_interceptions="0"),
                                  self.stat("Defender", "DE", 2, def_sacks="1", def_tackles_solo="2", def_tackles_with_assist="0", def_tackle_assists="2", def_interceptions="1")])
        stats = payload["players"][0]["stats"]
        self.assertEqual(stats["def_sacks"], 1.5)
        self.assertEqual(stats["def_tackles_solo"], 7)
        self.assertEqual(stats["def_tackles_with_assist"], 1)
        self.assertEqual(stats["def_tackle_assists"], 4)
        self.assertEqual(stats["def_interceptions"], 1)

    def test_missing_extended_values_are_not_zero_filled(self):
        stats = self.aggregate([self.stat("Kicker", "K", 1, fg_made="0")])["players"][0]["stats"]
        self.assertEqual(stats["fg_made"], 0)
        self.assertIsNone(stats["fg_att"])
        self.assertIsNone(stats["pat_made"])
        self.assertIsNone(stats["def_sacks"])

    def test_roster_only_kicker_stays_without_statistics(self):
        roster = [{"gsis_id": "Kicker", "full_name": "Kicker", "team": "SEA", "position": "K", "status": "ACT", "week": "5"}]
        player = self.aggregate([], roster)["players"][0]
        self.assertEqual(player["sample_games"], 0)
        self.assertIsNone(player["stats"])

    def test_touchdown_categories_and_fullback_contributors_are_preserved(self):
        record = self.stat("Scorer", "FB", 1, passing_tds="5", rushing_tds="1", receiving_tds="1", special_teams_tds="1", def_tds="1", fumble_recovery_tds="1")
        player = self.aggregate([record])["players"][0]
        self.assertEqual(player["position"], "FB")
        self.assertEqual([player["stats"][key] for key in ("rushing_tds", "receiving_tds", "special_teams_tds", "def_tds", "fumble_recovery_tds")], [1, 1, 1, 1, 1])
        self.assertEqual(player["stats"]["passing_tds"], 5)


if __name__ == "__main__":
    unittest.main()
