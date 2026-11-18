# Running the API and frontend locally

The API serves recommendations from an in-memory **snapshot** (no Snowflake in the request path);
the frontend is a React + Vite app that talks to it. Run both and open <http://localhost:5173>.

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

Endpoints: `GET /health`, `GET /meta`, `POST /import/letterboxd`, `POST /match`, `POST /recommend`,
`POST /franchises`, `POST /consent`, `POST /delete`.

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
| `npm test` | Vitest unit tests (Letterboxd export parser) |
| `npm run build` | Typecheck + production build into `web/dist/` |
| `npm run preview` | Serve the production build locally |

## Configuration

| Variable | Used by | Default | Purpose |
|---|---|---|---|
| `PLOTPOINTS_SNAPSHOT_DIR` | API | newest under `data/snapshots/` | Pin a specific snapshot folder |
| `PLOTPOINTS_DATA_DIR` | API, scripts | `data` | Root for snapshots, checkpoints, local inbox |
| `PLOTPOINTS_CORS_ORIGINS` | API | `http://localhost:5173` | Comma-separated allowed origins (needed when the frontend is hosted elsewhere) |
| `PLOTPOINTS_INBOX` | API | `local` | `local` writes consented imports under `data/inbox/`; `s3` writes to the bucket |
| `INBOX_AWS_ACCESS_KEY_ID` / `INBOX_AWS_SECRET_ACCESS_KEY` | API (inbox `s3` mode) | — | Write-only S3 credential; also needs `AWS_S3_BUCKET`, `AWS_REGION` |
| `VITE_API_URL` | Frontend build | `/api` | Absolute API URL for a deployed frontend, e.g. `https://plotpoints-api.example.run.app` |

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
