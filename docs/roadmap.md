# PlotPoints — Architecture & Roadmap

## Goal

A recommendation engine. Build our own TMDB-derived **movie + TV catalog**, vectorize it with
Snowflake Cortex, then ingest any user's Letterboxd watch+rating history to recommend **unwatched**
titles by vector similarity between the user's taste and the catalog.

The catalog is the foundation and is **user-independent**. A user's Letterboxd history is a *later
input* that becomes a query (taste vector) against the catalog — not a second corpus.

Recommendations serve both a **single user** and a **group** — suggesting a title that 2+ users can
watch together. Single-user is just the N=1 case of the group flow.

## The layers (data flow)

```
SOURCES            RAW (landing, VARIANT)      MODEL (dbt)              VECTORS (Cortex)        SERVE
──────────────     ───────────────────────     ─────────────────       ──────────────────      ─────────────
TMDB discovery  →  RAW.TMDB_TITLES         →   stg_ + dim_media /   →   MEDIA_EMBEDDINGS    →   recommend:
(popular/top/       (1 row per title)           dim_person / genre /     (vector per title)      cosine(taste,
 discover)                                       keyword + bridges                                catalog)
                                                                                                  minus watched
Letterboxd RSS  →  RAW.DIARY_ENTRIES       →   stg_ + fct_diary_    →   USER_TASTE_VECTORS  →
(one user)          (1 row per watch event)     entry + dim_user         (vector per user)
```

## Two ingestion sources (both land VARIANT via the S3 stage + COPY)

| | Catalog ingester | User-history ingester |
|---|---|---|
| Source | TMDB `/discover/movie` ([../src/fetch_catalog.py](../src/fetch_catalog.py)) | Letterboxd diary RSS ([../src/fetch_diary.py](../src/fetch_diary.py)) |
| Grain | one row per `(media_type, tmdb_id)` | one row per watch event (Letterboxd `guid`) |
| Table | `RAW.TMDB_TITLES` | `RAW.DIARY_ENTRIES` |
| Enrichment | `enrich_tmdb` via `enrich_catalog.py`, **lean** payload profile | `enrich_tmdb`, **full** payload profile |
| User-dependent? | No — this is the foundation | Yes — layered on later |

**Key reuse:** the movie/TV enrichment engine in [../src/enrich_tmdb.py](../src/enrich_tmdb.py)
(`extract_enrichment`, routing, raw+curated payload) is source-agnostic. The catalog ingester only
swaps *where the tmdb_id list comes from* — TMDB discovery instead of one diary.

## Model layer (dbt — the "TMDB-based schema")

Star schema, built on the RAW tables:

- **Dimensions (TMDB entities, deduped):** `dim_media` (grain: title), `dim_person`, `dim_genre`,
  `dim_keyword`, `dim_date`, `dim_user`.
- **Bridges (many-to-many):** `bridge_media_person` (role = director/writer/cast + order),
  `bridge_media_genre`, `bridge_media_keyword`.
- **Fact:** `fct_diary_entry` (grain: watch event; measures: rating, rewatch, watched_date; FKs to
  media/date/user). This stays event-grained — analyzing *what a user watched and how they rated it*
  is inherently event-shaped; TMDB entities are its dimensions.
- **Staging:** `stg_tmdb_titles`, `stg_diary_entries` flatten the `record`/`tmdb` VARIANT into typed
  columns and dedupe on natural key via `QUALIFY ROW_NUMBER() … ORDER BY loaded_at DESC`.

## Vectorization (Cortex — BUILT)

- [int_media_document](../plotpoints_dbt/models/intermediate/int_media_document.sql) builds one
  labeled **embedding document** per title from the star schema — title, year, type, genres,
  director(s), top 10 cast in billing order, keywords, tagline, overview — plus a `document_hash`.
