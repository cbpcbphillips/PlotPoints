"""The HTTP layer, against the synthetic snapshot. No network: Letterboxd is stubbed."""

import json

import pytest
from conftest import make_snapshot
from fastapi.testclient import TestClient

from api import letterboxd
from api.app import create_app
from api.inbox import Inbox, token_hash
from api.tmdb_lookup import TmdbLookup


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    no_tmdb = TmdbLookup(api_key="")  # tests never reach the network
    with TestClient(create_app(snap=make_snapshot(), inbox=Inbox(), lookup=no_tmdb)) as c:
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


def test_results_carry_the_ranking_score_and_a_novelty_standin(client):
    top = client.post("/recommend", json=body(1000, 1001, 1002)).json()["results"]
    assert all(isinstance(x["score"], float) for x in top)
    assert [x["score"] for x in top] == sorted((x["score"] for x in top), reverse=True)
    first = top[0]
    # novelty is 100 minus the closest explaining film's cosine, so it is derived from `because`
    assert first["novelty"] == 100 - first["members"][0]["because"][0]["match"]
    assert first["score"] != first["match"]  # the score is not the percentage


def test_enjoyed_row_only_on_the_first_unfiltered_page(client):
    r = client.post("/recommend", json=body(1000, 1001, 1020, limit=20)).json()
    assert r["enjoyed"] and len(r["enjoyed"]) <= 12
    assert {"tmdb_id", "title", "rating", "behind", "of"} <= set(r["enjoyed"][0])
    assert all(0 <= e["behind"] <= e["of"] for e in r["enjoyed"])
    assert {e["tmdb_id"] for e in r["enjoyed"]} <= {1000, 1001, 1020}
    assert client.post("/recommend", json=body(1000, offset=5)).json()["enjoyed"] is None
    assert (
        client.post("/recommend", json=body(1000, providers=["Netflix"])).json()["enjoyed"] is None
    )
    group = {
        "members": [
            {"name": "a", "films": films(1000, 1001)},
            {"name": "b", "films": films(1020, 1021)},
        ]
    }
    assert client.post("/recommend", json=group).json()["enjoyed"] is None


def test_franchises_are_capped_at_five_and_list_seen_films(client):
    s = client.app.state.snap
    names = ["F1", "F2", "F3", "F4", "F5", "F6"]
    for n, name in enumerate(names):  # six franchises of three A titles each (rows 3.. skip A03)
        for i in range(4 + 3 * n, 7 + 3 * n):
            s.franchise[i] = name
    s.franchise[0] = "F1"  # a watched film that belongs to F1
    r = client.post("/franchises", json=body(1000, 1001)).json()
    assert len(r["franchises"]) == 5
    f1 = next((g for g in r["franchises"] if g["franchise"] == "F1"), None)
    if f1:
        assert [x["tmdb_id"] for x in f1["seen"]] == [1000]
        assert f1["seen"][0]["rating"] == 4.5
    assert all(len(g["others"]) <= 7 for g in r["franchises"])


def test_profile_stats(client):
    s = client.app.state.snap
    s.genres[0] = ["Drama", "Crime"]
    s.genres[1] = ["Drama"]
    s.franchise[0] = s.franchise[1] = "Alpha"
    payload = {
        "films": [
            {"tmdb_id": 1000, "rating": 5},
            {"tmdb_id": 1001, "rating": 3.5},
            {"tmdb_id": 1002},
            {"tmdb_id": 999999, "rating": 4},
        ]
    }
    r = client.post("/profile", json=payload).json()
    assert (r["films"], r["rated"], r["in_catalog"], r["not_in_catalog"]) == (4, 3, 3, 1)
    assert r["average_rating"] == 4.17
    assert {h["rating"]: h["count"] for h in r["histogram"]}[5.0] == 1
    assert r["genres"][0] == {"name": "Drama", "count": 2, "share": 67}
    assert r["eras"] == [{"name": "2000s", "count": 3, "share": 100}]
    assert r["top_series"] == {"name": "Alpha", "count": 2}
    assert r["five_star"] == ["A00"] and r["average_runtime"] == 110


class StubLookup:
    """Stands in for TMDB: answers by title and records what it was asked."""

    enabled = True

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def resolve(self, rows):
        self.asked.extend(r["title"] for r in rows)
        return [self.answers.get(r["title"], {"kind": "not_found"}) for r in rows]


def wanted_files(tmp_path):
    return sorted((tmp_path / "inbox" / "inbox" / "titles").glob("*.json"))


