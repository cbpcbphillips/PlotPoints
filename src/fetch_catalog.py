"""Fetch a broad TMDB movie catalog by discovery — the user-independent candidate
pool that feeds enrichment and, later, embeddings (docs/roadmap.md Phase 1).

Selection: most-rated movies via /discover/movie sorted by vote_count.desc with a
vote-count floor. A single /discover query caps at 500 pages (10k results), so we
slide release-year windows to accumulate up to the target count. Walking from the
current year backward biases toward more recent titles — fine for a candidate pool.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from connection._env import require_env
from enrich_tmdb import tmdb_get

load_dotenv()

CHECKPOINT_PATH = Path("data/checkpoints/catalog_raw.json")

DEFAULT_TARGET = 50_000
DEFAULT_MIN_VOTES = 200
EARLIEST_YEAR = 1900  # walk back no further than this
MAX_PAGES = 500  # TMDB hard cap per /discover query


def discover_year(session, api_key, year, min_votes):
    """All /discover/movie results for one release year, most-rated first."""
    results = []
    page = 1
    while page <= MAX_PAGES:
        data = tmdb_get(
            session,
            api_key,
            "/discover/movie",
            {
                "sort_by": "vote_count.desc",
                "vote_count.gte": min_votes,
                "primary_release_year": year,
                "page": page,
            },
        )
        page_results = data.get("results") or []
        results.extend(page_results)
        if page >= min(data.get("total_pages") or 1, MAX_PAGES) or not page_results:
            break
        page += 1
    return results


def fetch_catalog(target, min_votes, limit=None):
    """Deduped list of catalog entries ({tmdb_id, tmdb_media_type, ...}), most-recent
    years first, stopping at `limit` (test runs) or `target`."""
    api_key = require_env("TMDB_API_KEY")
    session = requests.Session()
    stop = limit if limit is not None else target

    seen = set()
    entries = []
    for year in range(datetime.now(timezone.utc).year, EARLIEST_YEAR - 1, -1):
        for movie in discover_year(session, api_key, year, min_votes):
            movie_id = movie.get("id")
            if movie_id in seen:
                continue
            seen.add(movie_id)
            entries.append(
                {
                    "tmdb_id": movie_id,
                    "tmdb_media_type": "movie",
                    "title": movie.get("title"),
                    "popularity": movie.get("popularity"),
                    "vote_count": movie.get("vote_count"),
                }
            )
            if len(entries) >= stop:
                return entries
    return entries


def main():
    parser = argparse.ArgumentParser(description="Fetch a broad TMDB movie catalog by discovery.")
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET, help="target title count")
    parser.add_argument("--min-votes", type=int, default=DEFAULT_MIN_VOTES, help="vote_count floor")
    parser.add_argument("--limit", type=int, default=None, help="stop after N titles (test runs)")
    args = parser.parse_args()

    entries = fetch_catalog(args.target, args.min_votes, args.limit)

    checkpoint = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "tmdb:/discover/movie?sort_by=vote_count.desc",
        "min_votes": args.min_votes,
        "count": len(entries),
        "entries": entries,
    }

    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(
        json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Wrote {len(entries)} catalog entries to {CHECKPOINT_PATH}")
    if entries:
        print("Sample:", json.dumps(entries[0], ensure_ascii=False))


if __name__ == "__main__":
    main()
