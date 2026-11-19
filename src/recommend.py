"""Recommend unwatched titles from a Letterboxd diary (or several, for a group).

Request-time SQL over MART.MEDIA_EMBEDDINGS, deliberately not a dbt model: a brand-new user
should get an answer the moment their diary lands, not after the next batch build.

The work is split in two so each half can be reused and tested on its own:

  1. build_profiles -- turn diaries into (member, media_key, weight) rows. Pure Python plus one
     cheap query. A future CSV import or "pick films you like" UI produces the same shape.
  2. score_profiles -- one SQL statement that scores every unwatched catalog title.

How a title is scored, per member:

  relevance   Cosine similarity to each film the member liked, weighted by how much they liked
              it; the mean of the best three. NOT a centroid -- averaging a love of superhero
              films and a love of sports dramas lands in a bland middle that matches neither.
  z-scoring   Each seed film's similarities are standardized against that film's own
              distribution over the catalog first. Raw cosine has a per-film floor (measured on
              this catalog: mean similarity from 0.295 for Moneyball to 0.412 for Obsession,
              against a standard deviation of ~0.05), so without it films with a high floor
              dominate every recommendation regardless of what they actually resemble.
  penalty     Similarity to a *disliked* film subtracts from relevance. It is applied per
              candidate, so nothing is ever pulled toward or pushed away in vector space -- a
              strong negative can't drag an averaged taste vector somewhere arbitrary.
  quality     Bayesian-shrunk TMDB rating, judged against the member's OWN standard (the
              rating of what they like), not a global bar. Soft: it discounts, never excludes.

For a group, each member is scored independently and combined per title with least-misery
(the minimum), so nothing is chosen that one member would hate. Averaging members' vectors
instead tends toward compromises nobody loves. Titles any member has watched are excluded.

Run via `just recommend VetOW` (one user) or `just recommend VetOW friend` (a group).
"""

import argparse
import json
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

from connection.snowflake import get_snowflake_connection

# The constants and weight_for live in scoring.py (pure, no Snowflake) so this SQL scorer and the
# API's numpy scorer cannot drift apart. They are re-exported here for the CLI and its callers.
from scoring import (
    CANDIDATE_MIN_VOTES,
    DISLIKE_WEIGHT,
    MIN_RUNTIME_MINUTES,
    QUALITY_POWER,
    QUALITY_PRIOR_VOTES,
    RATING_MIDPOINT,
    REWATCH_BONUS,  # noqa: F401
    TOP_N,
    weight_for,
)

load_dotenv()


def _database() -> str:
    return os.environ.get("SNOWFLAKE_DATABASE", "PLOTPOINTS_DB")


