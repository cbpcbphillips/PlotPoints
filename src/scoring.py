"""The recommender's arithmetic, with no database in it.

Two implementations of one scorer exist on purpose. recommend.py runs it as SQL inside Snowflake
(batch, tests, anything that needs the live warehouse). This module runs the same arithmetic in
numpy against an exported snapshot (the API, where Snowflake must not be in the request path).
tests/test_equivalence.py holds them to the same answer; the constants below are shared so they
cannot drift apart.

How a title is scored is documented in recommend.py. What this module adds is the **match
percentage** shown to users: the raw cosine similarity between a recommendation and the films
that explain it, averaged over the same top-N films that drive its rank. It is deliberately not
the ranking score. The ranking score is z-scored per seed film (the hubness correction), which
makes it comparable across seeds but means nothing to a reader; cosine is what a reader would
guess "match" means. Consequence, called out on the About page: the percentage is NOT strictly
decreasing down the list.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from snapshot import Snapshot

# Letterboxd's half-star scale: 3 stars is "fine", so 4+ is liked and below 3 is disliked.
# Chosen over "relative to the user's own mean": for a user who rates high (this diary's mean
# is 4.26) that would turn their 4-star films into dislikes.
RATING_MIDPOINT = 3.0
# Coming back to a film you already liked is a stronger signal than the rating alone.
REWATCH_BONUS = 0.5

TOP_N = 3  # a candidate's relevance is the mean of its N best matches among liked films
DISLIKE_WEIGHT = 0.5
QUALITY_PRIOR_VOTES = 100  # shrinkage strength; equals the catalog's vote floor
QUALITY_POWER = 2.0  # how steeply being below the member's own standard is discounted
# Candidates only: the catalog holds ~3% sub-hour titles (shorts, specials, making-ofs), which
# slip past the "already watched" filter because they are different titles. The first run on the
# full catalog recommended an 18-minute short of Whiplash and a 23-minute Interstellar
# documentary. Shorts you HAVE watched still count as taste signal. 60 keeps Dumbo (64 min).
MIN_RUNTIME_MINUTES = 60

_CHUNK = 256  # seed films scored per pass; bounds memory for very large histories


def weight_for(rating: float | None, rewatched: bool) -> float | None:
    """Signed taste weight for one film: positive liked, negative disliked, None unrated."""
    if rating is None:
        return None
    weight = rating - RATING_MIDPOINT
    if weight > 0 and rewatched:
        weight += REWATCH_BONUS
    return weight


# profile = {member: [(catalog_index, weight_or_None), ...]}
Profile = dict[str, list[tuple[int, "float | None"]]]


@dataclass
class _Member:
    name: str
    liked_idx: np.ndarray
    liked_w: np.ndarray
    disliked_idx: np.ndarray
    disliked_w: np.ndarray
    w_max: float


def quality_array(snap: Snapshot, prior_votes: int = QUALITY_PRIOR_VOTES) -> np.ndarray:
    """Bayesian-shrunk TMDB rating: 9.0 from 12 votes is noise, so pull it toward the mean."""
    r = snap.rating.astype(np.float64)
    v = snap.votes.astype(np.float64)
    q = (v / (v + prior_votes)) * r + (prior_votes / (v + prior_votes)) * snap.catalog_mean_rating
    q[np.isnan(r)] = np.nan
    return q


def _split(profiles: Profile) -> list[_Member]:
    members = []
    for name in sorted(profiles):
        liked = [(i, w) for i, w in profiles[name] if w is not None and w > 0]
        disliked = [(i, w) for i, w in profiles[name] if w is not None and w < 0]
        if not liked:
            raise ValueError(f"{name} has no liked films (rated above {RATING_MIDPOINT}).")
        members.append(
            _Member(
                name=name,
                liked_idx=np.array([i for i, _ in liked], dtype=np.int64),
                liked_w=np.array([w for _, w in liked], dtype=np.float64),
                disliked_idx=np.array([i for i, _ in disliked], dtype=np.int64),
                disliked_w=np.array([w for _, w in disliked], dtype=np.float64),
                w_max=max(w for _, w in liked),
            )
        )
    return members


def _z_pass(sims: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Standardize each seed's similarities against its own distribution over the candidates.

    Sample standard deviation (ddof=1) to match Snowflake's STDDEV. A seed with no spread (only
    possible on a tiny catalog) contributes nothing, like SQL's `nullif(stddev, 0)`.
    """
    mean = sims.mean(axis=0)
    std = sims.std(axis=0, ddof=1) if sims.shape[0] > 1 else np.zeros(sims.shape[1])
    safe = np.where(std == 0, np.nan, std)
    z = np.nan_to_num((sims - mean) / safe, nan=0.0)
    return z, mean, std


