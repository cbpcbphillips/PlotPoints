"""User ingest: carry consented imports and deletion requests from the S3 inbox into Snowflake.

Manual trigger, like every DAG here. The public API only ever *writes* small JSON files to
`inbox/`; this is the batch side that picks them up. Each step is `just user-ingest <step>`, and
each is safe to repeat (COPY skips files it already loaded; deletes are by hash).

  preflight -> land -> delete -> titles -> load_titles -> purge

`land` precedes `delete` so a deletion arriving in the same batch as its import still removes it.
`purge` removes only inbox files already recorded in RAW, so personal data does not linger in S3.
Landing emits the `raw_user_imports` asset; `transform` runs on it and rebuilds the marts.
"""

import pendulum
from airflow.sdk import dag, task

from include.plotpoints_airflow import (
    ENRICH,
    LOAD,
    PREFLIGHT,
    RAW_TMDB_TITLES,
    RAW_USER_IMPORTS,
    notify_failure,
    run_preflight,
    stage_run_id,
)


@dag(
    dag_id="user_ingest",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"on_failure_callback": notify_failure},
    tags=["ingest", "users"],
    doc_md=__doc__,
)
def user_ingest():
    @task(**PREFLIGHT)
    def preflight():
        run_preflight("check_tmdb.py", "check_snowflake.py", "check_aws.py")

    @task(outlets=[RAW_USER_IMPORTS], **LOAD)
    def land() -> dict:
        import user_ingest as step

        return step.land()

    @task(**LOAD)
    def delete(landed: dict) -> int:
        import user_ingest as step

        return step.apply_deletions()

    @task(pool="tmdb_api", **ENRICH)
    def titles(removed: int) -> dict:
        import user_ingest as step

        return step.enrich_missing()

    @task(outlets=[RAW_TMDB_TITLES], **LOAD)
    def load_titles(summary: dict, run_id=None) -> int:
        if not summary.get("enriched"):
            print("No new titles to land")
            return 0
        import load_snowflake

        return load_snowflake.load("user_titles", run_id=stage_run_id(run_id))

    @task(**LOAD)
    def purge(loaded: int) -> int:
        import user_ingest as step

        return step.purge()

    checks = preflight()
    landed = land()
    checks >> landed
    purge(load_titles(titles(delete(landed))))


user_ingest()
