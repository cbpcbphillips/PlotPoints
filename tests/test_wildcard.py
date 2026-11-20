"""The comfort-zone pick: a good film from a genre the person rarely rates that still scores."""

import pytest
from conftest import idx, make_snapshot
from fastapi.testclient import TestClient

import scoring
from api.app import create_app
from api.inbox import Inbox
from api.tmdb_lookup import TmdbLookup


def genred():
    """Cluster A is Drama, B is Comedy, C is Western; C films are well rated and well known."""
    snap = make_snapshot()
    for i in range(60):
        snap.genres[i] = [["Drama"], ["Comedy"], ["Western"]][i // 20]
    for i in range(40, 60):
        snap.rating[i] = 8.0
        snap.votes[i] = 5000
    return snap


def scored(snap, liked=("A00", "A01", "A02", "B00", "B01")):
    prof = {"me": [(idx(snap, t), 2.0) for t in liked]}
    return scoring.score_candidates(snap, prof, reasons=prof)


def test_comfort_shares_reflect_what_the_person_likes():
    snap = genred()
    share, counts, total = scoring.comfort_shares(scored(snap))
    assert total == 5
    assert share["Drama"] == pytest.approx(0.6) and share["Comedy"] == pytest.approx(0.4)
    assert "Western" not in share
    assert counts == {"Drama": 3, "Comedy": 2}


def test_wildcard_comes_from_a_genre_the_person_never_rates():
    snap = genred()
    pick = scoring.wildcard_pick(scored(snap), signal_top=1.0)
    assert pick is not None
    assert snap.genres[pick["index"]] == ["Western"]
    assert pick["outside"]["genre"] == "Western"
    assert pick["outside"]["liked_in_genre"] == 0
    assert pick["outside"]["liked_total"] == 5
    assert 1 <= pick["outside"]["top_percent"] <= 100


def test_wildcard_needs_a_good_well_known_film():
    snap = genred()
    for i in range(40, 60):
        snap.rating[i] = 5.0  # poorly rated: not worth recommending as a stretch
    assert scoring.wildcard_pick(scored(snap), signal_top=1.0) is None
    snap = genred()
    for i in range(40, 60):
        snap.votes[i] = 50  # barely seen: the rating means little
    assert scoring.wildcard_pick(scored(snap), signal_top=1.0) is None


def test_wildcard_needs_a_real_signal_from_the_profile():
    snap = genred()
    # asking for the very top of the candidate list: nothing outside the niche is that close
    assert scoring.wildcard_pick(scored(snap), signal_top=0.0) is None


def test_wildcard_skips_excluded_films():
    snap = genred()
    sc = scored(snap)
    first = scoring.wildcard_pick(sc, signal_top=1.0)
    second = scoring.wildcard_pick(sc, signal_top=1.0, exclude=[first["index"]])
    assert second is not None and second["index"] != first["index"]


def test_group_comfort_zone_is_the_whole_group_not_one_person():
    snap = genred()
    prof = {
        "a": [(idx(snap, "A00"), 2.0), (idx(snap, "A01"), 2.0)],
        "b": [(idx(snap, "C00"), 2.0), (idx(snap, "C01"), 2.0)],  # b already likes Westerns
    }
    sc = scoring.score_candidates(snap, prof, reasons=prof)
    share, _, total = scoring.comfort_shares(sc)
    assert total == 4 and share["Western"] == pytest.approx(0.5)  # half of each person's mass
    pick = scoring.wildcard_pick(sc, signal_top=1.0)
    assert pick is None or snap.genres[pick["index"]] != ["Western"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    original = scoring.wildcard_pick
    monkeypatch.setattr(
        scoring, "wildcard_pick", lambda sc, **kw: original(sc, signal_top=1.0, **kw)
    )
    snap = genred()
    with TestClient(create_app(snap=snap, inbox=Inbox(), lookup=TmdbLookup(api_key=""))) as c:
        c.snap = snap
        yield c


def body(**extra):
    films = [{"tmdb_id": 1000 + i, "rating": 4.5} for i in (0, 1, 2, 20, 21)]
    return {"members": [{"name": "me", "films": films}], **extra}


def test_recommend_returns_a_wildcard_on_the_first_page_only(client):
    first = client.post("/recommend", json=body(bundle=True, limit=10)).json()
    w = first["wildcard"]
    assert w is not None and w["outside"]["genre"] == "Western"
    assert w["tmdb_id"] != first["results"][0]["tmdb_id"]
    later = client.post("/recommend", json=body(bundle=True, limit=10, offset=10)).json()
    assert later["wildcard"] is None
    assert client.post("/recommend", json=body(limit=10)).json()["wildcard"] is None


def test_branch_out_does_not_repeat_the_wildcard(client):
    r = client.post("/recommend", json=body(bundle=True, limit=10, branch_out=10)).json()
    assert r["wildcard"]["tmdb_id"] not in {x["tmdb_id"] for x in r["branch_out"]}
