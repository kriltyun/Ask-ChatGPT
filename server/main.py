"""FastAPI research service and production frontend host."""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import odds as market_config
from .ai import AIProviderError, ai_provider_status, generate_ai_report
from .data import (CENTRAL, ROOT, SCHEDULE_URL, SourceError, game_data, iso, kickoff, player_data,
                   regular_rows, season_and_week, source, store, team_metrics, utc_now)
from .odds import SOURCE_URL as ODDS_SOURCE_URL, odds_client
from .verification import SCOREBOARD_URL, verification_client, verification_label

app = FastAPI(title="Fieldwork NFL Research", version="1.0.0")


def schedule_dataset(force: bool = False) -> tuple[dict, list[dict]]:
    try:
        dataset = store.csv(SCHEDULE_URL, ttl=300, force=force)
        return dataset, regular_rows(dataset)
    except SourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def find_game(game_id: str, season: int | None = None) -> tuple[dict, dict, list[dict]]:
    dataset, rows = schedule_dataset()
    row = next((r for r in rows if r["game_id"] == game_id
                and (season is None or int(r["season"]) == season)), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Game was not found in the sourced regular-season schedule.")
    return row, dataset, rows


def verified_week(rows: list[dict], season: int, week: int) -> dict:
    selected = [row for row in rows if int(row["season"]) == season and int(row["week"]) == week]
    return verification_client.check(selected, season, week)


def sourced_game(row: dict, rows: list[dict], dataset: dict, crosscheck: dict | None = None) -> dict:
    result = game_data(row, rows, dataset)
    if crosscheck is None:
        crosscheck = verified_week(rows, int(row["season"]), int(row["week"]))
    if crosscheck.get("status") == "verified":
        verified_status = crosscheck.get("independent_status_by_game", {}).get(row["game_id"])
        if verified_status:
            result["status"] = verified_status
            result["status_source"] = {"name": "ESPN", "url": crosscheck.get("url"),
                                       "checked_at": crosscheck.get("checked_at")}
    return result


@app.get("/api/schedule")
def schedule(season: int | None = Query(None, ge=2024, le=2100),
             week: int | None = Query(None, ge=1, le=18), refresh: bool = False):
    try:
        dataset, rows = schedule_dataset(force=refresh)
        selected_season, selected_week, seasons, weeks = season_and_week(rows, season, week)
    except HTTPException as exc:
        return {"season": season, "week": week, "seasons": [], "weeks": [], "games": [],
                "byes": [], "source": {"name": "nflverse", "url": SCHEDULE_URL,
                "retrieved_at": None, "status": "unavailable", "verification": None}, "error": exc.detail}
    except SourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    selected = [row for row in rows if int(row["season"]) == selected_season
                and int(row["week"]) == selected_week]
    selected.sort(key=lambda r: (r["gameday"], r.get("gametime") or "23:59", r["game_id"]))
    season_teams = {row[side] for row in rows if int(row["season"]) == selected_season
                    for side in ("home_team", "away_team")}
    playing = {row[side] for row in selected for side in ("home_team", "away_team")}
    crosscheck = verification_client.check(selected, selected_season, selected_week, force=refresh)
    schedule_source = source(dataset, crosscheck=crosscheck, verification=verification_label(crosscheck))
    error = dataset.get("error")
    if crosscheck.get("material_mismatch"):
        error = "Independent schedule cross-check found a season, week, opponent or kickoff mismatch. Refresh the schedule before using this slate."
    games = [sourced_game(row, rows, dataset, crosscheck) for row in selected]
    mismatches = {item["game_id"]: item["fields"] for item in crosscheck.get("mismatches", [])}
    for game in games:
        game["source_warning"] = mismatches.get(game["id"])
    return {"season": selected_season, "week": selected_week, "seasons": seasons, "weeks": weeks,
            "games": games, "byes": sorted(season_teams - playing), "source": schedule_source, "error": error}


@app.get("/api/players")
def players(season: int | None = Query(None, ge=2024, le=2100),
            week: int | None = Query(None, ge=1, le=18), include_previous: bool = False):
    dataset, rows = schedule_dataset()
    try:
        selected_season, selected_week, _, _ = season_and_week(rows, season, week)
    except SourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    cutoff = None
    if week is None:
        response = player_data(selected_season, dataset)
    else:
        selected_games = [row for row in rows if int(row["season"]) == selected_season
                          and int(row["week"]) == selected_week]
        cutoff = min((kickoff(row) for row in selected_games if kickoff(row)), default=None)
        response = player_data(selected_season, dataset, cutoff_override=cutoff, roster_week=selected_week)
        response["week"] = selected_week
    if not include_previous:
        return response

    previous_season = selected_season - 1
    comparison_cutoff = min(cutoff or utc_now(), utc_now())
    previous_url = f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{previous_season}.csv"
    try:
        previous = player_data(previous_season, dataset, cutoff_override=comparison_cutoff, roster_week=18)
    except SourceError as exc:
        previous = {"players": [], "source": {"name": "nflverse", "url": previous_url,
                    "retrieved_at": None, "status": "unavailable", "cutoff_date": iso(comparison_cutoff)},
                    "stats_through_week": None, "status": "unavailable", "error": str(exc)}
    has_statistics = any(player.get("stats") is not None and player.get("sample_games", 0) > 0
                         for player in previous.get("players", []))
    previous_source = previous.get("source")
    if not has_statistics:
        # A roster snapshot cannot establish prior-season production totals.
        previous_source = next((item for item in previous.get("sources", []) if item.get("url") == previous_url),
                               previous_source)
    response.update({"previous_season": previous_season,
                     "previous_players": previous.get("players", []),
                     "previous_source": previous_source,
                     "previous_stats_through_week": previous.get("stats_through_week"),
                     "previous_status": previous.get("status", "available") if has_statistics else "unavailable",
                     "previous_error": previous.get("error") or (None if has_statistics else
                                       "No completed regular-season player statistics are available for the previous season.")})
    return response


@app.get("/api/prices")
def prices(season: int | None = Query(None, ge=2024, le=2100),
           week: int | None = Query(None, ge=1, le=18)):
    dataset, rows = schedule_dataset()
    try:
        selected_season, selected_week, _, _ = season_and_week(rows, season, week)
    except SourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    selected_games = [row for row in rows if int(row["season"]) == selected_season
                      and int(row["week"]) == selected_week]
    crosscheck = verified_week(rows, selected_season, selected_week)
    status_by_game = crosscheck.get("independent_status_by_game", {}) if crosscheck.get("status") == "verified" else {}
    quotes = {row["game_id"]: odds_client.game(row, include_props=False, verified_status=status_by_game.get(row["game_id"]))
              for row in selected_games}
    statuses = {quote["status"] for quote in quotes.values()}
    available = next((quote for quote in quotes.values() if quote["markets"]), None)
    representative = available or next(iter(quotes.values()), None)
    status = ("stale" if available and available["status"] == "stale" else "connected") if available else (
             "disconnected" if statuses == {"disconnected"} else "unavailable")
    return {"season": selected_season, "week": selected_week, "status": status, "games": quotes,
            "source": representative["source"] if representative else {"name": "The Odds API", "url": ODDS_SOURCE_URL, "retrieved_at": None},
            "error": representative.get("error") if representative else "No selected games available."}


@app.get("/api/markets")
def market_catalog():
    return market_config.MARKET_CATALOG


@app.get("/api/odds/{game_id}")
def odds(game_id: str, season: int | None = Query(None, ge=2024, le=2100), markets: str | None = None):
    requested_markets = None
    if markets is not None:
        keys = [key.strip() for key in markets.split(",")]
        supported = set(market_config.SUPPORTED_PROP_MARKETS) | {"h2h", "spreads", "totals"}
        if any(not key or key not in supported for key in keys):
            raise HTTPException(status_code=400, detail="Requested markets must be a comma-separated list of supported market identifiers.")
        requested_markets = tuple(dict.fromkeys(key for key in keys if key not in {"h2h", "spreads", "totals"}))
    row, dataset, rows = find_game(game_id, season)
    selected_game = sourced_game(row, rows, dataset)
    return odds_client.game(row, verified_status=selected_game["status"] if selected_game.get("status_source") else None,
                            requested_markets=requested_markets)


@app.get("/api/game/{game_id}")
def game(game_id: str, season: int | None = Query(None, ge=2024, le=2100)):
    row, dataset, rows = find_game(game_id, season)
    selected_season = int(row["season"])
    season_rows = [r for r in rows if int(r["season"]) == selected_season]
    start = kickoff(row)
    away = team_metrics(season_rows, row["away_team"], start)
    home = team_metrics(season_rows, row["home_team"], start)
    selected_game = sourced_game(row, rows, dataset)
    away["rest_days"] = selected_game["away_rest"]
    home["rest_days"] = selected_game["home_rest"]
    player_response = player_data(selected_season, dataset, row)
    return {"game": selected_game,
            "metrics": {"away": away, "home": home, "source": source(dataset),
                        "method": "Completed regular-season games before kickoff, capped at retrieval time. Points averages are descriptive season statistics."},
            "players": player_response["players"], "player_source": player_response["source"],
            "player_status": player_response["status"], "player_error": player_response["error"],
            "odds": odds_client.game(row, verified_status=selected_game["status"] if selected_game.get("status_source") else None),
            "weather": None, "injuries": None,
            "context": {"venue": row.get("stadium") or None, "roof": row.get("roof") or None,
                        "neutral_site": True if row.get("location") == "Neutral" else None,
                        "source_location": row.get("location") or None,
                        "kickoff_utc": iso(start) if start else None,
                        "weather_status": "No forecast provider connected.",
                        "injuries_status": "No current injury-report provider connected.",
                        "advanced_metrics_status": "Play-by-play efficiency and matchup adjustments are not connected.",
                        "projections_status": "No calibrated prediction model connected.",
                        "source": source(dataset)}}


class AnalysisRequest(BaseModel):
    game_id: str = Field(min_length=1, max_length=100)
    season: int | None = Field(default=None, ge=2024, le=2100)


@app.post("/api/analysis")
def analysis(request: AnalysisRequest):
    row, dataset, rows = find_game(request.game_id, request.season)
    start = kickoff(row)
    season_rows = [r for r in rows if r["season"] == row["season"]]
    away = team_metrics(season_rows, row["away_team"], start)
    home = team_metrics(season_rows, row["home_team"], start)
    matchup = f"{away['name']} at {home['name']}"
    schedule_sentence = f"Week {row['week']} of the {row['season']} regular season. "
    schedule_sentence += f"Kickoff: {start.astimezone(CENTRAL).strftime('%a, %b %d, %Y at %I:%M %p %Z')}. " if start else "Kickoff time is unavailable. "
    schedule_sentence += f"Venue: {row.get('stadium') or 'not reported'}. "
    schedule_sentence += f"Roof: {row.get('roof') or 'not reported'}."
    comparison = []
    for team in (away, home):
        if team["sample_games"]:
            comparison.append(f"{team['name']}: {team['record']} across {team['sample_games']} prior completed games; "
                              f"{team['points_per_game']:.1f} points scored and {team['points_allowed_per_game']:.1f} allowed per game.")
        else:
            comparison.append(f"{team['name']}: no prior completed games available for this cutoff.")
    selected_game = sourced_game(row, rows, dataset)
    price_data = odds_client.game(row, verified_status=selected_game["status"] if selected_game.get("status_source") else None)
    if price_data["markets"]:
        price_sentence = f"{len(price_data['markets'])} sportsbook market snapshots are available from DraftKings and/or FanDuel. "
        price_sentence += "Compare the exact market, threshold, and update time. Implied probabilities include bookmaker margin; they are not model probabilities."
    else:
        price_sentence = price_data.get("error") or "No current sportsbook prices are available."
    player_response = player_data(int(row["season"]), dataset, row)
    report = {"kind": "template", "title": f"{matchup}: source-based research brief",
            "sections": [{"heading": "Matchup context", "body": schedule_sentence},
                         {"heading": "Season scoring comparison", "body": " ".join(comparison)},
                         {"heading": "Market check", "body": price_sentence},
                         {"heading": "Workload assumptions", "body": "Prior game statistics describe recorded production. They do not confirm a starter, snap share, target share, or workload for this matchup. Any assumption that past usage will continue is unconfirmed."},
                         {"heading": "Weather", "body": "No game-time forecast source is connected. The schedule's roof label describes a venue or reported configuration; it does not establish future roof decisions, wind, or temperature."},
                         {"heading": "Injuries and availability", "body": "No current injury-report source is connected. Roster status is a sourced snapshot, not a current injury diagnosis or confirmation that a player will be active."},
                         {"heading": "Conditional game scripts", "body": "If a team trails, additional passing opportunities could change player totals. If it leads and runs more often, rushing opportunities could change. These are qualitative scenarios, not forecasts or assigned probabilities."},
                         {"heading": "Parlay dependencies", "body": "Same-game legs can share scoring and game-script dependencies. A quarterback passing touchdown and a receiver touchdown can overlap. No joint-probability model is available for these exact markets; multiplying separate probabilities would not establish a dependable parlay price."},
                         {"heading": "What would change the assessment", "body": "Updated exact-threshold sportsbook prices, a current availability report, confirmed player roles, a game-time weather forecast, or newly sourced performance data could change the research. A calibrated prediction model would still be required to quantify probability, expected value, or a claimed edge."},
                         {"heading": "Research limits", "body": "This factual brief uses a fixed template, not an AI prediction. Scoring averages are not projected scores. No calibrated win or prop probability, expected value, injury adjustment, or weather forecast is available, so this brief does not identify an edge or recommend a bet."}],
            "generated_at": iso(), "sources": [source(dataset), player_response["source"], price_data["source"]],
            "model": {"status": "unavailable", "name": None}, "game_id": row["game_id"],
            "ai_status": "disconnected", "ai_error": None}
    evidence = {"game": selected_game,
                "metrics": {"away": away, "home": home, "source": source(dataset),
                            "method": "Completed regular-season games before kickoff, capped at retrieval time."},
                "players": player_response["players"][:30],
                "player_source": player_response["source"], "player_status": player_response["status"],
                "player_error": player_response["error"], "odds": price_data,
                "weather": None, "injuries": None,
                "context": {"weather_status": "No forecast provider connected.",
                            "injuries_status": "No current injury-report provider connected.",
                            "workload_status": "Historical production does not confirm future roles or availability.",
                            "projections_status": "No calibrated prediction model connected.",
                            "joint_probability_status": "No exact-market dependency model connected.",
                            "player_evidence_count": min(len(player_response["players"]), 30)},
                "sources": report["sources"], "model": report["model"]}
    try:
        ai_report = generate_ai_report(evidence)
    except AIProviderError as exc:
        report["ai_status"] = "unavailable"
        report["ai_error"] = str(exc)
    else:
        if ai_report:
            ai_report["model"] = report["model"]
            ai_report["game_id"] = row["game_id"]
            return ai_report
    return report


@app.get("/api/status")
def status():
    dataset = store.memory.get(SCHEDULE_URL)
    has_key = bool(os.environ.get("ODDS_API_KEY"))
    schedule_status = "pending"
    if dataset:
        schedule_status = "stale" if dataset.get("status") == "stale" or time.time() - dataset.get("fetched_epoch", 0) >= 300 else "connected"
    elif SCHEDULE_URL in store.failures:
        schedule_status = "unavailable"
    player_datasets = [d for u, d in store.memory.items() if "stats_player_week_" in u]
    player_status = "pending"
    if player_datasets:
        player_status = "connected" if any(d.get("status") != "stale" and time.time() - d.get("fetched_epoch", 0) < 900 for d in player_datasets) else "stale"
    crosscheck = verification_client.latest
    verification_status = "pending"
    if crosscheck:
        verification_status = ("stale" if time.time() - verification_client.latest_epoch >= 600 else
                               "connected" if crosscheck["status"] == "verified" else
                               "warning" if crosscheck["status"] == "mismatch" else
                               "disconnected" if crosscheck["status"] == "unavailable" else "pending")
        if crosscheck["status"] == "mismatch" and schedule_status == "connected":
            schedule_status = "warning"
    source_connections = [
        {"id": "schedule", "name": "NFL schedule & results", "status": schedule_status,
         "detail": (dataset.get("error") or ("Cached source snapshot is stale; refresh the schedule to retry." if schedule_status == "stale" else verification_label(crosscheck or {}))) if dataset else store.failures.get(SCHEDULE_URL, {}).get("error", "Source will be fetched when the schedule is opened."),
         "last_update": dataset.get("retrieved_at") if dataset else None, "source_url": SCHEDULE_URL},
        {"id": "verification", "name": "Independent schedule check", "status": verification_status,
         "detail": crosscheck["detail"] if crosscheck else "ESPN comparison is checked when a sourced slate is opened.",
         "last_update": crosscheck.get("checked_at") if crosscheck else None,
         "source_url": crosscheck.get("url") if crosscheck else SCOREBOARD_URL},
        {"id": "odds", "name": "DraftKings & FanDuel odds",
         "status": ("stale" if odds_client.last_update and (odds_client.last_error or time.time() - odds_client.last_success_epoch >= 900) else "connected" if odds_client.last_update else "unavailable" if odds_client.last_error else "configured") if has_key else "disconnected",
         "detail": odds_client.last_error or ("Server-side credential configured; retrieval is checked on demand." if has_key else "ODDS_API_KEY is required in environment settings."),
         "last_update": odds_client.last_update, "source_url": ODDS_SOURCE_URL},
        {"id": "players", "name": "NFL player statistics", "status": player_status,
         "detail": "nflverse completed-game statistics; roster names remain available when statistics are missing.",
         "last_update": max((d.get("retrieved_at") for u, d in store.memory.items() if "stats_player" in u), default=None),
         "source_url": "https://github.com/nflverse/nflverse-data/releases/tag/stats_player"},
        {"id": "weather", "name": "Game weather", "status": "disconnected", "detail": "No forecast provider connected.", "last_update": None, "source_url": None},
        {"id": "injuries", "name": "Injury reports", "status": "disconnected", "detail": "No current injury-report provider connected.", "last_update": None, "source_url": None},
        ai_provider_status(),
    ]
    return {"connections": source_connections,
            "model": {"status": "unavailable", "name": None, "detail": "No calibrated prediction model connected."},
            "updated_at": iso(), "odds_quota": dict(odds_client.quota)}


@app.get("/api/health")
def health():
    return {"status": "ok"}


DIST = ROOT / "dist"
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found.")
    index = DIST / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend build unavailable. Run npm run dev or npm run build.")
    candidate = (DIST / path).resolve()
    if candidate.is_relative_to(DIST.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(index)
