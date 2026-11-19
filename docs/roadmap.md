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

## User taste + recommend (single & group) — BUILT, Phase 6

[../src/recommend.py](../src/recommend.py) (`just recommend VetOW`, or several usernames for a
group). It is request-time SQL over `MART.MEDIA_EMBEDDINGS`, not a dbt model, so a brand-new user
gets an answer the moment their diary lands.

**There is no stored taste vector.** The original design averaged a user's film embeddings into one
vector (`MART.USER_TASTE_VECTORS`). That was dropped on purpose: the mean of two tastes is not a
taste. Someone who loves both superhero films and sports dramas averages into a point near neither.
A profile is instead a *set of weighted films*, and each candidate is scored against the films that
actually resemble it.

- **Profile.** One row per film (latest watch's rating wins; unrated films stay in as "seen" but
  carry no signal). `weight = rating - 3`, plus 0.5 for a rewatched film the user liked.
- **Relevance.** Mean of a candidate's three best matches among liked films, each contribution being
  similarity x (weight / the user's strongest weight). The three best, rather than the single best,
  so one outlier film can't dominate.
- **Similarity is z-scored per seed film** against that film's own distribution over the catalog.
  Measured on this catalog, mean cosine similarity from a diary film to everything else ranges from
  0.295 (*Moneyball*) to 0.412 (*Obsession*) against a standard deviation of only ~0.05, so raw cosine
  would let high-floor films dominate every recommendation. This is the standard hubness correction.
- **Dislikes** subtract `0.5 x` the candidate's z-scored similarity above baseline to the nearest
  disliked film. Per candidate, so no vector is ever moved: a strong negative can't drag an averaged
  vector somewhere arbitrary.
- **Quality prior.** TMDB rating shrunk toward the catalog mean by vote count (`m` = 100, the vote
  floor), then compared with the *user's own* standard (the weighted rating of what they like):
  `min(1, q / anchor)^2`. A discount, never a boost or a filter; someone who loves schlock isn't
  denied it by a global bar.
- **Group mode.** Each member scored independently, combined per title with **least-misery** (the
  minimum), and anything *any* member has watched is excluded. Two identical members reproduce the
  single-user ranking exactly.
- **Explanations** (`because: [...]`) are the top-3 liked films behind each result — a by-product of
  the scoring, and what a frontend card needs.

## Orchestration (Airflow — BUILT, Phase 5)

Astro Runtime 3.3 (Airflow 3.3, Python 3.14) in Docker, project at the repo root so the image
contains `src/` and `plotpoints_dbt/`. Five DAGs; four are manually triggered, `transform` runs
on the assets:

| DAG | Trigger | Tasks |
|---|---|---|
| `catalog_ingest` | manual | preflight → fetch → enrich → load → emits `raw_tmdb_titles` asset |
| `diary_ingest` | manual | preflight → fetch → enrich → load → emits `raw_diary_entries` asset |
| `user_ingest` | manual | preflight → land inbox → apply deletions → enrich new titles → load → purge landed files |
| `transform` | any RAW asset updates | preflight → Cosmos task group (one task per dbt model/test) → cost record + **publish serving snapshot** |
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
- **Phase 5 — Orchestration + monitoring + containerization — DONE:** the Airflow DAGs above, the
  dbt monitoring models, and the Docker image. Exit criterion met on 2026-11-16: the real catalog
  load ran *through* `catalog_ingest` (23,746 titles, 2h33m end to end, no retries needed), and
  `transform` fired on its own and embedded the lot.
- **Phase 6 — Taste + recommend — DONE:** `src/recommend.py` and `just recommend`; see the section
  above. Verified with 23 checks on both the 1010-title and the full 23.7k catalog (no watched film
  returned, penalty arithmetic exact to 0.0001, group = min of members, identical members reproduce
  the single-user ranking); 1.3-2.0 s per call warm. The first full-catalog run was read critically
  and found two real defects (a short film and a making-of documentary recommended), fixed with a
  runtime floor; franchise saturation remains an open decision.
- **Phase 7 — Serving — BUILT (2026-11-16); AWS inbox permissions and deploy remain:**
  - *7a, snapshot.* [../src/publish_snapshot.py](../src/publish_snapshot.py) (`just snapshot`)
    exports vectors (float16, unit-normalized) plus the title/rating/poster/franchise/provider
    columns the app shows to `data/snapshots/<content-hash>/`; the `transform` DAG ends with it and
    uploads to S3 `artifacts/snapshots/`. Verified: the Airflow-built snapshot has the same content
    hash as the local one. dbt gained `bridge_media_provider` (209 raw provider names -> 171 groups),
    a `franchise` column (explicit merge seed, else the TMDB collection), and poster paths.
  - *7b, API.* [../api/](../api/) (FastAPI) + [../src/scoring.py](../src/scoring.py), the numpy
    port of the SQL scorer. **Equivalence verified against live Snowflake**: same top-50 in the same
    order, max score difference 0.0002 (float16), single user, dislike-penalty off, and a group.
    ~40 ms per request, 225 MB resident in the Docker image. Endpoints: `/recommend` (with provider
    filter inside the ranking, plus each title's overall rank), `/franchises`, `/import/letterboxd`,
    `/match` (title+year -> TMDB id, flagging ambiguity), `/consent`, `/delete`, `/meta`.
  - *7c, inbox.* [../src/user_ingest.py](../src/user_ingest.py) and the `user_ingest` DAG land the
    S3 inbox in `RAW.USER_IMPORTS` / `RAW.USER_DELETIONS`, delete on request, enrich titles the
    catalog lacks, and purge landed files. dbt unions imports into `fct_diary_entry` with a `source`
    column. **Not yet run against real S3**: it needs two IAM changes (see "Still to do").
- **Phase 8 — Frontend — BUILT (2026-11-16):** [../web/](../web/), React + Vite + TypeScript +
  Tailwind v4, 138 KB gzipped. Import (export zip/CSVs parsed in the browser, or a username), For
  You, Franchises, Streaming, Import (returning), About, Privacy/deletion. Desktop, tablet (hero and
  grid) and phone layouts verified in a browser at 1440, 820 and 402 px; light and dark.

### Still to do for Phases 7-8

1. **AWS (needs the console):** a new IAM user for the API with `s3:PutObject` on `inbox/*` only, and
   `s3:DeleteObject` on `inbox/*` for the pipeline uploader. Then run the inbox round trip for real
   (consent -> `just user-ingest` -> delete) and set `PLOTPOINTS_INBOX=s3` on the API.
2. **Deploy:** choose the API host (decision 8: Cloud Run or Render), host `web/dist` statically, set
   `VITE_API_URL` and `PLOTPOINTS_CORS_ORIGINS`.
3. **TMDB logo** (their brand asset, not in the repo) next to the disclaimer on the About page;
   currently text only. Required for a public site.
4. **Posters.** The app uses the chosen title-on-color tiles; real images come from TMDB's image CDN
   and carry the same attribution requirement.

### Where we are (2026-11-18)

Phases 0-8 are built and run locally end to end; **nothing is deployed**. The stage is *Phase 9:
redesign, posters and monetisation, then deploy*.

- **UI redesign in progress.** `web/` is the v0 (title-on-color tiles). Six alternative directions
  are mocked in `docs/mockups/` (constellation, projector noir, ticket stub, modernist poster, slate
  dots, red carpet); one has to be chosen and ported before the frontend is called done.
- **Ad rails (placeholder).** `Shell.tsx` reserves a 160x600 sticky slot either side of the 1200px
  column, shown only at >=1600px so narrower screens never reflow. Each holds a "please disable your
  adblocker so we can keep PlotPoints free for all" card standing in for the ad tag. No network is
  chosen. Open questions: pick one (AdSense needs an approved, deployed domain, so this cannot be
  finished before deploy), mobile placement (rails vanish below 1600px, so phones and laptops see no
  ads and earn nothing), and real adblock detection instead of always showing the card.
- **Posters.** Snapshot already carries `poster_path`, but the catalog's lean payload has no
  `images` append, so there is only TMDB's single default poster per title, not a US-language one.
  US posters means adding `images` with `include_image_language=en,null` to the catalog append set
  and choosing the top English poster in dbt. That re-enriches ~23.7k titles (~2.5 h, as before) or
  a targeted backfill of `/images` alone. Needs a decision, and TMDB's attribution requirement
  applies to the images.
- **Licensing conflict to resolve before ads.** Decision 8 notes TMDB's free tier is non-commercial
  and a project whose primary purpose is revenue needs a license. Ads put PlotPoints on the wrong
  side of that; get the commercial terms (or an alternative image/metadata source) settled before
  any ad network goes live.
- **Still outstanding** from the list above: IAM changes and a real inbox round trip, host choice,
  TMDB logo, and verifying the export import on a real Letterboxd zip.

### Where the data actually stands

The catalog is **23,747 titles** (23,746 from the 2026-11-16 `catalog_ingest` run, floor 100, plus one
diary-only film), spanning **1900-2026**, all embedded: `mart_embedding_coverage` reports coverage
1.0000 with 0 missing and 0 stale, the new batch has a match rate of 1.0, and under 0.4% of titles
lack any key field (0.07% no overview, 0.31% no cast). The fetch returned 23,746 against a
sampling-based estimate of 23,794 (see the vote-floor decision below).

Run economics, measured: fetch ~8 min, enrich ~2.35 h at 2.69 titles/s (the Sept trial's 1000 titles
were reused through resume), `transform` 1.5 min, **2h33m end to end**. Only 14,952 movies have 200+
votes, so the catalog's size is set by the floor, not by `--target`.

Still a **single-user** dataset: one Letterboxd diary (`VetOW`, 17 entries). Group mode is verified
only on a synthetic split of it.

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

7. **Recommendation scoring (Phase 6).** No stored taste vector; profile = weighted films;
   relevance = mean of the top-3 z-scored, weight-scaled similarities; dislikes as a per-candidate
   penalty; quality judged against the user's own standard; group = least-misery. Rating map is
   `rating - 3` (Letterboxd's midpoint), chosen over "relative to the user's mean" because this
   diary averages 4.26 and 14 of its 17 films are 4 stars or more, which a relative scale would
   turn into mild dislikes. Two things the first run exposed: per-seed similarity floors differ by
   ~0.12 (hence z-scoring), and **titles are not unique** — two different films are each named
   "Good Boy" and "The Killer" — so every result carries `media_key` and `tmdb_id`, and nothing may
   key on title.
   The first run on the full catalog added a runtime floor: candidates under 60 minutes are
   skipped (`--min-runtime`), because the vote floor does not keep out shorts and making-ofs. It
   recommended an 18-minute short of *Whiplash* (the film the feature grew from) and a 23-minute
   *Interstellar* documentary; both are different titles from the films watched, so the
   already-watched filter could not catch them. The floor touches 3.4% of the catalog and keeps
   every real feature in the borderline band (*Dumbo*, 64 min). It applies to candidates only, so
   shorts you have watched still count as taste signal.

8. **Serving and frontend stack (Phase 7-8).** Decided 2026-11-16.
   - **Serve from an exported snapshot, not live Snowflake.** All 23,747 vectors are 97 MB as
     float32 and 49 MB as float16, small enough to hold in memory and rank with numpy in
     milliseconds. A public URL backed by live Snowflake would let anyone spend warehouse credits,
     and the 25-credit monitor suspends the warehouse the pipeline also uses; it would also put a
     private key in the hosting environment and add cold-warehouse latency. Snowflake stays the batch
     side. Cost: the scorer exists twice (SQL for batch and tests, numpy for serving), so
     equivalence is a tested property, and the pipeline gains a publish step.
   - **Frontend:** React + Vite + TypeScript + Tailwind. It builds to static files, so any free
     static host works (Cloudflare Pages, Vercel Hobby); Cloudflare Pages caps a single asset at
     25 MiB, which is why the vectors live with the API and not on the static host.
   - **API host: undecided on purpose.** Build a Docker image that runs locally and on either
     candidate. Verified: Cloud Run's free tier is 2M requests, 180k vCPU-seconds and 360k GiB-seconds
     a month, scales to zero, and needs a billing account; Render's free tier gives 750 instance hours
     but sleeps after 15 minutes and takes about a minute to wake, and Render says not to use it for
     production. **Hugging Face Docker Spaces are not free** (only static Spaces are).
   - **Stateless serving, ingesting pipeline.** The app has no accounts or sessions. Imports are
     parsed in the browser and sent with each request. Separately, with consent, an import is dropped
     in an S3 inbox for the batch pipeline. The API's only AWS credential is write-only on that
     prefix, so a leaked key can add files but cannot read anything or touch Snowflake.
   - **Compliance that is not optional on a public site:** TMDB requires its logo and the sentence
     "This product uses the TMDB API but is not endorsed or certified by TMDB" in an About or Credits
     area; free use is non-commercial (a project whose primary purpose is revenue needs a license).
     Streaming availability must be attributed to **JustWatch**, and TMDB can revoke API access for
     not doing so. Show an "as of <date>, US only" label, since availability is a snapshot.

9. **Serving behaviour (Phase 7-8).** Decided 2026-11-16.
   - **The match percentage is raw cosine similarity**, shown as a whole percent: the mean cosine
     between a recommendation and the three liked films that explain it. The ranking is *not* by
     this number; it stays on the z-scored score (the hubness correction in decision 7), because raw
     cosine lets high-floor films dominate. Consequence, stated on the About page: percentages are
     not strictly decreasing down the list. Measured on the real catalog: top picks land at 51-64%
     and unrelated films at 30-40%, so a "good" match is a modest-looking number. A percentile
     was rejected (every top-20 pick would read 99%) and a star rating was rejected (nothing fits
     it).
   - **A provider filter is applied inside the ranking, after the per-seed z-scoring.** Restricting
     the pool first would change every title's score; filtering after means a title scores the same
     with or without the filter and only the set that competes changes. Each filtered result also
     reports its rank in the unfiltered list ("overall 22").
   - **Providers are grouped** (209 raw names -> 171): tier and channel suffixes are stripped
     ("Netflix Standard with Ads", "HBO Max Amazon Channel") and a seed maps brands TMDB spells two
     ways. Only subscription (flatrate) counts as "can watch".
   - **Franchises, first cut:** an explicit `collection_id -> franchise` seed merges the multi-
     collection series (Spider-Man's four collections, the MCU's eight, X-Men, Godzilla, Star Trek and
     so on), else the TMDB collection name, else none. Reviewable and wrong in known ways; the
     fuller model remains open decision 8.
   - **Imports and rewatches.** An import is a set of films seen and rated, not watch events. The
     recommender counts a rewatch only from dated RSS rows or an import's own Rewatch flag, so a
     film present in both is not double-counted. Inside a Letterboxd zip only the three exact
     top-level CSVs are read: `watchlist.csv` and `likes/films.csv` share watched.csv's columns and
     would otherwise mark unwatched films as seen.
   - **Deletion without accounts:** consent returns a random token once; only its SHA-256 is stored.
     `user_ingest` deletes the rows and purges the S3 files, and dbt also excludes any import whose
     hash has a tombstone, so a missed run cannot leak a deleted import. Time Travel can still hold
     deleted rows for its retention window.
   - **Snapshot baked into the image**, not read at start-up: the running API needs no AWS read
     credential and every deploy serves exactly one known version of the data.

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
3. **Query-side prefixing (free-text search only).** arctic-embed models are trained for asymmetric
   retrieval and conventionally want a query prefix ("Represent this sentence for searching relevant
   passages: "); `just search` embeds the raw string. This no longer touches recommendations, which
   compare film documents with film documents (symmetric), only free-text search.
4. **Tune the scoring constants — now possible, needs Carson's judgement.** `DISLIKE_WEIGHT` (0.5),
   `QUALITY_POWER` (2), `TOP_N` (3) and `REWATCH_BONUS` (0.5) are reasoned defaults, not fitted. On
   the full catalog the quality discount is mild (most results x0.83-1.0) and the dislike penalty
   small (<= ~0.35 against scores of 2-4). Whether that balance is right is a reading of the output,
   not a number to derive.
5a. **Franchise saturation.** For Carson's diary, 6 of the top 10 are Spider-Man films and 11 of 20
   are Marvel/DC. This is the scoring working as designed: three liked Spider-Man films give every
   Spider-Man film a perfect top-3, while one diary film each for Whiplash/Good Will Hunting/
   Moneyball cannot. Options, none applied: cap results per TMDB `collection_id`; re-rank for
   diversity (MMR) over the top-100; or cluster the liked films and take the best few per cluster.
5b. **"Unwatched" is only as good as the history.** The RSS feed shows 17 films, so *Iron Man*,
   *Inception* and *Avengers: Endgame* appear because the system cannot know they were seen long
   ago. This is the RSS-cap decision again, and it is the biggest limit on how good the output can
   get — a full-history CSV import would improve it more than any scoring change.
5c. **A "step outside your comfort zone" pick (wanted: a real feature, not built).** Stated
   requirement: offer the viewer *a good pick outside their typical niche that is still
   recommended from their taste profile*. It is a deliberate option, not a side effect of
   diversity, and it should be surfaced as its own recommendation (the 07 mock-ups put it beside
   the main pick). "Outside the niche" and "from their taste" pull in opposite directions, so the
   selection has to hold both: far from where the ratings cluster, but still carrying a positive
   signal from the profile (a mid-similarity film with strong ratings, not a random one). The 07
   mock fakes it as "best film outside the top franchise"
   (*Avengers: Infinity War*, overall rank 5 for the VetOW diary), which is only franchise
   diversity (5a), not a real wildcard. A real one needs its own selection step rather than a
   tweak to `recommend.py`'s ranking, because the ranking by design returns the nearest films.
   Candidates, none applied: take the best-scoring title from a *different cluster* of the
   catalog than the liked films (needs cluster labels in the snapshot); take a mid-similarity
   film (e.g. cosine 0.35-0.5) that is strongly rated on TMDB; or MMR re-ranking with an explicit
   "far from the profile" slot. It should be a separate function (and likely its own response
   field, e.g. `wildcard`) so the main ranking and its tests stay untouched. It also needs a
   "why" that does not claim similarity to the liked films.
5d. **A novelty signal (wanted in the frontend, not in the API).** The 07 mock-ups show a third
   dot, Novelty, beside Match and TMDB rating. The API exposes no such value, so the mock computes
   it as `100 - match` of the closest film the viewer rated (hero: 77% closest, novelty 23; the
   reel sits at 39-50). That is a stand-in, not a decision. Open: define it properly (distance
   from the nearest *seen* film vs. distance from the whole profile vs. obscurity from vote
   count; vote count was tried and reads near 0 for every blockbuster, so it separates nothing)
   and add it to `present()` as its own field. It is display-only and must not enter the ranking
   score. It also pairs naturally with the 5c wildcard, which is the same idea used as a selector.
6. **Presenting more than one taste (deferred).** Clustering a user's liked films into groups
   ("your slashers / your sci-fi") would organize the *output*; the scoring doesn't need it, since
   it never averages. It needs roughly 30+ rated films, which the ~50-entry RSS cap makes marginal.

7. **Platform filtering belongs inside the ranking.** Measured on real output: only 35 of the top 400
   recommendations stream on Netflix, and the best of them (*Alien*) is overall rank 22. Filtering a
   finished list would surface rank-22 as "your top Netflix pick" and hide better matches. The
   provider filter must restrict the candidate set before scoring. Also: 209 distinct streaming
   providers appear, and "Netflix" and "Netflix Standard with Ads" are listed separately, so the UI
   needs a normalized provider list. Availability is a Nov-16 snapshot with its own refresh cadence.
8. **What is a "franchise"?** TMDB collections are too narrow: Spider-Man spans four collections
   (Raimi, Amazing, MCU, Spider-Verse), the MCU at least five, and only 21% of the catalog belongs to
   a collection at all (36% of the top 80 recommendations belong to none). A franchise-grouping model
   is needed: merge collections via shared keywords or an explicit merge table, and decide what to do
   with standalone films.
9. **Letterboxd export import** (extends the RSS-cap decision above). The CSVs carry title, year and a
   Letterboxd link but no TMDB id, so films are matched on title and year, which collides (two films
   are named "Good Boy"). Films outside the catalog have no embedding and must be reported as
   unmatched. Combining RSS and CSV rows for one film must not trigger the rewatch bonus.
   **Built in Phase 7-8** (see decision 9): the browser parses the export, `/match` resolves title+year
   (a year either side tolerated, the most-voted film winning and the row flagged ambiguous), and
   `build_profiles` counts a rewatch only from RSS rows. Not yet verified on a real export zip, only
   on a synthetic one in unit tests.
10. **Consent and deletion for ingested users.** Storing someone's viewing history in the warehouse
    needs a clear consent notice at import time and a way to delete it, even though the RSS feed is
    public and an export is private. **Built in Phase 7-8** (consent checkbox, deletion token, the
    `user_ingest` delete/purge steps); awaiting the AWS permissions and a real round trip.
11. **API host** (Cloud Run vs Render), decided at deploy time; the image is host-agnostic and is
    measured at ~225 MB resident, inside either free tier's memory.
12. **Obscure imported titles join the recommendable catalog.** `user_ingest` enriches films a
    person imported that the catalog lacks, and they are then embedded and served to everyone,
    including titles under the 100-vote floor. A candidate vote floor in both scorers (they
    already share constants) would keep seeds unrestricted and candidates clean.
13. **Light-mode accent vs body text.** Vault 24 `#3F3327` has 10.1:1 contrast on the page, but only
    1.31:1 against the body text, so the accent reads nearly as text in light mode. WCAG does not
    require a gap; whether it is enough to look intentional is a judgement for the running app.

---

_Provisioning of the external services (TMDB / Snowflake / AWS) is covered in
[external_setup.md](external_setup.md)._
