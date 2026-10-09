# Deploy Fieldwork on Render

The React frontend and FastAPI API run together as one Python web service. Render builds the React files into `dist`, and FastAPI serves them alongside `/api`.

## Upload prerequisite

Render deploys files from GitHub. Publishing the Codex cloud environment preserves the development workspace; it does not upload these application files to the connected GitHub repository. The prepared source must be committed and pushed to `kriltyun/Ask-ChatGPT` on `main` before the first deployment. Do not upload `.env` files, credentials, dependencies, caches, or generated build output.

## Manual service settings

Select the connected `kriltyun/Ask-ChatGPT` repository in **New Web Service**, then enter:

| Field | Setting |
| --- | --- |
| Name | `fieldwork-nfl`, or another available name |
| Language | Python 3 |
| Branch | `main`, after the source upload creates it |
| Region | Keep the selected region |
| Root Directory | Leave blank |
| Compute | Free for the initial deployment |
| Health Check Path, under Advanced | `/api/health` |

Build command:

```sh
pip install -r requirements.txt && npm ci --include=dev && npm run build
```

Start command:

```sh
python -m uvicorn server.main:app --host 0.0.0.0 --port $PORT
```

The start command binds the port supplied by Render. Including development dependencies during the build installs Vite, even if the hosting environment uses `NODE_ENV=production`. The Codex-specific `scripts/setup.sh` and `scripts/start.sh` assume workspace caches and a local `.venv`; use the direct commands above for Render.

## Environment variables

Add each through Render's **Environment Variables** fields:

| Key | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.12.14` |
| `NODE_VERSION` | `24.19.0` |
| `ODDS_API_KEY` | Your actual provider key, entered securely in Render |

These Python and Node versions match the validated cloud environment. The credential already bound to Codex is scoped to Codex's network proxy; it does not transfer to Render. Never copy the injected proxy placeholder to Render. Enter the actual provider credential yourself. Optional AI uses a separate `AI_API_KEY`; it is not required for factual templates.

`render.yaml` mirrors these settings for a Render Blueprint deployment. Its `sync: false` credential entry asks for a secure value; the file contains no credential values. The manual web-service form does not automatically import that file.

## Deploy and verify

Once the source files are present on GitHub and the settings are complete, select **Deploy web service**. Wait for a successful build and live service status, then open the HTTPS URL provided by Render.

Confirm the homepage loads, the selected schedule is independently verified, and **Data & model status** shows the actual odds connection. Open one upcoming matchup's **Odds comparison** tab to confirm real prices and timestamps. Successful startup alone does not prove provider authentication or event coverage.

The Free plan shown in Render sleeps after inactivity and has no persistent disk. Source caches can be recreated; watchlists and drafts remain local to the visitor's browser. A sleeping service may need time to start on the first visit.

The deployed website is [fieldwork-nfl.onrender.com](https://fieldwork-nfl.onrender.com/). For subsequent updates, push the source to `main` and check Render's deployment status. If automatic deployments are disabled, select **Manual Deploy → Deploy latest commit**. Wait for **Live**, then reload the website. Verify the changed behavior as well as the health endpoint; a successful build alone does not prove updated source data or sportsbook coverage.
