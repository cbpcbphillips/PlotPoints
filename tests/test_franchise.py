"""Franchise handling: seed dampening, the "branch out" re-rank, and bundling in /recommend."""

import pytest
from conftest import idx, make_snapshot
from fastapi.testclient import TestClient

import scoring
from api.app import create_app
from api.inbox import Inbox
from api.tmdb_lookup import TmdbLookup

# ------------------------------------------------------------ seed dampening


def test_dampen_shares_one_vote_per_franchise():
    out = scoring.dampen_franchise_seeds([2.0, 1.5, 1.0, 2.5], ["Spider-Man"] * 3 + [None])
    assert out[:3] == pytest.approx([2.0 / 3**0.5, 1.5 / 3**0.5, 1.0 / 3**0.5])
    assert out[3] == 2.5  # standalone: untouched


def test_dampen_leaves_singletons_dislikes_unrated_alone():
    weights = [1.5, -1.0, None, 0.0, 2.0]
    franchises = ["Rocky", "Rocky", "Rocky", "Rocky", None]
    # only ONE liked Rocky film, so k = 1 and nothing changes; the others are not liked
    assert scoring.dampen_franchise_seeds(weights, franchises) == weights


def test_dampen_counts_only_liked_films():
    out = scoring.dampen_franchise_seeds([2.0, 1.0, -2.0], ["X", "X", "X"])
    assert out[0] == pytest.approx(2.0 / 2**0.5)
    assert out[2] == -2.0


def test_dampen_power_zero_is_the_old_behaviour():
    w = [2.0, 1.5]
    assert scoring.dampen_franchise_seeds(w, ["X", "X"], power=0.0) == w


def test_dampening_stops_a_franchise_crowding_out_a_single_taste():
    """Three liked films in cluster A vs one in B: undampened, A's films fill the top; dampened,
    B gets in sooner."""
    snap = make_snapshot()
    a = [idx(snap, f"A0{i}") for i in (0, 1, 2)]
    b = idx(snap, "B00")
    for i in a:
        snap.franchise[i] = "Series A"
    raw = [(i, 2.0) for i in a] + [(b, 2.0)]
    franchises = [snap.franchise[i] for i, _ in raw]
    damped = scoring.dampen_franchise_seeds([w for _, w in raw], franchises)

    def first_b_rank(weights):
        prof = {"me": [(i, w) for (i, _), w in zip(raw, weights, strict=True)]}
        ranked = scoring.rank(snap, prof, limit=60)
        return next(r["rank"] for r in ranked if snap.title[r["index"]].startswith("B"))

    assert first_b_rank(damped) <= first_b_rank([w for _, w in raw])


# ------------------------------------------------------------ diversify


def ranked_for_cluster_a(snap):
    prof = {"me": [(idx(snap, "A00"), 2.0), (idx(snap, "A01"), 2.0), (idx(snap, "A02"), 1.5)]}
    return scoring.rank(snap, prof, limit=60)


def test_diversify_with_zero_lambda_keeps_the_ranking():
    snap = make_snapshot()
    ranked = ranked_for_cluster_a(snap)
    got = scoring.diversify(snap, ranked, 8, lam=0.0)
    assert [r["index"] for r in got] == [r["index"] for r in ranked[:8]]


def test_diversify_spreads_across_clusters():
    snap = make_snapshot()
    ranked = ranked_for_cluster_a(snap)
    plain = {snap.title[r["index"]][0] for r in ranked[:10]}
    spread = {snap.title[r["index"]][0] for r in scoring.diversify(snap, ranked, 10, lam=0.7)}
    assert len(spread) > len(plain)


def test_diversify_never_returns_shown_films_or_their_franchises():
    snap = make_snapshot()
    for i in range(5, 9):
        snap.franchise[idx(snap, f"A0{i}")] = "Shown Series"
    ranked = ranked_for_cluster_a(snap)
    shown = [idx(snap, "A05"), idx(snap, "A10")]
    got = scoring.diversify(snap, ranked, 20, shown=shown)
    got_idx = {r["index"] for r in got}
    assert not got_idx & set(shown)
    assert all(snap.franchise[i] != "Shown Series" for i in got_idx)


