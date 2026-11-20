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
  labeled **embedding document** per title from the star schema — type, genres, director(s), top 10
  cast in billing order, keywords, tagline, overview (no title; see decision 4) — plus a `document_hash`.
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
- **Group mode.** Each member is scored independently and anything *any* member has watched is
  excluded. `just recommend` combines members per title with **least-misery** (the minimum). The
  API's group list (since 2026-11-20) takes turns instead (`scoring.group_rotation`; see "Where we
  are"). Two identical members reproduce the single-user ranking exactly in both.
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
  `voyage-multilingual-2`, 1024-dim, since 2026-11-19; arctic before) → `MART.MEDIA_EMBEDDINGS`, plus `just search` for semantic
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
    ~40 ms per request; 225 MB resident in the Docker image at 23.7k titles, ~375 MB (measured) at 28.5k titles with film-page text and keywords. Endpoints: `/recommend` (with provider
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

### Phase 9 — Movie detail page (BUILT 2026-11-19; browser pass and a Docker run pending)

Clicking a film card, title or poster (For You, Franchises, Streaming, the hero) opens
`/film/:tmdbId`. Built:

- **Snapshot.** A new optional `details.json` beside `catalog.json` (overview, tagline, directors,
  top 10 cast with characters), written by `publish_snapshot.py` from `DIM_MEDIA`,
  `BRIDGE_MEDIA_PERSON` and `DIM_PERSON` (three read-only queries) and folded into the version hash
  only when present, so old snapshots keep their versions and load with empty text. First real
  build, snapshot `9f7e186bc7d4` (arctic vectors; superseded by `c91a982e8db0`, Voyage): 28,555 titles, `details.json` 18 MB (vectors 58 MB, catalog 6 MB);
  coverage overview 99.9%, directors 99.9%, cast 99.6%, tagline 69.2%.
- **API.** `GET /film/{tmdb_id}` (card fields plus original title, tagline, overview, directors,
  cast, providers-as-of; 404 if absent) and `GET /film/{tmdb_id}/similar?limit=` (capped at 24).
  `scoring.similar_to` is plain cosine over the unit vectors with the recommender's candidate rule
  (60-minute floor, 100-vote floor, never the film itself); it is not z-scored because one seed
  rescales every candidate the same way, so the order is identical.
- **Frontend.** `pages/Film.tsx`: backdrop, poster, title, meta, genres, tagline, overview,
  director, cast, providers with the JustWatch/"as of" label, a Where-to-watch button (TMDB's
  `/watch` page, the same one the hero uses), a TMDB link, and a "more like this" row. `Backdrop`
  moved to `components/` and `FilmLink` is the one internal link used by every title and poster.
  `web/public/_redirects` gives Cloudflare Pages its SPA fallback.
- **Tests.** `tests/test_film.py` (similar vs brute force, exclusions, snapshot round trip with and
  without details, endpoints, 404s, log privacy) and `web/src/lib/film.test.ts`.

Decisions made while building: the URL is `tmdb_id` (stable across rebuilds, movies only today;
becomes `movie-603` style when TV arrives); person headshots deferred (`dim_person` has no
`profile_path`, adding it is a dbt change and a warehouse build); "where to watch" is the single
TMDB/JustWatch page, since TMDB gives no per-provider deep links and `_us_watch_providers()` drops
even the region link.

Built afterwards (2026-11-19): the taste-aware block. `POST /film/{id}/for-me` (the browser sends the
films it already holds, nothing stored) returns the viewer's five liked films closest to this one,
by plain cosine so the order matches the percentages shown, plus "your match" (the mean of the
closest three, the same number the recommendations show). A film the viewer has already logged
says so and shows its rating instead of a match; no import shows an invitation to import; someone
with nothing rated above 3 stars simply gets no block. (`scoring.closest_rated`; it deliberately
does not use the recommender's standardized "because" ordering, whose percentages are not in
order.)

Not built: a person page, trailers, keywords. SEO is unsolved: a client-rendered page
gives search engines nothing, so findable film pages need prerendering, which is a hosting decision.

Verified 2026-11-19 in the browser pane against snapshot `9f7e186bc7d4`: desktop, 768 and 375 px,
light and dark; a film with no tagline and no provider (*Return*) renders cleanly; unknown and
non-numeric ids show the not-found state; clicking a "more like this" title navigates and scrolls to
top; no console errors; no horizontal scroll on a phone. `/film/{id}/similar` takes about 40 ms.
The API process held about 300 MB resident (up from the ~225 MB measured at 23.7k titles; the
catalog is now 28.6k and `details.json` is loaded). **Not done:** the Docker image run (Docker
Desktop was not running), so the in-container figure is still unmeasured; keep at least 512 MB on
the host. Also changed: `api/app.py` now attaches a handler to its logger, because uvicorn
configures only its own loggers and the access log would otherwise have gone nowhere; and
`web/vite.config.ts` reads `PLOTPOINTS_API_PROXY` so a second API on another port can be used.

## Where we are (2026-11-20)

Phases 0-9 are built and run locally end to end. **Nothing is deployed.** The app is feature-complete
for a first launch to friends; what remains is hosting, AWS permissions and a handful of files only
Carson can supply (see "Road to deploy").

**The product, as it runs today**

- **For you:** the top pick with the three films that explain it, the thin-profile warning, a
  "Step outside your comfort zone" pick (below), "The films shaping your picks" (the twelve liked
  films that pull hardest on the top 50, with how many picks each is behind), then other
  recommendations and a "Branch out" row.
- **Browse:** genre, theme (TMDB keyword), director, billed actor and decade, several values per
  kind combined all-of or any-of, with removable filter chips. Every list is still ranked by the
  person's taste and shows only films they have not seen.
- **Watch together:** up to six people (others added by username or export, kept in the browser
  only). The list is built by taking turns (below), and each film shows how high it ranks for each
  person.
- **Franchises:** each shelf lists every unseen film of the series. **Streaming:** the best matches
  on the services you pick. **Film pages:** details, themes, cast, closest films you rated.
- **Settings:** theme, high contrast, text size to 150%, dyslexia-friendly reading, reduced motion.
  WCAG 2.2 AA fixes throughout, checked from 375 to 3840 px wide in light, dark and high contrast.
- **Switches:** `VITE_ADS` (ad slots, default off), `VITE_FEEDBACK_URL` (footer link, default
  hidden). `web/public/tmdb.svg` (TMDB's logo) is picked up if present.

**Decisions made on 2026-11-20 and why**

- **Comfort-zone pick** (decision 5c, now built): `scoring.wildcard_pick`. It qualifies when a film
  scores in the top 15% of all candidates (a real signal), has 1,500+ votes and a TMDB rating of
  7.2+, and none of its genres is more than 5% of what the person likes (widened to 8, 12, 20 and
  30% only if nothing qualifies); the best score wins. For a group the comfort zone is the group's.
  The reason states only what is true: how few liked films are in that genre, that it is well
  rated, and how high it scores. Thresholds are reasoned defaults, not tuned.
- **"Another side of your taste" was removed.** It picked a film whose reasons did not overlap the
  top pick's, which in practice was just the second-best different film and competed with the
  comfort-zone card. That film now appears in "Other recommendations" like any other.
- **Group lists now take turns** (`scoring.group_rotation`). Least-misery (rank by the least-keen
  member's score) was validated as safe, but in use it returned films nobody wanted to watch.
  Rotation: each member in turn gets their highest-scoring film among those every member has in the
  top 5% of their own ranking, widening to 10, 20 and 30% only when a turn finds nothing; one film
  per series; the thinnest history goes first. The SQL scorer (`just recommend`) still uses
  least-misery.
- **Consent is on by default and anonymous.** The "keep my ratings" box on import is pre-ticked,
  and what is kept is only a TMDB id, rating and rewatch flag per film: no Letterboxd username is
  sent. A pre-ticked box is not valid consent under the GDPR (the EU court's 2019 Planet49 ruling),
  so **revisit before any EU-facing or public launch.** This is not legal advice.

**Evidence for group picks** (`data/reports/group_validate.py`, `group_rotation_eval.py`; local,
they read other people's exports). Four real histories, only one of them large (301 films matched;
the others have 9, 47 and 17), so this is a sanity check, not a study.

- Least-misery: no group list ever held a film anyone had seen; each member's group picks sat in
  their own top 0.1-4.3% (popular films: 8-40%; another person's list: 0.5-82%); it protects the
  worst-off member better than a plain average.
- Rotation with a 5/10/20/30% fit ladder against least-misery, 20 picks per group: for the mismatched
  pairs the worst member's median percentile improved in every case (2.3% to 0.9%, 3.2% to 1.6%,
  1.8% to 0.8%, and 4.3% to 2.9% for all four) and top-5% coverage stayed at 100% for pairs, while
  the share of picks in members' own top 1% was about the same overall (57.6% vs 59.6%; better for
  mismatched groups, worse for aligned ones). Lists read as more varied and better known (higher
  median votes; no repeated series). The decisive test is Carson running his own real group.
- A hold-out on the one large diary (hide 25% of liked films): hidden films land at the 8th
  percentile solo and the 22nd as part of a group (random: 50th), while a plain "most-voted first"
  baseline lands at the 4th. That is expected (people mostly watch popular films) and is not a
  reason to rank by popularity, but it is the number to watch if scoring changes again.

**Data.** Snapshot `5b07b4a5e390`: 28,555 titles, 175 provider groups, `voyage-multilingual-2`
embeddings, TMDB keywords on 5+ films (about 7,500 themes; credit-stinger tags hidden), cast,
directors and film-page text. (The 2026-11-16 `catalog_ingest` run loaded 23,747 titles in 2h33m;
the catalog has grown since.) The API image built from it uses about 375 MB of memory, so budget a
host with at least 1 GB.

**Quality gates.** 161 Python tests (`just test`), 46 frontend tests (`cd web && npm test`), ruff,
`npm run build`, and the numpy-vs-SQL equivalence test (`just test -m snowflake`, hits Snowflake).

**Still open, by choice.** TV titles, taste clusters, accounts, keyword combinations beyond one filter
per kind, the commercial licence and ads (all after the friends launch).

### Road to deploy

The strategy is two steps. **Step 1 is a free, non-commercial passion-project launch for friends**,
spread by word of mouth, to gather a real audience. **Step 2 is the commercial push**: the demand
from step 1 is what gets better advertisers on board and what justifies the cost of a TMDB
licence. Nothing in step 1 is commercial (no ads, nothing sold), so TMDB's free terms cover it.

#### Step 1: free launch for friends

Done in code (2026-11-20): ads off by default (`VITE_ADS`), TMDB credit and JustWatch note in the
footer and on About, an optional TMDB logo slot (`web/public/tmdb.svg`), an optional "Send feedback"
link (`VITE_FEEDBACK_URL`), link-preview tags, a phone navigation with a "More" menu, a "Waking up
the server" message, consent on by default and anonymous, a Privacy "Visit counts" paragraph that
appears with `VITE_ANALYTICS=true`, `just test-inbox` to prove the AWS key's permissions, and the
IAM policy files in `docs/iam/`.

Decided: **Cloud Run** (scale to zero, 1 GB, at most 3 instances, a $5 budget alert) for the API;
**Cloudflare Pages** for the frontend; Cloudflare Web Analytics for visits; the S3 inbox for
consented imports; a monthly snapshot refresh by hand. The step-by-step runbook, with the exact
commands, is [deploy.md](deploy.md); the AWS steps are `external_setup.md` section 5b.

Carson's list, in order (consoles, accounts and files only he can provide):

1. [ ] **AWS inbox**: update the uploader policy, create `plotpoints-api-inbox` (put-only), run
       `just test-inbox --write` until every line passes, then one real consent -> `user-ingest`
       -> delete round trip. Optional S3 lifecycle rule. Do this before inviting anyone.
2. [ ] **Accounts**: Google Cloud project with billing (and the $5 budget alert), Cloudflare, and
       the domain (about $12-15 a year; at Cloudflare Registrar it is sold at cost).
3. [ ] **TMDB logo**: download from TMDB's brand assets, save as `web/public/tmdb.svg`.
4. [ ] **Deploy the API** (deploy.md section 3), then **publish the frontend** (section 4) with
       `VITE_API_URL`, optional `VITE_FEEDBACK_URL`, and later `VITE_ANALYTICS=true`.
5. [ ] **Smoke checklist** (section 6), including a consent import and deletion on the live site.
6. [ ] **Invite friends** and start the weekly routine (section 7): `just user-ingest`, a look at
       the budget alert; monthly snapshot refresh.
7. [ ] `just airflow-restart` so the Airflow image picks up the `src/` changes (not needed for the
       API).
8. [ ] Optional: a 1200x630 preview image and `og:image` / `twitter:image` tags.

Measuring demand (what step 2 rests on): Cloudflare Analytics gives visits, countries and devices.
The API log gives the rest: since 2026-11-20 it writes anonymous, count-only event lines (a list for
one or several people, which filter kinds, a bucketed history size, imports, kept copies, deletions;
`api/events.py`, never a title, id, name, username, token or address, with tests that check it) and
`just usage` turns a log into daily numbers (`src/usage_report.py`). It cannot count returning
people, since nothing in the log could tell them apart; "a few hundred monthly users who come back"
has to be read from Cloudflare's visit numbers, not from the log.

#### Step 2: commercial push (after the audience is proven)

Gates, in order:

1. **Demand shown:** repeat visits and real use of the features, not just first visits. Decide the
   bar before looking at the numbers (for example a few hundred monthly users, a healthy share
   returning within 30 days, and a meaningful share using group or browse). These are the numbers
   that get better advertisers on board and justify the licence.
2. **TMDB commercial licence.** Ads make PlotPoints commercial, and TMDB's [terms](https://themoviedb.org:443/api-terms-of-use)
   require a written agreement for that. A figure of about $149 a month appears only in
   third-party sources and is unconfirmed: ask `sales@themoviedb.org` for the real price when the
   demand numbers are in, so the licence cost is weighed against real traffic.
3. **Ads:** build with `VITE_ADS=true`; the slots and placement rules are in `components/Shell.tsx`.
   AdSense has no traffic minimum but can reject app-like pages with little text; the better-paying
   networks want traffic first (Mediavine's commonly quoted bar is 50k sessions a month; check
   with the networks). Requirements to carry into any contract: no autoplay audio or video,
   nothing moving for more than 5 seconds without a pause (WCAG 2.2.2), no focus traps.
4. **Consent and privacy review** for EU visitors: opt-in consent instead of a pre-ticked box, and a
   consent banner for ad cookies.
5. **Alternatives if the licence is unaffordable:** stay non-commercial (donations only), or swap
   the metadata and image source.

**Costs and break-even** (estimates, 2026-11-20; the sources below disagree in places, so confirm
with first-party pricing before budgeting).

Per-user cost is close to zero: a visit is roughly half a vCPU-second of API work, so 100k monthly
users would sit inside Cloud Run's free tier. Costs are fixed steps:

| Item | Monthly |
|---|---|
| API host: Cloud Run (free at this scale) or [Render](https://render.com/pricing.md) Standard | $0-25 |
| Frontend on a free static host (posters come from TMDB's CDN) | $0 |
| Snowflake, if the pipeline runs locally: about 1-3 credits a month at [$2 a credit](https://www.getorchestra.io/guides/snowflake-pricing) | $2-6 |
| S3, domain, odds and ends | $3-5 |
| **Total without a TMDB fee** | **about $10-35** |
| TMDB commercial licence (unconfirmed) | about $149 |
| **Total with it** | **about $160-190** |

Revenue per monthly user is page views times RPM (revenue per 1,000 page views), less ad blockers
(entertainment sites report [about $2-12 RPM](https://eastondev.com/blog/en/posts/media/20260110-adsense-alternatives-comparison/)):
low 5 views x $3 x 70% = $0.011; mid 9 x $6 x 70% = $0.038; high 12 x $10 x 80% = $0.096.

Break-even, in monthly users (fixed cost / revenue per user):

| | Low | Mid | High |
|---|---|---|---|
| Without the TMDB fee, about $25 | 2,400 | 660 | 260 |
| With the TMDB fee, about $175 | 16,700 | 4,600 | 1,800 |

The licence decides everything. Legal and privacy costs are not included.

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

4. **Embedding document + model (Phase 4; revised 2026-11-19, see below).** Field set is **theme +
   people**: type, genres, director(s), top 10 cast in billing order, keywords, tagline, overview — assembled from
   the star schema (not by re-flattening `record`) so it stays consistent with the tested marts.
   People are included deliberately: director/actor affinity drives a lot of real taste. Originally the
   model was `snowflake-arctic-embed-l-v2.0` at 1024 dims, with the title and year as the first line;
   see the revision below. Assembly uses
   `array_construct_compact` so absent fields drop their whole line rather than leaving a dangling
   label, and `listagg` ordering is deterministic — anything non-deterministic would re-embed the
   entire catalog on every run.

   **Revision, 2026-11-19: no title in the document, and Voyage.** With the title on the first line
   and a character who shares its name in the overview, nearest neighbours were films whose *titles*
   share a word: *Good Will Hunting* -> *Happy Hunting*, *MouseHunt*; *Moneyball* -> *Hardball*,
   *Rollerball*, *Cannonball*; *Heat* -> *Red Heat*, *The Heat*, *Dead Heat*. Measured on 400 seeds
   over the whole catalog, 40.2% of each film's ten neighbours shared a title word (0.3% for random
   pairs; 30.3% even when same-franchise films, the legitimate case, are ignored).
   Fix, in `int_media_document.sql` and the `strip_title` macro: drop the title and original-title
   lines, and replace the title in the overview and tagline with "the film" and adjacent word pairs
   of it with "the character" (case-sensitive, word-bounded, never single-word titles, never
   stopword or short-word pairs; about 8% of documents change). Tested first on a 2,411-film sample
   (read-only `SELECT`s, about a quarter of a catalog embed three times): title-word neighbours fell
   from 33.7% to about 12% for every variant, dropping the title line did nearly all of it, and
   `voyage-multilingual-2` gave the most thematic neighbours by eye (*La La Land* for *Whiplash*,
   *The Big Short* for *Moneyball*) but that is four hand-read examples, not a measured win.
   Result on the full catalog after the re-embed (28,555 titles, 125 s): 16.0% of neighbours share a
   title word (6.5% ignoring same franchise), *Good Will Hunting* -> *Finding Forrester*, *Dead
   Poets Society*, *A Beautiful Mind*; *Heat* -> *Thief*, *Heist*, *The Score*, *The Departed*;
   *Moneyball* -> *Million Dollar Arm*, *The Big Short*, *For Love of the Game*. The numpy-vs-SQL
   equivalence test still passes on the new vectors. Known cost of the pair rule: it cannot tell a
   character name from a franchise or person name, so an overview's "Assassin's Creed" or "Dave
   Chappelle" can become "the character". Two bugs the first run exposed and are fixed: `listagg`
   over no usable pairs returns `''`, not NULL, and an empty pattern matched at every word
   boundary, mangling the text (caught by reading samples before embedding). The 2014 *Whiplash*
   that kept topping the experiment was the real film; the seed was the 18-minute 2013 short that
   shares its title, which the candidate rules already exclude.

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
   **Re-checked against real users (2026-11-19), and kept at 100.** Three Letterboxd exports and one
   RSS feed (377 films): 97.3% matched. Of the 10 misses, 3 were matcher errors on films already in
   the catalog (*School of Rock* titled "The School of Rock"; *The Fall* 2006 vs TMDB 2008;
   *Hamilton* re-dated by TMDB 2020 -> 2025), 2 were TV, 1 a 12-minute short, and 4 were real films
   at 47, 29, 8 and 5 votes. Measured supply by floor (per-year `/discover` counts): 100 -> 23,781,
   75 -> 28,548, 50 -> 37,154, 35 -> 46,915, 20 -> 67,519, 10 -> 107,440. A 50 floor (+1.4 h enrich)
   catches none of the four; 20 (+4.5 h) catches two, and the two the users loved (8 and 5 votes)
   are out of reach of any floor. So the matcher was fixed (decision 9) and a user's own missing
   films are enriched directly as taste-only seeds (decision 12) instead.
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
3. **Query-side prefixing (free-text search only).** The earlier arctic-embed models were trained for asymmetric
   retrieval and conventionally want a query prefix ("Represent this sentence for searching relevant
   passages: "); `just search` embeds the raw string. This no longer touches recommendations, which
   compare film documents with film documents (symmetric), only free-text search.
4. **Tune the scoring constants — now possible, needs Carson's judgement.** `DISLIKE_WEIGHT` (0.5),
   `QUALITY_POWER` (2), `TOP_N` (3) and `REWATCH_BONUS` (0.5) are reasoned defaults, not fitted. On
   the full catalog the quality discount is mild (most results x0.83-1.0) and the dislike penalty
   small (<= ~0.35 against scores of 2-4). Whether that balance is right is a reading of the output,
   not a number to derive.
5a. **Franchise saturation. BUILT 2026-11-19** (the options were compared on a real 14-liked-film diary
   first). Three changes together:
   - *Seed dampening* (`scoring.dampen_franchise_seeds`, `DAMPEN_POWER = 0.5`): a person's liked films
     from one franchise share a vote, each weighted `1 / sqrt(k)`. This is the root-cause fix: three
     liked Spider-Man films used to give every Spider-Man-adjacent title a perfect top-3 while a
     one-off taste (one film each for Whiplash, Good Will Hunting, Moneyball) could never fill three
     slots. It is applied where a profile is built (`api.to_profiles`, `recommend.build_profiles`), so
     the SQL and numpy scorers receive identical weights and the equivalence test still passes.
     0.5 is a reasoned default, not fitted: 1.0 would count three films as one, 0.0 is the old
     behaviour.
   - *Bundling* (`POST /recommend` with `bundle: true`): the ranking is folded so each franchise
     appears once, as its best-ranked film with a "+N more" note, and the freed slots go to the next
     titles. Ranking untouched; paging is over the folded entries. The For You hero and reel use it;
     Streaming does not yet.
   - *"Branch out" row* (`branch_out: N`, first unfiltered page only): `scoring.diversify`, a
     maximal-marginal-relevance re-rank of the pool (lambda 0.45) that never returns anything already
     shown, skips the franchises already shown, and takes at most one film per franchise. A film in
     it is removed from later pages of the main reel so it appears once. This is spread, not the
     real wildcard of 5c: everything in it still comes from the person's own ranking.
   Result on the sample diary: the top 22 is now almost all drama and sci-fi picks (*La La Land*, *A
   Beautiful Mind*, *Dead Poets Society*, *The Martian*, *Moon*, *Oppenheimer*) with Spider-Man as
   one bundled entry; Marvel moves to the branch-out row (*Avengers: Infinity War*, overall #33).
   Honest caveat: with dampening the Marvel films fall out of the top 20 for this diary, which
   reads right for these ratings but is a judgement, so `DAMPEN_POWER` is the knob to turn.
   *Franchise data fixed along the way:* TMDB gives *Shang-Chi*, *Thunderbolts\**, *Eternals*,
   *Black Widow*, *Justice League* and others no collection, so they were untagged. `dim_media` now
   falls back to a shared-universe keyword (`seeds/franchise_keywords.csv`: the MCU and the DCEU),
   between the explicit merge seed and the collection name. 18 MCU and 6 DCEU films gained a
   franchise; no re-embedding (the document does not contain the franchise). Not done: MMR for the
   main list, taste clusters, a real wildcard.
5b. **"Unwatched" is only as good as the history.** The RSS feed shows 17 films, so *Iron Man*,
   *Inception* and *Avengers: Endgame* appear because the system cannot know they were seen long
   ago. This is the RSS-cap decision again, and it is the biggest limit on how good the output can
   get — a full-history CSV import would improve it more than any scoring change.
5c. **A "step outside your comfort zone" pick (BUILT 2026-11-20 as `scoring.wildcard_pick`; the original brief follows).** Stated
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
   `build_profiles` counts a rewatch only from RSS rows. Verified on a real export zip 2026-11-19.
   **Rebuilt 2026-11-19 and verified on three real exports.** `api/matching.py` now matches in tiers,
   each tried only when the narrower one finds nothing (so a remake's exact year always wins):
   strict title at the exact year, then +-1; a loose title (accents folded, `&` = and, II = 2, one
   leading article dropped in six languages) at the exact year, then +-1; then +-2. Both the TMDB
   title and the original title are indexed. Rows still unmatched go to `api/tmdb_lookup.py`, which
   searches TMDB at import time (only for those rows, at most 200 per import, cached): an exact title
   at the closest year catches re-dated films like *Hamilton*; an exact TV title marks the row as TV;
   anything else is a real film the catalog lacks (decision 12). Edge cases are pinned in
   `tests/test_matching.py` and `tests/test_tmdb_lookup.py`. The API reads `TMDB_API_KEY` from its
   environment, or that one value from a local `.env`; without it, matching is snapshot-only.
10. **Consent and deletion for ingested users.** Storing someone's viewing history in the warehouse
    needs a clear consent notice at import time and a way to delete it, even though the RSS feed is
    public and an export is private. **Built in Phase 7-8** (consent checkbox, deletion token, the
    `user_ingest` delete/purge steps); awaiting the AWS permissions and a real round trip.
11. **API host** (Cloud Run vs Render), decided at deploy time; the image is host-agnostic and is
    measured at ~225 MB resident, inside either free tier's memory.
12. **Obscure imported titles: taste only, never recommended. RESOLVED 2026-11-19.** A film someone
    imported that the catalog lacks is enriched and embedded so it counts in their profile, but
    `CANDIDATE_MIN_VOTES = 100` (in `scoring.py`, shared with the SQL scorer) keeps anything under
    the catalog floor out of every recommendation. Such films reach the pipeline two ways: in a
    consented import, or on the **anonymous wanted-title list** the API writes on every import
    (`inbox/titles/*.json`: `(media_type, tmdb_id)` pairs and a timestamp, nothing about who asked,
    so no consent is needed). `user_ingest land` copies the list into `RAW.WANTED_TITLES`; `titles`
    enriches whatever neither list's films have in `RAW.TMDB_TITLES` (capped at 500 per run).
    Until the S3 inbox has its IAM, `just user-ingest titles --local-inbox` reads the local inbox.
    First run: 5 titles (*Golden Boy*, *Last Night at the Alamo*, *Frogman*, *Evil Bong 2*,
    *Possibly in Michigan*), snapshot `d4c5aac7e90e` (23,752 titles).
13. **Light-mode accent vs body text.** The shipped light accent is `#8F5A0F` (5.25:1 on the page, 5.77:1 under white button text); the
    Vault 24 `#3F3327` considered earlier was not used. WCAG does not require a gap between accent
    and body text; whether it looks intentional is a judgement for the running app.
14. **Letterboxd ratings instead of TMDB's: not available.** Letterboxd's API is by request only, its
    terms forbid scraping, and exports and RSS hold only the member's own ratings, not the community
    average. The quality prior stays on the Bayesian-shrunk TMDB rating unless API access is granted.
15. **Logging and run visibility (planned, not built).** Today you can see what a run is doing only
    by watching its terminal. What exists and what is missing:
    - *Pipeline output is `print()`.* Only `include/plotpoints_airflow.py` uses `logging` (the single
      greppable `PIPELINE FAILURE` line). Under Airflow the prints still land in task logs; a `just`
      run on the host leaves nothing once the terminal closes.
    - *Silent stretches.* `fetch_catalog` accumulates in memory and prints only when done, so its ~8
      minutes look hung. Enrich prints every 100 titles, which is fine; `load` and
      `dbt build` print per step.
    - *No run history.* Only enrich leaves a summary (`catalog_enriched.summary.json`, overwritten each
      run). Load row counts, dbt results, the snapshot version published and `user_ingest` counts live
      only in the terminal or an Airflow task log, so "what did last Tuesday's run do" has no answer
      outside Airflow's database.
    - *The API is blind.* No request log and no counters. Failures are swallowed on purpose so an
      import never fails: `record_wanted` ignores storage errors and `TmdbLookup` turns any TMDB
      error into "not found". That is right for the user and wrong for the operator, who cannot tell
      a bad TMDB key from a film that does not exist.
    - *Already good:* `pipeline_monitor` (freshness, quality, 24 h cost), `mart_pipeline_health`
      (per-batch), `just cost`, and a single `notify_failure` hook that a Slack or email destination
      can be added to without touching any DAG.

    Proposed, smallest useful steps first:
    1. **Progress for `fetch_catalog`:** a line every N release years or pages (needs an image
       rebuild to reach Airflow).
    2. **One shared logger for `src/`** (stdlib `logging`, one format carrying the step and run id),
       replacing the `print()`s. `src/` must still never import Airflow; Airflow already captures
       the root logger, so DAG logs improve for free.
    3. **A run record per step**, appended as one JSON line to `data/logs/runs.jsonl`: step, start and
       end, counts (fetched, enriched, rows loaded, titles embedded, snapshot version). A later
       `RAW.PIPELINE_RUNS` table could carry the same record into dbt monitoring.
    4. **API logging:** one line per request (method, route, status, milliseconds) and counters for
       import outcomes (matched, missing, TV, TMDB lookups, lookup failures, skipped lookups,
       wanted-list writes). Log the snapshot version at start-up. Surface a failed TMDB lookup as a
       warning with a count, never as an import error.

    **Privacy rule, from the start:** never log request bodies, films, ratings, Letterboxd usernames,
    deletion tokens or the TMDB key. `tmdb_get` already raises path-only errors for the same reason.
    Counts and route names only.

    Open: where logs go once deployed (Cloud Run and Render both capture stdout), retention, and
    whether error tracking (a Sentry-style service) is worth adding before there is real traffic.

---

_Provisioning of the external services (TMDB / Snowflake / AWS) is covered in
[external_setup.md](external_setup.md)._
