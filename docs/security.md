# Security review (2026-11-21)

A review of the deployed friends-only launch: the API on Cloud Run, the site on Cloudflare Pages,
the S3 inbox, the build and the repo. It is a review by reading the code and probing the live
service, not a penetration test. Nothing here replaces one if the project goes commercial.

## What exists

| Surface | Exposure |
|---|---|
| Site (Cloudflare Pages) | Static files; no server code, no cookies, no accounts |
| API (Cloud Run) | Public. 15 routes. No authentication, by design: there are no accounts |
| S3 inbox | Written by the API with a put-only key; read, landed and purged only from your machine |
| Snowflake | Never reachable from the API or the site |
| Secrets | Secret Manager (`inbox-access-key-id`, `inbox-secret-access-key`, `tmdb-api-key`) and your local `.env` |

## Findings

Status: **fixed** = changed in this review (the API fixes went live on 2026-11-21, Cloud Run revision
`plotpoints-api-00002`; the log, `/docs` and body-cap changes were checked against the live service);
**ok** = checked, nothing to do; **accepted** = a known limit, noted.

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | The API's own access log (uvicorn) printed raw paths and query strings, so film numbers and search text reached the logs. The Privacy page said ids are never logged | Medium | **fixed**: `--no-access-log` in `api/Dockerfile` (the app's own line logs the route template only); the Privacy page now also says Google keeps its own request record for about 30 days |
| 2 | Deleting an import removed its Snowflake row but left its raw file in the S3 inbox, because `purge` only removes files recorded in RAW. A deletion request did not delete everything | Medium | **fixed**: `just user-ingest delete` removes the S3 file first, then the row (`src/user_ingest.py`); the one orphan from testing was removed |
| 3 | No Content-Security-Policy, framing protection or permissions policy on the site | Medium | **fixed**: `web/public/_headers` (CSP enforced, `X-Frame-Options: DENY`, Permissions-Policy, HSTS). The first-paint settings script moved from an inline tag to `web/public/theme-init.js` so inline scripts can be forbidden |
| 4 | 38 known advisories in 7 packages in the API image's pins (urllib3, certifi, cryptography, filelock, pyjwt, snowflake-connector-python, soupsieve) | Medium | **fixed**: `uv.lock` upgraded for those packages, `api/requirements.txt` regenerated; `pip-audit` now reports none. Deployed with the image rebuild |
| 5 | `/docs`, `/redoc` and `/openapi.json` were public, a free map of every route | Low | **fixed**: off unless `PLOTPOINTS_DOCS=1` (`just api` sets it for local work) |
| 6 | No cap on request body size; a 30 MB body would be parsed in memory before validation | Low | **fixed**: bodies over 12 MB get a 413 before they are read (`MAX_BODY_BYTES`); the largest honest request is about 9 MB |
| 7 | The API image carries packages it never uses (the Snowflake connector, filelock, pyjwt, beautifulsoup) because `api/requirements.txt` is exported from all project dependencies | Low | **accepted**: wider attack surface and a bigger image, no known hole. Worth trimming later with a smaller dependency group |
| 8 | Rate limits are per instance and in memory, so with two instances the real limit is up to double, and the table is never pruned | Low | **accepted**: it is a brake on scripts, not a security boundary. Tested live: 60 of 75 requests passed and 15 got 429, even with a different forged `X-Forwarded-For` on each, so the limit cannot be dodged by lying about the address |
| 9 | Anyone can write junk consent or deletion files to the inbox (5 per minute per address) | Low | **accepted**: bounded by the rate limit and the 12 MB cap; the pipeline treats imports as untrusted (`CANDIDATE_MIN_VOTES`, enrichment capped at 500 titles per run) |
| 10 | Letterboxd import fetches a URL built from user input | Info | **ok**: the username must match `^[A-Za-z0-9_-]{1,40}$`, so it cannot change the host or path; the response is capped at 3 MB with an 8 s timeout |
| 11 | CORS | Info | **ok**: an explicit origin list; an unlisted origin gets a 400 on preflight and no allow header; no credentials are used |
| 12 | Runtime identity | Info | **ok**: Cloud Run runs as the default service account, which has no project roles; it can read only the three named secrets. The AWS key is put-only on `inbox/*` and verified so with `just test-inbox` |
| 13 | Secrets in the repo | Info | **ok**: `.env`, `data/`, `CLAUDE.md` and the Snowflake key are ignored or outside the repo; no tracked file matches a secret pattern; no key material in git history; `.dockerignore` excludes `.env` and `data/`; the image copies named files only and runs as a non-root user |
| 14 | Frontend injection | Info | **ok**: no `dangerouslySetInnerHTML`, `innerHTML` or `eval`; external links carry `rel="noreferrer"`; `npm audit` reports 0 vulnerabilities |
| 15 | Deletion tokens | Info | **ok**: 256 random bits, only the SHA-256 is stored, a token cannot be guessed to delete someone else's import |

