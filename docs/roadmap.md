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

| | Catalog ingester (NEW) | User-history ingester (EXISTS) |
|---|---|---|
| Source | TMDB `/discover`, `/movie/popular`, `/movie/top_rated`, `/tv/*` | Letterboxd diary RSS (`fetch_diary.py`) |
| Grain | one row per `(media_type, tmdb_id)` | one row per watch event (Letterboxd `guid`) |
| Table | `RAW.TMDB_TITLES` (to build) | `RAW.DIARY_ENTRIES` (built) |
| Enrichment | **reuses `enrich_tmdb` unchanged** | same engine |
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

## Vectorization (Cortex — already granted `SNOWFLAKE.CORTEX_USER`)

- Build one **embedding document** per title: concatenate the semantic fields —
  title, overview, tagline, genres, keywords, top cast, director(s). (Field selection is a Phase-4
  decision.)
- `SNOWFLAKE.CORTEX.EMBED_TEXT_*` → a `VECTOR` column in `MART.MEDIA_EMBEDDINGS` keyed by
  `(media_type, tmdb_id)`. This is the vectorized catalog corpus.

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
- **Phase 1 — Catalog ingestion (NEXT, the foundation):** choose catalog scope (see open decisions);
  build a TMDB discovery source → list of `(media_type, tmdb_id)`; enrich via the existing engine;
  add `RAW.TMDB_TITLES` landing table + `copy_tmdb_titles`.
- **Phase 2 — Load layer:** `src/load_snowflake.py` — checkpoint → compact NDJSON → S3
  ([../src/connection/s3.py](../src/connection/s3.py)) → `COPY` (serves both catalog and diary). The
  COPY primitives already exist in `raw_schema.py`.
- **Phase 3 — dbt project:** init dbt, sources on `RAW.*`, staging + marts (dims/bridges/fact).
- **Phase 4 — Cortex embeddings:** embedding document + `EMBED_TEXT` → `MEDIA_EMBEDDINGS`.
- **Phase 5 — Taste + recommend:** taste vector + cosine-similarity serving, for a single user and
  for a group ("watch together").
- **Phase 6 — Airflow:** orchestrate + incremental refresh.

## Key open decisions (resolve at each phase)

1. **Catalog scope & source (Phase 1 — biggest):** TMDB has ~1M+ movies / ~150k+ shows; can't enrich
   all. Bound it — top-N by votes/popularity, `/discover` with a vote-count threshold + year/language
   filters, or seed-from-Letterboxd-and-grow via `recommendations`/`similar`. Sets enrich runtime and
   storage.
2. **Catalog payload weight (Phase 1):** the "keep the full ~555 KB TMDB payload" decision was scoped
   to the ~50-entry *diary*. A catalog of tens of thousands multiplies enrich time and storage ~1000×,
   so the catalog may warrant a **leaner** payload (drop images/translations/reviews for catalog rows
   while keeping them for diary rows). The full-payload choice should be revisited specifically for
   catalog scale.
3. **Diary ↔ catalog relationship (Phase 3):** once the catalog exists, `DIARY_ENTRIES` can slim to
   Letterboxd fields + `tmdb_id` and *reference* the catalog (dbt join), instead of re-embedding the
   full payload per watch. Trade-off: loses point-in-time snapshot of a title, but current catalog
   state is fine for recommending.
4. **Embedding document fields (Phase 4)** and **taste-vector formula / dislike handling (Phase 5).**
5. **Group aggregation (Phase 5):** average vs least-misery vs Borda for combining members' scores;
   whether to exclude titles seen by *any* member; whether to require shared availability/language.

---

_Provisioning of the external services (TMDB / Snowflake / AWS) is covered in
[external_setup.md](external_setup.md)._
