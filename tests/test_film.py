"""The film page's backend: details in the snapshot, /film, /film/{id}/similar, request logging."""

import logging

import numpy as np
import pytest
from conftest import idx, make_snapshot
from fastapi.testclient import TestClient

import scoring
import snapshot
from api.app import create_app
from api.inbox import Inbox
from api.tmdb_lookup import TmdbLookup


def with_details(snap: snapshot.Snapshot) -> snapshot.Snapshot:
    i = idx(snap, "A00")
    snap.overview[i] = "A film about a cluster."
    snap.tagline[i] = "Nothing is alone."
    snap.directors[i] = ["Ada Director"]
    snap.cast[i] = [["Ann Actor", "Lead"], ["Bo Actor", None]]
    snap.keywords[i] = ["time travel", "heist"]
    return snap


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    app = create_app(
        snap=with_details(make_snapshot()), inbox=Inbox(), lookup=TmdbLookup(api_key="")
    )
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ similar_to


def test_similar_matches_brute_force_cosine(snap):
    i = idx(snap, "B04")
    got = scoring.similar_to(snap, i, n=10)
    sims = snap.vectors @ snap.vectors[i]
    allowed = [
        j
        for j in range(len(snap))
        if j != i and (np.isnan(snap.runtime[j]) or snap.runtime[j] >= 60) and snap.votes[j] >= 100
    ]
    expect = sorted(allowed, key=lambda j: -sims[j])[:10]
    assert [r["index"] for r in got] == expect
    assert got[0]["cosine"] >= got[-1]["cosine"]


def test_similar_excludes_self_shorts_and_thin_votes(snap):
    snap.votes[idx(snap, "A07")] = 10  # under the catalog floor
    got = scoring.similar_to(snap, idx(snap, "A00"), n=60)
    titles = {r["title"] for r in got}
    assert "A00" not in titles  # itself
    assert "A03" not in titles  # an 18-minute short
    assert "A07" not in titles  # too few votes


def test_similar_stays_in_cluster(snap):
    got = scoring.similar_to(snap, idx(snap, "C02"), n=10)
    assert all(r["title"].startswith("C") for r in got)


# ------------------------------------------------------------------- snapshot


def catalog_of(snap: snapshot.Snapshot) -> dict:
    n = len(snap)
    return {
        "catalog_mean_rating": snap.catalog_mean_rating,
        "media_key": snap.media_key,
        "media_type": snap.media_type,
        "tmdb_id": [int(t) for t in snap.tmdb_id],
        "title": snap.title,
        "year": [int(y) for y in snap.year],
        "runtime": [float(r) for r in snap.runtime],
        "rating": [float(r) for r in snap.rating],
        "votes": [int(v) for v in snap.votes],
        "poster": [None] * n,
        "franchise": [None] * n,
        "genres": snap.genres,
        "providers": snap.providers,
        "provider_names": snap.provider_names,
    }


def details_of(snap: snapshot.Snapshot) -> dict:
    return {
        "overview": snap.overview,
        "tagline": snap.tagline,
        "directors": snap.directors,
        "cast": snap.cast,
        "keywords": snap.keywords,
    }


def save(tmp_path, snap, details):
    return snapshot.save(
        tmp_path,
        vectors=snap.vectors,
        catalog=catalog_of(snap),
        details=details,
        embedding_model="synthetic",
        created_at="2026-01-01T00:00:00+00:00",
        providers_as_of="2026-01-01",
    )


def test_details_round_trip_and_change_the_version(tmp_path):
    snap = with_details(make_snapshot())
    with_dir, without_dir = tmp_path / "with", tmp_path / "without"
    m_with = save(with_dir, snap, details_of(snap))
    m_without = save(without_dir, snap, None)
    assert m_with["version"] != m_without["version"]

    loaded = snapshot.load(with_dir)
    i = idx(snap, "A00")
    assert loaded.overview[i] == "A film about a cluster."
    assert loaded.directors[i] == ["Ada Director"]
    assert loaded.cast[i][0] == ["Ann Actor", "Lead"]
    assert loaded.keywords[i] == ["time travel", "heist"]


def test_snapshot_without_details_pads_empty(tmp_path):
    snap = make_snapshot()
    save(tmp_path, snap, None)
    assert not (tmp_path / snapshot.DETAILS).exists()
    loaded = snapshot.load(tmp_path)
    assert loaded.overview == [None] * len(snap)
    assert loaded.directors[0] == [] and loaded.cast[0] == []


# ------------------------------------------------------------------------ API


