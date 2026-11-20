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

from collections import Counter
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
# Candidates only, again: the catalog is fetched at 100 votes, but titles a user imported that the
# catalog lacked are enriched too (user_ingest), so their taste counts. Those can sit at 5 or 8
# votes and must never be *recommended*: they shape a profile as seeds and nothing more.
CANDIDATE_MIN_VOTES = 100

# Liked films from one franchise share their vote: each is weighted 1 / k**DAMPEN_POWER, where k is
# how many liked films the person has in that franchise. Without it, three liked Spider-Man films
# give every Spider-Man-adjacent title a perfect top-3, while a person's one-off tastes (one film
# each for Whiplash, Good Will Hunting, Moneyball) can never fill three slots, so a franchise
# crowds out everything else. 0.5 is a middle path (1.0 would make three films count as one
# film; 0.0 is the old behaviour). A reasoned default, not a fitted one.
DAMPEN_POWER = 0.5

# The "branch out" row: maximal-marginal-relevance re-rank. 0 keeps the ranking, 1 ignores it.
BRANCH_OUT_LAMBDA = 0.45

_CHUNK = 256  # seed films scored per pass; bounds memory for very large histories


def weight_for(rating: float | None, rewatched: bool) -> float | None:
    """Signed taste weight for one film: positive liked, negative disliked, None unrated."""
    if rating is None:
        return None
    weight = rating - RATING_MIDPOINT
    if weight > 0 and rewatched:
        weight += REWATCH_BONUS
    return weight


def dampen_franchise_seeds(
    weights: list[float | None],
    franchises: list[str | None],
    power: float = DAMPEN_POWER,
) -> list[float | None]:
    """Share one vote among a person's liked films from the same franchise (see DAMPEN_POWER).

    Pure and row-aligned: `weights[i]` belongs to the film whose franchise is `franchises[i]`.
    Only liked films (weight > 0) in a named franchise are touched; disliked, neutral, unrated and
    standalone films pass through unchanged. Callers apply this when they build a profile, so the
    numpy scorer and the SQL scorer receive identical weights.
    """
    liked_in = Counter(
        f for w, f in zip(weights, franchises, strict=True) if w is not None and w > 0 and f
    )
    return [
        w / (liked_in[f] ** power) if w is not None and w > 0 and f else w
        for w, f in zip(weights, franchises, strict=True)
    ]


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
    # Weights behind the "because" notes. The score uses `liked_w`, in which a franchise shares one
    # vote (DAMPEN_POWER); the notes use the person's own, undamped weights, so a Spider-Man pick
    # is explained by the Spider-Man films they rated and not out-voted by a one-off favourite
    # whose similarity is much lower. Defaults to `liked_w` when no separate weights are given.
    reason_w: np.ndarray | None = None
    reason_w_max: float = 0.0

    def __post_init__(self) -> None:
        if self.reason_w is None:
            self.reason_w = self.liked_w
        if self.reason_w_max <= 0:
            self.reason_w_max = float(self.reason_w.max())


def quality_array(snap: Snapshot, prior_votes: int = QUALITY_PRIOR_VOTES) -> np.ndarray:
    """Bayesian-shrunk TMDB rating: 9.0 from 12 votes is noise, so pull it toward the mean."""
    r = snap.rating.astype(np.float64)
    v = snap.votes.astype(np.float64)
    q = (v / (v + prior_votes)) * r + (prior_votes / (v + prior_votes)) * snap.catalog_mean_rating
    q[np.isnan(r)] = np.nan
    return q


def _split(profiles: Profile, reasons: Profile | None = None) -> list[_Member]:
    members = []
    for name in sorted(profiles):
        liked = [(i, w) for i, w in profiles[name] if w is not None and w > 0]
        raw = {i: w for i, w in (reasons or {}).get(name, []) if w is not None and w > 0}
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
                reason_w=np.array([raw.get(i, w) for i, w in liked], dtype=np.float64),
            )
        )
    return members


def _candidates(snap: Snapshot, profiles: Profile, min_runtime: int, min_votes: int) -> np.ndarray:
    """Rows that may be recommended: unwatched by anyone, feature length, enough votes."""
    watched = np.zeros(len(snap), dtype=bool)
    for films in profiles.values():
        for idx, _ in films:
            watched[idx] = True
    long_enough = np.isnan(snap.runtime) | (snap.runtime >= min_runtime)
    return np.flatnonzero(~watched & long_enough & (snap.votes >= min_votes))


