"""Independent ESPN schedule comparison, with no assumed verification on failure."""

from __future__ import annotations

import threading
import time
import unicodedata
from datetime import datetime, timezone

import httpx

from .data import iso, kickoff, number

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# Public field reference, explicitly unofficial; only actual ESPN responses can
# establish an independent match:
# https://github.com/pseudo-r/Public-ESPN-API/blob/main/docs/response_schemas.md
ALIASES = {"WSH": "WAS", "LAR": "LA"}
CACHE_SECONDS = 600
FAILURE_SECONDS = 30


def canonical_status(event_status: object, competition_status: object = None) -> str | None:
    """Map only explicitly reported ESPN status fields, never the game clock."""
    for status in (event_status, competition_status):
        if not isinstance(status, dict):
            continue
        reported = status.get("type", status)
        if not isinstance(reported, dict):
            continue
        name = reported.get("name") if isinstance(reported.get("name"), str) else None
        if name == "STATUS_POSTPONED":
            return "postponed"
        if name in {"STATUS_CANCELED", "STATUS_CANCELLED"}:
            return "canceled"
        if reported.get("completed") is True or reported.get("state") == "post":
            return "completed"
        if reported.get("state") == "pre":
            return "upcoming"
        if reported.get("state") == "in":
            return "live"
    return None


