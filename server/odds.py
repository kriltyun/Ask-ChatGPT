"""Server-only The Odds API adapter. Credentials never enter browser responses."""

from __future__ import annotations

import os
import json
import threading
import time
from datetime import datetime, timezone

import httpx

from .data import ROOT, TEAM_NAMES, iso, kickoff, number, utc_now

BASE_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
SOURCE_URL = "https://the-odds-api.com/liveapi/guides/v4/"
BOOKMAKERS = ("draftkings", "fanduel")
STALE_AFTER_SECONDS = 900
# Current provider-owned market documentation. Keep exact returned outcomes and
# thresholds; player_tds_over is not necessarily a 2+ touchdown market.
# https://the-odds-api.com/sports-odds-data/betting-markets.html
MARKET_CATALOG = json.loads((ROOT / "config" / "nfl-markets.json").read_text())
SUPPORTED_PROP_MARKETS = tuple(market["key"] for market in MARKET_CATALOG["markets"])
PROP_MARKETS = tuple(market["key"] for market in MARKET_CATALOG["markets"] if market["default"])


def american_implied(price: int | float | None) -> float | None:
    if price is None or price == 0:
        return None
    return round((-price / (-price + 100)) if price < 0 else 100 / (price + 100), 6)


def normalize_markets(event: dict, retrieved_at: str) -> list[dict]:
    result = []
    for book in event.get("bookmakers", []):
        if book.get("key") not in BOOKMAKERS:
            continue
        for market in book.get("markets", []):
            outcomes = []
            for outcome in market.get("outcomes", []):
                price = number(outcome.get("price"))
                outcomes.append({"name": outcome.get("name"),
                                 "description": outcome.get("description"),
                                 "point": number(outcome.get("point")), "price": price,
                                 "implied_probability": american_implied(price)})
            timestamp = market.get("last_update") or book.get("last_update")
            stale = None
            if timestamp:
                try:
                    updated = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    stale = (utc_now() - updated).total_seconds() > STALE_AFTER_SECONDS
                except (ValueError, TypeError):
                    pass
            result.append({"bookmaker": book.get("key"), "bookmaker_name": book.get("title"),
                           "market": market.get("key"), "outcomes": outcomes,
                           "updated_at": timestamp, "retrieved_at": retrieved_at, "stale": stale,
                           "stale_after_seconds": STALE_AFTER_SECONDS})
    return result


