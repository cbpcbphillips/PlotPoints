"""Enrich the diary checkpoint with TMDB metadata (movies and TV).

Each entry is routed to the matching TMDB endpoint (/movie or /tv) based on the
tmdb_media_type stamped by fetch_diary. Every enriched entry gets:
  - `tmdb`: the full details response, with all metadata append_to_response
    sub-responses, stored verbatim (the "cover everything" raw payload).
  - a curated, movie/TV-normalized projection of the fields most useful for
    analytics (directors, cast, genres, keywords, ...).
Typed flattening of `tmdb` is dbt's job downstream, not done here.
"""

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
REQUEST_TIMEOUT = 30  # generous — the all-append details payload can be large

# job titles that count as a "writer" for the curated writers field
WRITER_JOBS = {"Writer", "Screenplay"}

# bump when the enrichment field set changes, so a later backfill can tell which
# rows were written by which version of extract_enrichment / null_enrichment
ENRICHMENT_VERSION = 3

# All metadata append_to_response sub-requests, per media type. Two are excluded:
# account_states (needs a TMDB user session, not just an API key) and changes
# (TMDB's recent edit-log — operational noise, no content/taste value). Each list
# bundles into a single details request (well under the 20-sub-request limit).
APPEND_MOVIE = (
    "credits,keywords,videos,images,external_ids,release_dates,watch/providers,"
    "recommendations,similar,reviews,translations,alternative_titles,lists"
)
APPEND_TV = (
    "aggregate_credits,credits,keywords,videos,images,external_ids,content_ratings,"
    "watch/providers,recommendations,similar,reviews,translations,alternative_titles,"
    "episode_groups,screened_theatrically"
)
APPEND_BY_TYPE = {"movie": APPEND_MOVIE, "tv": APPEND_TV}

# Lean payload for the catalog (Phase 1): English-only, drops the bulky/low-value
# append blocks (images, translations, reviews, recommendations, similar,
# alternative_titles, lists). Keeps everything the curated fields + embeddings use.
# Diary rows keep the full APPEND_BY_TYPE above.
APPEND_MOVIE_LEAN = "credits,keywords,external_ids,release_dates,watch/providers,videos"
APPEND_BY_TYPE_LEAN = {"movie": APPEND_MOVIE_LEAN}


def tmdb_get(session, api_key, path, params=None):
    params = {**(params or {}), "api_key": api_key}
    url = f"{TMDB_BASE_URL}{path}"

    for _attempt in range(5):
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 1))
            time.sleep(retry_after)
            continue

        response.raise_for_status()
        time.sleep(REQUEST_DELAY)
        return response.json()

    raise RuntimeError(f"Gave up on {url} after repeated 429 responses")


def search_title(session, api_key, media_type, film_title, film_year):
    """Search TMDB for a title. Returns (media_type, result) or (media_type, None).

    When media_type is known we hit the typed /search/{movie,tv} endpoint. When it
    is unknown (an entry with no tmdb id) we use /search/multi and infer the media
    type from the top result.
    """
    if media_type in ("movie", "tv"):
        year_param = "primary_release_year" if media_type == "movie" else "first_air_date_year"
        params = {"query": film_title}
        if film_year:
            params[year_param] = film_year
        data = tmdb_get(session, api_key, f"/search/{media_type}", params)
        results = data.get("results") or []
    else:
        data = tmdb_get(session, api_key, "/search/multi", {"query": film_title})
        results = [r for r in (data.get("results") or []) if r.get("media_type") in ("movie", "tv")]

    if not results:
        return media_type, None

    # prefer an exact release-year match when we have a year to compare against
    for result in results:
        date = result.get("release_date") or result.get("first_air_date") or ""
        if film_year and date[:4] == str(film_year):
            return result.get("media_type") or media_type, result

    top = results[0]
    return top.get("media_type") or media_type, top


