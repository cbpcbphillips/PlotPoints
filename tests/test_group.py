"""Group lists by turns: each person offers a film they like that the others can live with."""

import numpy as np
import pytest
from conftest import idx, make_snapshot
from fastapi.testclient import TestClient

import scoring
from api.app import create_app
from api.inbox import Inbox
from api.tmdb_lookup import TmdbLookup


def scored(snap, members):
    profs = {n: [(idx(snap, t), 2.0) for t in liked] for n, liked in members.items()}
    return scoring.score_candidates(snap, profs, reasons=profs), profs


# two people whose tastes overlap in cluster A and differ elsewhere
TASTES = {
    "ann": ["A00", "A01", "A02", "B00", "B01"],
    "bob": ["A03", "A04", "A05", "C00", "C01", "C02"],
}


def test_picks_are_never_films_anyone_has_seen():
    snap = make_snapshot()
    sc, profs = scored(snap, TASTES)
    watched = {i for films in profs.values() for i, _ in films}
    picks = scoring.group_rotation(sc, 30)
    assert picks and not watched & {r["index"] for r in picks}


def test_members_take_turns():
    snap = make_snapshot()
    sc, _ = scored(snap, {"ann": ["A00", "A01", "A02", "A06"], "bob": ["A03", "A04", "A05", "A07"]})
    who = [r["picked_for"] for r in scoring.group_rotation(sc, 8, fits=(0.5,))]
    assert set(who) == {"ann", "bob"}
    assert all(a != b for a, b in zip(who, who[1:], strict=False))  # strictly alternating


def test_the_thinnest_history_goes_first():
    snap = make_snapshot()
    sc, _ = scored(snap, {"ann": ["A00", "A01", "A02", "A06", "B00"], "bob": ["A03", "A04"]})
    assert scoring.group_rotation(sc, 2)[0]["picked_for"] == "bob"


def test_every_member_gets_a_fit_for_every_pick():
    snap = make_snapshot()
    sc, _ = scored(snap, TASTES)
    for r in scoring.group_rotation(sc, 10):
        assert [f["member"] for f in r["fit"]] == ["ann", "bob"]
        assert all(1 <= f["top_percent"] <= 100 for f in r["fit"])


def test_picks_sit_inside_the_widest_slice_when_there_is_room():
    snap = make_snapshot()
    sc, _ = scored(snap, {"ann": ["A00", "A01", "A02", "A06"], "bob": ["A03", "A04", "A05", "A07"]})
    picks = scoring.group_rotation(sc, 6, fits=(0.3,))
    assert picks and all(f["top_percent"] <= 30 for r in picks for f in r["fit"])


def test_two_identical_people_get_the_single_person_ranking():
    snap = make_snapshot()
    liked = ["A00", "A01", "A02", "B00"]
    sc, profs = scored(snap, {"ann": liked, "bob": liked})
    solo = scoring.rank(snap, {"me": profs["ann"]}, limit=10, reasons={"me": profs["ann"]})
    got = [r["index"] for r in scoring.group_rotation(sc, 10, fits=(1.0,))]
    assert got == [r["index"] for r in solo]


def test_one_film_per_franchise():
    snap = make_snapshot()
    for i in range(4, 12):
        snap.franchise[i] = "Series"
    sc, _ = scored(snap, TASTES)
    picks = scoring.group_rotation(sc, 30)
    assert sum(1 for r in picks if snap.franchise[r["index"]] == "Series") <= 1


def test_it_widens_the_slice_instead_of_running_dry():
    snap = make_snapshot()
    sc, _ = scored(snap, TASTES)
    # nothing is in the top 0.01% of everyone's ranking, so every turn has to widen
    assert len(scoring.group_rotation(sc, 12, fits=(0.0001, 0.3))) == 12
    assert len(scoring.group_rotation(sc, 12, fits=(0.0001,))) == 12  # best worst-case fallback


def test_a_longer_list_starts_with_the_shorter_one():
    snap = make_snapshot()
    sc, _ = scored(snap, TASTES)
    short = [r["index"] for r in scoring.group_rotation(sc, 5)]
    long = [r["index"] for r in scoring.group_rotation(sc, 12)]
    assert long[:5] == short


def test_asking_for_more_than_exists_returns_what_there_is():
    snap = make_snapshot()
    sc, _ = scored(snap, TASTES)
    picks = scoring.group_rotation(sc, 10_000)
    assert 0 < len(picks) <= len(sc.cand)
    assert len({r["index"] for r in picks}) == len(picks)


def test_nothing_to_pick_from_is_an_empty_list():
    snap = make_snapshot()
    sc, _ = scored(snap, TASTES)
    assert scoring.group_rotation(sc, 0) == []
    assert np.isfinite(sc.group).all()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    snap = make_snapshot()
    with TestClient(create_app(snap=snap, inbox=Inbox(), lookup=TmdbLookup(api_key=""))) as c:
        c.snap = snap
        yield c


def members_body(**extra):
    def films(ids):
        return [{"tmdb_id": 1000 + i, "rating": 4.5} for i in ids]

    return {
        "members": [
            {"name": "ann", "films": films([0, 1, 2, 20, 21])},
            {"name": "bob", "films": films([3, 4, 5, 40, 41, 42])},
        ],
        **extra,
    }


def test_a_group_request_gets_the_turn_taking_list(client):
    r = client.post("/recommend", json=members_body(limit=10)).json()
    assert r["group"] is True and len(r["results"]) == 10
    first = r["results"][0]
    assert first["picked_for"] in {"ann", "bob"}
    assert {f["member"] for f in first["fit"]} == {"ann", "bob"}
    assert {1000, 1001, 1002, 1003, 1004, 1005}.isdisjoint(x["tmdb_id"] for x in r["results"])


def test_group_paging_does_not_repeat_or_skip(client):
    first = client.post("/recommend", json=members_body(limit=5)).json()
    second = client.post("/recommend", json=members_body(limit=5, offset=5)).json()
    both = client.post("/recommend", json=members_body(limit=10)).json()
    ids = [x["tmdb_id"] for x in first["results"] + second["results"]]
    assert ids == [x["tmdb_id"] for x in both["results"]]
    assert first["has_more"] is True


def test_one_person_is_unchanged(client):
    body = members_body(limit=5)
    body["members"] = body["members"][:1]
    r = client.post("/recommend", json=body).json()
    assert r["group"] is False and "picked_for" not in r["results"][0]
