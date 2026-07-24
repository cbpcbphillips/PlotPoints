"""Snowflake landing-layer definitions for the raw (RAW schema) tables.

Raw-ELT pattern: each row holds a full enriched record as a VARIANT, with the
natural key promoted out to real columns plus source_file/loaded_at load metadata.
Typed flattening is dbt's job (staging models on top of these), not done here.

Two landing tables + a shared NDJSON file format:
  - ensure_diary_entries_table / copy_diary_entries -> RAW.DIARY_ENTRIES
      one row per Letterboxd watch event, key (letterboxd_username, guid)
  - ensure_tmdb_titles_table   / copy_tmdb_titles   -> RAW.TMDB_TITLES
      one row per catalog title, key (media_type, tmdb_id)
  - ensure_json_file_format -> the NDJSON file format both COPYs use
A separate loader (src/load_snowflake.py, not built yet) orchestrates uploading
NDJSON to S3 and calling these.
"""

import os

import snowflake.connector

from connection._env import require_env
from connection.snowflake import STAGE_NAME, ensure_schema

SCHEMA_NAME = "RAW"
TABLE_NAME = "DIARY_ENTRIES"
TITLES_TABLE_NAME = "TMDB_TITLES"
FILE_FORMAT_NAME = "JSON_NDJSON"


def _qualified(name: str) -> str:
    """Fully-qualify an object name inside SNOWFLAKE_DATABASE.RAW."""
    return f"{require_env('SNOWFLAKE_DATABASE')}.{SCHEMA_NAME}.{name}"


def _stage_ref(stage_prefix: str) -> str:
    """External-stage reference for a path prefix. The stage is created by
    ensure_stage() in SNOWFLAKE_SCHEMA (default PUBLIC), a different schema than the
    RAW tables — resolve it the same way ensure_stage does."""
    stage_schema = os.environ.get("SNOWFLAKE_SCHEMA") or "PUBLIC"
    stage = f"{require_env('SNOWFLAKE_DATABASE')}.{stage_schema}.{STAGE_NAME}"
    return f"@{stage}/{stage_prefix.lstrip('/')}"


def _rows_loaded(results) -> int:
    """Sum rows_loaded across a COPY's per-file status rows: (file, status,
    rows_parsed, rows_loaded, ...) -> index 3."""
    return sum(row[3] for row in results if len(row) > 3 and isinstance(row[3], int))


