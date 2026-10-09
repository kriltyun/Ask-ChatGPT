"""Sourced NFL data, cached locally without substituting example fixtures."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = Path(os.environ.get("NFL_CACHE_DIR", ROOT / ".cache" / "nfl"))
SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
TEAMS_URL = "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"
VERIFICATION = "Source confirmed · independent cross-check unavailable"
EASTERN = ZoneInfo("America/New_York")
CENTRAL = ZoneInfo("America/Chicago")

# nflverse teams_colors_logos.csv names. Schedule's LA abbreviation means Rams.
TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def number(value: object) -> float | int | None:
    try:
        result = float(value)  # type: ignore[arg-type]
        if not math.isfinite(result):
            return None
        return int(result) if result.is_integer() else result
    except (ValueError, TypeError):
        return None


def kickoff(row: dict) -> datetime | None:
    if not row.get("gameday") or not row.get("gametime"):
        return None
    try:
        local = datetime.fromisoformat(f"{row['gameday']}T{row['gametime']}")
        return local.replace(tzinfo=EASTERN).astimezone(timezone.utc)
    except ValueError:
        return None


class SourceError(Exception):
    """Safe external-source failure; no secret-bearing request URL."""


class DataStore:
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.memory: dict[str, dict] = {}
        self.failures: dict[str, dict] = {}
        self.lock = threading.RLock()

    def csv(self, url: str, ttl: int = 900, force: bool = False) -> dict:
        with self.lock:
            key = hashlib.sha256(url.encode()).hexdigest()
            path = self.cache_dir / f"{key}.json"
            saved = self.memory.get(url)
            if saved is None and path.exists():
                try:
                    saved = json.loads(path.read_text())
                    if saved.get("url") != url or not isinstance(saved.get("rows"), list):
                        saved = None
                except (ValueError, OSError):
                    saved = None
            now = time.time()
            if (not force and saved and now - saved.get("fetched_epoch", 0) < ttl
                    and saved.get("status") != "stale" and url not in self.failures):
                self.memory[url] = {**saved, "status": "cached", "error": None}
                return {**saved, "status": "cached", "error": None}
            previous_failure = self.failures.get(url)
            if not force and previous_failure and now - previous_failure["epoch"] < 30:
                if saved:
                    return {**saved, "status": "stale", "error": previous_failure["error"]}
                raise SourceError(previous_failure["error"])
            failure = None
            try:
                response = httpx.get(url, follow_redirects=True, timeout=30)
                if response.status_code != 200:
                    raise SourceError(f"Source request returned HTTP {response.status_code}.")
                reader = csv.DictReader(io.StringIO(response.text))
                rows = list(reader)
                if not reader.fieldnames or not rows or "<!DOCTYPE" in response.text[:100]:
                    raise SourceError("Source did not return a usable CSV dataset.")
                saved = {"url": url, "rows": rows, "retrieved_at": iso(),
                         "last_modified": response.headers.get("last-modified"),
                         "fetched_epoch": now}
                self.memory[url] = {**saved, "status": "source_confirmed", "error": None}
                self.failures.pop(url, None)
                try:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(saved, separators=(",", ":")))
                    temporary.replace(path)
                except OSError:
                    pass  # The live dataset remains available if cache storage is read-only.
                return {**saved, "status": "source_confirmed", "error": None}
            except SourceError as exc:
                failure = str(exc)
            except httpx.RequestError:
                failure = "Source could not be reached. Check network access and try again."
            self.failures[url] = {"error": failure, "epoch": now}
            if saved:
                self.memory[url] = {**saved, "status": "stale", "error": failure}
                return {**saved, "status": "stale", "error": failure}
            raise SourceError(failure or "Source unavailable.")


store = DataStore()


def source(dataset: dict, name: str = "nflverse", **extra) -> dict:
    return {"name": name, "url": dataset.get("url"),
            "retrieved_at": dataset.get("retrieved_at"),
            "last_modified": dataset.get("last_modified"),
            "status": dataset.get("status", "unavailable"),
            "verification": VERIFICATION, **extra}


def regular_rows(dataset: dict, season: int | None = None) -> list[dict]:
    return [row for row in dataset["rows"] if row.get("game_type") == "REG"
            and (season is None or number(row.get("season")) == season)]


def season_and_week(rows: list[dict], season: int | None = None,
                    week: int | None = None, now: datetime | None = None) -> tuple[int, int, list[int], list[int]]:
    today = (now or utc_now()).astimezone(CENTRAL).date().isoformat()
    seasons = sorted({int(row["season"]) for row in rows if int(row["season"]) >= 2024})
    if not seasons:
        raise SourceError("No supported regular-season schedule is available.")
    if season is None:
        started = [year for year in seasons if any(row["gameday"] <= today for row in rows
                                                  if int(row["season"]) == year)]
        season = max(started) if started else min(seasons)
    if season not in seasons:
        raise SourceError("Requested season is not available in the sourced schedule.")
    selected = [row for row in rows if int(row["season"]) == season]
    weeks = sorted({int(row["week"]) for row in selected})
    if week is None:
        starts = {wk: min(row["gameday"] for row in selected if int(row["week"]) == wk)
                  for wk in weeks}
        begun = [wk for wk in weeks if starts[wk] <= today]
        week = max(begun) if begun else min(weeks)
    if week not in weeks:
        raise SourceError("Requested week is not available in the sourced schedule.")
    return season, week, seasons, weeks


def completed(row: dict) -> bool:
    return number(row.get("away_score")) is not None and number(row.get("home_score")) is not None


def team_metrics(rows: list[dict], team: str, cutoff: datetime | None = None) -> dict:
    cutoff = min(cutoff or utc_now(), utc_now())
    past = [row for row in rows if team in (row.get("home_team"), row.get("away_team"))
            and completed(row) and kickoff(row) is not None and kickoff(row) < cutoff]
    wins = losses = ties = 0
    scored = allowed = 0
    for row in past:
        home = row["home_team"] == team
        own = number(row["home_score"] if home else row["away_score"])
        opp = number(row["away_score"] if home else row["home_score"])
        scored += own  # type: ignore[operator]
        allowed += opp  # type: ignore[operator]
        wins += own > opp  # type: ignore[operator]
        losses += own < opp  # type: ignore[operator]
        ties += own == opp
    record = f"{wins}-{losses}" + (f"-{ties}" if ties else "")
    return {"abbr": team, "name": TEAM_NAMES.get(team, team), "record": record,
            "games_played": len(past), "sample_games": len(past),
            "points_per_game": round(scored / len(past), 2) if past else None,
            "points_allowed_per_game": round(allowed / len(past), 2) if past else None,
            "cutoff_date": iso(cutoff)}


def game_data(row: dict, all_rows: list[dict], dataset: dict) -> dict:
    start = kickoff(row)
    season_rows = [r for r in all_rows if r["season"] == row["season"]]
    home = team_metrics(season_rows, row["home_team"], start)
    away = team_metrics(season_rows, row["away_team"], start)
    status = "completed" if completed(row) else "upcoming"
    if not completed(row) and start and start < utc_now():
        status = "awaiting_result"
    reported_status = (row.get("status") or "").lower()
    if reported_status in {"postponed", "canceled", "cancelled"}:
        status = "canceled" if reported_status == "cancelled" else reported_status
    return {"id": row["game_id"], "season": int(row["season"]), "week": int(row["week"]),
            "away": {k: away[k] for k in ("abbr", "name", "record")},
            "home": {k: home[k] for k in ("abbr", "name", "record")},
            "kickoff_utc": iso(start) if start else None,
            "kickoff_local": start.astimezone(CENTRAL).strftime("%a, %b %d, %Y at %I:%M %p %Z") if start else None,
            "display_timezone": "America/Chicago", "gameday": row["gameday"],
            "status": status, "venue": row.get("stadium") or None,
            "roof": row.get("roof") or None,
            "neutral_site": True if row.get("location") == "Neutral" else None,
            "source_location": row.get("location") or None,
            "away_score": number(row.get("away_score")), "home_score": number(row.get("home_score")),
            "away_rest": number(row.get("away_rest")), "home_rest": number(row.get("home_rest")),
            "source_url": dataset["url"], "retrieved_at": dataset["retrieved_at"],
            "projections": None, "odds": None}


STAT_FIELDS = ("completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
               "carries", "rushing_yards", "rushing_tds", "receptions", "targets",
               "receiving_yards", "receiving_tds", "passing_epa", "rushing_epa", "receiving_epa")


def player_data(season: int, schedule: dict, game: dict | None = None,
                cutoff_override: datetime | None = None, roster_week: int | None = None) -> dict:
    stat_url = f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
    roster_url = f"https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{season}.csv"
    cutoff = min(cutoff_override or (kickoff(game) if game else None) or utc_now(), utc_now())
    cutoff_string = iso(cutoff)
    games = {row["game_id"]: row for row in regular_rows(schedule, season)}
    teams = {game["home_team"], game["away_team"]} if game else None
    warnings = []
    try:
        stats = store.csv(stat_url)
    except SourceError as exc:
        warnings.append(str(exc))
        stats = {"rows": [], "url": stat_url, "status": "unavailable", "retrieved_at": None}
    try:
        roster = store.csv(roster_url)
    except SourceError as exc:
        warnings.append(str(exc))
        roster = {"rows": [], "url": roster_url, "status": "unavailable", "retrieved_at": None}
    selected_stats = []
    for row in stats["rows"]:
        scheduled = games.get(row.get("game_id"))
        if row.get("season_type") != "REG" or not scheduled or not completed(scheduled):
            continue
        start = kickoff(scheduled)
        if start is None or start >= cutoff:
            continue
        if teams and row.get("team") not in teams:
            continue
        selected_stats.append(row)
    players: dict[str, dict] = {}
    # Latest roster row before cutoff. Roster status is not a current injury report.
    latest_roster = {}
    for row in sorted(roster["rows"], key=lambda r: number(r.get("week")) or 0):
        # Weekly roster snapshots after a historical target cannot identify its participants.
        target_week = int(game["week"]) if game else roster_week
        if target_week and (number(row.get("week")) or 0) > target_week:
            continue
        pid = row.get("gsis_id")
        if not pid:
            continue
        latest_roster[pid] = row
    for pid, row in latest_roster.items():
        if teams and row.get("team") not in teams:
            continue
        if row.get("position") not in {"QB", "RB", "WR", "TE"}:
            continue
        if row.get("status") not in (None, "", "ACT"):
            continue
        players[pid] = {"id": pid, "name": row.get("full_name"), "position": row.get("position"),
                        "team": row.get("team"), "jersey_number": number(row.get("jersey_number")),
                        "roster_status": row.get("status") or None,
                        "stats": None, "sample_games": 0, "cutoff_date": cutoff_string,
                        "projections": None, "source_url": roster_url,
                        "retrieved_at": roster.get("retrieved_at")}
    sample_ids: dict[str, set[str]] = {}
    for row in sorted(selected_stats, key=lambda r: int(r["week"])):
        if row.get("position") not in {"QB", "RB", "WR", "TE"}:
            continue
        pid = row["player_id"]
        if pid not in players:
            players[pid] = {"id": pid, "name": row.get("player_display_name") or row.get("player_name"),
                            "position": row.get("position"), "team": row.get("team"),
                            "roster_status": latest_roster.get(pid, {}).get("status") or None,
                            "stats": None, "sample_games": 0, "cutoff_date": cutoff_string,
                            "projections": None, "source_url": stat_url,
                            "retrieved_at": stats.get("retrieved_at")}
        player = players[pid]
        if player["stats"] is None:
            player["stats"] = {field: None for field in STAT_FIELDS}
        for field in STAT_FIELDS:
            value = number(row.get(field))
            if value is not None:
                player["stats"][field] = (player["stats"][field] or 0) + value
        sample_ids.setdefault(pid, set()).add(row["game_id"])
        player["sample_games"] = len(sample_ids[pid])
        player["source_url"] = stat_url
        player["retrieved_at"] = stats.get("retrieved_at")
    result = list(players.values())
    for player in result:
        if game:
            player["opponent"] = game["away_team"] if player["team"] == game["home_team"] else game["home_team"]
        if player["stats"]:
            player["stats"] = {k: round(v, 3) if isinstance(v, float) else v for k, v in player["stats"].items()}
            player["stats"]["games"] = player["sample_games"]
    result.sort(key=lambda p: (p["stats"] is not None, (p["stats"] or {}).get("passing_yards") or 0,
                               ((p["stats"] or {}).get("receiving_yards") or 0) +
                               ((p["stats"] or {}).get("rushing_yards") or 0)), reverse=True)
    active_source = stats if stats["rows"] else roster
    return {"season": season, "players": result, "source": source(active_source, cutoff_date=cutoff_string),
            "sources": [source(stats), source(roster)],
            "stats_through_week": max((int(r["week"]) for r in selected_stats), default=None),
            "status": "available" if result else "unavailable",
            "error": "; ".join(warnings) if warnings else None}
