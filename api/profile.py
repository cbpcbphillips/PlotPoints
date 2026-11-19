"""What a person's history says about their taste, read off the snapshot. Stateless and cheap."""

from __future__ import annotations

from collections import Counter

import numpy as np

import snapshot

HALF_STARS = [0.5 * k for k in range(1, 11)]


def profile_stats(s: snapshot.Snapshot, films: list[dict]) -> dict:
    """Counts and shares for the History page.

    `films` are {tmdb_id, media_type, rating|None}. Genre and era shares are the fraction of the
    films we could find in the catalog that carry that genre or sit in that decade, so a film with
    two genres counts toward both and the shares do not add to 100.
    """
    rated = [f for f in films if f.get("rating") is not None]
    rows = []
    for f in films:
        i = s.by_tmdb.get((f.get("media_type", "movie"), int(f["tmdb_id"])))
        if i is not None:
            rows.append((i, f))
    n = len(rows)

    hist = Counter(float(f["rating"]) for f in rated)
    genres, eras, series = Counter(), Counter(), Counter()
    runtimes, tmdb, years = [], [], []
    for i, _ in rows:
        for g in s.genres[i]:
            genres[g] += 1
        if s.year[i]:
            years.append(int(s.year[i]))
            eras[f"{int(s.year[i]) // 10 * 10}s"] += 1
        if s.franchise[i]:
            series[s.franchise[i]] += 1
        if not np.isnan(s.runtime[i]):
            runtimes.append(float(s.runtime[i]))
        if not np.isnan(s.rating[i]):
            tmdb.append(float(s.rating[i]))

    def shares(c: Counter, top: int) -> list[dict]:
        return [{"name": k, "count": v, "share": round(100 * v / n)} for k, v in c.most_common(top)]

    top_series = series.most_common(1)
    return {
        "films": len(films),
        "rated": len(rated),
        "in_catalog": n,
        "not_in_catalog": len(films) - n,
        "average_rating": round(sum(float(f["rating"]) for f in rated) / len(rated), 2)
        if rated
        else None,
        "histogram": [{"rating": r, "count": hist.get(r, 0)} for r in HALF_STARS],
        "genres": shares(genres, 5),
        "eras": shares(eras, 5),
        "average_runtime": round(sum(runtimes) / len(runtimes)) if runtimes else None,
        "average_tmdb": round(sum(tmdb) / len(tmdb), 1) if tmdb else None,
        "top_series": {"name": top_series[0][0], "count": top_series[0][1]} if top_series else None,
        "five_star": [s.title[i] for i, f in rows if f.get("rating") == 5],
        "newest": max(years) if years else None,
        "oldest": min(years) if years else None,
    }
