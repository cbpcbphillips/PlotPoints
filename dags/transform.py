"""Transform: dbt build of the whole star schema, including the Cortex embeddings.

Not triggered by hand in normal use. It is scheduled on the RAW assets, so it runs whenever
catalog_ingest, diary_ingest or user_ingest lands rows -- once, not several times, if more than
one did. It ends by publishing the serving snapshot the API is built from (publish_snapshot.py).

Cosmos renders the dbt project as one Airflow task per model and per test, so a failure
names the exact model and a retry reruns only that node, not all of dbt.
"""

from datetime import timedelta

import pendulum
from airflow.sdk import dag, task
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import InvocationMode

from include.plotpoints_airflow import (
    DBT,
    DBT_EXECUTABLE,
    DBT_PROJECT_DIR,
    PREFLIGHT,
    RAW_DIARY_ENTRIES,
    RAW_TMDB_TITLES,
    RAW_USER_IMPORTS,
    SERVING_SNAPSHOT,
    notify_failure,
    run_preflight,
)

# Reuses the project's own profiles.yml, which reads the connection from env vars -- the
# same file `just dbt` uses on the host, so there is one definition of "how dbt connects".
PROFILE = ProfileConfig(
    profile_name="plotpoints",
    target_name="dev",
    profiles_yml_filepath=DBT_PROJECT_DIR / "profiles.yml",
)


@dag(
    dag_id="transform",
    # `|` = run when EITHER asset updates. A bare list means ALL of them, which would make
    # a diary-only ingest wait forever for a catalog update that isn't coming.
    schedule=(RAW_TMDB_TITLES | RAW_DIARY_ENTRIES | RAW_USER_IMPORTS),
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"on_failure_callback": notify_failure},
    tags=["transform", "dbt"],
    doc_md=__doc__,
)
def transform():
    @task(**PREFLIGHT)
    def preflight():
        run_preflight("check_snowflake.py")

    dbt = DbtTaskGroup(
        group_id="dbt",
        project_config=ProjectConfig(dbt_project_path=DBT_PROJECT_DIR),
        profile_config=PROFILE,
        # SUBPROCESS, explicitly, for both rendering (`dbt ls`) and execution. Cosmos otherwise
        # picks in-process DBT_RUNNER whenever dbt is importable, which cannot be combined with
        # a separate venv's executable -- and that venv is the whole point (see Dockerfile).
        execution_config=ExecutionConfig(
            dbt_executable_path=DBT_EXECUTABLE, invocation_mode=InvocationMode.SUBPROCESS
        ),
        render_config=RenderConfig(
            dbt_executable_path=DBT_EXECUTABLE, invocation_mode=InvocationMode.SUBPROCESS
        ),
        operator_args={
            # dbt runs as a subprocess; without this it would not inherit the container's
            # SNOWFLAKE_* variables that profiles.yml reads via env_var().
            "append_env": True,
            "install_deps": False,  # no dbt packages in this project
            **DBT,
        },
    )

    @task
    def record_cost(run_id=None) -> dict:
        """Log what this run cost in warehouse time. Informational: never fails the DAG."""
        import pipeline_cost

        try:
            result = pipeline_cost.warehouse_cost(minutes=120)
        except Exception as exc:  # cost reporting must never mask a successful transform
            print(f"cost report unavailable: {exc!r}")
            return {}
        print(f"run {run_id}: {result}")
        return result

    @task(
        outlets=[SERVING_SNAPSHOT],
        retries=1,
        retry_delay=timedelta(minutes=2),
        execution_timeout=timedelta(minutes=30),
    )
    def publish_snapshot() -> dict:
        """Export the freshly built marts for the API and upload them to S3 artifacts/."""
        import publish_snapshot as snapshot_step

        return snapshot_step.run(upload=True)

    preflight() >> dbt >> [record_cost(), publish_snapshot()]


transform()