def test_diversify_caps_each_franchise():
    snap = make_snapshot()
    for i in range(10, 20):
        snap.franchise[idx(snap, f"A{i}")] = "Big Series"
    got = scoring.diversify(snap, ranked_for_cluster_a(snap), 30, max_per_franchise=1)
    assert sum(snap.franchise[r["index"]] == "Big Series" for r in got) <= 1


def test_diversify_edge_cases():
    snap = make_snapshot()
    assert scoring.diversify(snap, [], 5) == []
    assert scoring.diversify(snap, ranked_for_cluster_a(snap), 0) == []


# ------------------------------------------------------------ API bundling


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    snap = make_snapshot()
    for i in range(1, 7):  # A01..A06 are one series
        snap.franchise[idx(snap, f"A0{i}")] = "Series A"
    app = create_app(snap=snap, inbox=Inbox(), lookup=TmdbLookup(api_key=""))
    with TestClient(app) as c:
        c.snap = snap
        yield c


def body(**extra):
    films = [{"tmdb_id": 1000 + i, "rating": 4.5} for i in (0, 20)]  # one A film, one B film
    return {"members": [{"name": "me", "films": films}], **extra}


def body_for(ids, **extra):
    films = [{"tmdb_id": i, "rating": 4.5} for i in ids]
    return {"members": [{"name": "me", "films": films}], **extra}


def test_bundle_folds_a_series_into_one_entry(client):
    r = client.post("/recommend", json=body(bundle=True, limit=30)).json()
    series = [x for x in r["results"] if x["franchise"] == "Series A"]
    assert len(series) == 1
    assert series[0]["bundle"]["more"] >= 1
    assert series[0]["bundle"]["franchise"] == "Series A"
    assert all(x["bundle"] is None for x in r["results"] if x["franchise"] != "Series A")


def test_bundle_is_the_ranking_with_repeat_appearances_removed(client):
    flat = client.post("/recommend", json=body(limit=50)).json()["results"]
    bundled = client.post("/recommend", json=body(bundle=True, limit=50)).json()["results"]
    seen, expect = set(), []
    for x in flat:
        f = x["franchise"]
        if f is None or f not in seen:
            expect.append(x["tmdb_id"])
        if f:
            seen.add(f)
    assert [x["tmdb_id"] for x in bundled][: len(expect)] == expect[: len(bundled)]


def test_bundle_off_is_unchanged(client):
    r = client.post("/recommend", json=body(limit=20)).json()
    assert "bundle" not in r["results"][0]
    assert r["branch_out"] is None


def test_bundled_paging_does_not_repeat_or_lose_entries(client):
    first = client.post("/recommend", json=body(bundle=True, limit=10)).json()
    second = client.post("/recommend", json=body(bundle=True, limit=10, offset=10)).json()
    ids = [x["tmdb_id"] for x in first["results"] + second["results"]]
    assert len(ids) == len(set(ids))
    assert first["has_more"] is True


def test_branch_out_is_disjoint_from_the_first_page(client):
    r = client.post("/recommend", json=body(bundle=True, limit=10, branch_out=8)).json()
    row = r["branch_out"]
    assert row and len(row) <= 8
    shown = {x["tmdb_id"] for x in r["results"]}
    for x in r["results"]:
        if x["bundle"]:
            shown |= {f["tmdb_id"] for f in x["bundle"]["films"]}
    assert not shown & {x["tmdb_id"] for x in row}
    shown_series = {x["franchise"] for x in r["results"] if x["franchise"]}
    assert all(x["franchise"] not in shown_series for x in row)
    series_in_row = [x["franchise"] for x in row if x["franchise"]]
    assert len(series_in_row) == len(set(series_in_row))