def similar_to(
    snap: Snapshot,
    index: int,
    n: int = 12,
    min_runtime: int = MIN_RUNTIME_MINUTES,
    min_votes: int = CANDIDATE_MIN_VOTES,
) -> list[dict]:
    """The `n` films nearest to one film, taste-free: plain cosine, best first.

    Same candidate rule as recommendations (feature length, enough votes) so a "more like this"
    row never offers a short or a making-of; the film itself is never returned. Rows are unit
    vectors, so the dot product is the cosine. Raw cosine ranks identically to a z-score here
    (one seed rescales every candidate the same way), so the z-pass is skipped.
    """
    cand = _candidates(snap, {}, min_runtime, min_votes)
    cand = cand[cand != index]
    if cand.size == 0 or n <= 0:
        return []
    sims = snap.vectors[cand] @ snap.vectors[index]
    top = np.argsort(-sims, kind="stable")[:n]
    return [
        {
            "index": int(cand[j]),
            "media_key": snap.media_key[cand[j]],
            "tmdb_id": int(snap.tmdb_id[cand[j]]),
            "title": snap.title[cand[j]],
            "cosine": float(sims[j]),
        }
        for j in top
    ]


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
    contrib = z * (m.reason_w / m.reason_w_max)
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


@dataclass
class Scored:
    """Every candidate scored for every member, before any ordering. Lets one scoring pass feed
    the ranked list, the "another side" pick and the comfort-zone pick."""

    snap: Snapshot
    members: list[_Member]
    cand: np.ndarray  # catalog rows that may be recommended
    per_member: list[dict]
    group: np.ndarray  # per candidate: the lowest member score (least misery)
    top_n: int


def score_candidates(
    snap: Snapshot,
    profiles: Profile,
    *,
    dislike_weight: float = DISLIKE_WEIGHT,
    top_n: int = TOP_N,
    quality_power: float = QUALITY_POWER,
    min_runtime: int = MIN_RUNTIME_MINUTES,
    min_votes: int = CANDIDATE_MIN_VOTES,
    reasons: Profile | None = None,
) -> Scored:
    members = _split(profiles, reasons)
    cand = _candidates(snap, profiles, min_runtime, min_votes)
    q = quality_array(snap)
    per_member = [
        _member_scores(snap, cand, m, q, dislike_weight, top_n, quality_power) for m in members
    ]
    group = np.min(np.stack([p["score"] for p in per_member]), axis=0)
    return Scored(snap, members, cand, per_member, group, top_n)


def _row(sc: Scored, p: int, rank_no: int) -> dict:
    """The result entry for the candidate at position `p` of `sc.cand`."""
    snap = sc.snap
    row = int(sc.cand[p])
    details = []
    for pm in sc.per_member:
        because = _because(snap, row, pm, sc.top_n)
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
    return {
        "rank": rank_no,
        "index": row,
        "media_key": snap.media_key[row],
        "tmdb_id": int(snap.tmdb_id[row]),
        "title": snap.title[row],
        "year": int(snap.year[row]) or None,
        "score": float(sc.group[p]),
        # raw cosine, averaged over the films that explain it; the group's is its worst
        "match": min(d["match"] for d in details),
        "members": details,
    }


def rank_scored(sc: Scored, *, limit: int = 20, allow: np.ndarray | None = None) -> list[dict]:
    """The best `limit` candidates, best first (score desc, then title like SQL)."""
    keep = np.ones(len(sc.cand), dtype=bool) if allow is None else allow[sc.cand]
    pos = np.flatnonzero(keep)
    titles = np.asarray(sc.snap.title, dtype=object)[sc.cand[pos]]
    order = pos[np.lexsort((titles, -sc.group[pos]))][:limit]
    return [_row(sc, int(p), n) for n, p in enumerate(order, start=1)]


