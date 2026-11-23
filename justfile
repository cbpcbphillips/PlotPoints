set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# --- Ingestion ---

# Fetch a Letterboxd diary (pass a username, or omit to be prompted)
fetch *args:
    uv run src/fetch_diary.py {{args}}

# Enrich the diary checkpoint with full TMDB metadata
enrich:
    uv run src/enrich_tmdb.py

# Discover a broad TMDB movie catalog (--limit N for a quick test run)
catalog-fetch *args:
    uv run src/fetch_catalog.py {{args}}

# Enrich the catalog checkpoint with a lean TMDB payload (resumable; --restart to redo)
catalog-enrich *args:
    uv run src/enrich_catalog.py {{args}}

# --- Snowflake ---

# Verify Snowflake + S3 wiring and ensure the RAW landing objects exist
smoke-test:
    uv run src/smoke_test_connections.py

# Load an enriched checkpoint into its RAW table (source = diary | catalog | user_titles).
# Extra args pass through, e.g. `just load catalog --run-id 2026-11-19` for an idempotent retry
load source *args:
    uv run src/load_snowflake.py {{source}} {{args}}

# --- Recommendations (Phase 6) ---

# Recommend unwatched titles. One username = single user; several = a group (least-misery)
recommend *args:
    uv run src/recommend.py {{args}}

# --- Serving (Phase 7) ---

# Export MART to a versioned serving snapshot in data/snapshots/ (add --upload to push it to S3)
snapshot *args:
    uv run src/publish_snapshot.py {{args}}

# Run the API locally against the newest snapshot, with reload. http://localhost:8000/docs
api:
    $env:PLOTPOINTS_CACHE_SECONDS = '0'; $env:PLOTPOINTS_DOCS = '1'; uv run --group api uvicorn api.app:create_app --factory --reload --port 8000

# Regenerate api/requirements.txt (the API image's pins) from uv.lock
api-reqs:
    uv export --frozen --no-hashes --no-dev --group api --no-emit-project -o api/requirements.txt

# Build the API image: stages the newest snapshot into api/snapshot/, bakes it in
api-build:
    uv run src/publish_snapshot.py --stage api/snapshot
    docker build -f api/Dockerfile -t plotpoints-api .

# Run the API image locally on :8000
api-run:
    docker run --rm -p 8000:8000 plotpoints-api

# Offline tests (scoring, API, parsing). `just test -m snowflake` adds the numpy-vs-SQL check
test *args:
    uv run --group api pytest {{args}}

# --- Orchestration (Phase 5) ---

# Start the local Airflow stack in Docker (builds the image first run). UI: http://localhost:8080
airflow-start:
    astro dev start

# Stop Airflow, keeping its metadata DB
airflow-stop:
    astro dev stop

# Rebuild + restart (needed after changing src/, plotpoints_dbt/ or deps; only dags/ include/ are live)
airflow-restart:
    astro dev restart

# Run any airflow CLI command inside the stack, e.g. `just airflow dags list-import-errors`
airflow *args:
    astro dev run {{args}}

# Regenerate requirements.txt for the Airflow image from pyproject.toml / uv.lock
export-reqs:
    uv run scripts/export_airflow_requirements.py

# Estimated warehouse credits for recent activity (default: last 60 min)
cost *args:
    uv run src/pipeline_cost.py {{args}}

# --- Search (Phase 4) ---

# Semantic search over the embedded catalog. e.g. just search "a lonely robot on a dying earth"
search query *args:
    uv run src/search_media.py {{quote(query)}} {{args}}

# --- Connection checks ---

# Check every endpoint (TMDB, Snowflake, AWS) -- each may fail without hiding the others
test-all:
    -uv run src/check_tmdb.py
    -uv run src/check_snowflake.py
    -uv run src/check_aws.py

# TMDB: auth, both append profiles, the catalog discover query
test-tmdb *args:
    uv run src/check_tmdb.py {{args}}

# Snowflake: auth, RAW objects + row counts, stage LIST, dbt schemas, Cortex grant (read-only)
test-snowflake *args:
    uv run src/check_snowflake.py {{args}}

# AWS S3: credentials, bucket, list (read-only; --write adds a self-cleaning put/get/delete)
test-aws *args:
    uv run src/check_aws.py {{args}}

# The API's inbox key: put-only on inbox/*. --write proves it can write there and nothing else
test-inbox *args:
    uv run src/check_inbox.py {{args}}

# Daily usage numbers from the API log: gcloud run services logs read ... | just usage
usage *args:
    uv run src/usage_report.py {{args}}

# Is the live site healthy? Needs PLOTPOINTS_API_URL and PLOTPOINTS_SITE_URL in .env (or --api/--site)
status *args:
    uv run src/status_check.py {{args}}

# A private dashboard page from the API log -> data/reports/dashboard.html (see src/dashboard.py)
dashboard *args:
    uv run src/dashboard.py {{args}}

# Put the API's three secrets into Google Secret Manager from .env (-DryRun shows names only)
gcp-secrets *args:
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/create_secrets.ps1 {{args}}

# Deploy the API to Cloud Run (add -DryRun to preview every command): see docs/deploy.md
deploy-api *args:
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/deploy_api.ps1 {{args}}

# Build the site against the live API and publish it to Cloudflare Pages (-DryRun to preview)
deploy-web *args:
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/deploy_web.ps1 {{args}}

# --- dbt (transformed schema) ---

# Run dbt against plotpoints_dbt (.env loaded, isolated via uvx). e.g. `just dbt build`
dbt *args:
    uv run src/run_dbt.py {{args}}

# --- Dev ---

lint:
    uv run ruff check .

format:
    uv run ruff format .

check:
    uv run ruff check .
    uv run ruff format --check .

install-hooks:
    uv run pre-commit install

# --- User inbox (Phase 7c) ---

# Process the S3 inbox: land | delete | titles | purge | all  (needs PLOTPOINTS_INBOX unset or s3)
user-ingest step="all" *args:
    uv run src/user_ingest.py {{step}} {{args}}
