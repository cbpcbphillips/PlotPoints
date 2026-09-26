"""Connection check for the TMDB API.

Exercises the real client (`tmdb_get` from enrich_tmdb) against the endpoints the
pipeline actually depends on: the details call with both append profiles, and the
/discover query the catalog fetcher is built on. Read-only -- TMDB has no write
surface we use.

Run via `just test-tmdb`.
"""

import argparse
import json
import os

import requests
from dotenv import load_dotenv

from check_common import CheckWarning, human_bytes, run_checks
from connection._env import require_env
from enrich_tmdb import APPEND_MOVIE, APPEND_MOVIE_LEAN, TMDB_BASE_URL, tmdb_get

load_dotenv()

# Fight Club -- a stable, well-populated title to probe with. Any long-lived TMDB
# id works; this one has full credits/keywords/release_dates so the append
# sub-responses are all non-empty.
PROBE_MOVIE_ID = 550


def check_env():
    require_env("TMDB_API_KEY")
    return "TMDB_API_KEY set"


def check_auth(session, api_key):
    def probe():
        config = tmdb_get(session, api_key, "/configuration")
        base_url = (config.get("images") or {}).get("secure_base_url")
        if not base_url:
            raise RuntimeError(f"/configuration returned no images.secure_base_url: {config}")
        return f"/configuration OK, images at {base_url}"

    return probe


def check_full_payload(session, api_key):
    def probe():
        details = tmdb_get(
            session,
            api_key,
            f"/movie/{PROBE_MOVIE_ID}",
            {"append_to_response": APPEND_MOVIE},
        )
        expected = [block.strip() for block in APPEND_MOVIE.split(",")]
        # TMDB returns watch/providers under the key "watch/providers"
        missing = [block for block in expected if block not in details]
        size = len(json.dumps(details))

        if missing:
            raise CheckWarning(
                f"{details.get('title')} OK ({human_bytes(size)}) but append blocks "
                f"missing: {', '.join(missing)}"
            )
        return (
            f"{details.get('title')} ({(details.get('release_date') or '????')[:4]}), "
            f"{len(expected)} append blocks, {human_bytes(size)}"
        )

    return probe


def check_lean_payload(session, api_key):
    def probe():
        details = tmdb_get(
            session,
            api_key,
            f"/movie/{PROBE_MOVIE_ID}",
            {"append_to_response": APPEND_MOVIE_LEAN},
        )
        expected = [block.strip() for block in APPEND_MOVIE_LEAN.split(",")]
        missing = [block for block in expected if block not in details]
        size = len(json.dumps(details))

        if missing:
            raise CheckWarning(f"lean payload missing blocks: {', '.join(missing)}")
        return f"{len(expected)} append blocks, {human_bytes(size)} (catalog profile)"

    return probe


def check_discover(session, api_key):
    """The exact query shape fetch_catalog.discover_year uses."""

    def probe():
        data = tmdb_get(
            session,
            api_key,
            "/discover/movie",
            {
                "sort_by": "vote_count.desc",
                "vote_count.gte": 200,
                "primary_release_year": 1999,
                "page": 1,
            },
        )
        results = data.get("results") or []
        if not results:
            raise RuntimeError(f"/discover/movie returned no results: {data}")
        return (
            f"{data.get('total_results')} titles for 1999, "
            f"top: {results[0].get('title')} ({results[0].get('vote_count')} votes)"
        )

    return probe


def check_read_token(session):
    """The v4 bearer token is provisioned but unused by the pipeline today."""

    def probe():
        token = os.environ.get("TMDB_READ_TOKEN")
        if not token:
            raise CheckWarning("TMDB_READ_TOKEN not set (unused by the pipeline today)")

        response = session.get(
            f"{TMDB_BASE_URL}/authentication",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"bearer auth returned {response.status_code}: {response.text[:200]}"
            )
        return "v4 bearer token valid"

    return probe


def main():
    parser = argparse.ArgumentParser(description="Check the TMDB API connection.")
    parser.add_argument("--verbose", action="store_true", help="print tracebacks on failure")
    args = parser.parse_args()

    session = requests.Session()
    api_key = os.environ.get("TMDB_API_KEY", "")

    checks = [
        ("credentials", check_env),
        ("api auth", check_auth(session, api_key)),
        ("details (full profile)", check_full_payload(session, api_key)),
        ("details (lean profile)", check_lean_payload(session, api_key)),
        ("discover query", check_discover(session, api_key)),
        ("v4 read token", check_read_token(session)),
    ]

    raise SystemExit(run_checks("TMDB", checks, verbose=args.verbose))


if __name__ == "__main__":
    main()
