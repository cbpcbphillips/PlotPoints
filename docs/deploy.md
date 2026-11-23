# Deploy runbook

Status: **written, not yet run against a real host.** The local steps (1-2) are verified; the API
image was rebuilt and smoke-tested locally on 2026-11-20. The image is host-agnostic and honours
`$PORT`.

**This runbook is for the first launch: a free, non-commercial passion-project site for friends**,
to spread by word of mouth and gather an audience. Ads are off (the frontend builds without
`VITE_ADS`), nothing is sold, the TMDB credit is in the footer, and TMDB's free non-commercial terms
cover it. The later commercial push (ads, better advertisers, the TMDB licence) is justified by the
demand this phase shows; its gates are in the roadmap ("Road to deploy").

## 0. The order to do things in (the parts only you can do are marked **you**)

| # | Step | Where |
|---|---|---|
| 1 | **you** Save TMDB's logo as `web/public/tmdb.svg` (their brand-assets page). Optional but expected | repo |
| 2 | **you** AWS inbox: update the uploader policy, create the API's put-only user, then `just test-inbox --write` (all PASS), then one real round trip | `external_setup.md` section 5b |
| 3 | **you** Accounts: a Google Cloud project with billing on (a card is required; a $5 budget alert covers you), a Cloudflare account, optionally the domain | consoles |
| 4 | Build and prove the image locally | section 1 |
| 5 | **you** Deploy the API to Cloud Run, copy its URL | section 3 |
| 6 | **you** Build the frontend with that URL and publish it to Cloudflare Pages; add the custom domain; add it to the API's CORS origins | section 4 |
| 7 | **you** Turn on Cloudflare Web Analytics, rebuild with `VITE_ANALYTICS=true` | section 4 |
| 8 | Run the smoke checklist, including a consent import and deletion on the live site | section 6 |
| 9 | **you** Invite a handful of friends; start the weekly routine | section 7 |

Decisions already made (change them in the roadmap if you disagree):

| Decision | Choice | Why |
|---|---|---|
| API host | Cloud Run, scale to zero, 1 GB, max 3 instances | Free at friends' traffic and capped so it cannot become a bill. First visit after idle waits a few seconds; Render Standard ($25 a month, 2 GB, always on) is the no-cold-start alternative |
| Frontend host | Cloudflare Pages | `web/public/_redirects` handles the single-page fallback; free and fast; the domain is one click if bought there |
| Consent storage | The S3 inbox (section 5b) before inviting anyone | The import box is ticked by default and sends anonymous ratings, which need somewhere real to land |
| Snapshot refresh | Monthly, by hand | `just snapshot`, then rebuild and redeploy |
| Audience measurement | Cloudflare Web Analytics | Cookieless and free; the Privacy page says so when `VITE_ANALYTICS=true` |

Two pieces deploy separately:

- **API**: the Docker image from `api/Dockerfile`, with one snapshot baked in. Needs no database and
  no AWS read credential.
- **Frontend**: the static files in `web/dist/`.

## 1. Build and prove it locally

```powershell
just snapshot                      # only if the data changed; reads Snowflake
just api-build                     # stages the newest snapshot, builds the image
just api-run                       # http://localhost:8000
```

Check `http://localhost:8000/health` and `/meta` (the snapshot version should match the one you
built), then `/film/603` and `/film/603/similar`.

Frontend against that container, the production path (no Vite proxy):

```powershell
cd web
$env:VITE_API_URL = "http://localhost:8000"
npm run build
npm run preview
```

The container must allow the preview origin: run it with
`PLOTPOINTS_CORS_ORIGINS=http://localhost:4173`.

## 2. Configuration

| Where | Variable | Value |
|---|---|---|
| API | `PLOTPOINTS_CORS_ORIGINS` | the deployed frontend origin(s), comma-separated, e.g. `https://watchplotpoints.pages.dev,https://watchplotpoints.com,https://www.watchplotpoints.com` |
| API | `PLOTPOINTS_INBOX` | `s3` on the host (the image defaults to `local`, which an ephemeral disk loses on restart) |
| API | `INBOX_AWS_ACCESS_KEY_ID`, `INBOX_AWS_SECRET_ACCESS_KEY` | the put-only key from `external_setup.md` section 5b. **Secrets**, not plain env vars |
| API | `AWS_S3_BUCKET`, `AWS_REGION` | the bucket name and its region |
| API | `TMDB_API_KEY` | optional secret; without it `/match` is snapshot-only (films the catalog lacks are skipped) |
| Frontend build | `VITE_API_URL` | the API's public URL (no trailing slash) |
| Frontend build | `VITE_FEEDBACK_URL` | optional `mailto:` or form link for the footer |
| Frontend build | `VITE_ANALYTICS` | `true` once Cloudflare Web Analytics is on, so the Privacy page says so |
| Frontend build | `VITE_ADS` | leave unset: no ads in the free launch |