def test_branch_out_only_on_the_first_unfiltered_page(client):
    later = client.post(
        "/recommend", json=body(bundle=True, limit=5, offset=5, branch_out=8)
    ).json()
    assert later["branch_out"] is None
    filtered = client.post(
        "/recommend", json=body(bundle=True, limit=5, branch_out=8, providers=["Netflix"])
    ).json()
    assert filtered["branch_out"] is None


def test_api_profile_dampens_a_liked_series(client):
    """Liking three films of one series must not out-vote a single film in another cluster."""
    snap = client.snap
    films = [{"tmdb_id": int(snap.tmdb_id[idx(snap, f"A0{i}")]), "rating": 4.5} for i in (1, 2, 3)]
    films.append({"tmdb_id": int(snap.tmdb_id[idx(snap, "B00")]), "rating": 4.5})
    damped = client.post(
        "/recommend", json={"members": [{"name": "me", "films": films}], "limit": 40}
    ).json()["results"]
    prof = {
        "me": [(snap.by_tmdb[("movie", f["tmdb_id"])], 1.5) for f in films],
    }
    undamped = scoring.rank(snap, prof, limit=40)
    first_b_damped = next(n for n, x in enumerate(damped) if x["title"].startswith("B"))
    first_b_plain = next(
        n for n, r in enumerate(undamped) if snap.title[r["index"]].startswith("B")
    )
    assert first_b_damped <= first_b_plain


# ------------------------------------------------------------ reasons under dampening


def test_reasons_name_the_series_you_rated_not_a_one_off_favourite():
    """Spider-Man regression: damped weights let a standalone 5-star out-vote series seeds in the
    "because" notes. Reasons use the undamped weights; scores are identical either way."""
    snap = make_snapshot()
    series = [idx(snap, f"A0{i}") for i in (0, 1, 2)]
    for i in series:
        snap.franchise[i] = "Series A"
    solo = idx(snap, "A13")
    raw = [(i, 2.0) for i in series] + [(solo, 2.0)]
    damped = scoring.dampen_franchise_seeds(
        [w for _, w in raw], [snap.franchise[i] for i, _ in raw]
    )
    prof = {"me": [(i, w) for (i, _), w in zip(raw, damped, strict=True)]}

    old = scoring.rank(snap, prof, limit=60)
    new = scoring.rank(snap, prof, limit=60, reasons={"me": raw})
    assert [r["index"] for r in old] == [r["index"] for r in new]
    assert [r["score"] for r in old] == pytest.approx([r["score"] for r in new])

    names = {snap.title[i] for i in series}
    full = lost = 0
    for o, n in zip(old, new, strict=True):
        if not snap.title[n["index"]].startswith("A"):
            continue
        before = {b["title"] for b in o["members"][0]["because"]}
        after = {b["title"] for b in n["members"][0]["because"]}
        full += names <= after
        lost += len(before & names) < 3 and names <= after
    assert full and lost  # the old reasons dropped a series film that the new ones keep


def test_recommend_reports_how_much_taste_there_is(client):
    films = [
        {"tmdb_id": 1000, "rating": 5},
        {"tmdb_id": 1001, "rating": 4},
        {"tmdb_id": 1020, "rating": 3},  # neutral: rated, not liked
        {"tmdb_id": 1021, "rating": 1.5},
        {"tmdb_id": 1040},  # seen, unrated
    ]
    r = client.post(
        "/recommend", json={"members": [{"name": "me", "films": films}], "limit": 5}
    ).json()
    assert r["liked_films"] == 2
    assert r["rated_films"] == 4


def test_group_taste_count_is_the_thinnest_member(client):
    members = [
        {"name": "a", "films": [{"tmdb_id": 1000 + i, "rating": 4.5} for i in range(6)]},
        {"name": "b", "films": [{"tmdb_id": 1020, "rating": 4.5}]},
    ]
    r = client.post("/recommend", json={"members": members, "limit": 5}).json()
    assert r["liked_films"] == 1