def embedding_model(conn) -> str:
    """The model the catalog is embedded with, read from the data rather than duplicated.

    Whichever model covers the most titles wins, so a half-finished model migration (a few new
    rows alongside the old ones) can't silently switch the query to a model most of the
    catalog doesn't have vectors for.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"select embedding_model from {_database()}.MART.MEDIA_EMBEDDINGS "
            "group by 1 order by count(*) desc limit 1"
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError("MART.MEDIA_EMBEDDINGS is empty. Has `just dbt build` run?")
    return row[0]


def build_profiles(conn, usernames: list[str]) -> dict[str, list[dict]]:
    """{member: [{media_key, weight}]} from the diary fact, one row per film.

    A film logged several times counts once, with the *latest* watch's rating (people re-rate)
    and a rewatch bonus. Unrated films keep weight None: they carry no taste signal but still
    mean "already seen", so they stay in the profile for exclusion.
    """
    params = {f"u{i}": name.lower() for i, name in enumerate(usernames)}
    placeholders = ", ".join(f"%(u{i})s" for i in range(len(usernames)))

    with conn.cursor() as cur:
        cur.execute(
            f"select user_id, media_key, rating, rewatch, watched_date, source "
            f"from {_database()}.MART.FCT_DIARY_ENTRY "
            f"where lower(user_id) in ({placeholders}) and media_key is not null "
            f"order by user_id, media_key, watched_date desc nulls last",
            params,
        )
        rows = cur.fetchall()

    # (rating, rewatch flag, is a dated RSS watch). An import row says "seen and rated" but is not
    # a watch event: a film in both an RSS diary and an export must not look like a rewatch.
    by_film: dict[tuple[str, str], list] = defaultdict(list)
    for user_id, media_key, rating, rewatch, _watched, source in rows:
        by_film[(user_id, media_key)].append((rating, bool(rewatch), source == "letterboxd_rss"))

    profiles: dict[str, list[dict]] = defaultdict(list)
    for (user_id, media_key), watches in by_film.items():
        latest_rating = next(
            (r for r, _, _ in watches if r is not None), None
        )  # rows are newest first
        rewatched = sum(rss for _, _, rss in watches) > 1 or any(flag for _, flag, _ in watches)
        profiles[user_id].append(
            {
                "media_key": media_key,
                "weight": weight_for(
                    None if latest_rating is None else float(latest_rating), rewatched
                ),
            }
        )

    missing = [u for u in usernames if u.lower() not in {k.lower() for k in profiles}]
    if missing:
        with conn.cursor() as cur:
            cur.execute(f"select distinct user_id from {_database()}.MART.DIM_USER order by 1")
            known = [r[0] for r in cur.fetchall()]
        raise RuntimeError(f"No diary found for {missing}. Known users: {known}")

    return dict(profiles)


SCORE_SQL = """
with profile as (
    select value:member::string    as member,
           value:media_key::string as media_key,
           value:weight::float     as weight
    from table(flatten(input => parse_json(%(profile)s)))
),

-- anything ANY member has seen is excluded, rated or not
watched as (select distinct media_key from profile),

-- neutral (weight 0) and unrated films carry no taste signal
seeds as (
    select p.member, p.media_key as seed_key, p.weight, e.embedding, m.title as seed_title
    from profile p
    join {db}.MART.MEDIA_EMBEDDINGS e
        on e.media_key = p.media_key and e.embedding_model = %(model)s
    join {db}.MART.DIM_MEDIA m on m.media_key = p.media_key
    where p.weight is not null and p.weight != 0
),

candidates as (
    select e.media_key, e.embedding, m.title, year(m.release_date) as yr,
           m.media_type, m.tmdb_id, m.tmdb_rating, m.vote_count
    from {db}.MART.MEDIA_EMBEDDINGS e
    join {db}.MART.DIM_MEDIA m on m.media_key = e.media_key
    where e.embedding_model = %(model)s
      and e.media_key not in (select media_key from watched)
      and (m.runtime_minutes is null or m.runtime_minutes >= %(min_runtime)s)
      and coalesce(m.vote_count, 0) >= %(min_votes)s
),

-- strongest love per member, so weights normalize to (0, 1] and members share a scale
w_max as (
    select member, max(weight) as w_max from seeds where weight > 0 group by member
),

pairs as (
    select c.media_key, s.member, s.seed_key, s.seed_title, s.weight,
           vector_cosine_similarity(c.embedding, s.embedding) as sim
    from candidates c cross join seeds s
),

-- z-score each seed against its own catalog distribution (see module docstring)
zscored as (
    select media_key, member, seed_title, weight,
           (sim - avg(sim) over (partition by member, seed_key))
               / nullif(stddev(sim) over (partition by member, seed_key), 0) as z
    from pairs
),

liked as (
    select z.media_key, z.member, z.seed_title, z.z * z.weight / w.w_max as contribution
    from zscored z join w_max w on w.member = z.member
    where z.weight > 0
),

liked_ranked as (
    select *, row_number() over (partition by media_key, member order by contribution desc) as rn
    from liked
),

relevance as (
    select media_key, member, avg(contribution) as relevance,
           array_agg(seed_title) within group (order by contribution desc) as because
    from liked_ranked
    where rn <= %(top_n)s
    group by media_key, member
),

