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
| API | `PLOTPOINTS_CORS_ORIGINS` | the deployed frontend origin(s), comma-separated, e.g. `https://plotpoints.pages.dev,https://yourdomain.com` |
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

2. **Secrets** (paste each value when prompted; nothing lands in your shell history or the repo):

```powershell
foreach ($name in "inbox-access-key-id", "inbox-secret-access-key", "tmdb-api-key") {
  $v = Read-Host "Value for $name" -AsSecureString
  $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($v))
  $plain | gcloud secrets create $name --data-file=-
}
```

   Then let the service read them:
   `gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com" --role=roles/secretmanager.secretAccessor`

3. **Deploy**, with a hard ceiling on instances so a traffic spike cannot become a surprise bill:

```powershell
gcloud run deploy plotpoints-api --image $IMG --region $REGION --allow-unauthenticated `
  --cpu 1 --memory 1Gi --cpu-boost --concurrency 20 --timeout 60 `
  --min-instances 0 --max-instances 3 `
  --set-env-vars "^|^PLOTPOINTS_INBOX=s3|AWS_S3_BUCKET=$BUCKET|AWS_REGION=us-east-1|PLOTPOINTS_CORS_ORIGINS=https://plotpoints.pages.dev,https://yourdomain.com" `
  --set-secrets "INBOX_AWS_ACCESS_KEY_ID=inbox-access-key-id:latest,INBOX_AWS_SECRET_ACCESS_KEY=inbox-secret-access-key:latest,TMDB_API_KEY=tmdb-api-key:latest"
```

   It prints the service URL (`https://plotpoints-api-....run.app`): that is `VITE_API_URL`. Change
   `AWS_REGION` to your bucket's region and the CORS origins to your real frontend addresses. The
   `^|^` at the start of the variables switches gcloud's separator from a comma to `|`, because the
   CORS value itself contains commas. To change one later:
   `gcloud run services update plotpoints-api --update-env-vars "^|^PLOTPOINTS_CORS_ORIGINS=https://a,https://b"`.

4. **A budget alert** (console: Billing -> Budgets & alerts -> create a $5 monthly budget with email
   alerts at 50% and 100%). At friends' traffic the service should cost $0; the alert tells you if
   that stops being true.

### Render instead

Create a Web Service from the pushed image on the **Standard** plan (2 GB, $25 a month, always on).
Set the same environment variables (Render's dashboard marks them secret). Free and Starter (512 MB)
are too small for a ~380 MB process, and the free tier sleeps after 15 minutes.

## 4. Frontend host: Cloudflare Pages

Single-page app: `web/public/_redirects` already sends every path to `index.html`, so a refresh on
`/film/603` works.

**Without connecting GitHub (simplest; nothing unfinished gets published):**

```powershell
cd web
$env:VITE_API_URL = "https://plotpoints-api-XXXX.run.app"   # the Cloud Run URL
$env:VITE_FEEDBACK_URL = "mailto:you@example.com"            # optional
npm run build
npx wrangler pages deploy dist --project-name plotpoints
```

The first run opens a browser to sign in to Cloudflare. Your site is then at
`https://plotpoints.pages.dev` (use that as the first CORS origin).

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

- [ ] `GET /health` and `/meta` report the expected snapshot version and title count
- [ ] Landing page loads; importing a Letterboxd export returns recommendations
- [ ] A recommendation links to `/film/<id>`; refreshing that URL still loads the page
- [ ] An unknown id (`/film/999999999`) shows the not-found state, not a blank page
- [ ] Browser console shows no CORS errors
- [ ] API logs show one line per request (method, route template, status, ms) and no film titles,
      usernames or tokens
- [ ] About page carries the TMDB sentence and logo, and the JustWatch attribution- [ ] On the live site: import with the consent box ticked, then use Privacy -> "Delete with token";
      on your machine `just user-ingest` lands and then removes it (see `external_setup.md` 5b, step 5)
- [ ] `just test-inbox --write` still PASSes against the key the live service uses- [ ] Rate limits: `client_of` in `api/app.py` keys on the *first* `X-Forwarded-For` entry. Behind
      Cloud Run or Render a caller can add their own header and dodge the per-IP limits on
      `/import/letterboxd`, `/consent` and `/match`. At friends' scale that is harmless; before a wider
      launch, look at what the platform puts in that header on the live service and key on the
      entry the platform adds (the last one, with a single proxy).
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
