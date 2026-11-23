"""The live-site status check, against a fake network so no real service is touched."""

import json
from datetime import UTC, datetime

import pytest

import status_check as sc
from check_common import CheckWarning

API, SITE = "https://api.example.com", "https://site.example.com"
CACHE = {"Cache-Control": "public, max-age=3600"}


def make_fetcher(overrides=None):
    today = datetime.now(UTC).date().isoformat()
    responses = {
        ("GET", f"{API}/health"): (200, {}, json.dumps({"status": "ok", "snapshot": "abc"}), 40),
        ("GET", f"{API}/meta"): (
            200, {}, json.dumps({"snapshot": "abc", "titles": 28555, "providers_as_of": today}), 30,
        ),
        ("GET", f"{API}/film/603"): (200, CACHE, json.dumps({"title": "The Matrix"}), 25),
        ("GET", f"{API}/facets"): (200, CACHE, json.dumps({"genres": [1, 2, 3]}), 20),
        ("GET", f"{API}/film/999999999"): (404, {}, "{}", 10),
        ("OPTIONS", f"{API}/recommend"): (200, {"access-control-allow-origin": SITE}, "", 5),
        ("GET", f"{SITE}/"): (200, {}, '<div id="root"></div>', 50),
        ("GET", f"{SITE}/film/603"): (200, {}, '<div id="root"></div>', 50),
    }  # fmt: skip
    responses.update(overrides or {})

    def fetcher(url, method="GET", headers=None):
        status, hdrs, body, ms = responses[(method, url)]
        return status, hdrs, body.encode() if isinstance(body, str) else body, ms

    return fetcher


def run(fetcher, certs=lambda host: 90):
    results = {}
    for label, probe in sc.build_checks(API, SITE, fetcher, certs):
        try:
            results[label] = ("PASS", probe())
        except CheckWarning as exc:
            results[label] = ("WARN", str(exc))
        except Exception as exc:  # noqa: BLE001
            results[label] = ("FAIL", str(exc))
    return results


def test_a_healthy_site_passes_everything():
    results = run(make_fetcher())
    assert {k: v[0] for k, v in results.items()} == {k: "PASS" for k in results}
    assert "snapshot abc" in results["api health"][1]


def test_an_api_that_is_down_fails_health():
    results = run(make_fetcher({("GET", f"{API}/health"): (503, {}, "", 10)}))
    assert results["api health"][0] == "FAIL"


def test_a_slow_first_answer_is_a_warning_not_a_failure():
    slow = {("GET", f"{API}/health"): (200, {}, json.dumps({"snapshot": "abc"}), 9000)}
    assert run(make_fetcher(slow))["api health"][0] == "WARN"


def test_stale_streaming_data_is_flagged():
    old = {
        ("GET", f"{API}/meta"): (
            200, {}, json.dumps({"snapshot": "abc", "titles": 1, "providers_as_of": "2020-01-01"}),
            5,
        )
    }  # fmt: skip
    assert run(make_fetcher(old))["api data version"][0] == "WARN"


def test_missing_cache_headers_warn_and_a_cached_404_fails():
    no_cache = {("GET", f"{API}/film/603"): (200, {}, json.dumps({"title": "x"}), 5)}
    assert run(make_fetcher(no_cache))["film endpoint"][0] == "WARN"
    cached_404 = {("GET", f"{API}/film/999999999"): (404, CACHE, "{}", 5)}
    assert run(make_fetcher(cached_404))["unknown film"][0] == "FAIL"


def test_cors_for_the_wrong_origin_fails_with_the_fix():
    wrong = {
        ("OPTIONS", f"{API}/recommend"): (200, {"access-control-allow-origin": "https://x"}, "", 5)
    }
    status, detail = run(make_fetcher(wrong))["cors for the site"]
    assert status == "FAIL" and "PLOTPOINTS_CORS_ORIGINS" in detail


def test_a_broken_deep_link_is_caught():
    broken = {("GET", f"{SITE}/film/603"): (404, {}, "not found", 5)}
    assert run(make_fetcher(broken))["site deep link"][0] == "FAIL"


def test_certificates_warn_when_close_to_expiry():
    assert run(make_fetcher(), certs=lambda host: 10)["https certificates"][0] == "WARN"
    assert run(make_fetcher(), certs=lambda host: 60)["https certificates"][0] == "PASS"


def test_days_left_reads_the_ssl_date_format():
    now = datetime(2026, 11, 1, tzinfo=UTC)
    assert sc.days_left("Dec 1 00:00:00 2026 GMT", now) == 30


def test_trailing_slashes_are_dropped_from_settings(monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_API_URL", "https://a.example.com/")
    assert sc.setting("PLOTPOINTS_API_URL", None) == "https://a.example.com"
    assert sc.setting("PLOTPOINTS_API_URL", "https://b.example.com//") == "https://b.example.com"


@pytest.mark.parametrize("name", ["health", "meta"])
def test_the_data_version_must_agree(name):
    meta = json.dumps({"snapshot": "zzz", "titles": 1, "providers_as_of": "2026-01-01"})
    drift = {("GET", f"{API}/meta"): (200, {}, meta, 5)}
    assert run(make_fetcher(drift))["api data version"][0] == "FAIL"