-- only similarity ABOVE a disliked film's own baseline counts against a candidate
penalty as (
    select z.media_key, z.member,
           max(greatest(z.z, 0) * (-z.weight) / w.w_max) as penalty
    from zscored z join w_max w on w.member = z.member
    where z.weight < 0
    group by z.media_key, z.member
),

catalog_rating as (
    select avg(tmdb_rating) as c
    from {db}.MART.DIM_MEDIA where tmdb_rating is not null and vote_count > 0
),

-- shrink toward the catalog mean when a rating rests on few votes: 9.0 from 12 votes is noise
quality as (
    select m.media_key,
           (m.vote_count / (m.vote_count + %(prior_votes)s)) * m.tmdb_rating
             + (%(prior_votes)s / (m.vote_count + %(prior_votes)s)) * r.c as q
    from {db}.MART.DIM_MEDIA m cross join catalog_rating r
    where m.tmdb_rating is not null
),

-- each member's own bar: the quality of the films they like, weighted by how much
anchor as (
    select s.member, sum(s.weight * q.q) / sum(s.weight) as anchor
    from seeds s join quality q on q.media_key = s.seed_key
    where s.weight > 0
    group by s.member
),

scored as (
    select r.media_key, r.member, r.relevance, r.because,
           coalesce(p.penalty, 0) as penalty,
           r.relevance - %(dislike_weight)s * coalesce(p.penalty, 0) as adjusted,
           coalesce(power(least(1, q.q / a.anchor), %(quality_power)s), 1) as quality_factor
    from relevance r
    left join penalty p on p.media_key = r.media_key and p.member = r.member
    left join quality q on q.media_key = r.media_key
    join anchor a on a.member = r.member
)

select c.media_key, c.tmdb_id, c.title, c.yr, c.media_type, c.tmdb_rating, c.vote_count,
       min(case when s.adjusted > 0 then s.adjusted * s.quality_factor else s.adjusted end)
           as score,
       array_agg(object_construct(
           'member', s.member,
           'score', case when s.adjusted > 0 then s.adjusted * s.quality_factor else s.adjusted end,
           'relevance', s.adjusted,
           'penalty', s.penalty,
           'quality_factor', s.quality_factor,
           'because', s.because
       )) as members
