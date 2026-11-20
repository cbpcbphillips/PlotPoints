"""Usage events: counts and fixed words only, and nothing that could identify a person."""

import logging

import pytest
from conftest import make_snapshot
from fastapi.testclient import TestClient

from api.app import create_app
from api.events import bucket, log_event
from api.inbox import Inbox
from api.tmdb_lookup import TmdbLookup

EVENTS_LOGGER = "plotpoints.api.events"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    with TestClient(
        create_app(snap=make_snapshot(), inbox=Inbox(), lookup=TmdbLookup(api_key=""))
    ) as c:
        yield c


def events(caplog):
    return [r.getMessage() for r in caplog.records if r.name == EVENTS_LOGGER]


def films(*ids):
    return [{"tmdb_id": i, "rating": 4.5} for i in ids]


def test_counts_are_bucketed():
    assert [bucket(n) for n in (0, 1, 4, 5, 14, 15, 49, 50, 199, 200, 5000)] == [
        "0", "1-4", "1-4", "5-14", "5-14", "15-49", "15-49", "50-199", "50-199", "200+", "200+",
    ]  # fmt: skip
    assert bucket(-3) == "0"


def test_only_numbers_flags_and_short_lower_case_words_are_logged(caplog):
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        log_event(
            "recommend",
            members=2,
            paged=True,
            wildcard=False,
            facets="genre,era",
            title="Secretly Embarrassing Movie",  # capitals and spaces: dropped
            who="alex@example.com",  # an address: dropped
            token="Aq9-ZkLmN0pQrStUvWxYz1234567890abcdefghij",  # too long and mixed case: dropped
            nothing=None,  # not a number or a word: dropped
        )
    assert events(caplog) == ["event=recommend members=2 paged=1 wildcard=0 facets=genre,era"]


def test_unknown_events_and_odd_keys_are_dropped(caplog):
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        log_event("pageview", members=1)
        log_event("delete", **{"Bad Key": 1, "ok_key": 2})
    assert events(caplog) == ["event=delete ok_key=2"]


def test_recommend_logs_how_it_was_used_and_nothing_else(client, caplog):
    body = {
        "members": [{"name": "Secret Name", "films": films(1000, 1001, 1002, 1020)}],
        "limit": 5,
        "bundle": True,
        "facets": [{"kind": "genre", "values": ["Drama", "Crime"], "mode": "any"}],
    }
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        client.post("/recommend", json=body)  # 404: the synthetic catalog has no such genre
        plain = {**body, "facets": []}
        assert client.post("/recommend", json=plain).status_code == 200
    lines = events(caplog)
    assert len(lines) == 1  # the 404 is not a use of the feature, the 200 is
    line = lines[0]
    assert line.startswith("event=recommend members=1 facets=none multi=0 any_mode=0 providers=0")
    assert "paged=0" in line and "liked=1-4" in line
    assert "Secret" not in line and "1000" not in line


def test_a_group_request_says_how_many_people(client, caplog):
    body = {
        "members": [
            {"name": "ann", "films": films(1000, 1001, 1002)},
            {"name": "bob", "films": films(1020, 1021, 1022)},
        ],
        "limit": 5,
    }
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        assert client.post("/recommend", json=body).status_code == 200
    assert "members=2" in events(caplog)[0]


def test_import_consent_and_delete_events_carry_no_identifiers(client, caplog, monkeypatch):
    entries = [
        {
            "film_title": "Secretly Embarrassing Movie",
            "film_year": 1999,
            "tmdb_id": 1000,
            "tmdb_media_type": "movie",
            "rating": 4.0,
            "rewatch": False,
            "letterboxd_uri": "https://letterboxd.com/secretuser/film/x/",
            "watched_date": "2026-01-01",
        }
    ]
    monkeypatch.setattr("api.app.fetch_feed", lambda u: entries)
    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        client.post("/import/letterboxd", json={"username": "secretuser"})
        token = client.post(
            "/consent", json={"source": "letterboxd-username", "username": "secretuser",
                              "films": films(1000, 1001)},
        ).json()["token"]  # fmt: skip
        client.post("/delete", json={"token": token})
    lines = events(caplog)
    assert lines == [
        "event=import kind=username entries=1-4",
        "event=consent source=username films=1-4",
        "event=delete",
    ]
    text = "\n".join(lines)
    assert token not in text and "secretuser" not in text and "Secretly" not in text
