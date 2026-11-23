"""Is the live site up and healthy? One command, PASS / WARN / FAIL per check.

Run it after a deploy, and any time you wonder whether something is wrong. It only reads: a
handful of GET requests (and one CORS preflight) against the public site and API, the same
things a visitor's browser does. Set the two addresses once in `.env`:

    PLOTPOINTS_API_URL=https://plotpoints-api-xxxxx.a.run.app
    PLOTPOINTS_SITE_URL=https://plotpoints.pages.dev      (or your own domain)

or pass --api / --site. Run via `just status`.

What it checks: the API answers and reports its data version; the film and facet endpoints work and
carry cache headers; the data is not stale; the site loads and a deep link works (the single-page
fallback); the API allows the site's origin (CORS); the first request is not painfully slow (a cold
start); and the HTTPS certificates have time left. Output is ASCII-only for the Windows console.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import urlparse

from dotenv import dotenv_values

from check_common import CheckWarning, run_checks

TIMEOUT = 20
SLOW_FIRST_MS = 4000  # a first answer slower than this is a cold start people will notice
SLOW_MS = 1500
STALE_DAYS = 60  # streaming availability older than this is worth refreshing
CERT_WARN_DAYS = 21


def setting(name: str, cli: str | None) -> str:
    return (cli or os.environ.get(name) or dotenv_values(".env").get(name) or "").rstrip("/")


def fetch(url: str, method: str = "GET", headers: dict | None = None):
    """(status, headers, body, milliseconds). HTTP errors come back as a status, not a raise."""
    # Cloudflare answers the default "Python-urllib" agent with a 403 (error 1010): say who we are.
    sent = {"User-Agent": "PlotPointsStatusCheck/1.0", **(headers or {})}
    req = urllib.request.Request(url, method=method, headers=sent)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            return resp.status, dict(resp.headers), body, (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read(), (time.perf_counter() - started) * 1000


def days_left(not_after: str, now: datetime | None = None) -> int:
    """Whole days until a certificate's `notAfter` (the form Python's ssl module reports)."""
    expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    return (expires - (now or datetime.now(UTC))).days


def cert_days(host: str) -> int:
    ctx = ssl.create_default_context()
    with (
        socket.create_connection((host, 443), timeout=TIMEOUT) as raw,
        ctx.wrap_socket(raw, server_hostname=host) as tls,
    ):
        return days_left(tls.getpeercert()["notAfter"])


def build_checks(api: str, site: str, fetcher=fetch, certs=cert_days) -> list:
    """The probes, as (label, callable) pairs for check_common.run_checks. Injectable for tests."""
    state: dict = {}

    def health():
        status, _, body, ms = fetcher(f"{api}/health")
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        info = json.loads(body)
        state["snapshot"], state["first_ms"] = info.get("snapshot"), ms
        detail = f"snapshot {info.get('snapshot')} in {ms:.0f} ms"
        if ms > SLOW_FIRST_MS:
            raise CheckWarning(f"{detail} -- a slow first answer (a cold start?)")
        return detail

    def meta():
        status, headers, body, ms = fetcher(f"{api}/meta")
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        info = json.loads(body)
        if info.get("snapshot") != state.get("snapshot"):
            raise RuntimeError("/meta and /health disagree about the data version")
        age = (
            datetime.now(UTC).date() - datetime.fromisoformat(info["providers_as_of"]).date()
        ).days
        detail = f"{info['titles']} titles, streaming data {age} days old"
        if age > STALE_DAYS:
            raise CheckWarning(f"{detail} -- time for `just snapshot` and a redeploy")
        return detail

    def film():
        status, headers, body, ms = fetcher(f"{api}/film/603")
        if status != 200:
            raise RuntimeError(f"HTTP {status} for a film that should exist")
        if "max-age" not in {k.lower(): v for k, v in headers.items()}.get("cache-control", ""):
            raise CheckWarning("no cache headers: repeat views will all reach the API")
        return f"{json.loads(body)['title']}, {ms:.0f} ms, cacheable"

    def facets():
        status, _, body, ms = fetcher(f"{api}/facets")
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        genres = len(json.loads(body)["genres"])
        if ms > SLOW_MS:
            raise CheckWarning(f"{genres} genres but {ms:.0f} ms")
        return f"{genres} genres, {ms:.0f} ms"

    def not_found():
        status, headers, _, _ = fetcher(f"{api}/film/999999999")
        if status != 404:
            raise RuntimeError(f"expected 404 for an unknown film, got {status}")
        if "max-age" in {k.lower(): v for k, v in headers.items()}.get("cache-control", ""):
            raise RuntimeError("a 404 is being cached")
        return "unknown film is a 404 and is not cached"

    def cors():
        origin = site.rstrip("/")
        status, headers, _, _ = fetcher(
            f"{api}/recommend",
            "OPTIONS",
            {
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        allowed = {k.lower(): v for k, v in headers.items()}.get("access-control-allow-origin")
        if allowed not in (origin, "*"):
            raise RuntimeError(
                f"the API does not allow {origin} (got {allowed!r}). Add it to "
                "PLOTPOINTS_CORS_ORIGINS."
            )
        return f"{origin} is allowed"

    def site_home():
        status, _, body, ms = fetcher(f"{site}/")
        if status != 200 or b'id="root"' not in body:
            raise RuntimeError(f"HTTP {status}, or not the app's page")
        return f"loads in {ms:.0f} ms"

    def deep_link():
        status, _, body, _ = fetcher(f"{site}/film/603")
        if status != 200 or b'id="root"' not in body:
            raise RuntimeError(
                f"HTTP {status}: refreshing a film page would break (check _redirects)"
            )
        return "a direct link to a film page works"

    def certificates():
        notes = []
        for name, url in (("api", api), ("site", site)):
            host = urlparse(url).hostname
            if not url.startswith("https://") or not host:
                raise CheckWarning(f"{name} is not on https")
            left = certs(host)
            notes.append(f"{name} {left} days")
            if left < CERT_WARN_DAYS:
                raise CheckWarning(f"{name} certificate expires in {left} days")
        return ", ".join(notes)

    return [
        ("api health", health),
        ("api data version", meta),
        ("film endpoint", film),
        ("facets endpoint", facets),
        ("unknown film", not_found),
        ("cors for the site", cors),
        ("site loads", site_home),
        ("site deep link", deep_link),
        ("https certificates", certificates),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the live PlotPoints site and API.")
    parser.add_argument("--api", help="the API's address (default: PLOTPOINTS_API_URL)")
    parser.add_argument("--site", help="the site's address (default: PLOTPOINTS_SITE_URL)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    api, site = setting("PLOTPOINTS_API_URL", args.api), setting("PLOTPOINTS_SITE_URL", args.site)
    if not api or not site:
        raise SystemExit(
            "Set PLOTPOINTS_API_URL and PLOTPOINTS_SITE_URL in .env (or pass --api and --site)."
        )
    raise SystemExit(run_checks(f"PlotPoints at {site}", build_checks(api, site), args.verbose))


if __name__ == "__main__":
    main()