def test_film_endpoint(client):
    f = client.get("/film/1000").json()
    assert f["title"] == "A00" and f["tmdb_id"] == 1000
    assert f["tagline"] == "Nothing is alone."
    assert f["directors"] == ["Ada Director"]
    assert f["keywords"] == ["heist", "time travel"]  # equally common: by name
    assert f["cast"] == [
        {"name": "Ann Actor", "character": "Lead"},
        {"name": "Bo Actor", "character": None},
    ]
    assert f["providers"] == ["Netflix"] and f["providers_as_of"] == "2026-01-01"


def test_film_without_details_still_loads(client):
    f = client.get("/film/1001").json()
    assert f["overview"] is None and f["directors"] == [] and f["cast"] == []
    assert f["keywords"] == []


def test_unknown_film_is_404(client):
    assert client.get("/film/999999").status_code == 404
    assert client.get("/film/999999/similar").status_code == 404


def test_similar_endpoint(client):
    r = client.get("/film/1000/similar?limit=5").json()["films"]
    assert len(r) == 5
    assert 1000 not in {f["tmdb_id"] for f in r}
    assert all(f["title"].startswith("A") for f in r)
    assert all(isinstance(f["match"], int) and 0 <= f["match"] <= 100 for f in r)
    assert len(client.get("/film/1000/similar?limit=500").json()["films"]) <= 24


# -------------------------------------------------------------------- logging


def test_access_log_has_route_template_and_no_path_values(client, caplog):
    with caplog.at_level(logging.INFO, logger="plotpoints.api"):
        client.get("/film/1000")
        client.get("/film/999999")
    lines = [r.getMessage() for r in caplog.records]
    assert any(line.startswith("GET /film/{tmdb_id} 200") for line in lines)
    assert any(line.startswith("GET /film/{tmdb_id} 404") for line in lines)
    assert not any("1000" in line or "999999" in line for line in lines)


def test_match_logs_counts_only(client, caplog):
    rows = [{"title": "Secretly Embarrassing Movie", "year": 1999, "rating": 5.0, "rewatch": False}]
    with caplog.at_level(logging.INFO, logger="plotpoints.api"):
        assert client.post("/match", json={"rows": rows}).status_code == 200
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "match: 1 rows" in text
    assert "Secretly" not in text and "1999" not in text


# ------------------------------------------------------------------ for-me


def test_closest_rated_prefers_the_same_cluster_and_never_returns_the_target(snap):
    liked = [(idx(snap, t), 2.0) for t in ("A00", "A01", "B00", "B01", "C00")]
    target = idx(snap, "B05")
    got = scoring.closest_rated(snap, {"me": liked}, target, n=3)
    assert [r["title"][0] for r in got[:2]] == ["B", "B"]
    # the target is excluded even when the person liked it
    liked_target = liked + [(target, 2.5)]
    got = scoring.closest_rated(snap, {"me": liked_target}, target, n=10)
    assert target not in {r["index"] for r in got}


def films_for(*titles, rating=4.5, snap=None):
    snap = snap or make_snapshot()
    return [{"tmdb_id": int(snap.tmdb_id[idx(snap, t)]), "rating": rating} for t in titles]


def test_for_me_endpoint(client):
    films = films_for("A01", "A02", "B01", "B02", "C01")
    r = client.post("/film/1000/for-me", json={"films": films})  # 1000 = A00, unseen
    assert r.status_code == 200
    body = r.json()
    assert body["seen"] is False and body["rating"] is None
    assert body["closest"][0]["title"].startswith("A")
    assert 0 <= body["match"] <= 100 and len(body["closest"]) == 5
    assert {"tmdb_id", "title", "year", "poster_path", "match"} <= set(body["closest"][0])


def test_for_me_reports_a_film_you_have_already_rated(client):
    films = films_for("A00", "A01", "A02", "B01")
    body = client.post("/film/1000/for-me", json={"films": films}).json()
    assert body["seen"] is True and body["rating"] == 4.5
    assert 1000 not in {c["tmdb_id"] for c in body["closest"]}


def test_for_me_needs_something_liked_and_a_real_film(client):
    meh = films_for("A01", rating=2.0)
    assert client.post("/film/1000/for-me", json={"films": meh}).status_code == 422
    assert client.post("/film/999999/for-me", json={"films": films_for("A01")}).status_code == 404


def test_a_film_lists_its_most_common_themes_first():
    snap = with_details(make_snapshot())
    for i in range(1, 6):
        snap.keywords[i] = ["time travel"]  # now the more common of the two
    assert snap.top_keywords(0, 5) == ["time travel", "heist"]
    assert snap.top_keywords(0, 1) == ["time travel"]