def fetch_details(session, api_key, media_type, tmdb_id, append_by_type=APPEND_BY_TYPE):
    # fall back to the full append set if the given profile doesn't cover this media type
    append = append_by_type.get(media_type) or APPEND_BY_TYPE[media_type]
    return tmdb_get(session, api_key, f"/{media_type}/{tmdb_id}", {"append_to_response": append})


def _names_by_job(crew, jobs):
    """Names from a movie credits.crew list whose `job` is in `jobs` (deduped, ordered)."""
    return list(dict.fromkeys(m["name"] for m in crew if m.get("job") in jobs))


def _agg_names_by_job(crew, jobs):
    """Names from a TV aggregate_credits.crew list where any of the person's `jobs` is in `jobs`."""
    return list(
        dict.fromkeys(
            m["name"] for m in crew if any(j.get("job") in jobs for j in m.get("jobs", []))
        )
    )


def _us_movie_certification(release_dates):
    """First non-empty US certification from a movie's release_dates.results."""
    us = next((r for r in release_dates.get("results", []) if r.get("iso_3166_1") == "US"), None)
    if not us:
        return None
    return next(
        (rd["certification"] for rd in us.get("release_dates", []) if rd.get("certification")),
        None,
    )


def _us_watch_providers(details):
    us = ((details.get("watch/providers") or {}).get("results") or {}).get("US") or {}
    return {
        "flatrate": [p["provider_name"] for p in us.get("flatrate", [])],
        "rent": [p["provider_name"] for p in us.get("rent", [])],
        "buy": [p["provider_name"] for p in us.get("buy", [])],
    }


def _movie_fields(details):
    """Curated fields that read differently for movies. Returns the same key set as _tv_fields."""
    credits = details.get("credits", {})
    crew = credits.get("crew", [])
    cast = credits.get("cast", [])
    collection = details.get("belongs_to_collection") or {}
    return {
        "directors": _names_by_job(crew, {"Director"}),
        "writers": _names_by_job(crew, WRITER_JOBS),
        "cast": [m["name"] for m in cast[:10]],
        "cast_detail": [
            {"name": m.get("name"), "character": m.get("character"), "order": m.get("order")}
            for m in cast[:10]
        ],
        "keywords": [kw["name"] for kw in details.get("keywords", {}).get("keywords", [])],
        "runtime": details.get("runtime"),
        "seasons": None,
        "episodes": None,
        "networks": None,
        "collection_id": collection.get("id"),
        "collection_name": collection.get("name"),
        "countries": [c["iso_3166_1"] for c in details.get("production_countries", [])],
        "certification": _us_movie_certification(details.get("release_dates", {})),
        "imdb_id": details.get("imdb_id"),
    }


def _tv_fields(details):
    """Curated fields that read differently for TV. Returns the same key set as _movie_fields."""
    agg = details.get("aggregate_credits", {})
    crew = agg.get("crew", [])
    cast = agg.get("cast", [])
    episode_run_time = details.get("episode_run_time") or []
    ratings = details.get("content_ratings", {}).get("results", [])
    us_rating = next((r for r in ratings if r.get("iso_3166_1") == "US"), None)
    return {
        "directors": [c["name"] for c in details.get("created_by", [])],
        "writers": _agg_names_by_job(crew, WRITER_JOBS),
        "cast": [m["name"] for m in cast[:10]],
        "cast_detail": [
            {
                "name": m.get("name"),
                "character": (m.get("roles") or [{}])[0].get("character"),
                "order": m.get("order"),
            }
            for m in cast[:10]
        ],
        "keywords": [kw["name"] for kw in details.get("keywords", {}).get("results", [])],
        "runtime": episode_run_time[0] if episode_run_time else None,
        "seasons": details.get("number_of_seasons"),
        "episodes": details.get("number_of_episodes"),
        "networks": [n["name"] for n in details.get("networks", [])],
        "collection_id": None,
        "collection_name": None,
        "countries": details.get("origin_country") or [],
        "certification": us_rating.get("rating") if us_rating else None,
        "imdb_id": details.get("external_ids", {}).get("imdb_id"),
    }


