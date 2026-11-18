"""Server-side Letterboxd RSS import (browsers can't: the feed sends no CORS headers)."""

from __future__ import annotations

from collections import defaultdict

import feedparser
import requests

from fetch_diary import parse_entry

TIMEOUT_SECONDS = 8
MAX_BYTES = 3_000_000  # a real feed is ~100 KB; anything near this is not a Letterboxd feed
USER_AGENT = "PlotPoints/1.0 (+recommendation project; reads one public RSS feed per request)"


class LetterboxdError(Exception):
    """A user-facing problem: unknown user, private diary, Letterboxd unreachable."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def fetch_feed(username: str) -> list[dict]:
    url = f"https://letterboxd.com/{username}/rss/"
    try:
        resp = requests.get(
            url, timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}, stream=True
        )
    except requests.RequestException:
        raise LetterboxdError("Could not reach Letterboxd. Try again in a moment.") from None
    if resp.status_code == 404:
        raise LetterboxdError(f"No Letterboxd user named {username!r}.", status=404)
    if resp.status_code != 200:
        raise LetterboxdError(f"Letterboxd answered {resp.status_code}.")
    body = resp.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(body) > MAX_BYTES:
        raise LetterboxdError("That feed is larger than any Letterboxd diary should be.")
    feed = feedparser.parse(body)
    if not feed.entries:
        raise LetterboxdError(
            f"{username!r} has no public diary entries. Is the profile private or empty?",
            status=404,
        )
    return [parse_entry(e, username) for e in feed.entries]


def collapse(entries: list[dict]) -> list[dict]:
    """One row per film, the way recommend.build_profiles does it.

    The feed is newest first. A film logged twice counts once, rated by its latest *rated* watch
    (people re-rate), and is a rewatch if it appears more than once or any entry says so.
    """
    by_film: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for e in entries:
        if e.get("tmdb_id") and e.get("tmdb_media_type"):
            by_film[(e["tmdb_media_type"], e["tmdb_id"])].append(e)
    films = []
    for (media_type, tmdb_id), watches in by_film.items():
        rating = next((w["rating"] for w in watches if w["rating"] is not None), None)
        films.append(
            {
                "tmdb_id": tmdb_id,
                "media_type": media_type,
                "title": watches[0]["film_title"],
                "year": int(watches[0]["film_year"]) if watches[0]["film_year"] else None,
                "rating": rating,
                "rewatch": len(watches) > 1 or any(w["rewatch"] for w in watches),
            }
        )
    return films
