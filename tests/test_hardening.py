"""Edge hardening: public GETs are cacheable, rate limits key on a caller that cannot be faked."""

import pytest
from conftest import make_snapshot
from fastapi.testclient import TestClient

from api.app import CACHE_CONTROL, client_ip, create_app
from api.inbox import Inbox
from api.tmdb_lookup import TmdbLookup


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PLOTPOINTS_TRUSTED_PROXIES", raising=False)
    with TestClient(
        create_app(snap=make_snapshot(), inbox=Inbox(), lookup=TmdbLookup(api_key=""))
    ) as c:
        yield c


# ------------------------------------------------------------------ cache headers


@pytest.mark.parametrize(
    "path", ["/meta", "/facets", "/keywords", "/people?kind=director", "/film/1000"]
)
def test_public_gets_are_cacheable(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == CACHE_CONTROL


def test_similar_films_are_cacheable(client):
    assert client.get("/film/1000/similar").headers["cache-control"] == CACHE_CONTROL


def test_caching_can_be_switched_off_for_development(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLOTPOINTS_CACHE_SECONDS", "0")
    app = create_app(snap=make_snapshot(), inbox=Inbox(), lookup=TmdbLookup(api_key=""))
    with TestClient(app) as c:
        assert c.get("/meta").headers["cache-control"] == "no-cache"


def test_errors_posts_and_health_are_never_cached(client):
    assert "cache-control" not in client.get("/film/999999").headers  # a 404 must not stick
    assert "cache-control" not in client.get("/health").headers
    body = {"members": [{"name": "me", "films": [{"tmdb_id": 1000, "rating": 5}]}]}
    assert "cache-control" not in client.post("/recommend", json=body).headers
    assert "cache-control" not in client.post("/film/1000/for-me", json={"films": []}).headers


# ------------------------------------------------------------------ who is calling


def test_client_ip_takes_the_entry_the_nearest_proxy_added():
    # a caller can write anything at the front; only the end is the proxy's own record
    assert client_ip("6.6.6.6, 1.2.3.4", "10.0.0.1", proxies=1) == "1.2.3.4"
    assert client_ip("6.6.6.6, 1.2.3.4, 172.16.0.9", "10.0.0.1", proxies=2) == "1.2.3.4"


def test_client_ip_without_a_proxy_header_is_the_direct_peer():
    assert client_ip(None, "10.0.0.1") == "10.0.0.1"
    assert client_ip("", "10.0.0.1") == "10.0.0.1"
    assert client_ip(None, None) == "?"


def test_client_ip_with_fewer_entries_than_proxies_uses_what_there_is():
    assert client_ip("1.2.3.4", "10.0.0.1", proxies=2) == "1.2.3.4"


def test_a_spoofed_header_does_not_dodge_a_limit(client):
    # /delete allows 5 a minute. Same real caller (the last entry), a different fake each time.
    codes = [
        client.post(
            "/delete", json={"token": "x" * 20}, headers={"X-Forwarded-For": f"9.9.9.{n}, 1.2.3.4"}
        ).status_code
        for n in range(7)
    ]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


def test_different_real_callers_have_separate_limits(client):
    for n in range(7):
        r = client.post(
            "/delete", json={"token": "x" * 20}, headers={"X-Forwarded-For": f"1.1.1.{n}"}
        )
        assert r.status_code == 200


def test_the_heavy_endpoints_are_limited_too(client):
    body = {"members": [{"name": "me", "films": [{"tmdb_id": 1000, "rating": 5}]}], "limit": 1}
    codes = [client.post("/recommend", json=body).status_code for _ in range(122)]
    assert codes[:120] == [200] * 120 and codes[120:] == [429, 429]


# ------------------------------------------------------------------ public surface


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_interactive_docs_are_off_by_default(client, path):
    assert client.get(path).status_code == 404


def test_interactive_docs_can_be_switched_on_for_development(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PLOTPOINTS_DOCS", "1")
    with TestClient(
        create_app(snap=make_snapshot(), inbox=Inbox(), lookup=TmdbLookup(api_key=""))
    ) as c:
        assert c.get("/openapi.json").status_code == 200


def test_oversized_bodies_are_refused_before_they_are_read(client):
    r = client.post("/profile", content=b"x" * 10, headers={"content-length": "50000000"})
    assert r.status_code == 413
    assert "too large" in r.json()["detail"]


def test_a_normal_body_still_goes_through(client):
    assert client.post("/profile", json={"films": []}).status_code == 200
