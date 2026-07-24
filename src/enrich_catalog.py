"""Enrich the TMDB catalog checkpoint with a lean, English-only TMDB payload.

Mirrors enrich_tmdb.main but reads the discovery catalog (catalog_raw.json) and uses
the lean append profile (APPEND_BY_TYPE_LEAN) — see docs/roadmap.md Phase 1. Diary
enrichment (src/enrich_tmdb.py) keeps the full payload.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from enrich_tmdb import APPEND_BY_TYPE_LEAN, enrich_entries

INPUT_PATH = Path("data/checkpoints/catalog_raw.json")
OUTPUT_PATH = Path("data/checkpoints/catalog_enriched.json")


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Catalog checkpoint not found at {INPUT_PATH}. Run src/fetch_catalog.py first."
        )

    checkpoint = json.loads(INPUT_PATH.read_text(encoding="utf-8"))

    enriched_entries, match_summary = enrich_entries(
        checkpoint["entries"], append_by_type=APPEND_BY_TYPE_LEAN
    )

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": checkpoint.get("source"),
        "count": len(enriched_entries),
        "entries": enriched_entries,
        "match_summary": match_summary,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nWrote {len(enriched_entries)} enriched catalog titles to {OUTPUT_PATH}")
    print(json.dumps(match_summary, indent=2))


if __name__ == "__main__":
    main()