def rank(
    snap: Snapshot,
    profiles: Profile,
    *,
    limit: int = 20,
    dislike_weight: float = DISLIKE_WEIGHT,
    top_n: int = TOP_N,
    quality_power: float = QUALITY_POWER,
    min_runtime: int = MIN_RUNTIME_MINUTES,
    min_votes: int = CANDIDATE_MIN_VOTES,
    allow: np.ndarray | None = None,
    reasons: Profile | None = None,
) -> list[dict]:
    """Rank unwatched titles for one profile or a group (least-misery). Mirrors SCORE_SQL.

    `reasons` is the same profile with undamped weights; it only changes which liked films the
    "because" notes name and never a score (see `_Member.reason_w`).

    `allow` is an optional boolean mask over the catalog (e.g. "streams on Netflix"). It is applied
    AFTER the per-seed standardization, so a filter changes which titles compete, never what any
    title scores: restricting the pool first would shift every z-score.
    """
    sc = score_candidates(
        snap,
        profiles,
        dislike_weight=dislike_weight,
        top_n=top_n,
        quality_power=quality_power,
        min_runtime=min_runtime,
        min_votes=min_votes,
        reasons=reasons,
    )
    return rank_scored(sc, limit=limit, allow=allow)


def diversify(
    snap: Snapshot,
    ranked: list[dict],
    n: int,
    *,
    shown: list[int] | tuple[int, ...] = (),
    lam: float = BRANCH_OUT_LAMBDA,
    max_per_franchise: int = 1,
) -> list[dict]:
    """A second, deliberately varied row: maximal-marginal-relevance over a ranked pool.

    Greedy: each pick maximizes (1 - lam) * score - lam * redundancy, where score is the ranking
    score scaled to 0-1 over the pool and redundancy is the pick's cosine to the nearest film
    already chosen, scaled to 0-1 between the pool's own 10th and 99th percentile pairwise cosine
    (raw cosine runs high and narrow, so it needs rescaling to trade off against the score).

    `shown` are catalog rows already on the page. They are never returned, their franchises are
    skipped entirely, and they count as already-chosen for redundancy, so this row is varied from
    the main one as well as within itself. At most `max_per_franchise` per franchise. This is not
    the "wildcard" of roadmap decision 5c: everything here still comes from the person's ranking,
    it is only spread out.
    """
    shown_set = {int(i) for i in shown}
    shown_franchises = {snap.franchise[i] for i in shown_set if snap.franchise[i]}
    pool = [
        r
        for r in ranked
        if r["index"] not in shown_set
        and (
            snap.franchise[r["index"]] is None or snap.franchise[r["index"]] not in shown_franchises
        )
    ]
    if not pool or n <= 0:
        return []

    idx = np.array([r["index"] for r in pool])
    score = np.array([r["score"] for r in pool], dtype=np.float64)
    span = score.max() - score.min()
    score_n = (score - score.min()) / span if span > 0 else np.ones(len(pool))

    vecs = snap.vectors[idx]
    cos = vecs @ vecs.T
    pairs = cos[np.triu_indices(len(idx), 1)]
    lo, hi = (np.percentile(pairs, 10), np.percentile(pairs, 99)) if pairs.size else (0.0, 1.0)
    hi = max(hi, lo + 1e-6)

    def scaled(c: np.ndarray) -> np.ndarray:
        return np.clip((c - lo) / (hi - lo), 0.0, 1.0)

    redundancy = scaled(cos)
    nearest = np.zeros(len(idx))
    if shown_set:
        nearest = scaled(vecs @ snap.vectors[sorted(shown_set)].T).max(axis=1)

    picked: list[int] = []
    taken = np.zeros(len(idx), dtype=bool)
    per_franchise: Counter = Counter()
    while len(picked) < min(n, len(idx)):
        value = (1 - lam) * score_n - lam * nearest
        value[taken] = -np.inf
        for j in np.flatnonzero(~taken):
            f = snap.franchise[idx[j]]
            if f and per_franchise[f] >= max_per_franchise:
                value[j] = -np.inf
        best = int(np.argmax(value))
        if not np.isfinite(value[best]):
            break
        picked.append(best)
        taken[best] = True
        f = snap.franchise[idx[best]]
        if f:
            per_franchise[f] += 1
        nearest = np.maximum(nearest, redundancy[best])
    return [pool[j] for j in picked]


# A group list by turns. Least-misery (the lowest member's score) drifts to films nobody minds and
# nobody loves; real groups pick by taking turns, each person offering a film they are keen on that
# the others can live with. Each pick must sit inside every member's top slice of their own ranking,
# starting tight and widening only when a turn finds nothing.
ROTATION_FITS = (0.05, 0.10, 0.20, 0.30)