def test_match_asks_tmdb_only_about_leftovers_and_records_missing_ids_anonymously(client, tmp_path):
    stub = StubLookup(
        {
            "Redated": {"kind": "movie", "tmdb_id": 1007, "title": "A07", "year": 2000, "votes": 9},
            "Obscure": {
                "kind": "movie",
                "tmdb_id": 555,
                "title": "Obscure",
                "year": 1983,
                "votes": 8,
            },
            "A Series": {"kind": "tv"},
        }
    )
    client.app.state.lookup = stub
    rows = [
        {"title": "A00", "year": 2000, "rating": 4},  # the snapshot matches it: no lookup
        {"title": "Redated", "year": 1994, "rating": 3.5},
        {"title": "Obscure", "year": 1983, "rating": 4},
        {"title": "A Series", "year": 2024, "rating": 5},
        {"title": "Nothing", "year": 1999},
    ]
    r = client.post("/match", json={"rows": rows}).json()
    assert stub.asked == ["Redated", "Obscure", "A Series", "Nothing"]
    by_id = {f["tmdb_id"]: f for f in r["films"]}
    assert by_id[1000]["method"] == "strict"
    assert by_id[1007]["method"] == "tmdb" and by_id[1007]["rating"] == 3.5
    assert [(m["tmdb_id"], m["votes"], m["rating"]) for m in r["missing"]] == [(555, 8, 4)]
    assert r["tv"] == [{"title": "A Series", "year": 2024}]
    assert r["unmatched"] == [{"title": "Nothing", "year": 1999}]
    files = wanted_files(tmp_path)
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8"))
    assert record["titles"] == [{"media_type": "movie", "tmdb_id": 555}]
    assert set(record) == {"requested_at", "titles"}  # nothing about who asked


def test_match_without_a_key_stays_snapshot_only(client, tmp_path):
    r = client.post("/match", json={"rows": [{"title": "Nothing", "year": 1999}]}).json()
    assert r["missing"] == [] and r["unmatched"] == [{"title": "Nothing", "year": 1999}]
    assert wanted_files(tmp_path) == []


def test_rss_films_outside_the_catalog_are_recorded(client, monkeypatch, tmp_path):
    entries = [
        {
            "tmdb_id": 1000,
            "tmdb_media_type": "movie",
            "film_title": "A00",
            "film_year": "2000",
            "rating": 4.0,
            "rewatch": False,
        },
        {
            "tmdb_id": 424242,
            "tmdb_media_type": "movie",
            "film_title": "Rare",
            "film_year": "1980",
            "rating": 5.0,
            "rewatch": False,
        },
    ]
    monkeypatch.setattr("api.app.fetch_feed", lambda u: entries)
    r = client.post("/import/letterboxd", json={"username": "someone"}).json()
    assert {f["tmdb_id"]: f["in_catalog"] for f in r["films"]} == {1000: True, 424242: False}
    record = json.loads(wanted_files(tmp_path)[0].read_text(encoding="utf-8"))
    assert record["titles"] == [{"media_type": "movie", "tmdb_id": 424242}]


def test_results_carry_image_paths(client):
    s = client.app.state.snap
    s.poster[5], s.backdrop[5] = "/p.jpg", "/b.jpg"
    top = client.post("/recommend", json=body(1000, 1001, limit=20)).json()["results"]
    a05 = next(x for x in top if x["tmdb_id"] == 1005)
    assert (a05["poster_path"], a05["backdrop_path"]) == ("/p.jpg", "/b.jpg")


def test_franchise_shelf_lists_every_unseen_film_not_only_the_top_of_the_ranking(
    client, monkeypatch
):
    """A series' weaker entries can rank below the pool the series are picked from; they must still
    be on its shelf (Rocky V, Batman Forever), with scores unchanged."""
    s = client.app.state.snap
    for i in range(4, 12):  # eight A titles in one series; A03 is a short so it is skipped
        s.franchise[i] = "Alpha"
    before = client.post("/franchises", json=body(1000, 1001)).json()
    monkeypatch.setattr("api.app.FRANCHISE_POOL", 6)  # far shallower than the series is spread
    after = client.post("/franchises", json=body(1000, 1001)).json()

    def shelf(r):
        g = next(g for g in r["franchises"] if g["franchise"] == "Alpha")
        return {x["tmdb_id"]: x["score"] for x in [g["best"], *g["others"]]}, g["count"]

    full, full_count = shelf(before)
    shallow, shallow_count = shelf(after)
    assert len(full) == full_count == 8
    assert shallow == full  # nothing missing, nothing re-scored
    assert shallow_count == 8


def test_enjoyed_says_how_many_of_the_top_picks_each_liked_film_is_behind(client):
    r = client.post("/recommend", json=body(1000, 1001, 1020, bundle=True, limit=10)).json()
    enjoyed = r["enjoyed"]
    assert enjoyed and all(e["of"] <= 50 for e in enjoyed)
    assert any(e["behind"] > 0 for e in enjoyed)  # at least one film is a named reason somewhere
    assert enjoyed[0]["behind"] >= 1  # the one pulling hardest is behind at least one pick
