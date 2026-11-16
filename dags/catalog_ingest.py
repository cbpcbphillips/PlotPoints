"""Catalog ingest: TMDB discovery -> enrich -> S3 -> COPY into RAW.TMDB_TITLES.

Manual trigger only (schedule=None). The enrich step is ~2.5h at the default 100-vote floor
and is resumable, so interrupting or retrying it continues rather than restarts.
"""

import pendulum
from airflow.sdk import Param, dag, task

from include.plotpoints_airflow import (
    ENRICH,
    FETCH,
    LOAD,
    PREFLIGHT,
    RAW_TMDB_TITLES,
    notify_failure,
    run_preflight,
    stage_run_id,
)


@dag(
    dag_id="catalog_ingest",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    # catchup is moot with schedule=None, but if a schedule is ever added, an unset catchup
    # would backfill every missed interval -- each one a multi-hour enrichment.
    catchup=False,
    # Two runs racing the same checkpoint file and RAW table is corruption, not slowness.
    max_active_runs=1,
    params={
        "target": Param(30_000, type="integer", minimum=1, description="titles to fetch"),
        "min_votes": Param(100, type="integer", minimum=0, description="vote_count floor"),
        "limit": Param(None, type=["null", "integer"], description="cap for trial runs"),
    },
    default_args={"on_failure_callback": notify_failure},
    tags=["ingest", "tmdb"],
    doc_md=__doc__,
)
def catalog_ingest():
    @task(**PREFLIGHT)
    def preflight():
        run_preflight("check_tmdb.py", "check_snowflake.py", "check_aws.py")

    # pool="tmdb_api" (1 slot): the code's 0.3s delay only holds within one process; the pool
    # makes the TMDB rate limit hold across everything Airflow schedules.
    @task(pool="tmdb_api", **FETCH)
    def fetch(params=None) -> int:
        import fetch_catalog

        return fetch_catalog.run(params["target"], params["min_votes"], params["limit"])

    @task(pool="tmdb_api", **ENRICH)
    def enrich(fetched: int) -> dict:
        import enrich_catalog

        # restart=False on purpose: a retry must resume, not discard hours of progress.
        return enrich_catalog.run(restart=False)

    @task(outlets=[RAW_TMDB_TITLES], **LOAD)
    def load(summary: dict, run_id=None) -> int:
        import load_snowflake

        return load_snowflake.load("catalog", run_id=stage_run_id(run_id))

    # preflight must gate the FIRST work task. `preflight() >> load(enrich(fetch()))` reads like
    # a chain but only makes preflight upstream of load -- fetch and enrich would run beside it,
    # so a bad credential would still burn the whole enrich before preflight mattered.
    checks = preflight()
    fetched = fetch()
    checks >> fetched
    load(enrich(fetched))


catalog_ingest()