def _member_scores(
    snap: Snapshot,
    cand: np.ndarray,
    member: _Member,
    q: np.ndarray,
    dislike_weight: float,
    top_n: int,
    quality_power: float,
) -> dict:
    n = len(cand)
    cand_vecs = snap.vectors[cand]
    best = np.full((n, top_n), -np.inf)  # running top-N contributions per candidate
    penalty = np.zeros(n)
    liked_mean = np.empty(len(member.liked_idx))
    liked_std = np.empty(len(member.liked_idx))

    for start in range(0, len(member.liked_idx), _CHUNK):
        sel = slice(start, start + _CHUNK)
        sims = (cand_vecs @ snap.vectors[member.liked_idx[sel]].T).astype(np.float64)
        z, liked_mean[sel], liked_std[sel] = _z_pass(sims)
        contrib = z * (member.liked_w[sel] / member.w_max)
        merged = np.concatenate([best, contrib], axis=1)
        # merged always has more than top_n columns (best alone has top_n), so this is safe
        best = -np.partition(-merged, top_n - 1, axis=1)[:, :top_n]
    finite = np.isfinite(best)
    relevance = np.where(finite, best, 0.0).sum(axis=1) / finite.sum(axis=1)

    for start in range(0, len(member.disliked_idx), _CHUNK):
        sel = slice(start, start + _CHUNK)
        sims = (cand_vecs @ snap.vectors[member.disliked_idx[sel]].T).astype(np.float64)
        z, _, _ = _z_pass(sims)
        pen = np.maximum(z, 0) * (-member.disliked_w[sel] / member.w_max)
        penalty = np.maximum(penalty, pen.max(axis=1))

    adjusted = relevance - dislike_weight * penalty
    q_seed = q[member.liked_idx]
    ok = ~np.isnan(q_seed)
    anchor = (
        (member.liked_w[ok] * q_seed[ok]).sum() / member.liked_w[ok].sum() if ok.any() else np.nan
    )
    q_cand = q[cand]
    if np.isnan(anchor):
        quality_factor = np.ones(n)
    else:
        quality_factor = np.where(
            np.isnan(q_cand), 1.0, np.minimum(1.0, q_cand / anchor) ** quality_power
        )
    score = np.where(adjusted > 0, adjusted * quality_factor, adjusted)
    return {
        "member": member,
        "relevance": adjusted,
        "penalty": penalty,
        "quality_factor": quality_factor,
        "score": score,
        "liked_mean": liked_mean,
        "liked_std": liked_std,
    }


def _because(snap: Snapshot, row_idx: int, scored: dict, top_n: int) -> list[dict]:
    """The liked films behind one recommendation, strongest first, with their raw cosine."""
    m: _Member = scored["member"]
    sims = (snap.vectors[m.liked_idx] @ snap.vectors[row_idx]).astype(np.float64)
    std = np.where(scored["liked_std"] == 0, np.nan, scored["liked_std"])
    z = np.nan_to_num((sims - scored["liked_mean"]) / std, nan=0.0)
    contrib = z * (m.liked_w / m.w_max)
    order = np.argsort(-contrib, kind="stable")[:top_n]
    return [
        {
            "media_key": snap.media_key[m.liked_idx[j]],
            "tmdb_id": int(snap.tmdb_id[m.liked_idx[j]]),
            "title": snap.title[m.liked_idx[j]],
            "cosine": float(sims[j]),
        }
        for j in order
    ]


