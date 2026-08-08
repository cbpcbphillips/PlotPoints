"""Load an enriched checkpoint into its RAW landing table (extract-load).

Serializes the checkpoint's entries to compact NDJSON, uploads them to the S3
external stage in timestamped chunks, then runs the matching COPY primitive so
the data lands in RAW.* (docs/roadmap.md Phase 2).

Append-only + idempotent by design: each run uses a fresh timestamped stage
prefix, so COPY (which skips already-loaded filenames) always loads the new
files. Re-loading the same checkpoint appends duplicates, which dbt staging
deduplicates on the natural key by most-recent loaded_at. This parameter-driven,
single-responsibility shape is what the Phase-6 Airflow task will call.

Usage:
    uv run src/load_snowflake.py catalog [--chunk-size N]
    uv run src/load_snowflake.py diary   [--chunk-size N]
"""

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from connection._env import require_env
from connection.s3 import get_s3_client
from connection.snowflake import get_snowflake_connection
from raw_schema import (
    copy_diary_entries,
    copy_tmdb_titles,
    ensure_diary_entries_table,
    ensure_json_file_format,
    ensure_tmdb_titles_table,
)

load_dotenv()

DEFAULT_CHUNK_SIZE = 5000

# One code path for both sources; each maps a checkpoint to its landing objects.
SOURCES = {
    "diary": {
        "input": Path("data/checkpoints/diary_enriched.json"),
        "ensure": ensure_diary_entries_table,
        "copy": copy_diary_entries,
        "prefix": "diary",
    },
    "catalog": {
        "input": Path("data/checkpoints/catalog_enriched.json"),
        "ensure": ensure_tmdb_titles_table,
        "copy": copy_tmdb_titles,
        "prefix": "catalog",
    },
}


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _to_ndjson(entries):
    """Compact, one JSON object per line (VARIANT-friendly, unicode preserved)."""
    return "\n".join(json.dumps(e, separators=(",", ":"), ensure_ascii=False) for e in entries)


def load(source: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> int:
    cfg = SOURCES[source]
    if not cfg["input"].exists():
        raise FileNotFoundError(
            f"Enriched checkpoint not found at {cfg['input']}. "
            f"Run the {source} fetch + enrich first."
        )

    entries = json.loads(cfg["input"].read_text(encoding="utf-8"))["entries"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage_prefix = f"{cfg['prefix']}/{run_id}/"

    bucket = require_env("AWS_S3_BUCKET")
    s3 = get_s3_client()

    uploaded = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, chunk in enumerate(_chunks(entries, chunk_size)):
            local = Path(tmp) / f"{i:04d}.jsonl"
            local.write_text(_to_ndjson(chunk), encoding="utf-8")
            key = f"{stage_prefix}{i:04d}.jsonl"
            s3.upload_file(str(local), bucket, key)
            print(f"  uploaded s3://{bucket}/{key} ({len(chunk)} entries)")
            uploaded += 1

    print(f"Uploaded {uploaded} file(s) under s3://{bucket}/{stage_prefix}")

    with get_snowflake_connection() as conn:
        ensure_json_file_format(conn)
        table = cfg["ensure"](conn)
        rows = cfg["copy"](conn, stage_prefix)

    print(f"COPY into {table}: {rows} row(s) loaded")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Load an enriched checkpoint into its RAW table.")
    parser.add_argument("source", choices=sorted(SOURCES), help="which checkpoint to load")
    parser.add_argument(
        "--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="entries per NDJSON file"
    )
    args = parser.parse_args()

    load(args.source, args.chunk_size)


if __name__ == "__main__":
    main()
