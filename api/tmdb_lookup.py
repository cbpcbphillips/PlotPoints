"""Resolve export rows the snapshot cannot match by asking TMDB, at import time.

Only rows `api.matching` gave up on come here, so most imports make no calls at all. Three things
this catches that no offline rule can:

  * a film TMDB has re-dated by years (Hamilton: 2020 on Letterboxd, 2025 on TMDB), found by exact
    title at the closest year;
  * a film that is simply not in the catalog (below the vote floor), which now has a TMDB id and
    can be enriched for next time;
  * a TV series logged on Letterboxd (Baby Reindeer), which the movie-only catalog will never hold.

Safety: the key travels as a query parameter, so nothing here ever formats a request URL into a
message or log (the same rule as enrich_tmdb.tmdb_get). Any failure leaves the row unresolved; an
import never fails because TMDB is slow or down. Without TMDB_API_KEY the lookup is disabled and
matching is snapshot-only.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from dotenv import dotenv_values

from api.matching import loose_title

BASE = "https://api.themoviedb.org/3"
TIMEOUT_SECONDS = 5
MAX_WORKERS = 8  # TMDB allows ~40 requests/s; 8 in flight stays well inside it
CACHE_SIZE = 5000


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def _key_from_environment() -> str:
    """TMDB_API_KEY from the process environment (deployed), else from a local .env (development).

    Only this one value is read from .env; nothing else in it (Snowflake, AWS) enters the API.
    """
    key = os.environ.get("TMDB_API_KEY", "")
    if not key and Path(".env").is_file():
        key = dotenv_values(".env").get("TMDB_API_KEY") or ""
    return key


class TmdbLookup:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.key = _key_from_environment() if api_key is None else api_key
        self.session = session or requests.Session()
        self._cache: OrderedDict[tuple[str, int | None], dict] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _get(self, path: str, params: dict) -> dict | None:
        for _ in range(2):
            try:
                resp = self.session.get(
                    f"{BASE}{path}", params={**params, "api_key": self.key}, timeout=TIMEOUT_SECONDS
                )
            except requests.RequestException:
                return None
            if resp.status_code == 429:
                time.sleep(min(float(resp.headers.get("Retry-After", 1)), 2))
                continue
            return resp.json() if resp.ok else None
        return None

    def _search(self, path: str, title: str, year: int | None, year_param: str) -> list[dict]:
        hits: list[dict] = []
        for params in ({"query": title, year_param: year} if year else None, {"query": title}):
            if params is None:
                continue
            data = self._get(path, params)
            hits.extend((data or {}).get("results") or [])
        seen, unique = set(), []
        for h in hits:
            if h.get("id") not in seen:
                seen.add(h.get("id"))
                unique.append(h)
        return unique

    def resolve_one(self, title: str, year: int | None) -> dict:
        """One row's answer: a movie (tmdb_id, title, year, votes), "tv" or "not_found"."""
        key = (loose_title(title), year)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        result = self._resolve(title, year)
        with self._lock:
            self._cache[key] = result
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return result

    def _resolve(self, title: str, year: int | None) -> dict:
        want = loose_title(title)
        movies = self._search("/search/movie", title, year, "year")

        def exact(h, *fields):
            return any(loose_title(h.get(f) or "") == want for f in fields)

        def dist(h):
            y = _year(h.get("release_date"))
            if not year:
                return 0
            return abs(y - year) if y else 999  # an undated stub never beats a dated film

        same = [h for h in movies if exact(h, "title", "original_title")]
        if same:
            # exact title: the closest year wins at any distance (TMDB re-dates films), then votes
            best = min(same, key=lambda h: (dist(h), -(h.get("vote_count") or 0)))
            return self._movie(best)

        shows = self._search("/search/tv", title, year, "first_air_date_year")
        if any(exact(h, "name", "original_name") for h in shows):
            return {"kind": "tv"}

        # a near title (a subtitle added or dropped) only counts in the right year
        for h in movies:
            got = loose_title(h.get("title") or "")
            if got and (got.startswith(want) or want.startswith(got)) and year and dist(h) <= 1:
                return self._movie(h)
        return {"kind": "not_found"}

    @staticmethod
    def _movie(h: dict) -> dict:
        return {
            "kind": "movie",
            "tmdb_id": int(h["id"]),
            "title": h.get("title"),
            "year": _year(h.get("release_date")),
            "votes": int(h.get("vote_count") or 0),
        }

    def resolve(self, rows: list[dict]) -> list[dict]:
        """Resolve rows ({title, year}) in parallel, in order."""
        if not self.enabled or not rows:
            return [{"kind": "not_found"} for _ in rows]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            return list(pool.map(lambda r: self.resolve_one(r["title"], r.get("year")), rows))