from scored s
join candidates c on c.media_key = s.media_key
group by c.media_key, c.tmdb_id, c.title, c.yr, c.media_type, c.tmdb_rating, c.vote_count
having count(*) = (select count(distinct member) from seeds)
order by score desc, c.title
limit %(k)s
"""


def score_profiles(
    conn,
    profiles: dict[str, list[dict]],
    k: int = 20,
    dislike_weight: float = DISLIKE_WEIGHT,
    top_n: int = TOP_N,
    quality_power: float = QUALITY_POWER,
    min_runtime: int = MIN_RUNTIME_MINUTES,
) -> list[dict]:
    """Rank unwatched titles for one profile or a group. See the module docstring.

    `profiles` is {member: [{media_key, weight}]}. Taking profiles rather than usernames is the
    seam that makes group mode testable without a second real diary.
    """
    for member, films in profiles.items():
        if not any(f["weight"] is not None and f["weight"] > 0 for f in films):
            raise RuntimeError(f"{member} has no liked films (rated above {RATING_MIDPOINT}).")

    flat = [
        {"member": member, "media_key": f["media_key"], "weight": f["weight"]}
        for member, films in profiles.items()
        for f in films
    ]
    params = {
        "profile": json.dumps(flat),
        "model": embedding_model(conn),
        "top_n": top_n,
        "dislike_weight": dislike_weight,
        "quality_power": quality_power,
        "min_runtime": min_runtime,
        "min_votes": CANDIDATE_MIN_VOTES,
        "prior_votes": QUALITY_PRIOR_VOTES,
        "k": k,
    }

    with conn.cursor() as cur:
        cur.execute(SCORE_SQL.format(db=_database()), params)
        rows = cur.fetchall()

    results = []
    for rank, row in enumerate(rows, start=1):
        media_key, tmdb_id, title, year, media_type, tmdb_rating, vote_count, score, members = row
        details = sorted(json.loads(members), key=lambda m: m["member"])
        results.append(
            {
                "rank": rank,
                # identity: titles are not unique (two different films are both "Good Boy")
                "media_key": media_key,
                "tmdb_id": tmdb_id,
                "title": title,
                "year": year,
                "media_type": media_type,
                "tmdb_rating": float(tmdb_rating) if tmdb_rating is not None else None,
                "vote_count": vote_count,
                "score": round(float(score), 4),
                "members": [
                    {
                        "member": m["member"],
                        "score": round(m["score"], 4),
                        "relevance": round(m["relevance"], 4),
                        "penalty": round(m["penalty"], 4),
                        "quality_factor": round(m["quality_factor"], 4),
                        "because": m["because"],
                    }
                    for m in details
                ],
            }
        )
    return results


def recommend(
    usernames: list[str],
    k: int = 20,
    dislike_weight: float = DISLIKE_WEIGHT,
    min_runtime: int = MIN_RUNTIME_MINUTES,
) -> list[dict]:
    """Recommendations for one user, or a group (least-misery) when given several."""
    with get_snowflake_connection() as conn:
        profiles = build_profiles(conn, usernames)
        return score_profiles(
            conn, profiles, k=k, dislike_weight=dislike_weight, min_runtime=min_runtime
        )


def _print(results: list[dict]) -> None:
    group = len(results[0]["members"]) > 1 if results else False
    for r in results:
        year = f" ({r['year']})" if r["year"] else ""
        rating = f"[TMDB {r['tmdb_rating']:.1f}]"
        print(f"{r['rank']:>2}. {r['score']:>6.2f}  {r['title']}{year}   {rating}")
        if group:
            for m in r["members"]:
                because = ", ".join(m["because"])
                print(f"        {m['member']:<14} {m['score']:>6.2f}   because: {because}")
        else:
            m = r["members"][0]
            flags = []
            if m["quality_factor"] < 0.995:
                flags.append(f"quality x{m['quality_factor']:.2f}")
            if m["penalty"] > 0:
                flags.append(f"dislike-penalty {m['penalty']:.2f}")
            extra = f"   ({', '.join(flags)})" if flags else ""
            print(f"        because: {', '.join(m['because'])}{extra}")


def main():
    parser = argparse.ArgumentParser(description="Recommend unwatched titles from a diary.")
    parser.add_argument(
        "usernames", nargs="+", help="Letterboxd username(s); more than one makes a group"
    )
    parser.add_argument("--k", type=int, default=20, help="how many titles to return")
    parser.add_argument(
        "--dislike-weight",
        type=float,
        default=DISLIKE_WEIGHT,
        help="strength of the penalty for resembling a disliked film (0 disables it)",
    )
    parser.add_argument(
        "--min-runtime",
        type=int,
        default=MIN_RUNTIME_MINUTES,
        help="skip candidates shorter than this many minutes (0 allows shorts and specials)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    # titles carry non-ASCII; the Windows console defaults to cp1252 and would raise mid-list
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        results = recommend(
            args.usernames,
            k=args.k,
            dislike_weight=args.dislike_weight,
            min_runtime=args.min_runtime,
        )
    except RuntimeError as exc:  # expected user errors (unknown user, no liked films), not bugs
        raise SystemExit(f"error: {exc}") from None
    if not results:
        print("No recommendations. Is the catalog embedded?")
        raise SystemExit(1)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    who = " + ".join(args.usernames)
    mode = "group, least-misery" if len(args.usernames) > 1 else "single user"
    print(f"Top {len(results)} for {who} ({mode})\n")
    _print(results)


if __name__ == "__main__":
    main()
