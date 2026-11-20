# Frontend

The frontend is a React + Vite + TypeScript + Tailwind app in `web/`. It talks to a small FastAPI
service that serves recommendations from an in-memory **snapshot** (no Snowflake in the request
path). Run both and open <http://localhost:5173>. To get data into the snapshot in the first place,
see [pipeline.md](pipeline.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just) (`winget install Casey.Just`)
- Node.js 20+ and npm
- Docker Desktop, only if you want the containerised API (`just api-build` / `just api-run`)
- A filled-in `.env` (see `.env.example` and [external_setup.md](external_setup.md)) — **only
  needed to build a snapshot**, not to run the API afterwards

## 1. One-time setup

```powershell
uv sync                       # Python deps + .venv
cd web; npm install; cd ..    # frontend deps
```

## 2. Build a snapshot (first run, and whenever the data changes)

The API refuses to start without a snapshot. It reads `data/snapshots/LATEST`, which points at the
newest versioned folder. This step queries Snowflake (`MART`) once:

```powershell
just snapshot
```

Output goes to `data/snapshots/<version>/` (~49 MB of float16 vectors plus catalog metadata). Add
`--upload` to also push it to S3. The `transform` Airflow DAG produces snapshots too.

## 3. Start the API

```powershell
just api
```

- Serves on <http://127.0.0.1:8000> with auto-reload.
- Interactive docs: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health>; loaded snapshot version: `/meta`.

Endpoints: `GET /health`, `GET /meta`, `GET /facets`, `GET /people`, `GET /keywords`,
`GET /film/{id}`, `GET /film/{id}/similar`, `POST /film/{id}/for-me`, `POST /import/letterboxd`,
`POST /match`, `POST /recommend`, `POST /franchises`, `POST /profile`, `POST /consent`,
`POST /delete`.

## 4. Start the frontend

In a second terminal:

```powershell
cd web
npm run dev
```

- App on <http://localhost:5173>.
- Vite proxies `/api/*` to `http://127.0.0.1:8000` (stripping the `/api` prefix), so the browser
  stays on one origin and no CORS setup is needed locally. **Start the API first**, or requests
  will fail.

Other frontend commands:

| Command | What it does |
|---|---|
| `npm run typecheck` | TypeScript check |
| `npm test` | Vitest unit tests (export parser, import helpers, settings, browse URL model, group names) |
| `npm run build` | Typecheck + production build into `web/dist/` |
| `npm run preview` | Serve the production build locally |

## Pages

| Route | What it is |
|---|---|
| `/` | First visit: import a Letterboxd export or username. Returning visitors go to `/for-you` |
| `/for-you` | Top pick and why, the comfort-zone pick, the films shaping your picks, other recommendations, branch out |
| `/browse`, `/browse/:kind/:value` | Genre, theme (keyword), director, actor, decade. More values and kinds in the query string, e.g. `/browse/genre/Romance?genre=Comedy&genre_mode=any&era=1990`; all-of is the default, `*_mode=any` means either |
| `/together` | Watch together: add people, then a list built by taking turns |
| `/franchises`, `/streaming` | Series shelves, best matches on your streaming services |
| `/film/:tmdbId` | Film details, themes, cast, closest films you rated, similar films |
| `/import`, `/settings`, `/about`, `/privacy` | Profile and history, display settings, credits, data and deletion |

**Settings** (`/settings`, stored in `pp-settings`, applied as attributes on `<html>` by
`lib/settings.ts` and again before first paint by the script in `index.html`): `data-theme`,
`data-contrast="more"`, `data-reading="dyslexia"`, `data-motion="reduce"`, and the root font size.

**Navigation and focus.** On a route change focus moves to the page heading (the app waits briefly
for it to load), and `<main>` shows no focus ring. A skip link comes first in the tab order. On
phones the top bar shows four tabs and a "More" menu.

**Where data lives.** The profile (`pp-profile`) and any group members (`pp-group`) stay in the
browser. The consent box on import is ticked by default and sends only film ids and ratings,
anonymously (see [roadmap](roadmap.md) for the GDPR caveat).

## Configuration

| Variable | Used by | Default | Purpose |
|---|---|---|---|
| `PLOTPOINTS_SNAPSHOT_DIR` | API | newest under `data/snapshots/` | Pin a specific snapshot folder |
| `PLOTPOINTS_DATA_DIR` | API, scripts | `data` | Root for snapshots, checkpoints, local inbox |
| `PLOTPOINTS_CORS_ORIGINS` | API | `http://localhost:5173` | Comma-separated allowed origins (needed when the frontend is hosted elsewhere) |
| `PLOTPOINTS_INBOX` | API | `local` | `local` writes consented imports under `data/inbox/`; `s3` writes to the bucket |
| `INBOX_AWS_ACCESS_KEY_ID` / `INBOX_AWS_SECRET_ACCESS_KEY` | API (inbox `s3` mode) | — | Write-only S3 credential; also needs `AWS_S3_BUCKET`, `AWS_REGION` |
| `TMDB_API_KEY` | API (optional) | read from `.env` locally | Lets `/match` ask TMDB about import rows the snapshot cannot match (re-dated films, TV, films outside the catalog). Without it matching is snapshot-only |
| `VITE_API_URL` | Frontend build | `/api` | Absolute API URL for a deployed frontend, e.g. `https://plotpoints-api.example.run.app` |
| `VITE_ADS` | Frontend build | off | `true` renders the ad slots (rails, leaderboard, in-feed). Leave it off for the friends-only launch; ads need a TMDB commercial licence first |
| `VITE_ANALYTICS` | Frontend build | off | `true` once Cloudflare Web Analytics is on; adds a "Visit counts" paragraph to the Privacy page |
| `VITE_FEEDBACK_URL` | Frontend build | none | A `mailto:` or form URL; shows "Send feedback" in the footer when set |

Put the two `VITE_` switches in `web/.env.local` to try them in dev. TMDB's logo is picked up from
`web/public/tmdb.svg` if you add the file (their brand asset, not in the repo); without it the
footer and About page show the text credit only.

Locally you need none of these; the defaults work.

## Running the API in Docker

Bakes the newest snapshot into the image, so the container needs no database or credentials:

```powershell
just api-build    # stages the snapshot into api/snapshot/ and builds the image
just api-run      # http://localhost:8000
```

The image honours `$PORT` (Cloud Run / Render). To ship new data, rebuild.

## Tests

```powershell
just test                  # offline: scoring + API (uses the API dependency group)
just test -m snowflake     # also runs the numpy-vs-SQL equivalence check (needs live Snowflake)
```

## Troubleshooting

- **`FileNotFoundError: ... LATEST`** on API start — no snapshot yet; run `just snapshot`.
- **Frontend shows network errors / 502 on `/api/...`** — the API isn't running on port 8000.
- **Port 8000 or 5173 already in use** — stop the other process; the Vite proxy target is hard-coded to
  `127.0.0.1:8000` in `web/vite.config.ts`, so change both if you move the API.
- **Use `127.0.0.1`, not `localhost`, when calling the API directly** on Windows: `localhost` tries
  IPv6 first and adds ~2 s per request.
- **CORS errors against a deployed API** — add the frontend's origin to `PLOTPOINTS_CORS_ORIGINS`.
