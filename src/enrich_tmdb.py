"""Enrich the Phase 1 diary checkpoint with TMDB movie metadata."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from connection._env import require_env

load_dotenv()

TMDB_BASE_URL = "https://api.themoviedb.org/3"

INPUT_PATH = Path("data/checkpoints/diary_raw.json")
OUTPUT_PATH = Path("data/checkpoints/diary_enriched.json")

REQUEST_DELAY = 0.3  # ~40 req / 10s allowed; stay comfortably under that


def tmdb_get(session, api_key, path, params=None):
    params = {**(params or {}), "api_key": api_key}
    url = f"{TMDB_BASE_URL}{path}"

    for _attempt in range(5):
        response = session.get(url, params=params, timeout=10)

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 1))
            time.sleep(retry_after)
            continue

        response.raise_for_status()
        time.sleep(REQUEST_DELAY)
        return response.json()

    raise RuntimeError(f"Gave up on {url} after repeated 429 responses")


def search_movie(session, api_key, film_title, film_year):
    data = tmdb_get(session, api_key, "/search/movie", {"query": film_title})
    results = data.get("results") or []

    if not results:
        return None

    for result in results:
        release_date = result.get("release_date") or ""
        if release_date[:4] == str(film_year):
            return result

    return results[0]


# job titles that count as a "writer" for the writers field
WRITER_JOBS = {"Writer", "Screenplay"}

# bump when the enrichment field set changes, so a later backfill can tell which
# rows were written by which version of extract_enrichment / null_enrichment
ENRICHMENT_VERSION = 2


def fetch_details(session, api_key, tmdb_id):
    # keywords + watch/providers piggyback on the same details call — no extra requests
    return tmdb_get(
        session,
        api_key,
        f"/movie/{tmdb_id}",
        {"append_to_response": "credits,keywords,watch/providers"},
    )


def extract_enrichment(details, tmdb_id):
    crew = details.get("credits", {}).get("crew", [])
    cast = details.get("credits", {}).get("cast", [])

    director = next((member["name"] for member in crew if member.get("job") == "Director"), None)
    writers = list(
        dict.fromkeys(member["name"] for member in crew if member.get("job") in WRITER_JOBS)
    )

    collection = details.get("belongs_to_collection") or {}

    # watch/providers is region-keyed and volatile (current availability, not
    # availability-at-watch); we snapshot the US block at enrich time.
    providers_block = details.get("watch/providers") or {}
    us_providers = (providers_block.get("results") or {}).get("US") or {}
    watch_providers = {
        "flatrate": [p["provider_name"] for p in us_providers.get("flatrate", [])],
        "rent": [p["provider_name"] for p in us_providers.get("rent", [])],
        "buy": [p["provider_name"] for p in us_providers.get("buy", [])],
    }

    return {
        "matched": True,
        "tmdb_id": tmdb_id,
        "director": director,
        "writers": writers,
        "cast": [member["name"] for member in cast[:5]],
        "cast_detail": [
            {
                "name": member.get("name"),
                "character": member.get("character"),
                "order": member.get("order"),
            }
            for member in cast[:10]
        ],
        "genres": [genre["name"] for genre in details.get("genres", [])],
        "keywords": [kw["name"] for kw in details.get("keywords", {}).get("keywords", [])],
        "collection_id": collection.get("id"),
        "collection_name": collection.get("name"),
        "original_language": details.get("original_language"),
        "production_countries": [c["name"] for c in details.get("production_countries", [])],
        "runtime": details.get("runtime"),
        "release_date": details.get("release_date"),
        "overview": details.get("overview"),
        "tagline": details.get("tagline"),
        "imdb_id": details.get("imdb_id"),
        "tmdb_rating": details.get("vote_average"),
        "vote_count": details.get("vote_count"),
        "watch_providers": watch_providers,
        "watch_providers_region": "US",
        "tmdb_enrichment_version": ENRICHMENT_VERSION,
    }


def null_enrichment(tmdb_id=None):
    # must mirror extract_enrichment's key set exactly so matched and unmatched
    # entries land with an identical shape
    return {
        "matched": False,
        "tmdb_id": tmdb_id,
        "director": None,
        "writers": None,
        "cast": None,
        "cast_detail": None,
        "genres": None,
        "keywords": None,
        "collection_id": None,
        "collection_name": None,
        "original_language": None,
        "production_countries": None,
        "runtime": None,
        "release_date": None,
        "overview": None,
        "tagline": None,
        "imdb_id": None,
        "tmdb_rating": None,
        "vote_count": None,
        "watch_providers": None,
        "watch_providers_region": None,
        "tmdb_enrichment_version": ENRICHMENT_VERSION,
    }


def enrich_entry(session, api_key, entry):
    film_title = entry.get("film_title")
    film_year = entry.get("film_year")
    tmdb_id = entry.get("tmdb_id")

    try:
        if not tmdb_id:
            match = search_movie(session, api_key, film_title, film_year)
            if match is None:
                print(f"UNMATCHED (no search results): '{film_title}' ({film_year})")
                return {**entry, **null_enrichment()}
            tmdb_id = match["id"]

        details = fetch_details(session, api_key, tmdb_id)
        return {**entry, **extract_enrichment(details, tmdb_id)}

    except Exception as exc:
        print(f"UNMATCHED (TMDB call failed): '{film_title}' ({film_year}) - {exc}")
        return {**entry, **null_enrichment(tmdb_id)}


def enrich_entries(entries: list[dict], api_key: str | None = None) -> tuple[list[dict], dict]:
    """Enrich diary entries with TMDB metadata. Returns (enriched_entries, match_summary)."""
    api_key = api_key or require_env("TMDB_API_KEY")
    session = requests.Session()

    enriched_entries = [enrich_entry(session, api_key, entry) for entry in entries]

    unmatched_entries = [entry for entry in enriched_entries if not entry["matched"]]
    match_summary = {
        "matched": len(enriched_entries) - len(unmatched_entries),
        "unmatched": len(unmatched_entries),
        "total": len(enriched_entries),
    }

    return enriched_entries, match_summary


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Phase 1 checkpoint not found at {INPUT_PATH}. Run src/fetch_diary.py first."
        )

    checkpoint = json.loads(INPUT_PATH.read_text(encoding="utf-8"))

    enriched_entries, match_summary = enrich_entries(checkpoint["entries"])

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": checkpoint.get("source"),
        "count": len(enriched_entries),
        "entries": enriched_entries,
        "match_summary": match_summary,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nWrote {len(enriched_entries)} entries to {OUTPUT_PATH}")
    print(json.dumps(match_summary, indent=2))

    unmatched_entries = [entry for entry in enriched_entries if not entry["matched"]]
    if unmatched_entries:
        print("\nUnmatched entries:")
        for entry in unmatched_entries:
            print(f"  - {entry.get('film_title')} ({entry.get('film_year')})")


if __name__ == "__main__":
    main()
