"""FastAPI app: recommendations from an in-memory snapshot. No Snowflake in the request path.

Stateless by design: there are no accounts or sessions. The browser sends a person's films with each
request and this process computes an answer and forgets it. The only thing it ever writes is a
consented import (and a deletion request) into the S3 inbox, with a write-only credential.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

import scoring
import snapshot
from api.inbox import Inbox
from api.letterboxd import LetterboxdError, collapse, fetch_feed
from api.matching import match_rows
from api.profile import profile_stats
from api.schemas import (
    ConsentRequest,
    DeleteRequest,
    LetterboxdRequest,
    MatchRequest,
    Member,
    ProfileRequest,
    RecommendRequest,
)
from api.tmdb_lookup import TmdbLookup

log = logging.getLogger("plotpoints.api")
log.setLevel(logging.INFO)
if not logging.getLogger().handlers and not log.handlers:
    # uvicorn configures only its own loggers, so without this the access log would go nowhere
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(_handler)

MAX_POOL = 400  # offset + limit; deeper than this is not a recommendation list any more
FRANCHISE_POOL = 300  # how far down the ranking franchises are gathered from
FRANCHISES_SHOWN = 5  # the page shows a person's top five series, not every one
FILMS_PER_FRANCHISE = 8  # unseen films kept per series: its best plus the next seven
LOOKUP_CAP = 200  # TMDB lookups per import; the rest are reported as unmatched
WANTED_CAP = 200  # missing-title ids written to the inbox per request
INFLUENCE_PICKS = 20  # the top picks the "because you enjoyed" row is measured against
MAX_PROVIDERS_LISTED = 60
MAX_SIMILAR = 24  # "more like this" is a row, not a list
CLOSEST_SHOWN = 5  # liked films named on a film page as closest to it
BUNDLE_LISTED = 8  # films of a bundled series named in the response, in rank order


class RateLimiter:
    """Sliding-window limit per (client, bucket). In-memory, so per instance: a brake against a
    script hammering Letterboxd through us, not a security boundary."""

    def __init__(self) -> None:
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)

    def check(self, client: str, bucket: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        q = self.hits[(client, bucket)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Too many requests. Wait a minute and try again.")
        q.append(now)


def snapshot_dir() -> Path:
    explicit = os.environ.get("PLOTPOINTS_SNAPSHOT_DIR")
    if explicit:
        return Path(explicit)
    root = Path(os.environ.get("PLOTPOINTS_DATA_DIR", "data")) / "snapshots"
    return root / (root / "LATEST").read_text(encoding="utf-8").strip()


def create_app(
    snap: snapshot.Snapshot | None = None,
    inbox: Inbox | None = None,
    lookup: TmdbLookup | None = None,
) -> FastAPI:
    limiter = RateLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.snap = snap or snapshot.load(snapshot_dir())
        app.state.inbox = inbox or Inbox()
        app.state.lookup = lookup or TmdbLookup()
        s: snapshot.Snapshot = app.state.snap
        log.info("snapshot %s loaded: %d titles, model %s", s.version, len(s), s.embedding_model)
        counts: dict[int, int] = defaultdict(int)
        for ps in s.providers:
            for p in ps:
                counts[p] += 1
        app.state.provider_listing = [
            {"name": s.provider_names[p], "titles": counts[p]}
            for p in sorted(counts, key=lambda p: -counts[p])[:MAX_PROVIDERS_LISTED]
        ]
        yield

    app = FastAPI(title="PlotPoints API", version="1.0.0", lifespan=lifespan)
    origins = [
        o.strip()
        for o in os.environ.get("PLOTPOINTS_CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        # Privacy: method, route TEMPLATE (never the raw path or query), status and time only.
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            log.info(
                "%s %s %s %dms",
                request.method,
                getattr(route, "path", "(no route)"),
                status,
                (time.perf_counter() - started) * 1000,
            )

    def client_of(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for")
        return (
            fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
        )

    # ---------------------------------------------------------------- helpers

    def to_profiles(s: snapshot.Snapshot, req: RecommendRequest) -> tuple[scoring.Profile, dict]:
        profiles: scoring.Profile = {}
        unmatched = 0
        for m in req.members:
            if m.name in profiles:
                raise HTTPException(422, f"Two members are both called {m.name!r}.")
            films, seen = [], set()
            for f in m.films:
                i = s.by_tmdb.get((f.media_type, f.tmdb_id))
                if i is None:
                    unmatched += 1  # not in the catalog: nothing to compare it with
                    continue
                if i in seen:
                    continue
                seen.add(i)
                films.append((i, scoring.weight_for(f.rating, f.rewatch)))
            if not any(w is not None and w > 0 for _, w in films):
                raise HTTPException(
                    422,
                    f"{m.name} has no rated-above-3-star films in the catalog, so there is "
                    "nothing to compare. Rate a few films you liked on Letterboxd.",
                )
            # liked films from one franchise share a vote (scoring.DAMPEN_POWER)
            damped = scoring.dampen_franchise_seeds(
                [w for _, w in films], [s.franchise[i] for i, _ in films]
            )
            profiles[m.name] = [(i, w) for (i, _), w in zip(films, damped, strict=True)]
        return profiles, {"unmatched_films": unmatched}

    def novelty_of(r: dict) -> int | None:
        because = r["members"][0]["because"] if r["members"] else []
        return 100 - round(because[0]["cosine"] * 100) if because else None

    def present(s: snapshot.Snapshot, r: dict) -> dict:
        i = r["index"]
        return {
            "rank": r["rank"],
            "tmdb_id": r["tmdb_id"],
            "media_key": r["media_key"],
            "title": r["title"],
            "year": r["year"],
            "match": round(r["match"] * 100),
            # the ranking score (hubness-corrected, roughly 2-4 at the top); NOT a percentage
            "score": round(r["score"], 1),
            # Stand-in until roadmap decision 5d settles a definition: how far the pick sits from
            # the film that explains it best. Display only; it never enters the ranking.
            "novelty": novelty_of(r),
            "tmdb_rating": None if np.isnan(s.rating[i]) else round(float(s.rating[i]), 1),
            "runtime": None if np.isnan(s.runtime[i]) else int(s.runtime[i]),
            "poster_path": s.poster[i],
            "backdrop_path": s.backdrop[i],
            "franchise": s.franchise[i],
            "genres": s.genres[i],
            "providers": [s.provider_names[p] for p in s.providers[i]],
            "members": [
                {
                    "member": m["member"],
                    "match": round(m["match"] * 100),
                    "because": [
                        {
                            "title": b["title"],
                            "tmdb_id": b["tmdb_id"],
                            "match": round(b["cosine"] * 100),
                        }
                        for b in m["because"]
                    ],
                }
                for m in r["members"]
            ],
        }

    def bundle_by_franchise(s: snapshot.Snapshot, ranked: list[dict]) -> list[dict]:
        """Fold each franchise into its best-ranked film. Standalone films stay as they are.

        Order follows the best film of each franchise, so the list is the ranking with the
        repeat appearances of a series removed. Each kept row gets `_rest`: the rest of its series,
        in rank order, for the "+N more" note.
        """
        entries: list[dict] = []
        by_franchise: dict[str, dict] = {}
        for r in ranked:
            name = s.franchise[r["index"]]
            if name is None:
                entries.append(r)
            elif name not in by_franchise:
                by_franchise[name] = {**r, "_rest": []}
                entries.append(by_franchise[name])
            else:
                by_franchise[name]["_rest"].append(r)
        return entries

    def bundle_info(s: snapshot.Snapshot, r: dict) -> dict:
        rest = r.get("_rest") or []
        if not rest:
            return {"bundle": None}
        return {
            "bundle": {
                "franchise": s.franchise[r["index"]],
                "more": len(rest),
                "films": [
                    {"tmdb_id": x["tmdb_id"], "title": x["title"], "year": x["year"]}
                    for x in rest[:BUNDLE_LISTED]
                ],
            }
        }

    def enjoyed_films(s: snapshot.Snapshot, profiles, results: list[dict], films) -> list[dict]:
        """The liked films that best explain the top picks, ranked by weighted similarity."""
        ratings = {f.tmdb_id: f.rating for f in films}
        top = scoring.influence(s, profiles, [r["index"] for r in results[:INFLUENCE_PICKS]])
        return [
            {
                "tmdb_id": e["tmdb_id"],
                "media_key": e["media_key"],
                "title": e["title"],
                "year": int(s.year[e["index"]]) or None,
                "poster_path": s.poster[e["index"]],
                "rating": ratings.get(e["tmdb_id"]),
                "avg_match": round(e["avg_cosine"] * 100),
            }
            for e in top
        ]

    def seen_in_franchise(s: snapshot.Snapshot, name: str, req: RecommendRequest) -> list[dict]:
        """Films of this series the first member has already seen, with their own rating."""
        out = []
        for f in req.members[0].films:
            i = s.by_tmdb.get((f.media_type, f.tmdb_id))
            if i is None or s.franchise[i] != name:
                continue
            out.append(
                {
                    "tmdb_id": f.tmdb_id,
                    "media_key": s.media_key[i],
                    "title": s.title[i],
                    "year": int(s.year[i]) or None,
                    "rating": f.rating,
                    "tmdb_rating": None if np.isnan(s.rating[i]) else round(float(s.rating[i]), 1),
                    "poster_path": s.poster[i],
                }
            )
        out.sort(key=lambda x: (x["year"] or 0, x["title"]))
        return out

    def allow_mask(s: snapshot.Snapshot, providers: list[str]):
        if not providers:
            return None
        unknown = [p for p in providers if p not in s.provider_names]
        if unknown:
            raise HTTPException(422, f"Unknown provider(s): {unknown}")
        return s.provider_mask(providers)

    # -------------------------------------------------------------- endpoints

    @app.get("/health")
    def health(request: Request):
        return {"status": "ok", "snapshot": request.app.state.snap.version}

    @app.get("/meta")
    def meta(request: Request):
        s = request.app.state.snap
        return {
            "snapshot": s.version,
            "titles": len(s),
            "embedding_model": s.embedding_model,
            "providers_as_of": s.providers_as_of,
            "providers": request.app.state.provider_listing,
        }

    def film_fields(s: snapshot.Snapshot, i: int) -> dict:
        """What every film card shows, independent of any taste profile."""
        return {
            "tmdb_id": int(s.tmdb_id[i]),
            "media_key": s.media_key[i],
            "title": s.title[i],
            "year": int(s.year[i]) or None,
            "tmdb_rating": None if np.isnan(s.rating[i]) else round(float(s.rating[i]), 1),
            "runtime": None if np.isnan(s.runtime[i]) else int(s.runtime[i]),
            "poster_path": s.poster[i],
            "backdrop_path": s.backdrop[i],
            "franchise": s.franchise[i],
            "genres": s.genres[i],
            "providers": [s.provider_names[p] for p in s.providers[i]],
        }

    def movie_index(s: snapshot.Snapshot, tmdb_id: int) -> int:
        i = s.by_tmdb.get(("movie", tmdb_id))
        if i is None:
            raise HTTPException(404, "That film is not in the catalog.")
        return i

    @app.get("/film/{tmdb_id}")
    def film(tmdb_id: int, request: Request):
        s = request.app.state.snap
        i = movie_index(s, tmdb_id)
        return {
            **film_fields(s, i),
            "original_title": s.original_title[i],
            "tagline": s.tagline[i],
            "overview": s.overview[i],
            "directors": s.directors[i],
            "cast": [{"name": n, "character": c} for n, c in s.cast[i]],
            "providers_as_of": s.providers_as_of,
        }

    @app.get("/film/{tmdb_id}/similar")
    def film_similar(tmdb_id: int, request: Request, limit: int = 12):
        s = request.app.state.snap
        i = movie_index(s, tmdb_id)
        found = scoring.similar_to(s, i, n=max(1, min(limit, MAX_SIMILAR)))
        return {
            "films": [
                {**film_fields(s, r["index"]), "match": round(r["cosine"] * 100)} for r in found
            ]
        }

    @app.post("/film/{tmdb_id}/for-me")
    def film_for_me(tmdb_id: int, body: ProfileRequest, request: Request):
        """How one film sits against a person's own films: the closest ones they liked.

        Like /recommend, nothing is stored; the browser sends the films it already holds. A person
        with nothing rated above 3 stars gets the same 422 as /recommend, which the page treats as
        "nothing to show".
        """
        s = request.app.state.snap
        i = movie_index(s, tmdb_id)
        req = RecommendRequest(members=[Member(name="me", films=body.films)])
        profiles, _ = to_profiles(s, req)
        closest = scoring.closest_rated(s, profiles, i, n=CLOSEST_SHOWN)
        mine = next((f for f in body.films if f.tmdb_id == tmdb_id), None)
        return {
            "seen": mine is not None,
            "rating": None if mine is None else mine.rating,
            # the same number the recommendations show: mean cosine over the three closest
            "match": round(float(np.mean([c["cosine"] for c in closest[:3]])) * 100)
            if closest
            else None,
            "closest": [
                {
                    "tmdb_id": c["tmdb_id"],
                    "title": c["title"],
                    "year": int(s.year[c["index"]]) or None,
                    "poster_path": s.poster[c["index"]],
                    "match": round(c["cosine"] * 100),
                }
                for c in closest
            ],
        }

    @app.post("/import/letterboxd")
    def import_letterboxd(body: LetterboxdRequest, request: Request):
        limiter.check(client_of(request), "rss", limit=10)
        s = request.app.state.snap
        try:
            entries = fetch_feed(body.username)
        except LetterboxdError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        films = collapse(entries)
        for f in films:
            f["in_catalog"] = (f["media_type"], f["tmdb_id"]) in s.by_tmdb
        record_wanted(
            request, [f for f in films if not f["in_catalog"] and f["media_type"] == "movie"]
        )
        return {
            "username": body.username,
            "entries": len(entries),
            "films": films,
            "note": "Letterboxd only returns the latest ~50 entries; an export has everything.",
        }

    def record_wanted(request: Request, films: list[dict]) -> None:
        """Note films the catalog lacks so the next pipeline run can enrich them as taste signal.

        Only (media_type, tmdb_id) pairs are written: no user, rating or username, so this needs
        no consent. Best effort: a rate limit or a storage error never fails the import.
        """
        ids = {(f["media_type"], int(f["tmdb_id"])) for f in films if f.get("tmdb_id")}
        if not ids:
            return
        try:
            limiter.check(client_of(request), "wanted", limit=20)
            request.app.state.inbox.store_wanted(sorted(ids)[:WANTED_CAP])
        except HTTPException:
            log.info("wanted-title write skipped: rate limited (%d titles)", len(ids))
        except Exception as exc:  # noqa: BLE001 - deliberately best effort
            # the exception CLASS only: a message could carry a bucket key or path
            log.warning(
                "wanted-title write failed (%s), %d titles dropped", type(exc).__name__, len(ids)
            )

    @app.post("/match")
    def match(body: MatchRequest, request: Request):
        s = request.app.state.snap
        res = match_rows(s, [r.model_dump() for r in body.rows])
        films, rest = res["films"], res["unmatched"]
        have = {f["tmdb_id"] for f in films}
        missing, tv, still = [], [], []
        lookup: TmdbLookup = request.app.state.lookup
        skipped = 0
        if lookup.enabled and rest:
            limiter.check(client_of(request), "lookup", limit=20)
            todo, later = rest[:LOOKUP_CAP], rest[LOOKUP_CAP:]
            skipped = len(later)
            for row, hit in zip(todo, lookup.resolve(todo), strict=True):
                if hit["kind"] == "tv":
                    tv.append({"title": row["title"], "year": row["year"]})
                elif hit["kind"] != "movie":
                    still.append(row)
                elif (i := s.by_tmdb.get(("movie", hit["tmdb_id"]))) is not None:
                    if hit["tmdb_id"] not in have:  # TMDB knew it under another title or year
                        have.add(hit["tmdb_id"])
                        films.append(
                            {
                                "tmdb_id": hit["tmdb_id"],
                                "media_type": "movie",
                                "title": s.title[i],
                                "year": int(s.year[i]) or None,
                                "rating": row["rating"],
                                "rewatch": row["rewatch"],
                                "ambiguous": False,
                                "method": "tmdb",
                            }
                        )
                elif hit["tmdb_id"] not in have:  # a real film the catalog does not hold yet
                    have.add(hit["tmdb_id"])
                    missing.append(
                        {
                            "tmdb_id": hit["tmdb_id"],
                            "media_type": "movie",
                            "title": row["title"],
                            "year": row["year"],
                            "tmdb_title": hit["title"],
                            "tmdb_year": hit["year"],
                            "votes": hit["votes"],
                            "rating": row["rating"],
                            "rewatch": row["rewatch"],
                        }
                    )
            rest = still + later
        record_wanted(request, missing)
        # counts only: never titles, ratings or anything that identifies the person
        log.info(
            "match: %d rows -> %d matched, %d missing, %d tv, %d unmatched, %d ambiguous, "
            "%d lookups skipped",
            len(body.rows),
            len(films),
            len(missing),
            len(tv),
            len(rest),
            res["ambiguous"],
            skipped,
        )
        return {
            "films": films,
            "missing": missing,
            "tv": tv,
            "unmatched": [{"title": r["title"], "year": r["year"]} for r in rest],
            "ambiguous": res["ambiguous"],
            "lookups_skipped": skipped,
        }

    @app.post("/recommend")
    def recommend(body: RecommendRequest, request: Request):
        s = request.app.state.snap
        if body.offset + body.limit > MAX_POOL:
            raise HTTPException(422, f"offset + limit may not exceed {MAX_POOL}.")
        profiles, info = to_profiles(s, body)
        allow = allow_mask(s, body.providers)
        if body.bundle:
            # Rank the whole pool, then fold each franchise into its best-ranked film; paging is
            # over the folded entries. The ranking itself is untouched.
            pool = scoring.rank(s, profiles, limit=MAX_POOL, allow=allow)
            entries = bundle_by_franchise(s, pool)
            results = entries[: body.offset + body.limit]
            has_more = len(entries) > body.offset + body.limit
            page = [present(s, r) | bundle_info(s, r) for r in results[body.offset :]]
        else:
            pool = None
            results = scoring.rank(s, profiles, limit=body.offset + body.limit, allow=allow)
            has_more = len(results) == body.offset + body.limit
            page = [present(s, r) for r in results[body.offset :]]
        if allow is not None:
            # Where each title sits in the UNFILTERED ranking, so "best on Netflix" can say it is
            # overall #22. Filtering a finished list instead would be dishonest, which is why the
            # filter lives inside scoring.rank (see roadmap open decision 7).
            overall = scoring.rank(s, profiles, limit=MAX_POOL)
            by_index = {r["index"]: r["rank"] for r in overall}
            for item, r in zip(page, results[body.offset :], strict=True):
                item["overall_rank"] = by_index.get(r["index"])
            info["pool_size"] = len(overall)
            info["pool_matches"] = sum(1 for r in overall if allow[r["index"]])
        enjoyed = None
        if body.offset == 0 and not body.providers and len(profiles) == 1:
            enjoyed = enjoyed_films(s, profiles, results, body.members[0].films)
        branch_out = None
        if body.branch_out and body.offset == 0 and not body.providers and pool is not None:
            # varied from the page above it: nothing already shown, none of its franchises
            shown = [r["index"] for r in results]
            branch_out = [
                present(s, r) for r in scoring.diversify(s, pool, body.branch_out, shown=shown)
            ]
        return {
            "snapshot": s.version,
            "group": len(profiles) > 1,
            "providers": body.providers,
            "results": page,
            "enjoyed": enjoyed,
            "branch_out": branch_out,
            "has_more": has_more,
            **info,
        }

    @app.post("/franchises")
    def franchises(body: RecommendRequest, request: Request):
        s = request.app.state.snap
        profiles, info = to_profiles(s, body)
        results = scoring.rank(
            s, profiles, limit=FRANCHISE_POOL, allow=allow_mask(s, body.providers)
        )
        groups: dict[str, list[dict]] = {}
        for r in results:
            name = s.franchise[r["index"]]
            if name:
                groups.setdefault(name, []).append(present(s, r))
        out = [
            {
                "franchise": name,
                "best": rs[0],
                "others": rs[1:FILMS_PER_FRANCHISE],
                "count": len(rs),
                "seen": seen_in_franchise(s, name, body),
            }
            for name, rs in groups.items()
            if len(rs) >= 2  # a franchise of one is just a recommendation
        ]
        out.sort(key=lambda g: g["best"]["rank"])
        return {"snapshot": s.version, "franchises": out[:FRANCHISES_SHOWN], **info}

    @app.post("/profile")
    def profile(body: ProfileRequest, request: Request):
        return profile_stats(request.app.state.snap, [f.model_dump() for f in body.films])

    @app.post("/consent")
    def consent(body: ConsentRequest, request: Request):
        limiter.check(client_of(request), "consent", limit=5)
        # every film is kept, catalog or not: a title we don't have yet is how the catalog grows
        films = [f.model_dump() for f in body.films]
        if not films:
            raise HTTPException(422, "Nothing to store.")
        done = request.app.state.inbox.store_import(
            source=body.source, username=body.username, films=films
        )
        return {
            "stored": len(films),
            "token": done["token"],
            "note": "Keep this token. It is the only way to delete your data; it is not stored.",
        }

    @app.post("/delete")
    def delete(body: DeleteRequest, request: Request):
        limiter.check(client_of(request), "delete", limit=5)
        request.app.state.inbox.request_deletion(body.token)
        return {"requested": True, "note": "Removed the next time the pipeline runs."}

    return app