def extract_enrichment(details, media_type, tmdb_id):
    specific = _movie_fields(details) if media_type == "movie" else _tv_fields(details)
    return {
        "matched": True,
        "media_type": media_type,
        "tmdb_id": tmdb_id,
        "title": details.get("title") or details.get("name"),
        "original_title": details.get("original_title") or details.get("original_name"),
        "release_date": details.get("release_date") or details.get("first_air_date"),
        "genres": [g["name"] for g in details.get("genres", [])],
        "original_language": details.get("original_language"),
        "overview": details.get("overview"),
        "tagline": details.get("tagline"),
        "tmdb_rating": details.get("vote_average"),
        "vote_count": details.get("vote_count"),
        "watch_providers": _us_watch_providers(details),
        "watch_providers_region": "US",
        **specific,
        "tmdb_enrichment_version": ENRICHMENT_VERSION,
        "tmdb": details,
    }


def null_enrichment(media_type=None, tmdb_id=None):
    # must mirror extract_enrichment's key set exactly (including `tmdb`) so matched
    # and unmatched entries land with an identical shape
    return {
        "matched": False,
        "media_type": media_type,
        "tmdb_id": tmdb_id,
        "title": None,
        "original_title": None,
        "release_date": None,
        "directors": None,
        "writers": None,
        "cast": None,
        "cast_detail": None,
        "genres": None,
        "keywords": None,
        "runtime": None,
        "seasons": None,
        "episodes": None,
        "networks": None,
        "collection_id": None,
        "collection_name": None,
        "countries": None,
        "original_language": None,
        "certification": None,
        "imdb_id": None,
        "overview": None,
        "tagline": None,
        "tmdb_rating": None,
        "vote_count": None,
        "watch_providers": None,
        "watch_providers_region": None,
        "tmdb_enrichment_version": ENRICHMENT_VERSION,
        "tmdb": None,
    }


def enrich_entry(session, api_key, entry, append_by_type=APPEND_BY_TYPE):
    film_title = entry.get("film_title")
    film_year = entry.get("film_year")
    media_type = entry.get("tmdb_media_type")
    tmdb_id = entry.get("tmdb_id")

    try:
        if not tmdb_id:
            media_type, match = search_title(session, api_key, media_type, film_title, film_year)
            if match is None:
                print(f"UNMATCHED (no search results): '{film_title}' ({film_year})")
                return {**entry, **null_enrichment(media_type)}
            tmdb_id = match["id"]
        elif media_type not in ("movie", "tv"):
            # legacy raw checkpoints predate tmdb_media_type and were all movies
            media_type = "movie"

        details = fetch_details(session, api_key, media_type, tmdb_id, append_by_type)
        return {**entry, **extract_enrichment(details, media_type, tmdb_id)}

    except Exception as exc:
        print(f"UNMATCHED (TMDB call failed): '{film_title}' ({film_year}) - {exc}")
        return {**entry, **null_enrichment(media_type, tmdb_id)}


def enrich_entries(
    entries: list[dict], api_key: str | None = None, append_by_type: dict = APPEND_BY_TYPE
) -> tuple[list[dict], dict]:
    """Enrich diary entries with TMDB metadata. Returns (enriched_entries, match_summary).

    append_by_type selects the payload profile — the full APPEND_BY_TYPE (diary, default) or
    APPEND_BY_TYPE_LEAN (catalog)."""
    api_key = api_key or require_env("TMDB_API_KEY")
    session = requests.Session()

    enriched_entries = [enrich_entry(session, api_key, entry, append_by_type) for entry in entries]

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
            f"Diary checkpoint not found at {INPUT_PATH}. Run src/fetch_diary.py first."
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
