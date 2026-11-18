"""Shared Airflow wiring for the PlotPoints DAGs.

Everything Airflow-specific lives here and in dags/. src/ never imports Airflow, so every
pipeline step stays runnable on its own through `just`; DAGs only call into it.
"""

import logging
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from airflow.sdk import Asset

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
DBT_PROJECT_DIR = ROOT / "plotpoints_dbt"
# dbt runs from its own venv (see Dockerfile): it can't share an environment with Airflow.
DBT_EXECUTABLE = "/usr/local/airflow/dbt_venv/bin/dbt"

# Assets are the contract between ingest and transform. An ingest task that lands rows
# declares one as an outlet; `transform` is scheduled on them, so it runs when data actually
# changed rather than on a clock, and ingests never need to know transform exists.
RAW_TMDB_TITLES = Asset(name="raw_tmdb_titles", uri="snowflake://PLOTPOINTS_DB/RAW/TMDB_TITLES")
RAW_USER_IMPORTS = Asset(name="raw_user_imports", uri="snowflake://PLOTPOINTS_DB/RAW/USER_IMPORTS")
SERVING_SNAPSHOT = Asset(name="serving_snapshot", uri="plotpoints://serving/snapshot")
RAW_DIARY_ENTRIES = Asset(
    name="raw_diary_entries", uri="snowflake://PLOTPOINTS_DB/RAW/DIARY_ENTRIES"
)

# Retry policy per task class. Transient failures (network, API, warehouse resume) retry with
# exponential backoff; every task still has an execution_timeout, because an infinite hang is
# strictly worse than a failure you can see.
PREFLIGHT = dict(
    retries=1, retry_delay=timedelta(minutes=1), execution_timeout=timedelta(minutes=5)
)
FETCH = dict(
    retries=3,
    retry_delay=timedelta(minutes=5),
    retry_exponential_backoff=True,
    max_retry_delay=timedelta(hours=1),
    execution_timeout=timedelta(hours=2),
)
# Enrich is the long one (~2.5h at 24k titles) but is resumable, so a retry continues from the
# last fsynced title instead of repeating hours of TMDB calls.
ENRICH = dict(
    retries=2,
    retry_delay=timedelta(minutes=10),
    retry_exponential_backoff=True,
    max_retry_delay=timedelta(hours=1),
    execution_timeout=timedelta(hours=8),
)
LOAD = dict(
    retries=2,
    retry_delay=timedelta(minutes=2),
    retry_exponential_backoff=True,
    max_retry_delay=timedelta(minutes=30),
    execution_timeout=timedelta(hours=2),
)
DBT = dict(retries=1, retry_delay=timedelta(minutes=1), execution_timeout=timedelta(hours=1))


def notify_failure(context: dict) -> None:
    """Task failure hook. Today it logs a single greppable line.

    The *pattern* is the point: every task routes failures through one function, so adding a
    Slack or email destination later is an edit here rather than in every DAG.
    """
    ti = context.get("task_instance") or context.get("ti")
    log.error(
        "PIPELINE FAILURE dag=%s task=%s run=%s try=%s exception=%r",
        getattr(ti, "dag_id", "?"),
        getattr(ti, "task_id", "?"),
        context.get("run_id"),
        getattr(ti, "try_number", "?"),
        context.get("exception"),
    )


def stage_run_id(run_id: str) -> str:
    """S3-safe prefix scope derived from the Airflow run id.

    Passed to load_snowflake.load(run_id=...). It is stable across retries of the same DAG
    run, so a retried load targets the same S3 prefix and COPY (which skips files it has
    already loaded) becomes a no-op instead of appending a duplicate copy of every row.
    A *new* run gets a new prefix and appends; dbt staging dedupes on the natural key.
    """
    return re.sub(r"[^A-Za-z0-9_-]", "-", run_id)


def run_preflight(*scripts: str) -> None:
    """Run connection-check scripts from src/ and fail fast if any of them fails.

    These are the same read-only checks behind `just test-*`. Making them each DAG's first
    task means a bad TMDB key or an expired Snowflake trial fails in seconds, not two and a
    half hours into an enrich.
    """
    failed = []
    for script in scripts:
        print(f"--- {script} ---", flush=True)
        result = subprocess.run(
            [sys.executable, str(SRC_DIR / script)], capture_output=True, text=True, check=False
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode != 0:
            failed.append(script)

    if failed:
        raise RuntimeError(f"Preflight failed: {', '.join(failed)}")
