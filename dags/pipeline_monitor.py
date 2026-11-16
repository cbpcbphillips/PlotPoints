"""Pipeline monitor: freshness, data-quality warnings and recent warehouse cost.

Kept out of `transform` deliberately. Freshness is only meaningful on a clock -- "has anyone
loaded anything lately?" -- not as a step after a load, when it is fresh by definition. And
a stale source should raise an alert here, not mark a perfectly good dbt build as failed.

Manual for now (schedule=None); this is the DAG to put on a daily schedule first, since
a manually-triggered pipeline's characteristic failure is that nobody triggered it.
The three checks are independent, so one failing never hides the others.
"""

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task

from include.plotpoints_airflow import DBT_EXECUTABLE, DBT_PROJECT_DIR, notify_failure

# dbt would otherwise write target/ and logs/ into the project directory baked into the image.
DBT = (
    f"{DBT_EXECUTABLE} {{cmd}} --project-dir {DBT_PROJECT_DIR} "
    f"--profiles-dir {DBT_PROJECT_DIR} --target-path /tmp/dbt_target --log-path /tmp/dbt_logs"
)


@dag(
    dag_id="pipeline_monitor",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"on_failure_callback": notify_failure},
    tags=["monitoring"],
    doc_md=__doc__,
)
def pipeline_monitor():
    # Exits non-zero only past error_after (90 days); between warn_after (30) and that it
    # logs a WARN and passes. Thresholds live in models/staging/_sources.yml.
    BashOperator(
        task_id="source_freshness",
        bash_command=DBT.format(cmd="source freshness"),
    )

    # Both tests are severity=warn: they surface a low match rate or an embedding gap in the
    # log without failing the task.
    BashOperator(
        task_id="data_quality_warnings",
        bash_command=DBT.format(
            cmd="test --select assert_embedding_coverage_complete assert_batch_match_rate_healthy"
        ),
    )

    @task
    def warehouse_cost() -> dict:
        import pipeline_cost

        result = pipeline_cost.warehouse_cost(minutes=24 * 60)
        print(result)
        return result

    warehouse_cost()


pipeline_monitor()