## 3. API host: Cloud Run (recommended) or Render

The image listens on `$PORT`, is stateless, and loads its snapshot at start-up. **Measured locally
(2026-11-20): 2.1 s from `docker run` to a healthy `/health`, then about 0.1 s per recommendation,
and ~380 MB of memory.** Cloud Run adds an image pull and a slower, shared CPU, so expect a first
visit after idle to take roughly 5-10 seconds (an estimate: time it on the real service). The app
shows "Waking up the server" after 3.5 s. Pay for `--min-instances 1` only if that annoys people.

*Shortcut:* `just deploy-api` runs the steps below from your `.env` settings (section 10; add
`-DryRun` to preview). The commands are kept here so you can see, and run, each one yourself.

### Cloud Run, step by step (PowerShell)

Prerequisites (you): a Google Cloud project with billing on, and the `gcloud` CLI signed in.
Set these once for the session:

```powershell
$PROJECT = "your-gcp-project-id"; $REGION = "us-central1"; $BUCKET = "your-s3-bucket"
$IMG = "$REGION-docker.pkg.dev/$PROJECT/plotpoints/api:latest"
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

1. **Registry and push** (after `just api-build`):

```powershell
gcloud artifacts repositories create plotpoints --repository-format=docker --location=$REGION
gcloud auth configure-docker "$REGION-docker.pkg.dev"
docker tag plotpoints-api $IMG
docker push $IMG
```

2. **Secrets.** *Shortcut:* with the values already in `.env`, `just gcp-secrets -DryRun` lists what it
   will do (names only) and `just gcp-secrets` stores them in Secret Manager and lets the Cloud Run
   service account read exactly those three. Or by hand (paste each value when prompted; nothing
   lands in your shell history or the repo):

```powershell
foreach ($name in "inbox-access-key-id", "inbox-secret-access-key", "tmdb-api-key") {
  $v = Read-Host "Value for $name" -AsSecureString
  $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($v))
  $plain | gcloud secrets create $name --data-file=-
}
```

   Then let the service read them:
   `gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com" --role=roles/secretmanager.secretAccessor`

3. **Deploy**, with a hard ceiling on instances so a traffic spike cannot become a surprise bill.
   *Shortcut:* `just deploy-api` does this step (and the build and push) for you. By hand, put the
   plain settings in a small file, because `gcloud.cmd` runs through `cmd.exe`, which mangles `|` and
   `^` in a command-line value, and the CORS value contains commas:

```powershell
@"
PLOTPOINTS_INBOX: "s3"
AWS_S3_BUCKET: "$BUCKET"
AWS_REGION: "us-east-1"
PLOTPOINTS_CORS_ORIGINS: "https://watchplotpoints.pages.dev,https://watchplotpoints.com,https://www.watchplotpoints.com"
PLOTPOINTS_TRUSTED_PROXIES: "1"
"@ | Set-Content -Encoding ascii env.yaml
gcloud.cmd run deploy plotpoints-api --image $IMG --region $REGION --allow-unauthenticated `
  --cpu 1 --memory 1Gi --cpu-boost --concurrency 20 --timeout 60 `
  --min-instances 0 --max-instances 2 --env-vars-file env.yaml `
  --set-secrets "INBOX_AWS_ACCESS_KEY_ID=inbox-access-key-id:latest,INBOX_AWS_SECRET_ACCESS_KEY=inbox-secret-access-key:latest,TMDB_API_KEY=tmdb-api-key:latest"
Remove-Item env.yaml
```

   It prints the service URL (`https://plotpoints-api-....run.app`): that is `VITE_API_URL`. Change
   `AWS_REGION` to your bucket's region and the CORS origins to your real frontend addresses. To
   change one value later, edit the file and deploy again, or:
   `gcloud.cmd run services update plotpoints-api --update-env-vars PLOTPOINTS_TRUSTED_PROXIES=2`
   (one value without commas needs no file).

4. **A budget alert** (console: Billing -> Budgets & alerts -> create a $5 monthly budget with email
   alerts at 50% and 100%). At friends' traffic the service should cost $0; the alert tells you if
   that stops being true.

