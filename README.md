# PlotPoints

Vector-powered ELT pipeline that turns a Letterboxd watch history into film & TV taste
analytics and recommendations — built on Snowflake, dbt, Airflow, and Cortex embeddings.

**The idea:** build our own TMDB-derived movie/TV **catalog**, vectorize it with Cortex,
then ingest a user's Letterboxd watch + rating history to recommend **unwatched** titles —
for one viewer, or a group ("what should we watch together?").

## Pipeline

| Stage | What it does | Command |
|---|---|---|
| Fetch diary | Pull a Letterboxd diary (RSS) → raw checkpoint | `just fetch <username>` |
| Enrich diary | Match each entry to TMDB (movie/TV), full payload | `just enrich` |
| Fetch catalog | Discover a broad TMDB movie catalog (candidate pool) | `just catalog-fetch` |
| Enrich catalog | Lean, English-only TMDB payload for catalog titles | `just catalog-enrich` |
| Load | NDJSON → S3 → `COPY` into `RAW.*` | `just load <diary\|catalog>` |
| Transform (dbt) | Star schema: `dim_media` / `dim_person` / … | `just dbt build` |
| Vectorize (Cortex) | Embedding document → `VECTOR` in `MART.MEDIA_EMBEDDINGS` | `just dbt build` |
| Search | Semantic lookup over the embedded catalog | `just search "..."` |
| Recommend *(later)* | Taste vector → single & group recommendations | — |

See **[docs/roadmap.md](docs/roadmap.md)** for the full architecture and phase plan.

## Project layout

```
src/
  fetch_diary.py               Letterboxd diary RSS  → data/checkpoints/diary_raw.json
  enrich_tmdb.py               TMDB enrichment engine (movie + TV, full payload)
  fetch_catalog.py             TMDB discovery         → data/checkpoints/catalog_raw.json
  enrich_catalog.py            lean catalog enrichment (reuses enrich_tmdb)
  raw_schema.py                RAW landing tables + COPY primitives (Snowflake)
  load_snowflake.py            NDJSON → S3 → COPY into RAW.* (diary | catalog)
  run_dbt.py                   `just dbt` wrapper (loads .env, runs dbt via uvx)
  smoke_test_connections.py    verifies Snowflake + S3 wiring, creates RAW objects
  check_tmdb.py                connection check — TMDB
  check_snowflake.py           connection check — Snowflake (read-only)
  check_aws.py                 connection check — AWS S3
  check_common.py              shared PASS/WARN/FAIL harness for the checks
  search_media.py              semantic search over MART.MEDIA_EMBEDDINGS
  pipeline_cost.py             estimated warehouse credits for recent activity
  paths.py                     checkpoint location (PLOTPOINTS_DATA_DIR)
dags/                          Airflow DAGs (catalog_ingest, diary_ingest, transform, pipeline_monitor)
include/                       Airflow-only helpers (src/ never imports Airflow)
scripts/                       build tooling (generates the image's requirements.txt)
Dockerfile                     Astro Runtime image: src/, plotpoints_dbt/, and dbt in its own venv
docker-compose.override.yml    bind-mounts data/ and the Snowflake key into the containers
  connection/                  Snowflake key-pair auth, S3 client, external stage
plotpoints_dbt/                dbt project — staging views + marts (the star schema)
docs/
  roadmap.md                   architecture & phased build plan
  external_setup.md            provisioning TMDB / Snowflake / AWS
```

## Setup (fresh clone / new machine)