def group_rotation(
    sc: Scored,
    n: int,
    *,
    fits: tuple[float, ...] = ROTATION_FITS,
) -> list[dict]:
    """`n` picks for a group, taking turns, in the order they are offered.

    On each turn the member whose turn it is gets their highest-scoring film among those that every
    member has in the top `fits[0]` of their own ranking; if none is left, the slice widens to
    `fits[1]`, then `fits[2]`; past that the turn goes to the film with the best worst-case slice.
    At most one film per franchise, so the list is not a series. The member whose history is
    thinnest goes first (they would otherwise steer a least-misery list, so they lead a fair one).

    Each entry is the usual result plus `picked_for` (whose turn) and `fit`: for every member, the
    top percent of their own ranking the film sits in (1 = their very best). Stable: the first k
    picks of a longer list are the same k, so a page can be asked for later.
    """
    snap, cand = sc.snap, sc.cand
    total = len(cand)
    if total == 0 or n <= 0:
        return []
    count = len(sc.per_member)
    scores = [np.asarray(pm["score"], dtype=np.float64) for pm in sc.per_member]
    # position in each member's own ranking, 0 = their favourite; ties broken by candidate order
    pct = np.empty((count, total))
    for i, sco in enumerate(scores):
        order = np.argsort(-sco, kind="stable")
        ranks = np.empty(total)
        ranks[order] = np.arange(total)
        pct[i] = ranks / total
    worst = pct.max(axis=0)  # a film's fit is only as good as its least-keen member's slice

    thin_first = sorted(range(count), key=lambda i: len(sc.members[i].liked_idx))
    franchise = np.array([snap.franchise[int(c)] or "" for c in cand], dtype=object)
    taken = np.zeros(total, dtype=bool)
    picks: list[tuple[int, int]] = []  # (candidate position, member index whose turn it was)
    turn = 0
    while len(picks) < n:
        who = thin_first[turn % count]
        turn += 1
        free = ~taken
        chosen = None
        for limit in fits:
            ok = free & (worst <= limit)
            if ok.any():
                idx = np.flatnonzero(ok)
                chosen = int(idx[np.argmax(scores[who][idx])])
                break
        if chosen is None:  # nothing within the widest slice: best worst-case, then their score
            idx = np.flatnonzero(free)
            if idx.size == 0:
                break
            chosen = int(idx[np.lexsort((-scores[who][idx], worst[idx]))[0]])
        picks.append((chosen, who))
        taken[chosen] = True
        name = franchise[chosen]
        if name:
            taken |= franchise == name

    out = []
    for rank_no, (p, who) in enumerate(picks, start=1):
        row = _row(sc, p, rank_no)
        row["picked_for"] = sc.members[who].name
        row["fit"] = [
            {"member": sc.members[i].name, "top_percent": max(1, int(np.ceil(pct[i][p] * 100)))}
            for i in range(count)
        ]
        out.append(row)
    return out


# "Step outside your comfort zone" (roadmap decision 5c): a well-rated film from a genre the person
# rarely rates, that still scores well for them. It is picked from the full candidate list, not
# the top few hundred, because by construction it is not near the top. Reasoned defaults, not
# fitted; see docs/roadmap.md for how they were set against real diaries.
WILDCARD_SIGNAL_TOP = 0.15  # must score in the top 15% of all candidates: a real taste signal
WILDCARD_MIN_VOTES = 1500  # and be a film many people have rated, so its rating means something
WILDCARD_MIN_RATING = 7.2  # TMDB rating: a good film, not just an unfamiliar one
# A film is outside the comfort zone when its best-covered genre is a small share of what the
# person likes. Tried in order, widening only if nothing qualifies (a very wide-ranging viewer).
WILDCARD_SHARES = (0.05, 0.08, 0.12, 0.2, 0.3)


def comfort_shares(sc: Scored) -> tuple[dict[str, float], dict[str, int], int]:
    """How much of what each person likes sits in each genre, averaged over the group.

    Returns (share per genre, liked films per genre, liked films in all). A share is the fraction
    of a person's liked weight (rating minus 3, rewatch bonus; undamped) carried by films of that
    genre, so Drama can be 0.6 and Western 0.01, and a film in three genres counts toward each.
    Members count equally however many films they have rated.
    """
    snap = sc.snap
    share: dict[str, float] = {}
    counts: dict[str, int] = {}
    total = 0
    for m in sc.members:
        w_sum = float(m.reason_w.sum())
        mine: dict[str, float] = {}
        for row, w in zip(m.liked_idx, m.reason_w, strict=True):
            total += 1
            for g in snap.genres[int(row)]:
                mine[g] = mine.get(g, 0.0) + float(w)
                counts[g] = counts.get(g, 0) + 1
        for g, v in mine.items():
            share[g] = share.get(g, 0.0) + v / w_sum / len(sc.members)
    return share, counts, total