5. **Keep it warm** (so a friend's first visit rarely waits for a cold start). Cloud Run keeps an idle
   instance for a while after its last request and bills only while a request is being handled, so a
   ping every few minutes keeps one ready at almost no cost. Cloud Scheduler's free allowance covers
   one job:

```powershell
gcloud services enable cloudscheduler.googleapis.com
$URL = gcloud run services describe plotpoints-api --region $REGION --format "value(status.url)"
gcloud scheduler jobs create http plotpoints-warm --location $REGION `
  --schedule "*/8 * * * *" --uri "$URL/health" --http-method GET
```

   Google does not promise an instance survives, so an occasional cold start can still happen; time
   a visit after an hour of quiet to see how it behaves. The pings appear in the log as
   `GET /health`; `just usage` leaves them out. If the wait is still too long, set
   `--min-instances 1` (a small steady cost) or move to an always-on host (see the roadmap).

### Render instead

Create a Web Service from the pushed image on the **Standard** plan (2 GB, $25 a month, always on).
Set the same environment variables (Render's dashboard marks them secret). Free and Starter (512 MB)
are too small for a ~380 MB process, and the free tier sleeps after 15 minutes.

## 4. Frontend host: Cloudflare Pages

Single-page app: `web/public/_redirects` already sends every path to `index.html`, so a refresh on
`/film/603` works.

*Check first:* Cloudflare has been merging Pages into Workers. Before running the commands below,
look at what the dashboard offers for a new static site (Workers & Pages -> Create) and use the
deploy command it shows if it differs from `wrangler pages deploy`; the build output (`web/dist`)
and the environment variables are the same either way.

**Without connecting GitHub (simplest; nothing unfinished gets published):**

```powershell
cd web
$env:VITE_API_URL = "https://plotpoints-api-XXXX.run.app"   # the Cloud Run URL
$env:VITE_FEEDBACK_URL = "mailto:you@example.com"            # optional
npm run build
npx wrangler pages deploy dist --project-name watchplotpoints
```

The first run opens a browser to sign in to Cloudflare. Your site is then at
`https://watchplotpoints.pages.dev` (use that as the first CORS origin).

**Or connect the repository** (deploys on every push): Pages -> Create project -> connect GitHub ->
root directory `web`, build command `npm run build`, output `dist`, and the `VITE_*` variables from
section 2 under Settings -> Environment variables, plus `NODE_VERSION=20`.

**Domain.** Buying it at Cloudflare Registrar (sold at cost, no markup) makes the rest one click:
Pages project -> Custom domains -> add it. Then add the domain to `PLOTPOINTS_CORS_ORIGINS`.

**Analytics.** Pages project -> Metrics -> enable Web Analytics (cookieless, no consent banner
needed). Then rebuild with `VITE_ANALYTICS=true` so the Privacy page mentions it.

Remember: a client-rendered page gives search engines nothing. If film pages should be findable,
they need prerendering, which is a separate decision for after the launch.

## 5. Shipping new data

Rebuild the image (`just snapshot`, `just api-build`, push, redeploy). The running API never reads
the warehouse.

## 6. Smoke checklist after deploy

- [ ] Security headers on the site (`curl.exe -I https://watchplotpoints.com/`): a `content-security-policy`,
      `x-frame-options: DENY` and HSTS. If the API address changes, update `connect-src` in
      `web/public/_headers` (see `docs/security.md`)
- [ ] `/docs` and `/openapi.json` on the API answer 404

- [ ] `GET /health` and `/meta` report the expected snapshot version and title count
- [ ] Landing page loads; importing a Letterboxd export returns recommendations
- [ ] A recommendation links to `/film/<id>`; refreshing that URL still loads the page
- [ ] An unknown id (`/film/999999999`) shows the not-found state, not a blank page
- [ ] Browser console shows no CORS errors
- [ ] API logs show one line per request (method, route template, status, ms) and no film titles,
      usernames or tokens
- [ ] About page carries the TMDB sentence and logo, and the JustWatch attribution- [ ] On the live site: import with the consent box ticked, then use Privacy -> "Delete with token";
      on your machine `just user-ingest` lands and then removes it (see `external_setup.md` 5b, step 5)
- [ ] `just test-inbox --write` still PASSes against the key the live service uses- [ ] Rate limits: from your own machine, send about 130 `POST /recommend` requests in a minute and
      confirm the last few get a 429; then check `PLOTPOINTS_TRUSTED_PROXIES` matches your setup (1
      for Cloud Run alone, 2 behind Cloudflare). If every visitor shares one limit, the wrong header
      entry is being read.
- [ ] The API starts with `PLOTPOINTS_INBOX=s3` only if both `INBOX_AWS_*` secrets and
      `AWS_S3_BUCKET` are set: a missing one stops the container at start-up with a message naming
      it (check `gcloud run services logs read`)

## 7. Running the launch

- **Weekly:** `just user-ingest` (lands consented imports, applies deletion requests, purges landed
  files). The Privacy page promises removal "the next time the pipeline runs", so do not let it
  slip past a week or two. Check the Cloud Run request count and the budget alert while you are there.
- **Monthly:** `just snapshot`, `just api-build`, push and redeploy (section 3 step 1 and 3), so new
  films and fresh streaming availability reach the site.
- **When someone asks to be removed without a token:** there is no way to find their data (it is
  anonymous by design), so say so plainly: the deletion token is the only handle. This is the cost
  of storing nothing that identifies a person, and the Privacy page already explains it.
- **Measuring demand:** Cloudflare Analytics gives visits, countries and devices. The API's own log
  gives the rest, with no identifiers. Pull it and summarise it:

```powershell
gcloud run services logs read plotpoints-api --region $REGION --limit 20000 | just usage
```

  One block per day: requests and server errors, `/recommend` speed, imports (export or username),
  how many kept their ratings, deletions, group and browse use, how often the comfort-zone pick
  appears, and how thin or thick people's histories are. It cannot count unique or returning
  people, because nothing in the log could tell them apart; that is the price of keeping the log
  anonymous, and Cloudflare covers visits.
  Cloud Run keeps request logs for 30 days by default, so pull them at least monthly.

## 8. Already built into the app (so you do not have to)

- **Cache headers.** The public, same-for-everyone GETs (`/meta`, `/facets`, `/keywords`, `/people`,
  `/film/{id}`, `/film/{id}/similar`) carry `Cache-Control: public, max-age=3600`, so browsers and
  Cloudflare serve repeat views without reaching the API. 404s, POSTs and `/health` are never cached.
  `just api` turns this off locally (`PLOTPOINTS_CACHE_SECONDS=0`) so you always see fresh data. After
  a monthly data refresh, people may see the old snapshot for up to an hour.
- **Per-caller limits** (per minute, per instance): `/recommend` 120, `/franchises` 60,
  `/film/{id}/for-me` 120, `/profile` 60, plus the existing ones on Letterboxd imports, `/match`,
  `/consent` and `/delete`. The caller is read from the *end* of `X-Forwarded-For`, which a caller
  cannot forge; `PLOTPOINTS_TRUSTED_PROXIES` says how many proxies add to that header (1 for Cloud Run
  alone, the default; 2 once Cloudflare proxies the API in front of it).
- **A cost ceiling.** `--max-instances 2` caps the compute that can ever run at once. A Google budget
  alert warns but does **not** stop spending, so that cap is what keeps a flood from becoming a
  surprise bill.
- **Saved recommendations.** A returning visitor's last list is kept in their browser and shown at
  once while a fresh one loads, which also hides a cold start. It goes when the profile does.

## 9. Watching it: uptime, traffic, alerts

The full guide to reading the dashboard is in `docs/dashboard.md`; the security review and the
site's headers are in `docs/security.md`.

Three layers, all free at this scale:

1. **Google Cloud Monitoring uptime check** (alerts you by email if the API stops answering).
   Console -> Monitoring -> Uptime checks -> Create: protocol HTTPS, host = the Cloud Run URL without
   `https://`, path `/health`, every 5 to 15 minutes. Then Create alert -> notify your email. (A free
   outside monitor such as UptimeRobot works too, and keeps working if Google is the thing that is
   down.) Do the same for the site's address if you like.
2. **Cloudflare Web Analytics** for visits, countries and devices, and Cloudflare's own dashboard for
   cache hits and blocked traffic.
3. **Your own commands**, which read the live site without anyone logging in anywhere:

```powershell
just status                              # PASS/WARN/FAIL: API up, data version, cache headers, CORS,
                                         # the site loads, deep links work, certificates have time left
just usage < api.log                     # daily numbers from a saved log
just dashboard --gcloud --status --open  # pull the live log, run the checks, open a private page
```

`just status` and `just dashboard` read `PLOTPOINTS_API_URL` and `PLOTPOINTS_SITE_URL` from `.env`;
`--gcloud` needs the `gcloud` CLI and `GCP_REGION`. The dashboard is one static HTML file at
`data/reports/dashboard.html`: requests, server errors, speed, imports, kept ratings, group and
browse use, a chart and a table for each day, and the live check results. It never leaves your
machine, so there is nothing to log in to or to protect. It cannot show unique or returning people
(the log has nothing that could tell them apart); Cloudflare covers visits.

**A weekly routine** (ten minutes): `just status`; `just dashboard --gcloud --status --open`;
`just user-ingest`; glance at the Billing page. Monthly: refresh the snapshot and redeploy.

## 10. The commands, once the accounts exist

```powershell
winget install Google.CloudSDK            # one time; then: gcloud auth login
# put GCP_PROJECT, GCP_REGION, PLOTPOINTS_CORS_ORIGINS in .env (see .env.example)
just deploy-api -DryRun                   # every command, none of them run
just deploy-api                           # build, push, deploy; prints the API address
# put that address in .env as PLOTPOINTS_API_URL, and the site's as PLOTPOINTS_SITE_URL
just deploy-web -DryRun                   # then without -DryRun
just status
```

`scripts/deploy_api.ps1` and `scripts/deploy_web.ps1` wrap the commands in sections 3 and 4 with the
same settings. They have only been run in `-DryRun` mode (no cloud account yet), so read the dry run
before the first real one.