- [media_embeddings](../plotpoints_dbt/models/marts/media_embeddings.sql) embeds it via
  `SNOWFLAKE.CORTEX.EMBED_TEXT_1024` into a `VECTOR(FLOAT, 1024)` column in
  `MART.MEDIA_EMBEDDINGS`, keyed by `media_key`. This is the vectorized catalog corpus.
- The model is **incremental on `document_hash`**: a rerun re-embeds only new or changed titles,
  and a model switch re-embeds everything (`embedding_model` is part of the match). `dbt build
  --full-refresh` re-embeds the whole catalog — cheap at sample size, a real bill at 50k.
- [search_media.py](../src/search_media.py) (`just search "..."`) embeds a free-text query with the
  same model and ranks by `VECTOR_COSINE_SIMILARITY` — the same mechanism Phase 5 runs on, with a
  taste vector in place of the typed string.

## User taste + recommend (single & group)

- **Taste vector:** aggregate the embeddings of the user's rated titles, weighted by rating (liked
  pulls toward, disliked pushes away). One vector per user → `MART.USER_TASTE_VECTORS`.
- **Single-user recommend:** `VECTOR_COSINE_SIMILARITY(taste, media_embedding)` over the catalog,
  anti-join `fct_diary_entry` to drop already-watched, optional filters (media_type, language,
  released), top-K → a serving view/table.
- **Group recommend ("watch together"):** given 2+ users, combine their signals into one ranking.
  Prefer per-title **score aggregation** over averaging the taste vectors — averaging vectors tends
  toward bland compromises nobody loves. Strategies: *average* (max total satisfaction),
  *least-misery* (max the minimum member score → nothing anyone hates), or *Borda/fairness*. Exclude
  titles **any** member has already seen (union of histories), and optionally intersect availability
  (shared watch providers) and language. Single-user falls out as the N=1 case.

## Orchestration (Airflow, later)

DAGs: `catalog_refresh` (periodic; incremental via TMDB `changes` API + `tmdb_enrichment_version`),
`user_ingest` (on-demand per user), `embed` (after catalog refresh), `recommend` (after user ingest).

## Build sequence

- **Phase 0 — DONE:** enrichment engine (movie+TV, full payload), connection layer (S3 + Snowflake
  key-pair), `RAW.DIARY_ENTRIES` + COPY primitives ([../src/raw_schema.py](../src/raw_schema.py)), Letterboxd
  fetch.
- **Phase 1 — Catalog ingestion — DONE:** TMDB discovery → `(media_type, tmdb_id)` list
  ([../src/fetch_catalog.py](../src/fetch_catalog.py)), lean enrichment
  ([../src/enrich_catalog.py](../src/enrich_catalog.py)), `RAW.TMDB_TITLES` + `copy_tmdb_titles`.
- **Phase 2 — Load layer — DONE:** [../src/load_snowflake.py](../src/load_snowflake.py) — checkpoint
  → compact NDJSON → S3 ([../src/connection/s3.py](../src/connection/s3.py)) → `COPY`, serving both
  catalog and diary.
- **Phase 3 — dbt project — DONE:** sources on `RAW.*`, staging views + intermediate + marts
  (dims/bridges/fact), 20 schema tests. `just dbt build` runs green.
- **Phase 4 — Cortex embeddings — DONE:** `int_media_document` + `media_embeddings` (incremental,
  `arctic-embed-l-v2.0`, 1024-dim) → `MART.MEDIA_EMBEDDINGS`, plus `just search` for semantic
  lookup. `just dbt build` runs green at PASS=45.
- **Phase 5 — Taste + recommend (NEXT):** taste vector + cosine-similarity serving, for a single
  user and for a group ("watch together").
- **Phase 6 — Airflow:** orchestrate + incremental refresh.

### Where the data actually stands

