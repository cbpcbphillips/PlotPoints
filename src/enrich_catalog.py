"""Enrich the TMDB catalog checkpoint with a lean, English-only TMDB payload.

Writes NDJSON incrementally (one enriched title per line) and resumes from whatever is
already on disk. At catalog scale neither is optional: 80k lean payloads is ~15 GB, which
does not want to sit in memory, and a run that takes ~15 hours at the TMDB rate limit
will eventually be interrupted. Losing 12 hours of API calls to a laptop sleeping is not
an acceptable failure mode.

Diary enrichment (src/enrich_tmdb.py) keeps the single-document form — ~50 entries never
needs any of this.

Usage:
    uv run src/enrich_catalog.py              # enrich, resuming if progress exists
    uv run src/enrich_catalog.py --restart    # discard progress and start over
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from enrich_tmdb import APPEND_BY_TYPE_LEAN, enrich_entries_iter
from paths import CHECKPOINT_DIR

INPUT_PATH = CHECKPOINT_DIR / "catalog_raw.json"
OUTPUT_PATH = CHECKPOINT_DIR / "catalog_enriched.jsonl"
SUMMARY_PATH = CHECKPOINT_DIR / "catalog_enriched.summary.json"

# Entries between fsyncs. Bounds how much is lost to a hard kill without paying for a
# sync on every one of 80k writes.
FLUSH_EVERY = 25
PROGRESS_EVERY = 100


def completed_tmdb_ids(path: Path) -> set:
    """tmdb_ids already written, so a resumed run can skip them.

    Tolerates a truncated final line: a process killed mid-write leaves a partial JSON
    object, which we drop rather than crash on.
    """
    if not path.exists():
        return set()

    done = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["tmdb_id"])
            except (json.JSONDecodeError, KeyError):
                continue  # truncated tail from an interrupted run
    return done


def _format_eta(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


def main():
    parser = argparse.ArgumentParser(
        description="Enrich the catalog checkpoint with a lean TMDB payload (resumable)."
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="discard existing progress and re-enrich every title from scratch",
    )
    args = parser.parse_args()
    run(restart=args.restart)


def run(restart: bool = False) -> dict:
    """Enrich the catalog checkpoint, resuming unless `restart`. Returns a summary dict.

    The entry point an orchestrator calls. Because progress is read back from the output
    file, an Airflow retry of this task resumes where the failed attempt stopped instead
    of starting over -- the whole reason the output is append-only NDJSON.
    """
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Catalog checkpoint not found at {INPUT_PATH}. Run src/fetch_catalog.py first."
        )

    checkpoint = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    entries = checkpoint["entries"]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if restart and OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()
        print(f"--restart: discarded {OUTPUT_PATH}")

    done = completed_tmdb_ids(OUTPUT_PATH)
    pending = [e for e in entries if e.get("tmdb_id") not in done]

    if done:
        print(f"Resuming: {len(done)} already enriched, {len(pending)} remaining")
    if not pending:
        print(f"Nothing to do — all {len(done)} titles already enriched in {OUTPUT_PATH}")
        return {"count": len(done), "match_summary": {"skipped_already_done": len(done)}}

    matched = unmatched = 0
    started = time.monotonic()

    # append, not write: resume must not truncate prior progress
    with OUTPUT_PATH.open("a", encoding="utf-8") as fh:
        stream = enrich_entries_iter(pending, append_by_type=APPEND_BY_TYPE_LEAN)
        for i, enriched in enumerate(stream, start=1):
            fh.write(json.dumps(enriched, separators=(",", ":"), ensure_ascii=False) + "\n")

            if enriched.get("matched"):
                matched += 1
            else:
                unmatched += 1

            if i % FLUSH_EVERY == 0:
                fh.flush()
                os.fsync(fh.fileno())

            if i % PROGRESS_EVERY == 0:
                elapsed = time.monotonic() - started
                rate = i / elapsed
                remaining = (len(pending) - i) / rate if rate else 0
                print(
                    f"  {i}/{len(pending)}  {rate:.2f} titles/s  "
                    f"elapsed {_format_eta(elapsed)}  eta {_format_eta(remaining)}",
                    flush=True,
                )

        fh.flush()
        os.fsync(fh.fileno())

    elapsed = time.monotonic() - started
    total_done = len(done) + matched + unmatched
    size_bytes = OUTPUT_PATH.stat().st_size

    summary = {
        "enriched_at": datetime.now(timezone.utc).isoformat(),
        "source": checkpoint.get("source"),
        "count": total_done,
        "match_summary": {
            "matched": matched,
            "unmatched": unmatched,
            "total": matched + unmatched,
            "skipped_already_done": len(done),
        },
        "elapsed_seconds": round(elapsed, 1),
        "titles_per_second": round((matched + unmatched) / elapsed, 3) if elapsed else None,
        "output_bytes": size_bytes,
        "bytes_per_title": round(size_bytes / total_done) if total_done else None,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nWrote {total_done} enriched titles to {OUTPUT_PATH}")
    print(f"  {size_bytes / 1024 / 1024:.1f} MB ({summary['bytes_per_title']} bytes/title)")
    print(f"  {_format_eta(elapsed)} elapsed, {summary['titles_per_second']} titles/s")
    print(json.dumps(summary["match_summary"], indent=2))
    return summary


if __name__ == "__main__":
    main()
