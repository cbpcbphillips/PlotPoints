# Deploy runbook

Status: **written, not yet run.** Nothing here has been executed against a real host; the local
steps (1-2) are the ones verified. Host choice is still open (roadmap decision 11): the image is
host-agnostic and honours `$PORT`.

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
| API | `PLOTPOINTS_CORS_ORIGINS` | the deployed frontend origin, e.g. `https://plotpoints.pages.dev` |
| API | `PLOTPOINTS_INBOX` | `local` until the AWS inbox is set up, then `s3` |
| API | `TMDB_API_KEY` | optional; without it `/match` is snapshot-only |
| API (inbox `s3`) | `INBOX_AWS_ACCESS_KEY_ID`, `INBOX_AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET`, `AWS_REGION` | write-only credential |
| Frontend build | `VITE_API_URL` | the API's public URL |

`PLOTPOINTS_INBOX=local` on a host with an ephemeral disk loses consented imports on restart. Leave
the consent box effectively off (or accept the loss) until the S3 inbox is configured.

## 3. API host

Either one runs the same image. Registry and project names below are placeholders.

**Cloud Run** (scales to zero, free tier, needs a billing account):

```powershell
docker tag plotpoints-api REGION-docker.pkg.dev/PROJECT/plotpoints/api:latest
docker push REGION-docker.pkg.dev/PROJECT/plotpoints/api:latest
gcloud run deploy plotpoints-api --image REGION-docker.pkg.dev/PROJECT/plotpoints/api:latest `
  --region REGION --allow-unauthenticated --memory 512Mi `
  --set-env-vars PLOTPOINTS_CORS_ORIGINS=https://YOUR-FRONTEND
```

**Render** (free tier sleeps after 15 minutes, about a minute to wake): create a Web Service from the
pushed image, set the same environment variables; Render supplies `$PORT`.

Memory: measured ~225 MB resident before the film details; `details.json` adds roughly 18 MB on
disk and somewhat more in memory. Re-measure with `docker stats` after `just api-run`, and keep at
least 512 MB on either host.

## 4. Frontend host

Build with `VITE_API_URL` set, then publish `web/dist/`. The site is a single-page app, so a
refresh on `/film/603` needs a fallback to `index.html`:

- **Cloudflare Pages:** handled by `web/public/_redirects` (copied into `dist/`).
- **Vercel:** add `web/vercel.json` with `{"rewrites":[{"source":"/(.*)","destination":"/index.html"}]}`.

Remember: a client-rendered page gives search engines nothing. If film pages should be findable,
they need prerendering, which is a separate decision.

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
- [ ] About page carries the TMDB sentence and logo, and the JustWatch attribution