1. Install [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
   (`winget install Casey.Just`), then clone the repo.
2. `uv sync` — creates `.venv` and installs dependencies (uv fetches the Python version pinned in
   `.python-version` itself). Point your IDE (e.g. DataSpell) at the resulting `.venv`.
3. **Copy your RSA private key file onto the machine.** It lives *outside* the repo (e.g.
   `~/.snowflake/plotpoints/rsa_key.p8`), so a clone won't bring it — it's the one thing you must move by hand.
4. `cp .env.example .env` and fill it in. Set `SNOWFLAKE_PRIVATE_KEY_PATH` to the key's path on *this*
   machine; the other values are the same account/keys as before. First-time provisioning of the external
   services is covered in **[docs/external_setup.md](docs/external_setup.md)**.
5. `just smoke-test` — verifies Snowflake + S3 wiring and creates the RAW landing objects.
6. `just test-all` — per-endpoint checks for TMDB, Snowflake and AWS (see below).

dbt needs no separate install — `just dbt <cmd>` runs it isolated via `uvx`. Then run the pipeline
stages above (`just catalog-fetch --limit 60` is a quick trial run).

## Checking the connections

Three read-only checks, one per external service, each reporting `PASS` / `WARN` / `FAIL` per probe.
A probe failing never stops the others — the point is a full picture of what's broken.

| Command | Checks |
|---|---|
| `just test-tmdb` | API auth, both append profiles, the `/discover` query the catalog is built on |
| `just test-snowflake` | key-pair auth, session context, `RAW.*` row counts, stage `LIST` via S3, dbt output schemas, Cortex grant |
| `just test-aws` | credentials, caller identity, bucket reachability, list access |
| `just test-all` | all three in sequence |

`just test-aws --write` additionally round-trips a probe object (put, read back, delete) under
`_healthcheck/`. It's opt-in because it writes to the bucket, though it cleans up after itself. The
uploader IAM user can only *write* the landing data; it may read and delete just the scratch
prefixes `artifacts/` and `_healthcheck/` (see `docs/external_setup.md` step 5).

These *report* state; they never create anything. `just smoke-test` is the provisioning path that
creates the RAW landing objects if they're missing.

## Orchestration (Airflow)

The pipeline runs in Docker under Airflow 3 via the [Astro CLI](https://www.astronomer.io/docs/astro/cli/overview)
(`winget install Astronomer.Astro`) and Docker Desktop. Airflow cannot run natively on Windows, so
the container *is* the supported way to run it here.

```bash
just airflow-start      # build the image and start the stack -> http://localhost:8080
just airflow-restart    # rebuild after changing src/, plotpoints_dbt/ or dependencies
just airflow-stop
```

Only `dags/` and `include/` are live-mounted; everything else is baked into the image, so edits to
`src/` need a restart. Every DAG is manually triggered (`schedule=None`) from the UI:

| DAG | What it does |
|---|---|
| `diary_ingest` | Letterboxd RSS → TMDB → S3 → `RAW.DIARY_ENTRIES`. Seconds; the one to debug against. |
| `catalog_ingest` | TMDB discovery → enrich → S3 → `RAW.TMDB_TITLES`. Hours at full scale; resumable. |
| `transform` | `dbt build`, one Airflow task per model/test. Fires automatically when either ingest lands rows. |
| `pipeline_monitor` | Source freshness, data-quality warnings, 24h warehouse cost. |

Each ingest DAG opens with the read-only connection checks (the same ones behind `just test-*`), so
a bad credential fails in seconds rather than hours in. Step-level logic is unchanged and still runs
standalone through `just`; the DAGs call the same `run()` functions.

Two things worth knowing:

- **Checkpoints use a bind mount**, so the tasks share `data/` with the host. This is a deliberate
  stopgap: the cleaner design passes artifacts through S3. The IAM permission for that now exists
  (`GetObject` on `artifacts/*`), but the code doesn't — S3 objects can't be appended to, so the
  resumable enrich would need to become numbered part-files. The bind mount breaks the moment
  workers are distributed.
- **The container runs Python 3.14**, the Astro runtime's version, while the host venv is pinned to
  3.13. `requirements.txt` is generated by `just export-reqs` from `pyproject.toml` (direct
  dependencies only, pinned to `uv.lock`'s versions) rather than `uv export`, which would have
  downgraded packages Airflow itself depends on.

## Embeddings & search

`MART.MEDIA_EMBEDDINGS` holds one `VECTOR(FLOAT, 1024)` per title, built by dbt from a labeled
embedding document (title, year, genres, director, top cast, keywords, tagline, overview) via
`SNOWFLAKE.CORTEX.EMBED_TEXT_1024` with `snowflake-arctic-embed-l-v2.0`.

The model is **incremental on a document hash** — a rerun embeds only new or changed titles, so
`just dbt build` is cheap to repeat. Changing `embedding_model` or `embedding_dimension` in
`plotpoints_dbt/dbt_project.yml` re-embeds everything, and so does `just dbt build --full-refresh`:
free at sample size, a real bill at the 50k target.

```bash
just search "a lonely robot on a dying earth"
```

## Data model

The **raw** layer lands each source record as a Snowflake `VARIANT` at its natural grain —
one row per watch event (`RAW.DIARY_ENTRIES`), one row per catalog title (`RAW.TMDB_TITLES`).
dbt later transforms these into a TMDB-centric **star schema** (media / people / genres /
keywords dimensions + a diary-event fact), where actors and directors become first-class,
deduplicated entities. See the roadmap for the full model.
