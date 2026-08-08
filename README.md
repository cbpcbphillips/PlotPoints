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
| Vectorize *(Cortex, later)* | Embeddings over the catalog | — |
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
  smoke_test_connections.py    verifies Snowflake + S3 wiring
  connection/                  Snowflake key-pair auth, S3 client, external stage
plotpoints_dbt/                dbt project — staging views + marts (the star schema)
docs/
  roadmap.md                   architecture & phased build plan
  external_setup.md            provisioning TMDB / Snowflake / AWS
```

## Setup (fresh clone / new machine)

1. Install [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
   (`winget install Casey.Just`), then clone the repo.
2. `uv sync` — creates `.venv` and installs dependencies (uv fetches Python 3.13 itself). Point your
   IDE (e.g. DataSpell) at the resulting `.venv`.
3. **Copy your RSA private key file onto the machine.** It lives *outside* the repo (e.g.
   `~/.snowflake/plotpoints/rsa_key.p8`), so a clone won't bring it — it's the one thing you must move by hand.
4. `cp .env.example .env` and fill it in. Set `SNOWFLAKE_PRIVATE_KEY_PATH` to the key's path on *this*
   machine; the other values are the same account/keys as before. First-time provisioning of the external
   services is covered in **[docs/external_setup.md](docs/external_setup.md)**.
5. `just smoke-test` — verifies Snowflake + S3 wiring and ensures the RAW landing objects exist.

dbt needs no separate install — `just dbt <cmd>` runs it isolated via `uvx`. Then run the pipeline
stages above (`just catalog-fetch --limit 60` is a quick trial run).

## Data model

The **raw** layer lands each source record as a Snowflake `VARIANT` at its natural grain —
one row per watch event (`RAW.DIARY_ENTRIES`), one row per catalog title (`RAW.TMDB_TITLES`).
dbt later transforms these into a TMDB-centric **star schema** (media / people / genres /
keywords dimensions + a diary-event fact), where actors and directors become first-class,
deduplicated entities. See the roadmap for the full model.
