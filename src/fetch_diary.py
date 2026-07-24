"""Fetch a Letterboxd diary RSS feed and save a clean JSON checkpoint.

Note: Letterboxd's RSS feed only returns the ~50 most recent diary entries.
This is an expected limitation of the feed, not a bug in this script.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup

CHECKPOINT_PATH = Path("data/checkpoints/diary_raw.json")


def parse_review_text(description_html):
    """Strip the poster image and return the review text, or None if the
    description only contains the 'Watched on [date].' filler line."""
    soup = BeautifulSoup(description_html, "html.parser")

    for img in soup.find_all("img"):
        img.decompose()

    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if p]

    if not paragraphs:
        return None

    if len(paragraphs) == 1 and paragraphs[0].startswith("Watched on"):
        return None

    return "\n\n".join(paragraphs)


def parse_entry(entry, username):
    rating_raw = getattr(entry, "letterboxd_memberrating", None)
    rewatch_raw = getattr(entry, "letterboxd_rewatch", None)

    # Letterboxd tags each entry with either a movie or a TV tmdb id; keep track of
    # which so enrichment can hit the right TMDB endpoint (/movie vs /tv).
    movie_id = getattr(entry, "tmdb_movieid", None)
    tv_id = getattr(entry, "tmdb_tvid", None)
    tmdb_id_raw = movie_id or tv_id
    media_type = "movie" if movie_id else ("tv" if tv_id else None)

    return {
        "letterboxd_username": username,
        "letterboxd_uri": entry.link,
        "guid": entry.guid,
        "film_title": getattr(entry, "letterboxd_filmtitle", None),
        "film_year": getattr(entry, "letterboxd_filmyear", None),
        "watched_date": getattr(entry, "letterboxd_watcheddate", None),
        "rewatch": rewatch_raw == "Yes",
        "rating": float(rating_raw) if rating_raw else None,
        "tmdb_id": int(tmdb_id_raw) if tmdb_id_raw else None,
        "tmdb_media_type": media_type,
        "review_text": parse_review_text(entry.description),
        "published": getattr(entry, "published", None),
    }


def fetch_diary(username: str) -> list[dict]:
    rss_url = f"https://letterboxd.com/{username}/rss/"
    feed = feedparser.parse(rss_url)

    if feed.bozo and not feed.entries:
        raise RuntimeError(
            f"Failed to parse Letterboxd RSS feed at {rss_url}: {feed.bozo_exception}"
        )

    if not feed.entries:
        raise RuntimeError(
            f"No entries found in feed at {rss_url}. Double-check that "
            f"the username ('{username}') is correct."
        )

    return [parse_entry(entry, username) for entry in feed.entries]


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else input("Letterboxd username: ").strip()

    entries = fetch_diary(username)

    checkpoint = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": f"https://letterboxd.com/{username}/rss/",
        "count": len(entries),
        "entries": entries,
    }

    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(
        json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Wrote {len(entries)} entries to {CHECKPOINT_PATH}")
    print("\nSample entry:")
    print(json.dumps(entries[0], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