The pipeline is proven end-to-end but only on a **trial-sized sample** — the catalog holds 60 titles
from a `just catalog-fetch --limit 60` run, not the 50k `DEFAULT_TARGET`. Worse, the sample is
**entirely 2026 releases**: `fetch_catalog` walks release years backward from the current year, and
`--limit 60` stops inside the first one. So the sample is not just small, it is unrepresentative —
semantic search over it can show that the vectors work, but says nothing about recommendation
quality across eras. Everything downstream
(staging, marts, tests) is built on that sample. A full catalog fetch + enrich is the main
outstanding *data* task; it is independent of Phase 4 code work, but embeddings over 60 titles won't
produce meaningful recommendations, so the real catalog has to land before Phase 5 is worth judging.

## Decisions made

1. **Catalog scope & source (Phase 1).** `/discover/movie` sorted `vote_count.desc` with a
   `vote_count.gte` floor (default 200), accumulating toward `DEFAULT_TARGET` = 50,000 titles. A
   single `/discover` query caps at 500 pages (10k results), so
   [../src/fetch_catalog.py](../src/fetch_catalog.py) slides `primary_release_year` windows backward
   from the current year to 1900, which biases toward recent titles — acceptable for a candidate
   pool. **Movies only; TV is not in the catalog yet** (see still-open #1).
2. **Catalog payload weight (Phase 1).** Resolved in favour of a split: the catalog uses
   `APPEND_BY_TYPE_LEAN` (credits, keywords, external_ids, release_dates, watch/providers, videos —
   ~182 KB/title), the diary keeps the full `APPEND_BY_TYPE` (~366 KB/title). Dropping
   images/translations/reviews/recommendations/similar/alternative_titles/lists costs nothing the
   curated fields or embeddings use.
3. **Diary ↔ catalog relationship (Phase 3).** Resolved as a union rather than a slim-down:
   [../plotpoints_dbt/models/intermediate/int_media.sql](../plotpoints_dbt/models/intermediate/int_media.sql)
   unions catalog and diary to one row per `(media_type, tmdb_id)`, with catalog winning on conflict
   via `source_rank`. `DIARY_ENTRIES` keeps its full payload, so a watched title that isn't in the
   catalog still resolves.

4. **Embedding document + model (Phase 4).** Field set is **theme + people**: title, year, type,
   genres, director(s), top 10 cast in billing order, keywords, tagline, overview — assembled from
   the star schema (not by re-flattening `record`) so it stays consistent with the tested marts.
   People are included deliberately: director/actor affinity drives a lot of real taste. Model is
   **`snowflake-arctic-embed-l-v2.0` at 1024 dims** (all seven Cortex models are available in this
   region; arctic-l was chosen for retrieval quality and multilingual handling). Assembly uses
   `array_construct_compact` so absent fields drop their whole line rather than leaving a dangling
   label, and `listagg` ordering is deterministic — anything non-deterministic would re-embed the
   entire catalog on every run.

## Key open decisions (resolve at each phase)

1. **TV in the catalog (deferred).** The catalog is movies-only. `APPEND_BY_TYPE_LEAN` has no `"tv"`
   key, and `fetch_details()` silently falls back to the *full* append set for any media type the
   profile misses — harmless today, but it multiplies payload size the moment TV is added. Fix that
   fallback as part of adding TV discovery.
2. **Query-side prefixing (Phase 5):** arctic-embed models are trained for asymmetric retrieval and
   conventionally want a query prefix ("Represent this sentence for searching relevant
   passages: "). `just search` currently embeds the raw string. Similarity scores land around
   0.23-0.30, which is plausible but worth A/B-ing when the taste vector replaces the typed query.
3. **Taste-vector formula (Phase 5):** how ratings weight the aggregate, and how dislikes are
   handled (push away vs simply exclude).
4. **Group aggregation (Phase 5):** average vs least-misery vs Borda for combining members' scores;
   whether to exclude titles seen by *any* member; whether to require shared availability/language.

---

_Provisioning of the external services (TMDB / Snowflake / AWS) is covered in
[external_setup.md](external_setup.md)._