def wildcard_pick(
    sc: Scored,
    *,
    exclude: list[int] | tuple[int, ...] = (),
    signal_top: float = WILDCARD_SIGNAL_TOP,
    min_votes: int = WILDCARD_MIN_VOTES,
    min_rating: float = WILDCARD_MIN_RATING,
) -> dict | None:
    """A good film outside the person's usual genres that still scores well for them.

    Qualifies when it (1) is in the top `signal_top` of all candidates by score, so it carries a
    real signal from the profile; (2) has at least `min_votes` votes and a TMDB rating of at least
    `min_rating`; (3) has no genre that is more than a small share of what the person likes
    (`WILDCARD_SHARES`, widened step by step if nothing qualifies). The best by score wins.

    Returns the usual result entry plus `outside`: the least-covered genre of the pick, how many
    of the person's liked films are in it, and how high the pick scores overall, for an honest
    "why" that does not claim the film is similar to what they rated. None if nothing qualifies.
    """
    snap, cand, group = sc.snap, sc.cand, sc.group
    if len(cand) == 0:
        return None
    share, counts, total = comfort_shares(sc)
    floor = np.quantile(group, 1 - signal_top)
    skip = {int(i) for i in exclude}

    rating = snap.rating[cand]
    votes = snap.votes[cand]
    ok = (group > max(floor, 0.0)) & (votes >= min_votes) & (rating >= min_rating)
    pool = [int(p) for p in np.flatnonzero(ok) if int(cand[p]) not in skip]
    if not pool:
        return None

    def comfort(p: int) -> float:
        gs = snap.genres[int(cand[p])]
        return max((share.get(g, 0.0) for g in gs), default=1.0) if gs else 1.0

    scored = [(p, comfort(p)) for p in pool]
    for limit in WILDCARD_SHARES:
        hits = [p for p, c in scored if c <= limit]
        if hits:
            best = min(hits, key=lambda p: (-group[p], snap.title[int(cand[p])]))
            break
    else:
        return None

    row = _row(sc, best, 0)
    genres = snap.genres[row["index"]]
    rare = min(genres, key=lambda g: share.get(g, 0.0)) if genres else None
    row["outside"] = {
        "genre": rare,
        "liked_in_genre": counts.get(rare, 0) if rare else 0,
        "liked_total": total,
        "top_percent": max(1, round(100 * float((group > group[best]).sum()) / len(cand))),
    }
    return row


def closest_rated(
    snap: Snapshot,
    profiles: Profile,
    index: int,
    *,
    n: int = 5,
    member: str | None = None,
) -> list[dict]:
    """The films a person liked that sit closest to one film, nearest first.

    Plain cosine, so the order matches the percentage shown beside each one. (The recommender's
    "because you liked" notes use a standardized, weight-scaled score instead, which is right for
    ranking candidates but would show a list whose percentages are not in order.) The target
    itself is never returned, even if the person liked it.
    """
    members = _split(profiles)
    m = next((x for x in members if x.name == member), members[0])
    sims = (snap.vectors[m.liked_idx] @ snap.vectors[index]).astype(np.float64)
    out = []
    for j in np.argsort(-sims, kind="stable"):
        row = int(m.liked_idx[j])
        if row == index:
            continue
        out.append(
            {
                "index": row,
                "media_key": snap.media_key[row],
                "tmdb_id": int(snap.tmdb_id[row]),
                "title": snap.title[row],
                "cosine": float(sims[j]),
            }
        )
        if len(out) == n:
            break
    return out


def influence(
    snap: Snapshot,
    profiles: Profile,
    picks: list[int],
    *,
    member: str | None = None,
    top_n: int = 6,
    min_runtime: int = MIN_RUNTIME_MINUTES,
    min_votes: int = CANDIDATE_MIN_VOTES,
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
    cand = _candidates(snap, profiles, min_runtime, min_votes)
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
