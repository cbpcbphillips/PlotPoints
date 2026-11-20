# Running the pipeline

How data gets from TMDB and Letterboxd into the snapshot the API serves. Everything runs through
`just`, or through Airflow, which calls the same code. For the frontend and the API, see
[frontend.md](frontend.md); for provisioning TMDB, Snowflake and AWS, see
[external_setup.md](external_setup.md).

```
TMDB discover ─> catalog_raw.json ─> enrich ─> catalog_enriched.jsonl ─> S3 ─> RAW.TMDB_TITLES ┐
Letterboxd RSS ─> diary_raw.json ─> enrich ─> diary_enriched.json ────> S3 ─> RAW.DIARY_ENTRIES ├─> dbt ─> MART ─> snapshot ─> API
API inbox (imports, wanted ids) ─> RAW.USER_IMPORTS / WANTED_TITLES ─> enrich ─> RAW.TMDB_TITLES ┘
```

| I want to... | Run | Takes | Cost |
|---|---|---|---|
| [**Fill** the catalog from scratch](#1-fill-the-catalog) | `catalog_ingest` DAG, or `catalog-fetch` + `catalog-enrich` + `load catalog` + `dbt build` | ~2.5 h at 100 votes | ~0.2 AI credits + under 1 warehouse credit |
| [**Add** titles to the catalog](#2-upsert-add-new-titles-or-refresh-existing-ones) | the same run, with a lower floor or higher target | only the new titles | proportional |
| [**Refresh** titles already loaded](#2-upsert-add-new-titles-or-refresh-existing-ones) | `catalog-enrich --restart`, then load + dbt | ~2.5 h | no re-embedding unless a title's text changed |
| [Load **missing user titles**](#3-load-missing-user-titles) | `user_ingest` DAG, or `user-ingest titles --local-inbox` | seconds | negligible |
| [Add a **diary**](#4-diary-ingest) | `diary_ingest` DAG, or `fetch` + `enrich` + `load diary` | seconds | negligible |
| [**Publish** what the API serves](#5-rebuild-and-publish-the-snapshot) | `transform` DAG, or `dbt build` + `snapshot` | ~1.5 min | ~0.02 credits |
| [Process **consented imports and deletions**](#6-consented-imports-and-deletions) | `user_ingest` DAG | seconds | negligible |

## Before you run anything

- **Never kick off a full catalog enrich casually.** It is about 50,000 TMDB calls spread over
  hours, and it writes ~1.3 GB to `data/checkpoints/`.
- **Credits.** `PLOTPOINTS_WH` is XSMALL with a 60 s auto-suspend, and `PLOTPOINTS_MONITOR` caps
  *warehouse* credits at 25 (it suspends at 100%). Cortex embeddings bill separately as
  `AI_SERVICES`, which the monitor does not cap. At these volumes both are tiny: embedding the whole
  catalog costs about 0.2 credits (0.45 at 50k titles). Check recent spend with `just cost`.
- **Preflight.** `just test-all` checks TMDB, Snowflake and S3 with read-only calls. Each ingest DAG
  runs the same checks first, so a bad credential fails in seconds.
- **TMDB rate limit.** The code waits 0.3 s between calls and retries on 429. In Airflow the
  `tmdb_api` pool (one slot) makes that hold across tasks.
- **Which way to run.** Everything below has a `just` command (runs on the host, `.env` loaded) and
  an Airflow DAG (runs in Docker, UI at <http://localhost:8080>). They share the same checkpoint
  files under `data/`. Pick one per run; do not run the same step both ways at once.

### Running through Airflow

```powershell
just airflow-start      # build the image and start the stack -> http://localhost:8080
just airflow-restart    # rebuild after changing src/, plotpoints_dbt/ or dependencies
just airflow-stop
```

Only `dags/` and `include/` are live-mounted. After changing anything in `src/` or `plotpoints_dbt/`
you must `just airflow-restart`, or the DAGs run stale code. Every DAG is manual (`schedule=None`):
open it in the UI, press Trigger, and fill in the parameters. Set parameters in the UI rather than
`airflow dags trigger --conf`, because PowerShell 5.1 mangles the JSON quotes.

## 1. Fill the catalog

Builds the candidate pool: every TMDB movie at or above a vote floor, enriched, embedded and
searchable. This is how the 23,747-title catalog was made.

**Airflow (recommended):** trigger `catalog_ingest` with

| Parameter | Default | Meaning |
|---|---|---|
| `min_votes` | 100 | TMDB `vote_count` floor. **This decides the catalog size** (see below) |
| `target` | 30,000 | Stop after this many titles. At floor 100 the supply is ~23.8k, so this is not the limit |
| `limit` | empty | Cap for a trial run. Set `50` to try the whole path in about a minute |

The DAG runs `preflight → fetch → enrich → load`, then the `transform` DAG starts by itself.

**By hand:**

```powershell
just catalog-fetch --min-votes 100            # ~8 min, writes data/checkpoints/catalog_raw.json
just catalog-enrich                           # ~2.5 h, resumable, writes catalog_enriched.jsonl
just load catalog                             # NDJSON -> S3 -> COPY into RAW.TMDB_TITLES
just dbt build                                # staging, marts, embeddings (incremental)
just snapshot                                 # export what the API serves
```

Try it small first: `just catalog-fetch --limit 50`, then the rest of the commands. A 50-title run
exercises every step.

**Supply by vote floor** (measured 2026-11-19, TMDB `/discover` counts per release year):

| Floor | Titles | Extra enrich vs 100 | Extra disk |
|---|---|---|---|
| 200 | ~14,950 | | |
| **100** | **23,781** | | |
| 75 | 28,548 | +0.5 h | +0.26 GB |
| 50 | 37,154 | +1.4 h | +0.74 GB |
| 35 | 46,915 | +2.4 h | +1.28 GB |
| 20 | 67,519 | +4.5 h | +2.43 GB |

Enrich runs at about 2.7 titles per second and writes about 55 KB per title. Below 100 votes the
catalog fills with featurettes, specials and shorts that would show up as recommendations. The floor
review (roadmap decision 5) found that a lower floor would not have caught the films real users were
missing, so it stays at 100.

**Resuming.** Progress lives in the output file. Killing the run (or a laptop sleep) loses nothing:
run `just catalog-enrich` again, or let Airflow retry the task, and it prints
`Resuming: N already enriched, M remaining`.

**Check it worked:**

```powershell
just test-snowflake     # RAW row counts, schemas, Cortex grant
just dbt test           # includes embedding coverage and the batch match rate
```

`mart_embedding_coverage` should report coverage 1.0000 with 0 missing and 0 stale.

## 2. Upsert: add new titles, or refresh existing ones

There is no separate upsert command. The pipeline behaves like one because of how three layers
treat repeats:

| Layer | Behaviour |
|---|---|
| Enrich checkpoint | **Skips** any `tmdb_id` already in `catalog_enriched.jsonl` |
| `RAW.TMDB_TITLES` | **Append-only.** Every load adds rows, and a repeat becomes a duplicate row |
| dbt staging | Keeps the **latest** row per `(media_type, tmdb_id)` by `loaded_at` |
| `MART.MEDIA_EMBEDDINGS` | **Merge**, keyed on the document hash. Only new or changed titles are re-embedded |

So "latest load wins", and re-embedding only happens when something that goes into the embedding
document changed.

### Add new titles (the normal case)

Lower the floor, or raise the target, and run the fill again. The fetch re-reads TMDB; enrich skips
everything already on disk and fetches only the new titles; embedding covers only those.

```powershell
just catalog-fetch --min-votes 75
just catalog-enrich
just load catalog
just dbt build
just snapshot
```

`load` re-sends the whole checkpoint file, so existing titles land again as duplicate RAW rows.
That is expected and harmless: staging keeps the latest. Dbt's embedding step still embeds only the
new titles.

### Refresh existing titles (ratings, vote counts, streaming availability)

Enrich never re-fetches a title it has, so a plain re-run will **not** update anything. To pull
fresh data for every title, discard the checkpoint:

```powershell
just catalog-fetch --min-votes 100
just catalog-enrich --restart          # ~2.5 h: deletes catalog_enriched.jsonl and re-enriches all
just load catalog
just dbt build
just snapshot
```

- It overwrites `data/checkpoints/catalog_raw.json` and `catalog_enriched.jsonl`. Nothing in
  Snowflake is deleted: the new rows land beside the old ones and staging keeps the newest.
- Embeddings are not recomputed unless a title's embedding document changed (its title, year,
  genres, people, keywords, tagline or overview). New ratings and availability do not change it. If
  the document did change for a title, only that title is re-embedded.
- RAW keeps growing by one row per title per refresh. At ~24k titles that is small; if it ever
  matters, dedupe `RAW.TMDB_TITLES` in Snowflake, since staging already ignores the older rows.
- Streaming availability is a snapshot of the day you enriched. The API reports it as "as of" that
  date, taken from the newest `loaded_at`.
- **Do not use `just dbt build --full-refresh`** to "refresh". It re-embeds the whole catalog
  (about 0.2 AI credits, harmless but wasteful) and does not fetch anything new.

### Re-running a load safely

Pass a stable run id and a repeat does nothing:

```powershell
just load catalog --run-id 2026-11-19
```

The same id uploads to the same S3 key, and `COPY` skips a file it has already loaded, so a retry
loads 0 rows instead of duplicating. (Airflow does this for you, keyed on the run id.) Without
`--run-id`, each load gets a wall-clock prefix and always loads.

## 3. Load missing user titles

People import films the catalog does not have (below the vote floor, or just never fetched). Those
films still carry taste, so the pipeline enriches them and lets them shape a profile. They are
**never recommended**: `CANDIDATE_MIN_VOTES = 100` in `src/scoring.py` keeps anything under the
catalog floor out of every result.

**How the films get noticed.** Every import through the API writes an anonymous file to the inbox,
`inbox/titles/<id>.json`, holding `(media_type, tmdb_id)` pairs and a timestamp. There is no user,
rating or username in it, so it needs no consent. `/match` fills it from rows the snapshot could not
match but TMDB identified; the Letterboxd username import fills it from films outside the catalog.
Consented imports (`inbox/imports/`) are a second source: every film in them counts too.

**Run it, from the S3 inbox** (once the inbox IAM exists; roadmap, "Still to do"):

Trigger the `user_ingest` DAG. It runs
`preflight → land → delete → titles → load_titles → purge`.

```powershell
just user-ingest land       # inbox -> RAW.USER_IMPORTS, RAW.USER_DELETIONS, RAW.WANTED_TITLES
just user-ingest titles     # enrich wanted films that RAW.TMDB_TITLES lacks (max 500 per run)
just load user_titles       # land them in RAW.TMDB_TITLES
just dbt build              # embed them
just snapshot
```

**Run it, from the local inbox** (what works today; the API writes to `data/inbox/inbox/` while
`PLOTPOINTS_INBOX=local`, the default):

```powershell
just user-ingest titles --local-inbox    # reads data/inbox/inbox/{imports,titles}/*.json
just load user_titles
just dbt build
just dbt test
just snapshot
```

Then restart `just api` so it loads the new snapshot. Do not run `just user-ingest` with no
`--local-inbox` while `PLOTPOINTS_INBOX=local` is set: it exits with a message saying there is
nothing in S3 to ingest.

**What to expect.**
- `Titles: {'missing': N, 'enriched': N, 'deferred': 0}`. `deferred` is anything past the 500 cap,
  left for the next run.
- Each title is enriched with the same lean TMDB payload as the catalog, so it is embedded like one.
- A TMDB id that no longer exists is skipped, not an error.
- The local files are not deleted afterwards. Re-running is safe: films already in
  `RAW.TMDB_TITLES` are filtered out, so the second run reports `missing: 0`.
- After the snapshot, an imported film that was listed under "Films we can't use yet" in the app
  counts toward the profile and drops off that list.

## 4. Diary ingest

A Letterboxd diary, enriched with the full TMDB payload (it keeps credits, images and the rest).
Small, so it is the one to debug against. This is the original path and is separate from the
in-browser import in the app.

```powershell
just fetch <letterboxd_username>    # RSS -> data/checkpoints/diary_raw.json
just enrich                         # TMDB match -> diary_enriched.json
just load diary                     # S3 -> RAW.DIARY_ENTRIES
just dbt build
```

Or trigger the `diary_ingest` DAG. A feed only holds the newest ~50 entries; a Letterboxd export has
the full history (the app's importer handles that).

## 5. Rebuild and publish the snapshot

The API never queries Snowflake. It loads a snapshot: the embeddings plus what the app shows (title,
year, rating, poster and backdrop paths, franchise, genres, streaming providers), and in
`details.json` the film-page text, directors, the top ten billed cast and TMDB keywords. Keywords
come from `MART.BRIDGE_MEDIA_KEYWORD`; only themes on at least `MIN_KEYWORD_FILMS` (5) films are
kept, and a few disc tags (credit stingers) are hidden (`HIDDEN_KEYWORDS` in
`src/publish_snapshot.py`). That is about 7,500 themes and 2.8 MB. Browsing by genre, director,
actor, theme and decade runs on these fields, so an older snapshot without `details.json` still
serves everything except the people and theme pages. The snapshot read is a handful of `SELECT`s,
about 20 seconds and 0.01 credits.

```powershell
just snapshot                  # MART -> data/snapshots/<version>/, moves LATEST
just snapshot --upload         # also push it to S3
just api-build                 # bake the newest snapshot into the API image
```

- The `transform` DAG already ends with this step (and uploads), so after an Airflow run there is
  nothing to do. You only need `just snapshot` after a manual `just dbt build`.
- The version is a hash of the content. Publishing identical data is a no-op
  (`already published; nothing changed`).
- The API reads the snapshot **once at start-up**. Restart `just api` (or rebuild the image) to
  serve a new one.

## 6. Consented imports and deletions

People who tick the consent box in the app have their ratings stored (to improve the project) and
get a one-time deletion token. The `user_ingest` DAG carries those from the S3 inbox into Snowflake:

| Step | Command | What it does |
|---|---|---|
| land | `just user-ingest land` | `COPY` the inbox into `RAW.USER_IMPORTS` / `USER_DELETIONS` / `WANTED_TITLES`. Skips files it already loaded |
| delete | `just user-ingest delete` | Remove imports whose deletion token hash has a request. dbt filters them anyway |
| titles | `just user-ingest titles` | See section 3 |
| purge | `just user-ingest purge` | Remove inbox files already recorded in RAW, so personal data does not sit in S3 |

`just user-ingest` with no step runs all of them in order. `land` runs before `delete` on purpose, so
a deletion that arrives with its import still removes it. This path needs the inbox IAM changes
(roadmap, "Still to do") and has not yet run against real S3.

## Monitoring and cost

- `pipeline_monitor` DAG: source freshness, data-quality warnings and 24-hour warehouse cost.
- `just cost [--minutes N]`: estimated warehouse credits from recent query history. It covers the
  warehouse only; AI credits come from token counts, and billed truth needs ACCOUNTADMIN in
  Snowsight.
- `just dbt test`: schema tests plus freshness and match-rate checks. One warning is expected until
  the batch match rate recovers: `assert_batch_match_rate_healthy` flags the 94.4% diary batch left
  from a failure-path test.

## Troubleshooting

- **`Catalog checkpoint not found`**: run `just catalog-fetch` first; enrich reads its output.
- **Enrich says nothing to do**: every id is already in `catalog_enriched.jsonl`. To re-fetch, use
  `--restart` (section 2).
- **A run was interrupted**: run the same command again. Enrich, and a retried Airflow task, resume.
- **`just user-ingest` says PLOTPOINTS_INBOX=local**: use `--local-inbox`, or unset the variable once
  the S3 inbox exists.
- **Airflow runs old code**: `just airflow-restart` after editing `src/` or `plotpoints_dbt/`.
- **TMDB 401 or 429 storms**: `just test-tmdb`. Error messages carry the request path only, never
  the API key.
- **New films not appearing in the app**: the API loaded its snapshot at start-up; restart `just api`.
- **Duplicate rows in `RAW.TMDB_TITLES`**: expected after repeated loads (the real catalog has
  24,807 rows for 23,747 titles). Staging keeps the latest; nothing downstream sees the duplicates.
