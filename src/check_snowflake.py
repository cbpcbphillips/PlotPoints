"""Connection check for Snowflake.

Read-only: reports what exists rather than creating it, so it can be run freely
without provisioning side effects. `just smoke-test` is the one that creates the RAW
landing objects -- this one tells you whether they're there, what's in them, and
whether the S3 storage integration still works.

Run via `just test-snowflake`.
"""

import argparse
import os

from dotenv import load_dotenv

from check_common import CheckWarning, run_checks
from connection._env import require_env
from connection.snowflake import STAGE_NAME, get_snowflake_connection

load_dotenv()

RAW_TABLES = ("DIARY_ENTRIES", "TMDB_TITLES")
FILE_FORMAT = "JSON_NDJSON"
DBT_SCHEMAS = ("STAGING", "INTERMEDIATE", "MART")


def _scalar(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()


def _rows(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def check_context(conn):
    def probe():
        role, warehouse, database, schema = _scalar(
            conn,
            "select current_role(), current_warehouse(), current_database(), current_schema()",
        )
        if not warehouse:
            raise RuntimeError(
                "no active warehouse -- SNOWFLAKE_WAREHOUSE may be wrong or the role "
                "lacks USAGE on it (docs/external_setup.md step 3)."
            )
        return f"role={role} wh={warehouse} db={database} schema={schema}"

    return probe


def check_warehouse(conn):
    """Confirms the warehouse actually resumes and runs a query."""

    def probe():
        (version,) = _scalar(conn, "select current_version()")
        return f"query OK, Snowflake {version}"

    return probe


def check_raw_table(conn, database, table):
    def probe():
        if not _rows(conn, f"show tables like '{table}' in schema {database}.RAW"):
            raise RuntimeError(
                f"{database}.RAW.{table} does not exist -- run `just smoke-test` to create it."
            )
        count, last_loaded = _scalar(
            conn, f"select count(*), max(loaded_at) from {database}.RAW.{table}"
        )
        if count == 0:
            raise CheckWarning("exists but empty -- nothing loaded yet")
        return f"{count} row(s), last load {last_loaded:%Y-%m-%d %H:%M}"

    return probe


def check_file_format(conn, database):
    def probe():
        if not _rows(conn, f"show file formats like '{FILE_FORMAT}' in schema {database}.RAW"):
            raise RuntimeError(
                f"{database}.RAW.{FILE_FORMAT} does not exist -- run `just smoke-test`."
            )
        return f"{database}.RAW.{FILE_FORMAT} present"

    return probe


def check_stage(conn, database, schema):
    def probe():
        if not _rows(conn, f"show stages like '{STAGE_NAME}' in schema {database}.{schema}"):
            raise RuntimeError(
                f"{database}.{schema}.{STAGE_NAME} does not exist -- run `just smoke-test`. "
                f"Note the stage lives in {schema}, not RAW."
            )
        return f"{database}.{schema}.{STAGE_NAME} present"

    return probe


def check_stage_list(conn, database, schema):
    """The actual S3 <-> Snowflake link: LIST goes through the storage integration."""

    def probe():
        qualified = f"{database}.{schema}.{STAGE_NAME}"
        try:
            rows = _rows(conn, f"list @{qualified}")
        except Exception as exc:
            integration = os.environ.get("SNOWFLAKE_STORAGE_INTEGRATION", "<unset>")
            raise RuntimeError(
                f"LIST failed: {exc}. If this mentions Access Denied / AssumeRole, run "
                f"DESC STORAGE INTEGRATION {integration} and confirm "
                f"STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID still match the "
                f"AWS IAM role trust policy (docs/external_setup.md steps 7-8)."
            ) from exc
        total_mb = sum(row[1] for row in rows) / 1024 / 1024 if rows else 0
        return f"{len(rows)} staged file(s), {total_mb:.1f} MB"

    return probe


def check_storage_integration(conn):
    def probe():
        integration = require_env("SNOWFLAKE_STORAGE_INTEGRATION")
        try:
            rows = _rows(conn, f"desc storage integration {integration}")
        except Exception as exc:
            raise CheckWarning(
                f"cannot DESC {integration} ({type(exc).__name__}) -- needs ACCOUNTADMIN "
                f"or ownership; the stage LIST above already proves it works"
            ) from exc
        props = {row[0]: row[2] for row in rows}
        return f"{integration} ENABLED={props.get('ENABLED', '?')}"

    return probe


def check_dbt_schemas(conn, database):
    def probe():
        summary = []
        empty = []
        for schema in DBT_SCHEMAS:
            count = len(_rows(conn, f"show tables in schema {database}.{schema}")) + len(
                _rows(conn, f"show views in schema {database}.{schema}")
            )
            summary.append(f"{schema}={count}")
            if count == 0:
                empty.append(schema)
        if empty:
            raise CheckWarning(
                f"{', '.join(summary)} -- {', '.join(empty)} empty; run `just dbt build`"
            )
        return ", ".join(summary) + " object(s)"

    return probe


def check_cortex(conn, role):
    """Phase 4 gate -- embeddings need the CORTEX_USER database role."""

    def probe():
        rows = _rows(conn, f"show grants to role {role}")
        if not any("CORTEX_USER" in str(value) for row in rows for value in row):
            raise CheckWarning(
                f"SNOWFLAKE.CORTEX_USER not granted to {role} -- needed for Phase 4 "
                f"embeddings (GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE {role})"
            )
        return f"SNOWFLAKE.CORTEX_USER granted to {role}"

    return probe


def main():
    parser = argparse.ArgumentParser(description="Check the Snowflake connection.")
    parser.add_argument("--verbose", action="store_true", help="print tracebacks on failure")
    args = parser.parse_args()

    database = os.environ.get("SNOWFLAKE_DATABASE", "")
    schema = os.environ.get("SNOWFLAKE_SCHEMA") or "PUBLIC"
    role = os.environ.get("SNOWFLAKE_ROLE", "")
    user = os.environ.get("SNOWFLAKE_USER", "")

    # Auth is a precondition, not a probe: without a connection every later check
    # would fail for the same reason and bury the real error.
    try:
        conn = get_snowflake_connection()
    except Exception as exc:
        print("== Snowflake ==")
        print(f"FAIL  {'key-pair auth':<26} {type(exc).__name__}: {exc}")
        print("\n0 passed, 1 FAILED")
        raise SystemExit(1) from exc

    checks = [
        ("key-pair auth", lambda: f"connected as {user}"),
        ("session context", check_context(conn)),
        ("warehouse", check_warehouse(conn)),
        *[(f"RAW.{table}", check_raw_table(conn, database, table)) for table in RAW_TABLES],
        ("RAW file format", check_file_format(conn, database)),
        ("external stage", check_stage(conn, database, schema)),
        ("stage LIST (via S3)", check_stage_list(conn, database, schema)),
        ("storage integration", check_storage_integration(conn)),
        ("dbt output schemas", check_dbt_schemas(conn, database)),
        ("cortex access", check_cortex(conn, role)),
    ]

    try:
        exit_code = run_checks("Snowflake", checks, verbose=args.verbose)
    finally:
        conn.close()

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