def abbreviation(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().upper()
    return ALIASES.get(normalized, normalized)


def normalize_venue(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKD", value).casefold()
                   if character.isalnum())


def parse_scoreboard(payload: object) -> list[dict] | None:
    """Accept only explicit competitor designations, timestamps and venue fields."""
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        return None
    events = []
    for event in payload["events"]:
        if not isinstance(event, dict) or not isinstance(event.get("competitions"), list):
            continue
        for competition in event["competitions"]:
            if not isinstance(competition, dict) or not isinstance(competition.get("competitors"), list):
                continue
            teams = {}
            for competitor in competition["competitors"]:
                if not isinstance(competitor, dict):
                    continue
                side = competitor.get("homeAway")
                team = competitor.get("team")
                if side not in {"home", "away"} or not isinstance(team, dict):
                    continue
                code = abbreviation(team.get("abbreviation"))
                if code:
                    teams[side] = code
            if set(teams) != {"home", "away"}:
                continue
            stamp = event.get("date") or competition.get("date")
            if not isinstance(stamp, str):
                continue
            try:
                start = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if start.tzinfo is None:
                    continue
                start = start.astimezone(timezone.utc)
            except ValueError:
                continue
            venue = competition.get("venue")
            venue_name = venue.get("fullName") if isinstance(venue, dict) else None
            season = event.get("season") or payload.get("season")
            week = event.get("week") or payload.get("week")
            season = season if isinstance(season, dict) else {}
            week = week if isinstance(week, dict) else {}
            events.append({"id": str(event["id"]) if event.get("id") is not None else None,
                           "season": number(season.get("year")) if not isinstance(season.get("year"), bool) else None,
                           "week": number(week.get("number")) if not isinstance(week.get("number"), bool) else None,
                           "season_type": number(season.get("type")),
                           "home": teams["home"], "away": teams["away"], "kickoff": start,
                           "venue": venue_name if isinstance(venue_name, str) and venue_name.strip() else None,
                           "status": canonical_status(event.get("status"), competition.get("status"))})
    return events


def compare(rows: list[dict], events: list[dict]) -> dict:
    mismatches = []
    missing = []
    checked = 0
    venue_checks = 0
    season_week_checks = 0
    missing_metadata = []
    authoritative_statuses = {}
    for row in rows:
        expected_start = kickoff(row)
        espn_id = str(row.get("espn") or "").strip()
        event = next((candidate for candidate in events if espn_id and candidate["id"] == espn_id), None)
        if event is None:
            event = next((candidate for candidate in events if
                          {candidate["home"], candidate["away"]} == {row.get("home_team"), row.get("away_team")}), None)
        if event is None or expected_start is None:
            missing.append(row["game_id"])
            continue
        checked += 1
        if event.get("status"):
            authoritative_statuses[row["game_id"]] = event["status"]
        fields = []
        if event.get("season") is None or event.get("week") is None:
            missing_metadata.append(row["game_id"])
        else:
            season_week_checks += 1
            if event["season"] != number(row.get("season")):
                fields.append("season")
            if event["week"] != number(row.get("week")):
                fields.append("week")
        if event.get("season_type") is not None and event["season_type"] != 2:
            fields.append("season_type")
        if event["home"] != row.get("home_team") or event["away"] != row.get("away_team"):
            fields.append("opponents")
        if abs((event["kickoff"] - expected_start).total_seconds()) > 60:
            fields.append("kickoff")
        venue = row.get("stadium")
        if isinstance(venue, str) and venue.strip() and event["venue"]:
            venue_checks += 1
            if normalize_venue(venue) != normalize_venue(event["venue"]):
                fields.append("venue")
        if fields:
            mismatches.append({"game_id": row["game_id"], "fields": fields,
                               "source": {"home": row.get("home_team"), "away": row.get("away_team"),
                                          "kickoff_utc": iso(expected_start), "venue": venue or None},
                               "independent": {"home": event["home"], "away": event["away"],
                                               "kickoff_utc": iso(event["kickoff"]), "venue": event["venue"]}})
    material = any(any(field != "venue" for field in item["fields"]) for item in mismatches)
    state = "mismatch" if mismatches else "incomplete" if missing or missing_metadata or not rows else "verified"
    detail = ("Independent ESPN cross-check found conflicting schedule fields." if mismatches else
              "Independent ESPN cross-check did not include every required game, season, week, and kickoff field." if missing or missing_metadata or not rows else
              "All selected seasons, weeks, opponents and kickoff times match ESPN; venue names match wherever both sources supply them.")
    result = {"status": state, "detail": detail, "checked_games": checked, "expected_games": len(rows),
            "venue_checks": venue_checks, "season_week_checks": season_week_checks,
            "missing_metadata": missing_metadata, "missing_games": missing, "mismatches": mismatches,
            "material_mismatch": material}
    if state == "verified":
        result["independent_status_by_game"] = authoritative_statuses
    return result


class VerificationClient:
    def __init__(self):
        self.cache: dict[tuple[int, int, tuple[str, ...]], dict] = {}
        self.latest: dict | None = None
        self.latest_epoch = 0.0
        self.lock = threading.RLock()

    def check(self, rows: list[dict], season: int, week: int, force: bool = False) -> dict:
        dates = sorted({row.get("gameday") for row in rows if row.get("gameday")})
        if not dates:
            return {"status": "unavailable", "detail": "Independent ESPN cross-check unavailable",
                    "checked_at": iso(), "url": SCOREBOARD_URL, "material_mismatch": False}
        cache_key = (season, week, tuple(dates))
        urls = [f"{SCOREBOARD_URL}?dates={date.replace('-', '')}&limit=1000" for date in dates]
        url = urls[0] if len(urls) == 1 else SCOREBOARD_URL
        with self.lock:
            cached = self.cache.get(cache_key)
            ttl = CACHE_SECONDS if cached and cached.get("events") is not None else FAILURE_SECONDS
            if force or not cached or time.time() - cached["epoch"] >= ttl:
                cached = {"epoch": time.time(), "checked_at": iso(), "events": None, "request_urls": []}
                try:
                    # Date ranges can be rejected by the Site scoreboard API.
                    # Use distinct source game dates, and stop after any failed day.
                    deduplicated = {}
                    all_days_available = True
                    for date, request_url in zip(dates, urls):
                        cached["request_urls"].append(request_url)
                        response = httpx.get(SCOREBOARD_URL, params={"dates": date.replace('-', ''), "limit": 1000},
                                             timeout=httpx.Timeout(8.0, connect=5.0))
                        if response.status_code != 200:
                            all_days_available = False
                            break
                        daily_events = parse_scoreboard(response.json())
                        if daily_events is None:
                            all_days_available = False
                            break
                        for event in daily_events:
                            event_key = event["id"] or (event["home"], event["away"], iso(event["kickoff"]))
                            previous = deduplicated.get(event_key)
                            if previous and previous != event:
                                all_days_available = False
                                break
                            deduplicated[event_key] = event
                        if not all_days_available:
                            break
                    if all_days_available:
                        cached["events"] = list(deduplicated.values())
                except (httpx.RequestError, ValueError):
                    pass
                self.cache[cache_key] = cached
            if cached["events"] is None:
                result = {"status": "unavailable", "detail": "Independent ESPN cross-check unavailable",
                          "checked_at": cached["checked_at"], "url": url,
                          "expected_games": len(rows), "checked_games": 0,
                          "mismatches": [], "material_mismatch": False}
            else:
                result = {**compare(rows, cached["events"]), "checked_at": cached["checked_at"], "url": url}
            result["request_urls"] = cached.get("request_urls", [])
            result["requested_dates"] = dates
            result["scope"] = "Selected source games on their listed game dates; omitted games on other dates are not checked."
            self.latest = result
            self.latest_epoch = cached["epoch"]
            return result


verification_client = VerificationClient()


def verification_label(crosscheck: dict) -> str:
    return {"verified": "Independently confirmed against ESPN",
            "mismatch": "Source warning · ESPN cross-check mismatch",
            "incomplete": "Source confirmed · independent cross-check incomplete"}.get(
                crosscheck.get("status"), "Source confirmed · independent cross-check unavailable")