## The site's headers

`web/public/_headers` is served by Cloudflare Pages on every response:

- `Content-Security-Policy`: scripts only from the site itself and Cloudflare's analytics beacon;
  images from the site and `image.tmdb.org`; fonts from the site (and inlined `data:` fonts);
  `connect-src` only the site, **the API's Cloud Run address** and Cloudflare analytics; no objects;
  no framing.
- `X-Frame-Options: DENY`, `Permissions-Policy` (camera, microphone, location, payment, USB off),
  `Strict-Transport-Security` (one year).

**If the API address ever changes** (a custom domain such as `api.watchplotpoints.com`, a new
service), update `connect-src` in `web/public/_headers` and redeploy the site, or every API call will
be blocked and the site will look empty. To test a change safely, rename the header to
`Content-Security-Policy-Report-Only`, deploy, browse the site, and read the browser console for
"Refused" lines; the site was tested exactly that way.

## Residual risks and what to do about them

- **Consent is on by default.** Fine for friends in the US; not valid GDPR consent for EU visitors
  (`docs/roadmap.md`, decision on consent). Revisit before any public or EU-facing launch.
- **Google's request log keeps full URLs for about 30 days.** The Privacy page says so. To stop
  recording them: Logs Router, `_Default` sink, add an exclusion for
  `logName:"run.googleapis.com%2Frequests"`. That also hides the request list in the Cloud Run
  console; metrics, the dashboard and the uptime check are unaffected. If you add the exclusion,
  trim that Privacy paragraph.
- **Cost abuse.** The API is open, so a script could run up Cloud Run. Caps in place: at most 2
  instances, 20 requests per instance at a time, the per-address rate limits, and a budget alert.
  There is no hard spending stop on Google Cloud; a budget only warns.
- **TMDB key burn.** `/match` can be made to call TMDB (20 per minute per address, capped per
  request). The key is read-only and revocable at TMDB.
- **No accounts means no account takeover**, and also no way to tell abusive users apart. That is
  the trade made on purpose (`docs/roadmap.md`).

## Re-run these checks

```powershell
just test                                   # includes tests/test_hardening.py
uvx pip-audit -r api/requirements.txt       # known advisories in the API image
cd web; npm audit --omit=dev                # and in the site's dependencies
just test-inbox                             # the API's AWS key can write inbox/ and nothing else
just status                                 # live: CORS, headers, certificates, deep links
```

Quick live probes (from any machine):

```powershell
curl.exe -I https://watchplotpoints.com/                                  # CSP, X-Frame-Options, HSTS
curl.exe -s -o NUL -w "%{http_code}" https://<api-address>/docs           # expect 404
```

Do the dependency audits monthly, when you refresh the snapshot: upgrade with
`uv lock --upgrade-package <name>`, then `just api-reqs`, `just test`, `just api-build` and
`just deploy-api`.
