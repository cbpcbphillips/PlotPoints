# The dashboard: how to watch PlotPoints

Three places show how the live site is doing. Each answers a different question, and none of them
needs anyone to log in to anything on your behalf.

| Question | Where | Cost |
|---|---|---|
| Is it up, and is the API healthy? | `just status`, and the Google Cloud uptime check (every 15 minutes, emails you) | free |
| Is anyone using it, and which features? | **The private dashboard** (`just dashboard`), built from the API's own anonymous log | free |
| How many people visit, from where, on what device? | Cloudflare Web Analytics (dashboard.cloudflare.com, Web Analytics) | free |
| Is it fast, and how many instances ran? | Google Cloud console, Cloud Run, the service's Metrics tab | free |
| What is it costing? | Google Cloud console, Billing, Budgets | free |

The first two rows are this repo's tools. The rest are the providers' own consoles; the dashboard
links to them instead of pretending to hold their numbers.

## Run it

```powershell
just dashboard --gcloud --status --open
```

This pulls the live Cloud Run log with `gcloud`, runs the same live checks as `just status`, writes
`data/reports/dashboard.html` and opens it. The file is one self-contained page (no scripts, no
outside requests, light and dark, every chart also a table). It lives under `data/`, which git
ignores, and it never leaves your machine: there is nothing to host and nothing to protect.

| Flag | What it does |
|---|---|
| `--gcloud` | Pull the live log. Needs the `gcloud` CLI, signed in, and `GCP_REGION` in `.env` (or `--region`) |
| `--log FILE` | Build from a saved log instead (also: pipe a log in on standard input) |
| `--status` | Add the live health checks (needs `PLOTPOINTS_API_URL` and `PLOTPOINTS_SITE_URL` in `.env`) |
| `--open` | Open the page in your browser when it is done |
| `--limit N` | How many log lines to pull (default 20,000) |
| `--service`, `--region` | Only if the service is not named `plotpoints-api` or the region is not in `.env` |

For plain text in the terminal instead of a page: `just usage api.log`, or
`gcloud run services logs read plotpoints-api --region us-central1 --limit 20000 | just usage`.

If `gcloud` is not found, a terminal opened before it was installed does not have it on `PATH`;
open a new one. On Windows PowerShell use `gcloud.cmd` if scripts are blocked.

## Reading the page

**Cards (the totals over the days in the log)**

| Card | Meaning |
|---|---|
| Requests | API calls from the site. Health pings (the uptime check and the keep-warm ping) are left out |
| Server errors | Responses in the 500s, and their share of requests. Should be 0 or close to it |
| Slowest day, /recommend p95 | The slowest 5% of recommendation requests on the worst day. About 0.5-0.9 s is normal; a cold start adds a few seconds on the first request |
| Imports | Letterboxd imports (by username or by export) and the share where the person left "keep my ratings" ticked |
| Group lists | Recommendation requests for two or more people (Together) |
| Browse lists | Recommendation requests that used a genre, theme, director, actor or decade filter |

**Charts and the Per day table.** Requests per day; imports per day split into kept and not kept;
and recommendation requests split into main list, group and browse. The table under them holds the
same numbers plus `/recommend` p50 and p95 in milliseconds and how often the comfort-zone pick was
shown on a main list (it should be near 100%).

**Live checks.** The same PASS / WARN / FAIL rows as `just status`: API health, data version and age,
a film endpoint, filters, an unknown film being a 404 that is not cached, CORS, the site loading, a
film deep link, and certificate days left.

## What the numbers can and cannot tell you

- **They are counts, not people.** The log holds no usernames, titles, film ids, ratings, tokens or
  addresses (see `api/events.py`). Counts such as a history size are stored as ranges ("15-49").
  That is deliberate, and it means **the dashboard cannot say how many different people came or
  whether anyone returned.** Cloudflare Web Analytics covers visits and countries; for returning use
  rely on feedback and on whether the import count keeps growing.
- **Your own testing is in there.** Early numbers are mostly you. There is no way to filter yourself
  out, because nothing identifies anyone. Judge growth by the trend after friends arrive.
- **Imports are the best demand signal.** Someone who imported a history meant to use the app. Watch
  imports per day, the kept-ratings share, and whether group and browse lists appear at all.
- **The log is short-lived.** Cloud Run keeps logs about 30 days, and `--limit 20000` lines is
  roughly 7,000 requests. Run the dashboard at least weekly, and save the page if you want a record
  (copy `dashboard.html` somewhere under a dated name; it is a single file).
- **Lines per request.** Each request is one line with a route and time (for example
  `GET /facets 200 46ms`); the route is always the template (`/film/{tmdb_id}`), never the real
  path. Google's own request line, and (until the API image is redeployed with `--no-access-log`)
  uvicorn's, also appear in the raw log; the dashboard ignores them.

## A weekly routine (ten minutes)

1. `just status` (or the live checks inside the dashboard).
2. `just dashboard --gcloud --status --open`: errors near zero, imports moving, nothing slow.
3. `just user-ingest` to land consented imports and apply deletion requests. The Privacy page
   promises removal "the next time the pipeline runs", so do not let it slip past a week or two.
4. Google Cloud console, Billing: confirm the spend and the budget alert.
5. Cloudflare Web Analytics: visits, top countries, top pages.

Monthly: refresh the snapshot and redeploy the API (`docs/deploy.md`, section 7).

## Alerts

- **Google Cloud uptime check** on `/health` of the API, every 15 minutes, with an email alert.
  This is the only thing that tells you the site is down while you are not looking.
- **The budget alert** (Billing, Budgets) emails you as spend crosses 10%, 50% and 100%.
- **`just status`** is the manual version of both and is worth running before you share the link
  with anyone new.

## When it looks wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| "0 days of log" or "gcloud returned no log lines" | `GCP_REGION` missing from `.env`, wrong service name, or not signed in to `gcloud` | Set `GCP_REGION=us-central1`, or pass `--region`; run `gcloud auth list` |
| "gcloud is not installed or not on PATH" | Terminal opened before the install | Open a new terminal |
| Live checks show WARN "Set PLOTPOINTS_API_URL and PLOTPOINTS_SITE_URL" | The two addresses are not in `.env` | Add them (the API's Cloud Run address and `https://watchplotpoints.com`) |
| `site loads` FAIL with HTTP 403 | A script sending the default Python user agent is blocked by Cloudflare | Already handled in `src/status_check.py` (it sends its own agent) |
| Requests per day look low | Health pings are excluded by design, and only the most recent `--limit` lines are pulled | Raise `--limit`, or build from a saved log |
| A cold-start day shows a high p95 | Cloud Run scaled to zero; the first request waits a few seconds | Normal; the keep-warm ping and the "Waking up the server" message exist for this |

## Where it is built

`src/dashboard.py` builds the page; `src/usage_report.py` parses the log and does the arithmetic
(`just usage` uses it directly); `api/events.py` defines the anonymous events the API writes;
`src/status_check.py` runs the live checks. Tests: `tests/test_dashboard.py`,
`tests/test_usage_report.py`, `tests/test_status_check.py`, `tests/test_events.py`.
