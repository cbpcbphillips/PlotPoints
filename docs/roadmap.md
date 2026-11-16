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

## Orchestration (Airflow — BUILT, Phase 5)

Astro Runtime 3.3 (Airflow 3.3, Python 3.14) in Docker, project at the repo root so the image
contains `src/` and `plotpoints_dbt/`. Four DAGs, all manually triggered (`schedule=None`):

| DAG | Trigger | Tasks |
|---|---|---|
| `catalog_ingest` | manual | preflight → fetch → enrich → load → emits `raw_tmdb_titles` asset |
| `diary_ingest` | manual | preflight → fetch → enrich → load → emits `raw_diary_entries` asset |
| `transform` | either asset updates | preflight → Cosmos task group (one task per dbt model/test) → cost record |
| `pipeline_monitor` | manual | source freshness · data-quality warnings · 24h warehouse cost (independent tasks) |

The roadmap's earlier four-DAG sketch (`catalog_refresh`, `user_ingest`, `embed`, `recommend`)
collapsed: embeddings became a dbt model in Phase 4, so there is no separate `embed` DAG, and
`recommend` is request-time SQL behind an API rather than a batch job.

**Operating principles** — the reason this phase exists, more than the DAGs themselves:

1. **Atomic, resumable tasks.** fetch / enrich / load / transform stay separate, so a dbt failure
   never re-runs hours of TMDB calls, and the enrich task resumes from its last fsynced title.
2. **Idempotent per run.** `load` receives a run-scoped S3 prefix derived from the Airflow run id,
   so a retry targets the same prefix and `COPY` (which skips already-loaded files) is a no-op
   rather than a duplicate append.
3. **Retry transient, fail loud on deterministic.** Exponential backoff on network/API tasks, and
   every task has an `execution_timeout` — a hang is worse than a failure.
4. **Airflow orchestrates; it is never the only entry point.** `src/` never imports Airflow. Every
   step still runs through `just`; DAGs call the same `run()` functions the CLIs wrap.
5. **Fail in seconds, not hours.** Each ingest DAG opens with the same read-only connection checks
   behind `just test-*`, so a bad key fails immediately instead of mid-enrich.

**Monitoring**, cheapest first: a single `on_failure_callback` (the pattern, not a destination);
`dbt source freshness` on the RAW tables; two dbt models, `mart_pipeline_health` (per-load-batch
match rate and metadata completeness, read from RAW so a bad batch cannot hide behind newer rows)
and `mart_embedding_coverage` (missing vs stale embeddings), each with a warn-severity test; and
warehouse cost per run from `INFORMATION_SCHEMA.QUERY_HISTORY` (`just cost`).

`tmdb_api` is a **1-slot pool**: the code's 0.3s delay only holds within one process, and the
pool makes the rate limit hold across everything Airflow schedules.

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
- **Phase 5 — Orchestration + monitoring + containerization (IN PROGRESS):** the Airflow DAGs
  above, the dbt monitoring models, and the Docker image. Exit criterion: the real catalog load
  runs *through* `catalog_ingest` as the pipeline's first production run, not by hand.
- **Phase 6 — Taste + recommend:** request-time parameterized SQL (not a dbt model, so a brand-new
  user gets an answer without waiting for a batch run). Per-candidate score is the mean of its
  top-3 similarities to the user's rated films, weighted by rating, blended with a
  Bayesian-shrunk TMDB quality prior calibrated to the user's own standard; anti-join watched;
  group mode scores each member separately and combines with least-misery.
- **Phase 7 — Serving API (new):** FastAPI over the recommendation SQL with a connection pool built
  once at startup. This phase was missing from earlier versions of this roadmap, and it is the
  actual gap between "pipeline" and "product": every entry point was a CLI script.
- **Phase 8 — Frontend:** localhost first, deployment optional. Scope stays thin until the API's
  response shapes are real.

### Where the data actually stands

The catalog holds **1000 titles** spanning several years (a `--limit 1000` trial run on
2026-09-26), replacing the earlier 60-title sample that was entirely 2026 releases. 1009 documents
and embeddings exist — 1000 catalog titles plus 9 diary-only ones. Semantic search is visibly
better for it: "gritty crime drama about organized crime families" now returns a clean run of crime
films at 0.33-0.35 similarity, against 0.23-0.30 on the 60-title sample.

Still short of a full catalog, and there's a supply ceiling worth knowing: only **14,952 movies have
`vote_count >= 200`**, so the current `DEFAULT_MIN_VOTES` caps the achievable catalog near 15k
regardless of `--target`. Reaching 50k+ means lowering the floor to roughly 20-50 votes, which trades
metadata quality for volume. Measured economics for a full run are in CLAUDE.md; the short version is
that credits are negligible (~1-3 total) and the real costs are wall-clock time (~5.4h at 50k, ~8.6h
at 80k) and local disk (~4.8-7.6 GB). Everything downstream
(staging, marts, tests) is built on that 1000-title sample. The real load is the exit criterion for
Phase 5 and runs through `catalog_ingest` (floor 100, ~24k titles, ~2.5h) — see the vote-floor
decision below. Recommendations are not worth judging until it lands.

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

