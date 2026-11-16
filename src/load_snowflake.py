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
from paths import CHECKPOINT_DIR
from raw_schema import (
    copy_diary_entries,
    copy_tmdb_titles,
    ensure_diary_entries_table,
    ensure_json_file_format,
    ensure_tmdb_titles_table,
)

load_dotenv()

# Snowflake COPY parallelises best on roughly 100-250 MB files, and payload size varies
# ~2x between the lean catalog profile and the full diary profile — so chunk by bytes
# rather than row count, which would otherwise give 90 MB catalog files and 2 KB diary ones.
DEFAULT_CHUNK_BYTES = 128 * 1024 * 1024
MAX_CHUNK_ENTRIES = 50_000  # secondary bound so tiny payloads still produce several files

# One code path for both sources; each maps a checkpoint to its landing objects.
# `input` may be NDJSON (.jsonl, catalog — streamed) or a single JSON document
# (.json, diary). See _iter_entries.
SOURCES = {
    "diary": {
        "input": CHECKPOINT_DIR / "diary_enriched.json",
        "ensure": ensure_diary_entries_table,
        "copy": copy_diary_entries,
        "prefix": "diary",
    },
    "catalog": {
        "input": CHECKPOINT_DIR / "catalog_enriched.jsonl",
        "ensure": ensure_tmdb_titles_table,
        "copy": copy_tmdb_titles,
        "prefix": "catalog",
    },
}


def _iter_entries(path: Path):
    """Yield entries from an NDJSON checkpoint or a single JSON document.

    NDJSON is read a line at a time, so a catalog-scale file never loads whole — the
    whole point of enrich_catalog writing .jsonl. The .json branch is the ~50-entry
    diary, where holding it in memory costs nothing.
    """
    if path.suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
    else:
        yield from json.loads(path.read_text(encoding="utf-8"))["entries"]


def _write_chunks(entries, tmp_dir: Path, chunk_bytes: int):
    """Write entries into NDJSON files capped at ~chunk_bytes, yielding (path, count).

    Rolls over on accumulated bytes so memory stays bounded to one chunk regardless of
    how many titles the checkpoint holds.
    """
    index = 0
    handle = None
    written = count = 0

    def _open(i):
        path = tmp_dir / f"{i:04d}.jsonl"
        return path, path.open("w", encoding="utf-8")

    path, handle = _open(index)
    try:
        for entry in entries:
            line = json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n"
            handle.write(line)
            written += len(line.encode("utf-8"))
            count += 1

            if written >= chunk_bytes or count >= MAX_CHUNK_ENTRIES:
                handle.close()
                yield path, count
                index += 1
                path, handle = _open(index)
                written = count = 0
    finally:
        if not handle.closed:
            handle.close()

    if count:
        yield path, count


def load(source: str, run_id: str | None = None, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> int:
    """Stage an enriched checkpoint to S3 and COPY it into its RAW table.

    run_id scopes the S3 prefix. It defaults to wall-clock so the CLI stays convenient,
    but an orchestrator should pass its own logical date: a retry then targets the *same*
    prefix, and because COPY skips filenames it has already loaded, the retry becomes a
    no-op instead of appending a second copy of the same rows. Keying on wall-clock time
    makes every retry a duplicate load.
    """
    cfg = SOURCES[source]
    if not cfg["input"].exists():
        raise FileNotFoundError(
            f"Enriched checkpoint not found at {cfg['input']}. "
            f"Run the {source} fetch + enrich first."
        )

    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage_prefix = f"{cfg['prefix']}/{run_id}/"

    bucket = require_env("AWS_S3_BUCKET")
    s3 = get_s3_client()

    uploaded = entry_total = byte_total = 0
    with tempfile.TemporaryDirectory() as tmp:
        entries = _iter_entries(cfg["input"])
        for local, count in _write_chunks(entries, Path(tmp), chunk_bytes):
            key = f"{stage_prefix}{local.name}"
            size = local.stat().st_size
            s3.upload_file(str(local), bucket, key)
            print(f"  uploaded s3://{bucket}/{key} ({count} entries, {size / 1024 / 1024:.1f} MB)")
            local.unlink()  # keep peak disk to one chunk, not the whole checkpoint
            uploaded += 1
            entry_total += count
            byte_total += size

    print(
        f"Uploaded {uploaded} file(s), {entry_total} entries, "
        f"{byte_total / 1024 / 1024:.1f} MB under s3://{bucket}/{stage_prefix}"
    )

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
        "--run-id",
        default=None,
        help="stage prefix scope; defaults to wall-clock. Pass a stable id (e.g. an "
        "orchestrator's logical date) to make a retry idempotent instead of duplicating.",
    )
    parser.add_argument(
        "--chunk-bytes",
        type=int,
        default=DEFAULT_CHUNK_BYTES,
        help="approximate bytes per staged NDJSON file",
    )
    args = parser.parse_args()

    load(args.source, args.run_id, args.chunk_bytes)


if __name__ == "__main__":
    main()
