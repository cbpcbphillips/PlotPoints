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

# Enrich the catalog checkpoint with a lean TMDB payload
catalog-enrich:
    uv run src/enrich_catalog.py

# --- Snowflake ---

# Verify Snowflake + S3 wiring and ensure the RAW landing objects exist
smoke-test:
    uv run src/smoke_test_connections.py

# Load an enriched checkpoint into its RAW table (source = diary | catalog)
load source:
    uv run src/load_snowflake.py {{source}}

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

# AWS S3: credentials, bucket, list (read-only; --write also tests PutObject)
test-aws *args:
    uv run src/check_aws.py {{args}}

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
