"""Diary ingest: a Letterboxd RSS diary -> enrich -> S3 -> COPY into RAW.DIARY_ENTRIES.

Manual trigger only. The RSS feed returns at most ~50 recent entries, so this is seconds of
work -- which makes it the right DAG to debug orchestration against before the catalog run.
"""

import pendulum
from airflow.sdk import Param, dag, task

from include.plotpoints_airflow import (
    ENRICH,
    FETCH,
    LOAD,
    PREFLIGHT,
    RAW_DIARY_ENTRIES,
    notify_failure,
    run_preflight,
    stage_run_id,
)


@dag(
    dag_id="diary_ingest",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    params={"username": Param("VetOW", type="string", minLength=1, description="Letterboxd user")},
    default_args={"on_failure_callback": notify_failure},
    tags=["ingest", "letterboxd"],
    doc_md=__doc__,
)
def diary_ingest():
    @task(**PREFLIGHT)
    def preflight():
        run_preflight("check_tmdb.py", "check_snowflake.py", "check_aws.py")

    @task(**FETCH)
    def fetch(params=None) -> int:
        import fetch_diary

        return fetch_diary.run(params["username"])

    @task(pool="tmdb_api", **ENRICH)
    def enrich(fetched: int) -> dict:
        import enrich_tmdb

        return enrich_tmdb.run()

    @task(outlets=[RAW_DIARY_ENTRIES], **LOAD)
    def load(summary: dict, run_id=None) -> int:
        import load_snowflake

        return load_snowflake.load("diary", run_id=stage_run_id(run_id))

    # preflight must gate the FIRST work task. `preflight() >> load(enrich(fetch()))` reads like
    # a chain but only makes preflight upstream of load -- fetch and enrich would run beside it,
    # so a bad credential would still burn the whole enrich before preflight mattered.
    checks = preflight()
    fetched = fetch()
    checks >> fetched
    load(enrich(fetched))


diary_ingest()
