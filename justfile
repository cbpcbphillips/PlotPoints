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