class OddsClient:
    def __init__(self):
        self.cache: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.quota = {"remaining": None, "used": None, "last_cost": None}
        self.last_update: str | None = None
        self.last_success_epoch = 0.0
        self.last_error: str | None = None
        self.retry_after = 0.0

    def request(self, path: str, markets: tuple[str, ...]) -> dict:
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            return {"status": "disconnected", "payload": None,
                    "error": "Connect ODDS_API_KEY in environment settings to load live sportsbook prices.",
                    "retrieved_at": None}
        cache_key = f"{path}:{','.join(markets)}"
        with self.lock:
            saved = self.cache.get(cache_key)
            if saved and time.time() - saved["epoch"] < 120:
                return {**saved, "status": "connected", "error": None}
            if time.time() < self.retry_after:
                return {**(saved or {"payload": None, "retrieved_at": None}),
                        "status": "stale" if saved else "unavailable", "error": self.last_error}
            try:
                response = httpx.get(f"{BASE_URL}{path}", params={"apiKey": key,
                    "bookmakers": ",".join(BOOKMAKERS), "regions": "us",
                    "markets": ",".join(markets), "oddsFormat": "american", "dateFormat": "iso"},
                    timeout=20)
                for field, header in (("remaining", "x-requests-remaining"),
                                      ("used", "x-requests-used"), ("last_cost", "x-requests-last")):
                    if response.headers.get(header) is not None:
                        self.quota[field] = number(response.headers[header])
                messages = {401: "The sportsbook provider rejected the configured credential.",
                            403: "Sportsbook provider access is denied. Check the plan and network policy.",
                            404: "This sportsbook event is missing or has expired.",
                            422: "Requested sportsbook markets are unavailable for this account or event.",
                            429: "Sportsbook quota is exhausted or rate limited. Cached prices are shown when available."}
                if response.status_code != 200:
                    known_code = None
                    try:
                        error_payload = response.json()
                        reported_code = (error_payload.get("error_code") or error_payload.get("code")) if isinstance(error_payload, dict) else None
                        if isinstance(reported_code, str) and reported_code in {
                            "OUT_OF_USAGE_CREDITS", "INVALID_KEY", "DEACTIVATED_KEY", "EXCEEDED_FREQ_LIMIT"
                        }:
                            known_code = reported_code
                    except ValueError:
                        pass
                    coded_messages = {
                        "OUT_OF_USAGE_CREDITS": "Sportsbook usage credits are exhausted. Cached prices are shown when available.",
                        "INVALID_KEY": "The sportsbook provider rejected the configured credential.",
                        "DEACTIVATED_KEY": "The sportsbook credential is deactivated. Check provider account settings.",
                        "EXCEEDED_FREQ_LIMIT": "Sportsbook requests are temporarily rate limited. Cached prices are shown when available.",
                    }
                    self.last_error = coded_messages.get(known_code) or messages.get(response.status_code,
                                                   f"Sportsbook provider returned HTTP {response.status_code}.")
                    self.retry_after = time.time() + (300 if known_code == "OUT_OF_USAGE_CREDITS" or response.status_code == 429 else 60)
                else:
                    payload = response.json()
                    if not isinstance(payload, (list, dict)):
                        raise ValueError("Invalid response shape")
                    saved = {"payload": payload, "retrieved_at": iso(), "epoch": time.time()}
                    self.cache[cache_key] = saved
                    self.last_update = saved["retrieved_at"]
                    self.last_success_epoch = saved["epoch"]
                    self.last_error = None
                    if self.quota["remaining"] == 0:
                        self.last_error = "Sportsbook quota is exhausted. Current cached prices remain available."
                        self.retry_after = time.time() + 300
                    return {**saved, "status": "connected", "error": None}
            except (httpx.RequestError, ValueError):
                # httpx exception URLs contain the API key. Never return or log them.
                self.last_error = "Sportsbook prices could not be retrieved. Check provider and network access."
                self.retry_after = time.time() + 60
            return {**(saved or {"payload": None, "retrieved_at": None}),
                    "status": "stale" if saved else "unavailable", "error": self.last_error}

    def game(self, row: dict, include_props: bool = True, verified_status: str | None = None,
             requested_markets: tuple[str, ...] | None = None) -> dict:
        prop_markets = PROP_MARKETS if requested_markets is None else tuple(dict.fromkeys(requested_markets))
        initial = {"status": "disconnected", "event_id": None, "markets": [], "props": [],
                   "source": {"name": "The Odds API", "url": SOURCE_URL, "retrieved_at": None},
                   "quota": dict(self.quota), "props_supported": list(SUPPORTED_PROP_MARKETS),
                   "props_status": "disconnected", "props_max_request_cost": len(prop_markets), "error": None}
        if any(market not in SUPPORTED_PROP_MARKETS for market in prop_markets):
            return {**initial, "status": "unavailable", "error": "Requested NFL markets are not supported by this configuration."}
        if not os.environ.get("ODDS_API_KEY"):
            initial["error"] = "Connect ODDS_API_KEY in environment settings to load live sportsbook prices."
            return initial
        expected_start = kickoff(row)
        if expected_start is None:
            return {**initial, "status": "unavailable",
                    "error": "A sourced kickoff time is required to match the exact sportsbook event."}
        if expected_start < utc_now() and verified_status != "live":
            return {**initial, "status": "unavailable",
                    "error": "Prices are available for upcoming or independently confirmed live provider events. Historical schedule prices are not used."}
        data = self.request("/odds", ("h2h", "spreads", "totals"))
        initial.update(status=data["status"], error=data["error"], quota=dict(self.quota))
        initial["source"]["retrieved_at"] = data["retrieved_at"]
        event = None
        for candidate in data.get("payload") or []:
            if not isinstance(candidate, dict):
                continue
            if (candidate.get("home_team") == TEAM_NAMES.get(row["home_team"])
                    and candidate.get("away_team") == TEAM_NAMES.get(row["away_team"])):
                try:
                    provider_start = datetime.fromisoformat(candidate["commence_time"].replace("Z", "+00:00"))
                    if provider_start.tzinfo is None or abs((provider_start - expected_start).total_seconds()) > 60:
                        continue
                    if not isinstance(candidate.get("id"), str) or not candidate["id"]:
                        continue
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
                event = candidate
                break
        if event is None:
            if data["payload"] is not None:
                initial.update(status="unavailable", error="This game is not listed among the provider's upcoming events.")
            return initial
        initial["event_id"] = event["id"]
        initial["markets"] = normalize_markets(event, data["retrieved_at"])
        if not initial["markets"]:
            initial["status"] = "unavailable"
            initial["error"] = "No DraftKings or FanDuel game prices were returned for this event."
        elif all(market["stale"] is True for market in initial["markets"]):
            initial["status"] = "stale"
        if not include_props or not prop_markets:
            initial["props_status"] = "not_requested"
            return initial
        prop_data = self.request(f"/events/{event['id']}/odds", prop_markets)
        if isinstance(prop_data.get("payload"), dict):
            initial["props"] = normalize_markets(prop_data["payload"], prop_data["retrieved_at"])
        initial["props_status"] = prop_data["status"]
        initial["props_error"] = prop_data["error"]
        if prop_data["status"] == "connected" and not initial["props"]:
            initial["props_status"] = "unavailable"
            initial["props_error"] = "No requested NFL player prices were returned for this event."
        elif initial["props"] and not initial["markets"]:
            initial["status"] = prop_data["status"]
        initial["quota"] = dict(self.quota)
        return initial


odds_client = OddsClient()
