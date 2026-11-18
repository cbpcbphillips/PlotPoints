"""The HTTP layer, against the synthetic snapshot. No network: Letterboxd is stubbed."""

import json

import pytest
from conftest import make_snapshot
from fastapi.testclient import TestClient

from api import letterboxd
from api.app import create_app
from api.inbox import Inbox, token_hash


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    with TestClient(create_app(snap=make_snapshot(), inbox=Inbox())) as c:
        yield c


def films(*ids, rating=4.5):
    return [{"tmdb_id": i, "rating": rating} for i in ids]


def body(*ids, **extra):
    return {"members": [{"name": "me", "films": films(*ids)}], **extra}


def test_health_and_meta(client):
    assert client.get("/health").json()["status"] == "ok"
    meta = client.get("/meta").json()
    assert meta["titles"] == 60
    assert {p["name"] for p in meta["providers"]} == {"Netflix", "Hulu"}


def test_recommend_shape_and_match_percent(client):
    r = client.post("/recommend", json=body(1000, 1001, 1002)).json()
    assert r["results"][0]["title"].startswith("A")
    top = r["results"][0]
    assert isinstance(top["match"], int) and 0 <= top["match"] <= 100
    assert len(top["members"][0]["because"]) == 3
    assert {"tmdb_id", "title", "year", "poster_path", "providers"} <= set(top)
    watched = {1000, 1001, 1002}
    assert watched.isdisjoint(x["tmdb_id"] for x in r["results"])


def test_paging(client):
    first = client.post("/recommend", json=body(1000, limit=5)).json()["results"]
    second = client.post("/recommend", json=body(1000, limit=5, offset=5)).json()["results"]
    assert [x["rank"] for x in first] == [1, 2, 3, 4, 5]
    assert [x["rank"] for x in second] == [6, 7, 8, 9, 10]


def test_provider_filter_keeps_only_that_service(client):
    r = client.post("/recommend", json=body(1000, 1001, providers=["Netflix"], limit=50)).json()
    assert r["results"] and all("Netflix" in x["providers"] for x in r["results"])
    assert client.post("/recommend", json=body(1000, providers=["Nope"])).status_code == 422


def test_unknown_films_are_counted_not_fatal(client):
    r = client.post("/recommend", json=body(1000, 1001, 999999)).json()
    assert r["unmatched_films"] == 1 and r["results"]


def test_a_profile_with_nothing_liked_is_a_clear_422(client):
    res = client.post(
        "/recommend", json={"members": [{"name": "me", "films": films(1000, rating=2)}]}
    )
    assert res.status_code == 422 and "nothing to compare" in res.json()["detail"]


def test_group_recommend(client):
    req = {
        "members": [
            {"name": "a", "films": films(1000, 1001)},
            {"name": "b", "films": films(1020, 1021)},
        ]
    }
    r = client.post("/recommend", json=req).json()
    assert r["group"] and len(r["results"][0]["members"]) == 2


def test_payload_caps(client):
    too_many = {"members": [{"name": str(i), "films": films(1000)} for i in range(7)]}
    assert client.post("/recommend", json=too_many).status_code == 422
    assert client.post("/recommend", json=body(1000, limit=51)).status_code == 422
    assert client.post("/recommend", json=body(1000, limit=50, offset=360)).status_code == 422


def test_franchises_group_and_need_two(client):
    s = client.app.state.snap
    for i in range(0, 6):
        s.franchise[i] = "Alpha"  # six A titles in one franchise
    s.franchise[30] = "Lonely"  # a franchise of one is not a franchise
    r = client.post("/franchises", json=body(1010, 1011)).json()
    names = [g["franchise"] for g in r["franchises"]]
    assert "Alpha" in names and "Lonely" not in names
    alpha = next(g for g in r["franchises"] if g["franchise"] == "Alpha")
    assert alpha["best"]["rank"] < min(o["rank"] for o in alpha["others"])


def test_csv_matching_flags_ambiguity_and_reports_the_unmatched(client):
    s = client.app.state.snap
    s.title[0] = s.title[1] = "Good Boy"  # two different films, same title and year
    s.by_title_year.clear()
    for n, (t, y) in enumerate(zip(s.title, s.year, strict=True)):
        s.by_title_year.setdefault((snapshot_norm(t), int(y)), []).append(n)
    s.votes[1] = 10**6  # the more famous of the two should win
    rows = [
        {"title": "Good Boy", "year": 2000, "rating": 4},
        {"title": "A05", "year": 2001},  # off by one year: still matches
        {"title": "No Such Film", "year": 1999},
    ]
    r = client.post("/match", json={"rows": rows}).json()
    assert r["ambiguous"] == 1
    assert r["films"][0]["tmdb_id"] == int(s.tmdb_id[1]) and r["films"][0]["ambiguous"]
    assert [f["title"] for f in r["films"]][1] == "A05"
    assert r["unmatched"] == [{"title": "No Such Film", "year": 1999}]


