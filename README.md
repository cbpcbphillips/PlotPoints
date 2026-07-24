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
| Load *(Phase 2, WIP)* | NDJSON → S3 → `COPY` into `RAW.*` | — |
| Transform *(dbt, later)* | Star schema: `dim_media` / `dim_person` / … | — |
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
  smoke_test_connections.py    verifies Snowflake + S3 wiring
  connection/                  Snowflake key-pair auth, S3 client, external stage
docs/
  roadmap.md                   architecture & phased build plan
  external_setup.md            provisioning TMDB / Snowflake / AWS
```

## Getting started

1. Provision the external services and fill in `.env` — see **[docs/external_setup.md](docs/external_setup.md)**.
2. Install dependencies with [uv](https://docs.astral.sh/uv/); recipes are run via [just](https://github.com/casey/just).
3. Verify the wiring: `just smoke-test`.
4. Run the ingestion stages above (`just catalog-fetch --limit 60` for a quick trial run).

## Data model

The **raw** layer lands each source record as a Snowflake `VARIANT` at its natural grain —
one row per watch event (`RAW.DIARY_ENTRIES`), one row per catalog title (`RAW.TMDB_TITLES`).
dbt later transforms these into a TMDB-centric **star schema** (media / people / genres /
keywords dimensions + a diary-event fact), where actors and directors become first-class,
deduplicated entities. See the roadmap for the full model.
