"""Enrich the Phase 1 diary checkpoint with TMDB movie metadata."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TMDB_API_KEY = os.environ["TMDB_API_KEY"]
TMDB_BASE_URL = "https://api.themoviedb.org/3"

INPUT_PATH = Path("data/checkpoints/diary_raw.json")
OUTPUT_PATH = Path("data/checkpoints/diary_enriched.json")

REQUEST_DELAY = 0.3  # ~40 req / 10s allowed; stay comfortably under that

session = requests.Session()


def tmdb_get(path, params=None):
    params = {**(params or {}), "api_key": TMDB_API_KEY}
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


def search_movie(film_title, film_year):
    data = tmdb_get("/search/movie", {"query": film_title})
    results = data.get("results") or []

    if not results:
        return None

    for result in results:
        release_date = result.get("release_date") or ""
        if release_date[:4] == str(film_year):
            return result

    return results[0]


def fetch_details(tmdb_id):
    return tmdb_get(f"/movie/{tmdb_id}", {"append_to_response": "credits"})


def extract_enrichment(details, tmdb_id):
    crew = details.get("credits", {}).get("crew", [])
    cast = details.get("credits", {}).get("cast", [])

    director = next((member["name"] for member in crew if member.get("job") == "Director"), None)

    return {
        "matched": True,
        "tmdb_id": tmdb_id,
        "director": director,
        "cast": [member["name"] for member in cast[:5]],
        "genres": [genre["name"] for genre in details.get("genres", [])],
        "runtime": details.get("runtime"),
        "overview": details.get("overview"),
        "tmdb_rating": details.get("vote_average"),
    }


def null_enrichment(tmdb_id=None):
    return {
        "matched": False,
        "tmdb_id": tmdb_id,
        "director": None,
        "cast": None,
        "genres": None,
        "runtime": None,
        "overview": None,
        "tmdb_rating": None,
    }


def enrich_entry(entry):
    film_title = entry.get("film_title")
    film_year = entry.get("film_year")
    tmdb_id = entry.get("tmdb_id")

    try:
        if not tmdb_id:
            match = search_movie(film_title, film_year)
            if match is None:
                print(f"UNMATCHED (no search results): '{film_title}' ({film_year})")
                return {**entry, **null_enrichment()}
            tmdb_id = match["id"]

        details = fetch_details(tmdb_id)
        return {**entry, **extract_enrichment(details, tmdb_id)}

    except Exception as exc:
        print(f"UNMATCHED (TMDB call failed): '{film_title}' ({film_year}) - {exc}")
        return {**entry, **null_enrichment(tmdb_id)}


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Phase 1 checkpoint not found at {INPUT_PATH}. Run src/fetch_diary.py first."
        )

    checkpoint = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    entries = checkpoint["entries"]

    enriched_entries = [enrich_entry(entry) for entry in entries]

    unmatched_entries = [entry for entry in enriched_entries if not entry["matched"]]
    match_summary = {
        "matched": len(enriched_entries) - len(unmatched_entries),
        "unmatched": len(unmatched_entries),
        "total": len(enriched_entries),
    }

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

    if unmatched_entries:
        print("\nUnmatched entries:")
        for entry in unmatched_entries:
            print(f"  - {entry.get('film_title')} ({entry.get('film_year')})")


if __name__ == "__main__":
    main()
