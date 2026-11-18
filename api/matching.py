"""Match Letterboxd export rows (title + year, no TMDB id) to catalog titles.

Titles are not unique: two different films are each called "Good Boy" and "The Killer". So a
match is on (normalized title, year), tolerating a year either side because Letterboxd and TMDB
disagree about a film's year (festival premiere vs release) often enough to matter. When several
films still fit, the most-voted one wins and the row is flagged `ambiguous` so the UI can say so;
silently picking would be a guess presented as a fact.
"""

from __future__ import annotations

from snapshot import Snapshot, normalize_title


def match_rows(snap: Snapshot, rows: list[dict]) -> dict:
    films, unmatched, ambiguous = [], [], 0
    seen: set[int] = set()
    for row in rows:
        title = normalize_title(row["title"])
        year = row.get("year")
        candidates: list[int] = []
        if year:
            for y in (year, year - 1, year + 1):  # exact year first
                candidates = [
                    i
                    for i in snap.by_title_year.get((title, y), [])
                    if snap.media_type[i] == "movie"
                ]
                if candidates:
                    break
        else:
            candidates = [
                i
                for (t, _y), idxs in snap.by_title_year.items()
                if t == title
                for i in idxs
                if snap.media_type[i] == "movie"
            ]
        if not candidates:
            unmatched.append({"title": row["title"], "year": year})
            continue
        flagged = len(candidates) > 1
        best = max(candidates, key=lambda i: int(snap.votes[i]))
        if best in seen:  # the same film listed twice (e.g. a rewatch row): keep the first
            continue
        seen.add(best)
        ambiguous += flagged
        films.append(
            {
                "tmdb_id": int(snap.tmdb_id[best]),
                "media_type": snap.media_type[best],
                "title": snap.title[best],
                "year": int(snap.year[best]) or None,
                "rating": row.get("rating"),
                "rewatch": bool(row.get("rewatch")),
                "ambiguous": flagged,
            }
        )
    return {"films": films, "unmatched": unmatched, "ambiguous": ambiguous}