def rank(
    snap: Snapshot,
    profiles: Profile,
    *,
    limit: int = 20,
    dislike_weight: float = DISLIKE_WEIGHT,
    top_n: int = TOP_N,
    quality_power: float = QUALITY_POWER,
    min_runtime: int = MIN_RUNTIME_MINUTES,
    allow: np.ndarray | None = None,
) -> list[dict]:
    """Rank unwatched titles for one profile or a group (least-misery). Mirrors SCORE_SQL.

    `allow` is an optional boolean mask over the catalog (e.g. "streams on Netflix"). It is applied
    AFTER the per-seed standardization, so a filter changes which titles compete, never what any
    title scores: restricting the pool first would shift every z-score.
    """
    members = _split(profiles)
    watched = np.zeros(len(snap), dtype=bool)
    for films in profiles.values():
        for idx, _ in films:
            watched[idx] = True

    ok = ~watched & (np.isnan(snap.runtime) | (snap.runtime >= min_runtime))
    cand = np.flatnonzero(ok)
    q = quality_array(snap)
    per_member = [
        _member_scores(snap, cand, m, q, dislike_weight, top_n, quality_power) for m in members
    ]
    group = np.min(np.stack([p["score"] for p in per_member]), axis=0)

    keep = np.ones(len(cand), dtype=bool) if allow is None else allow[cand]
    pos = np.flatnonzero(keep)
    titles = np.asarray(snap.title, dtype=object)[cand[pos]]
    order = pos[np.lexsort((titles, -group[pos]))][:limit]  # score desc, then title like SQL

    results = []
    for rank_no, p in enumerate(order, start=1):
        row = int(cand[p])
        details = []
        for pm in per_member:
            because = _because(snap, row, pm, top_n)
            details.append(
                {
                    "member": pm["member"].name,
                    "score": float(pm["score"][p]),
                    "relevance": float(pm["relevance"][p]),
                    "penalty": float(pm["penalty"][p]),
                    "quality_factor": float(pm["quality_factor"][p]),
                    "match": float(np.mean([b["cosine"] for b in because])),
                    "because": because,
                }
            )
        results.append(
            {
                "rank": rank_no,
                "index": row,
                "media_key": snap.media_key[row],
                "tmdb_id": int(snap.tmdb_id[row]),
                "title": snap.title[row],
                "year": int(snap.year[row]) or None,
                "score": float(group[p]),
                # raw cosine, averaged over the films that explain it; the group's is its worst
                "match": min(d["match"] for d in details),
                "members": details,
            }
        )
    return results


def influence(
    snap: Snapshot,
    profiles: Profile,
    picks: list[int],
    *,
    member: str | None = None,
    top_n: int = 6,
    min_runtime: int = MIN_RUNTIME_MINUTES,
) -> list[dict]:
    """Which liked films best explain a set of picks, strongest first.

    Uses the scorer's own unit: each seed's similarity to a candidate is standardized against that
    seed's distribution over all candidates (the hubness correction), then weighted by how much the
    person liked the seed (rating - 3, over their largest weight). A seed's influence is that
    weighted z summed over the picks, so a film you loved that sits close to many picks outranks
    one you merely liked, and a hub that is close to everything is not rewarded for it.

    `picks` are catalog row indices. `avg_cosine` is the plain mean cosine to the picks, for show.
    Returns [] when no pick is a candidate or the member has no liked films.
    """
    members = _split(profiles)
    m = next((x for x in members if x.name == member), members[0])
    watched = np.zeros(len(snap), dtype=bool)
    for films in profiles.values():
        for idx, _ in films:
            watched[idx] = True
    cand = np.flatnonzero(~watched & (np.isnan(snap.runtime) | (snap.runtime >= min_runtime)))
    where = {int(i): k for k, i in enumerate(cand)}
    rows = [where[p] for p in picks if p in where]
    if not rows:
        return []

    cand_vecs = snap.vectors[cand]
    infl = np.empty(len(m.liked_idx))
    avg = np.empty(len(m.liked_idx))
    for start in range(0, len(m.liked_idx), _CHUNK):
        sel = slice(start, start + _CHUNK)
        sims = (cand_vecs @ snap.vectors[m.liked_idx[sel]].T).astype(np.float64)
        z, _, _ = _z_pass(sims)
        infl[sel] = (z[rows] * (m.liked_w[sel] / m.w_max)).sum(axis=0)
        avg[sel] = sims[rows].mean(axis=0)

    order = np.argsort(-infl, kind="stable")[:top_n]
    return [
        {
            "media_key": snap.media_key[m.liked_idx[j]],
            "tmdb_id": int(snap.tmdb_id[m.liked_idx[j]]),
            "title": snap.title[m.liked_idx[j]],
            "index": int(m.liked_idx[j]),
            "weight": float(m.liked_w[j]),
            "influence": float(infl[j]),
            "avg_cosine": float(avg[j]),
        }
        for j in order
    ]