def ensure_diary_entries_table(conn: snowflake.connector.SnowflakeConnection) -> str:
    """Idempotently create the RAW schema and DIARY_ENTRIES landing table.
    Returns the fully-qualified table name."""
    ensure_schema(conn, SCHEMA_NAME)
    qualified_name = _qualified(TABLE_NAME)

    # The PRIMARY KEY is informational only — Snowflake enforces NOT NULL but not
    # uniqueness on it. Dedup on rerun is handled downstream in dbt (see
    # copy_diary_entries). A JSON `null` inside `record` (e.g. via
    # PARSE_JSON('null')) isn't the same as SQL NULL — use IS_NULL_VALUE(record),
    # not `record IS NULL`, to check that.
    with conn.cursor() as cur:
        try:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {qualified_name} (
                    guid                 VARCHAR NOT NULL,
                    letterboxd_username  VARCHAR NOT NULL,
                    media_type           VARCHAR,
                    record               VARIANT NOT NULL,
                    source_file          VARCHAR,
                    loaded_at            TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
                    PRIMARY KEY (letterboxd_username, guid)
                )
                """
            )
        except snowflake.connector.errors.ProgrammingError as exc:
            raise RuntimeError(f"Failed to create/verify table {qualified_name}: {exc}.") from exc

    return qualified_name


def ensure_json_file_format(conn: snowflake.connector.SnowflakeConnection) -> str:
    """Idempotently create the NDJSON file format used to COPY diary entries.
    Plain TYPE=JSON loads one top-level JSON object per line as its own row, which
    is exactly the newline-delimited shape the loader writes. Returns the
    fully-qualified file-format name."""
    ensure_schema(conn, SCHEMA_NAME)
    qualified_name = _qualified(FILE_FORMAT_NAME)

    with conn.cursor() as cur:
        try:
            cur.execute(f"CREATE FILE FORMAT IF NOT EXISTS {qualified_name} TYPE = JSON")
        except snowflake.connector.errors.ProgrammingError as exc:
            raise RuntimeError(
                f"Failed to create/verify file format {qualified_name}: {exc}."
            ) from exc

    return qualified_name


def copy_diary_entries(conn: snowflake.connector.SnowflakeConnection, stage_prefix: str) -> int:
    """Append-only COPY of NDJSON diary entries from the external stage into
    DIARY_ENTRIES, promoting the natural key + source filename out of each record.

    `stage_prefix` is the path under the stage (e.g. "diary/2026-07-22/"). Assumes
    the table, file format, and stage already exist — call ensure_diary_entries_table
    and ensure_json_file_format first. Returns the number of rows loaded.

    The explicit SELECT transform is required to populate the promoted columns
    (it can't be combined with MATCH_BY_COLUMN_NAME); loaded_at fills from DEFAULT.
    COPY skips files it has already loaded, but re-uploaded files with overlapping
    guids will append duplicate rows — dbt staging deduplicates on
    (letterboxd_username, guid) by most-recent loaded_at.
    """
    table = _qualified(TABLE_NAME)
    file_format = _qualified(FILE_FORMAT_NAME)
    stage_ref = _stage_ref(stage_prefix)

    with conn.cursor() as cur:
        try:
            cur.execute(
                f"""
                COPY INTO {table} (guid, letterboxd_username, media_type, record, source_file)
                FROM (
                    SELECT $1:guid::string,
                           $1:letterboxd_username::string,
                           $1:tmdb_media_type::string,
                           $1,
                           METADATA$FILENAME
                    FROM {stage_ref}
                )
                FILE_FORMAT = (FORMAT_NAME = {file_format})
                """
            )
            results = cur.fetchall()
        except snowflake.connector.errors.ProgrammingError as exc:
            raise RuntimeError(f"Failed to COPY into {table} from {stage_ref}: {exc}.") from exc

    return _rows_loaded(results)


def ensure_tmdb_titles_table(conn: snowflake.connector.SnowflakeConnection) -> str:
    """Idempotently create the RAW schema and TMDB_TITLES catalog landing table —
    one row per (media_type, tmdb_id). Returns the fully-qualified table name."""
    ensure_schema(conn, SCHEMA_NAME)
    qualified_name = _qualified(TITLES_TABLE_NAME)

    # PRIMARY KEY is informational only (Snowflake enforces NOT NULL, not uniqueness);
    # dedup on rerun is handled downstream in dbt on (media_type, tmdb_id).
    with conn.cursor() as cur:
        try:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {qualified_name} (
                    media_type   VARCHAR NOT NULL,
                    tmdb_id      NUMBER  NOT NULL,
                    record       VARIANT NOT NULL,
                    source_file  VARCHAR,
                    loaded_at    TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
                    PRIMARY KEY (media_type, tmdb_id)
                )
                """
            )
        except snowflake.connector.errors.ProgrammingError as exc:
            raise RuntimeError(f"Failed to create/verify table {qualified_name}: {exc}.") from exc

    return qualified_name


def copy_tmdb_titles(conn: snowflake.connector.SnowflakeConnection, stage_prefix: str) -> int:
    """Append-only COPY of NDJSON catalog titles from the external stage into
    TMDB_TITLES, promoting (media_type, tmdb_id) + source filename out of each record.
    Call ensure_tmdb_titles_table + ensure_json_file_format first. Returns rows loaded.
    Duplicates from re-uploaded files are deduped downstream in dbt."""
    table = _qualified(TITLES_TABLE_NAME)
    file_format = _qualified(FILE_FORMAT_NAME)
    stage_ref = _stage_ref(stage_prefix)

    with conn.cursor() as cur:
        try:
            cur.execute(
                f"""
                COPY INTO {table} (media_type, tmdb_id, record, source_file)
                FROM (
                    SELECT $1:media_type::string,
                           $1:tmdb_id::number,
                           $1,
                           METADATA$FILENAME
                    FROM {stage_ref}
                )
                FILE_FORMAT = (FORMAT_NAME = {file_format})
                """
            )
            results = cur.fetchall()
        except snowflake.connector.errors.ProgrammingError as exc:
            raise RuntimeError(f"Failed to COPY into {table} from {stage_ref}: {exc}.") from exc

    return _rows_loaded(results)
