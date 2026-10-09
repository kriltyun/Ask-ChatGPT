# Fieldwork — NFL research

A responsive React research workspace with a Python FastAPI data service. The default experience uses the real maintained nflverse regular-season schedule. There are no fictional matchups, odds, projections, or default demo fixtures.

## Run

Requirements: Python 3.12+, Node.js 22.12+ (the environment provides Node 24), and network access to the source destinations below.

```bash
cd /workspace/Ask-ChatGPT
bash scripts/setup.sh
bash scripts/start.sh
```

FastAPI serves the built frontend and `/api` from the same origin on port 8000. Set `PORT` to use another port. The host must support a long-running Python process; a static-only host cannot provide the data service or securely connect odds.

For frontend development, run the backend and Vite in separate terminals:

```bash
.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
npm run dev
```

Vite proxies `/api` to the backend. Use the existing isolated checkout; do not create a worktree for ordinary cloud tasks. The shell scripts use workspace caches so setup works without writing to a restricted home directory.

## Data and methodology

- **Schedule and results:** maintained [nflverse schedule](https://github.com/nflverse/nfldata/blob/master/data/games.csv), fetched on the server with source URL and retrieval time. Source Eastern timestamps are converted using `America/New_York` to UTC; the frontend uses `America/Chicago`, including daylight-saving changes. Current season/week comes from the supplied schedule dates. All views retain the same `game_id`.
- **Player names and statistics:** maintained nflverse roster and weekly `stats_player` release datasets. Historical statistics include only completed regular-season games before the selected week or matchup cutoff and no later than the current time. Season production is descriptive, not a projection. Sample games and cutoffs are displayed.
- **Team comparison:** reproducible pregame records, scored/allowed points per game, and sourced rest days. No unsupported advanced efficiency metrics are filled in.
- **Models:** no trained or calibrated projection model is included. Means, outcome probabilities, fair odds, EV, and projected scores remain unavailable. Bookmaker break-even probabilities derive from actual American prices and are not model forecasts.
- **Analysis:** without AI, the button produces an explicitly labeled factual template using the actual matchup. An optional server-side AI adapter explains only the supplied evidence; it does not create model outputs.
- **Availability and weather:** no current injury report or weather feed is connected. Roof and stadium values are schedule fields; they do not establish game-day conditions.

The current 2026 Week 5 slate was **independently checked against ESPN**: all 15 season/week identities, opponents, UTC kickoff times, and venue names match. Verification queries individual game dates, caches successful comparisons, and never assumes success after blocked, incomplete, or conflicting responses. The default homepage shows a retryable unavailable state until the selected slate's independent comparison succeeds. An explicit “Inspect nflverse records” action opens real sourced records with a pending-verification label. “Refresh data” forces both source refresh and verification retry.

Rudebets and the previous website return HTTP 403 with Cloudflare error 1010. Their interfaces could not be inspected; this is an original implementation of the requested workflow. Current official sportsbook documentation was accessible and inspected. Required destinations have been saved in the environment draft; saving a draft does not apply the network policy.

Schedule failure produces a retryable “Schedule temporarily unavailable” state. Cached source data is timestamped; failed refreshes are reported rather than replaced with invented data. Explicit ESPN status fields provide live, upcoming, completed, postponed, and canceled states only after fixture verification. Without explicit status, an elapsed kickoff without a result is labeled awaiting result, never inferred as live.

## Connect providers

Supply credentials securely through server environment settings. The `.env.example` lists names only and is not loaded automatically.

- `ODDS_API_KEY`: The Odds API credential. The server requests FanDuel and DraftKings featured moneyline/spread/total prices, and event-specific player markets. Featured requests are shared and cached; prop requests occur on demand. Invalid credentials, quota exhaustion, missing events/markets, network failures, and stale cached prices have explicit states. No sportsbook account or wagering connection is required.
- `AI_API_KEY`: optional OpenAI credential, separate from odds. `AI_MODEL` defaults to `gpt-4.1-mini`. A provider failure falls back to a clearly labeled template with an explicit AI error.

The current official [NFL market definitions](https://the-odds-api.com/sports-odds-data/betting-markets.html#nfl-ncaaf-cfl-player-props-api), [bookmakers](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html), [API guide](https://the-odds-api.com/liveapi/guides/v4/), and [error codes](https://the-odds-api.com/liveapi/guides/v4/api-error-codes.html) were checked. The adapter covers all 15 requested passing, rushing, receiving, combined-production, and touchdown market keys. Actual subscription/event coverage determines which prices are available. Event prop requests can cost one credit per returned market; they are requested on demand and cached, while the slate shares one featured-odds request.

The provider's `player_tds_over` means touchdowns scored, over only. The “2+ touchdowns” research selector requires an actual Over 1.5 threshold; other thresholds retain their exact definitions. `player_1st_td` means first scorer in the game, not first scorer for a team. Rushing-plus-receiving touchdown season totals are labeled accordingly; they exclude passing and other unsupported touchdown categories. No historical touchdown total is treated as a scoring probability.

Credentials remain exclusively in the server environment. Provider errors are sanitized; browser responses contain no credential values or credential-bearing request URLs. Adding an odds key does not enable forecasts, injuries, weather, or AI.

Required runtime source hosts: `raw.githubusercontent.com`, `github.com`, and GitHub release redirect hosts supplied by the package-manager network preset. Odds requires `api.the-odds-api.com`; AI requires `api.openai.com`. Reference/cross-check documentation hosts are listed in the saved network draft. Review and save the draft in environment settings, then publish the environment to snapshot the prepared filesystem. Publication and fresh-task restoration are separate from current-instance validation.

## Saved research and parlays

Watchlists and drafts persist in this browser's local storage and do not sync across devices. Matchups and players can be saved without providers. Exact markets retain game, player, market definition, outcome, threshold, sportsbook timestamps, and source context. Refreshing saved prices matches the exact selection and keeps the original saved quote separately.

The parlay builder multiplies actual single-market decimal prices as a **synthetic calculation**, displaying total return and profit separately. It detects duplicates, missing/stale prices, repeated players, nested touchdown outcomes, incompatible selections, and same-game dependence. It does not assert a same-game joint hit probability or submit a bet. A cross-game product is shown only when actual input probabilities exist and is labeled an independence approximation.

## Validation

```bash
npm run build
npm test
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Unit tests cover exact market identity, odds math, dependency warnings, source cache behavior, timezone conversion, pregame cutoffs, and secret-safe provider failures. Browser validation uses the actual current schedule and sourced players; development fixtures remain confined to tests.