def snapshot_norm(t):
    from snapshot import normalize_title

    return normalize_title(t)


def test_letterboxd_import_collapses_to_one_row_per_film(client, monkeypatch):
    entries = [
        {
            "tmdb_id": 1000,
            "tmdb_media_type": "movie",
            "film_title": "A00",
            "film_year": "2000",
            "rating": None,
            "rewatch": False,
        },
        {
            "tmdb_id": 1000,
            "tmdb_media_type": "movie",
            "film_title": "A00",
            "film_year": "2000",
            "rating": 5.0,
            "rewatch": False,
        },
        {
            "tmdb_id": 1001,
            "tmdb_media_type": "movie",
            "film_title": "A01",
            "film_year": "2000",
            "rating": 4.0,
            "rewatch": False,
        },
        {
            "tmdb_id": None,
            "tmdb_media_type": None,
            "film_title": "x",
            "film_year": None,
            "rating": 3.0,
            "rewatch": False,
        },
    ]
    monkeypatch.setattr("api.app.fetch_feed", lambda u: entries)
    r = client.post("/import/letterboxd", json={"username": "someone"}).json()
    by_id = {f["tmdb_id"]: f for f in r["films"]}
    assert set(by_id) == {1000, 1001}
    assert by_id[1000]["rating"] == 5.0 and by_id[1000]["rewatch"] is True  # logged twice
    assert by_id[1001]["rewatch"] is False
    assert by_id[1000]["in_catalog"]


def test_letterboxd_errors_surface_with_their_status(client, monkeypatch):
    def boom(_):
        raise letterboxd.LetterboxdError("No Letterboxd user named 'x'.", status=404)

    monkeypatch.setattr("api.app.fetch_feed", boom)
    assert client.post("/import/letterboxd", json={"username": "x"}).status_code == 404
    assert client.post("/import/letterboxd", json={"username": "bad name!"}).status_code == 422


def test_rss_fetch_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr("api.app.fetch_feed", lambda u: [])
    codes = [
        client.post("/import/letterboxd", json={"username": "u"}).status_code for _ in range(12)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_consent_stores_a_record_and_returns_a_token_that_is_not_stored(client, tmp_path):
    res = client.post(
        "/consent",
        json={"source": "letterboxd-export", "films": films(1000, 1001)},
    ).json()
    token = res["token"]
    files = list((tmp_path / "inbox" / "inbox" / "imports").glob("*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8"))
    assert record["token_hash"] == token_hash(token)
    assert token not in files[0].read_text(encoding="utf-8")
    assert record["user_id"].startswith("import-")  # anonymous unless a username was the source

    assert client.post("/delete", json={"token": token}).json()["requested"] is True
    gone = list((tmp_path / "inbox" / "inbox" / "deletions").glob("*.json"))
    assert [p.stem for p in gone] == [token_hash(token)]


def test_username_import_keeps_the_public_username(client, tmp_path):
    client.post(
        "/consent",
        json={"source": "letterboxd-username", "username": "VetOW", "films": films(1000)},
    )
    f = next((tmp_path / "inbox" / "inbox" / "imports").glob("*.json"))
    assert json.loads(f.read_text(encoding="utf-8"))["user_id"] == "vetow"


def test_provider_filter_reports_overall_rank_and_pool_stats(client):
    r = client.post("/recommend", json=body(1000, 1001, providers=["Netflix"], limit=5)).json()
    assert r["pool_size"] > 0
    assert 0 < r["pool_matches"] <= r["pool_size"]
    ranks = [x["rank"] for x in r["results"]]
    overall = [x["overall_rank"] for x in r["results"]]
    assert ranks == [1, 2, 3, 4, 5]
    assert all(o >= k for o, k in zip(overall, ranks, strict=True))  # never better than overall
    unfiltered = client.post("/recommend", json=body(1000, 1001, limit=5)).json()
    assert "overall_rank" not in unfiltered["results"][0]