5. **Catalog vote floor: 100 (Phase 5).** Sampled TMDB before choosing, rather than guessing at
   how "niche" a floor was. Acclaimed arthouse mostly clears 200 already — 10 of 12 sampled films
   (*Aftersun* 2049 votes, *Past Lives* 2554, *Drive My Car* 1598, *First Cow* 569) — and the two
   that did not (*Showing Up* 141, *Hit the Road* 161) sit in the 100-200 band, not the deep tail.
   What lives below 100 is mostly not cinema: sampled 2023 titles at 20-35 votes were making-of
   featurettes, Christmas specials, anime side-stories and direct-to-video sequels, which would
   surface as recommendations and look like bugs. Estimated catalog by floor: 200 -> ~14,950
   (~1.6h enrich), **100 -> ~23,800 (~2.5h)**, 50 -> ~36,350, 20 -> ~62,300. Floor 100 picks up
   near-miss arthouse and international cinema that never accumulates US votes, and metadata stays
   rich enough for the embedding documents and the quality prior. Note this means the earlier
   "50-80k titles" goal is not reachable without taking the featurette-heavy tail.
6. **Orchestration choices (Phase 5).** Astro CLI + Docker Desktop (Airflow cannot run natively on
   Windows); Cosmos for one task per dbt model; Airflow 3 Assets (not time) to chain ingest ->
   transform; per-run idempotency keyed on the Airflow `run_id`, because Airflow 3 manual triggers
   have no `logical_date`. Things verification overturned or added, worth keeping:
   - **`requirements.txt` is generated from direct dependencies, not `uv export`.** A fully pinned
     export would have downgraded Airflow's own `cryptography` 50 -> 49 and `urllib3` 2.8 -> 2.7
     inside the image, and loose bounds let pip jump `snowflake-connector-python` to an untested
     5.x. So: directly-used packages pinned to `uv.lock`'s exact versions, Airflow-owned ones left
     to the image ([../scripts/export_airflow_requirements.py](../scripts/export_airflow_requirements.py)).
   - **dbt runs in its own venv in the image, with `dbt-core` pinned explicitly** — pinning only the
     adapter let pip resolve a 1.13 *beta* of core. Cosmos must be forced to
     `InvocationMode.SUBPROCESS`; its in-process default cannot target a separate venv.
   - **Artifacts use a bind mount, not S3.** This began as a workaround for the uploader lacking
     `s3:GetObject`; that grant now exists (scoped to `artifacts/*` and `_healthcheck/*`), so what
     remains is code. It is a known downgrade (it assumes tasks share a filesystem), and reversing
     it is a real redesign rather than a switch: S3 objects are immutable, so the resumable
     append-only enrich would become numbered part-files that a retry lists to find its progress.
   - **`preflight` must be wired as an explicit upstream of the first work task.** The first draft
     chained it only to `load`, so it ran *beside* fetch and enrich and gated nothing — visible only
     in the task start timestamps.
   - **Credentials in logs.** `raise_for_status()` puts the request URL, `?api_key=` included, in
     the exception text; under Airflow that is persisted and shown in the UI. `tmdb_get` now raises
     a path-only error. The longer-term fix is TMDB's bearer-token auth (the v4 read token is
     already provisioned and validated by `just test-tmdb`) so the key is never in a URL at all.
   - Freshness is a separate `pipeline_monitor` DAG rather than a step in `transform`: it is only
     meaningful on a clock, and a stale source should alert, not mark a good dbt build as failed.

## Key open decisions (resolve at each phase)

1. **TV in the catalog (deferred).** The catalog is movies-only. `APPEND_BY_TYPE_LEAN` has no `"tv"`
   key, and `fetch_details()` silently falls back to the *full* append set for any media type the
   profile misses — harmless today, but it multiplies payload size the moment TV is added. Fix that
   fallback as part of adding TV discovery.
2. **Letterboxd RSS cap (Phase 6/7):** `fetch_diary` reads the public RSS feed, which returns only
   the ~50 most recent diary entries (noted only as a docstring in
   [../src/fetch_diary.py](../src/fetch_diary.py) until now). That caps every user's taste profile
   at ~50 recent films — thin, recency-biased, and not every entry is rated. Letterboxd's data
   export (a CSV of full history) would lift it, but it is a manual user upload rather than a feed,
   which would change the shape of `diary_ingest` and of the API's onboarding flow. It also decides
   whether taste clustering is viable at all (it wants ~30+ rated films).
3. **Query-side prefixing (Phase 6):** arctic-embed models are trained for asymmetric retrieval and
   conventionally want a query prefix ("Represent this sentence for searching relevant
   passages: "). `just search` currently embeds the raw string. Similarity scores land around
   0.23-0.30, which is plausible but worth A/B-ing when the taste vector replaces the typed query.
4. **Taste-vector formula (Phase 6):** how ratings weight the aggregate, and how dislikes are
   handled (push away vs simply exclude).
5. **Group aggregation (Phase 6):** average vs least-misery vs Borda for combining members' scores;
   whether to exclude titles seen by *any* member; whether to require shared availability/language.

---

_Provisioning of the external services (TMDB / Snowflake / AWS) is covered in
[external_setup.md](external_setup.md)._
