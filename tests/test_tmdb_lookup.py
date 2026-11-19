"""The import-time TMDB fallback, with the HTTP layer stubbed (no network, no key)."""

import requests

from api.tmdb_lookup import TmdbLookup


class Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.headers = payload, status, {}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self.payload


class Session:
    """Serves canned search results; anything not in the table returns no results."""

    def __init__(self, table, fail=False):
        self.table, self.fail, self.calls = table, fail, []

    def get(self, url, params, timeout):
        path = url.rsplit("/3", 1)[1]
        self.calls.append((path, dict(params)))
        if self.fail:
            raise requests.ConnectionError("boom")
        key = (path, params["query"], params.get("year") or params.get("first_air_date_year"))
        return Resp({"results": self.table.get(key, [])})


def movie(i, title, date, votes):
    return {
        "id": i,
        "title": title,
        "original_title": title,
        "release_date": date,
        "vote_count": votes,
    }


def lookup(table, **kw):
    return TmdbLookup(api_key="test-key", session=Session(table, **kw))


def test_exact_title_takes_the_closest_year_even_when_tmdb_redated_it():
    table = {
        ("/search/movie", "Hamilton", None): [
            movie(1, "Hamilton", "1998-01-01", 57),
            movie(2, "Hamilton", "2025-09-05", 176),
            movie(3, "Hamilton: In the Interest of the Nation", "2012-01-01", 140),
        ]
    }
    hit = lookup(table).resolve_one("Hamilton", 2020)
    assert (hit["kind"], hit["tmdb_id"], hit["year"]) == ("movie", 2, 2025)


def test_a_film_below_the_floor_resolves_with_its_votes():
    table = {
        ("/search/movie", "Last Night at the Alamo", None): [
            movie(9, "Last Night at the Alamo", "1984-01-01", 8)
        ]
    }
    hit = lookup(table).resolve_one("Last Night at the Alamo", 1983)
    assert (hit["tmdb_id"], hit["votes"]) == (9, 8)


def test_an_undated_stub_never_beats_a_dated_film():
    # seen for real: "Golden Boy" (1995 on Letterboxd) also exists on TMDB as an undated 0-vote stub
    table = {
        ("/search/movie", "Golden Boy", None): [
            movie(1810787, "Golden Boy", "", 0),
            movie(2018, "Golden Boy", "2018-01-01", 6),
            movie(1996, "Golden Boy", "1996-05-01", 5),
        ]
    }
    assert lookup(table).resolve_one("Golden Boy", 1995)["tmdb_id"] == 1996


def test_tv_is_recognized_when_no_movie_has_the_title():
    table = {
        ("/search/movie", "Baby Reindeer", None): [movie(5, "Reindeer Games", "2000-01-01", 900)],
        ("/search/tv", "Baby Reindeer", None): [
            {"id": 7, "name": "Baby Reindeer", "original_name": "Baby Reindeer"}
        ],
    }
    assert lookup(table).resolve_one("Baby Reindeer", 2024) == {"kind": "tv"}


def test_a_near_title_needs_the_right_year_and_a_shared_prefix():
    near = movie(4, "Mission: Impossible - Dead Reckoning Part One", "2023-07-08", 4000)
    table = {("/search/movie", "Mission: Impossible - Dead Reckoning", 2023): [near]}
    assert lookup(table).resolve_one("Mission: Impossible - Dead Reckoning", 2023)["tmdb_id"] == 4
    other = {("/search/movie", "Frog", None): [movie(8, "Frogman", "2024-01-01", 29)]}
    assert lookup(other).resolve_one("Frog", 2010)["kind"] == "not_found"  # wrong year


def test_failures_and_a_missing_key_leave_rows_unresolved():
    assert lookup({}, fail=True).resolve_one("Anything", 2000) == {"kind": "not_found"}
    off = TmdbLookup(api_key="")
    assert not off.enabled
    assert off.resolve([{"title": "x", "year": 1}]) == [{"kind": "not_found"}]


def test_results_are_cached_and_the_key_never_reaches_a_url():
    table = {("/search/movie", "Amélie", None): [movie(1, "Amélie", "2001-04-25", 11000)]}
    lk = lookup(table)
    lk.resolve_one("Amélie", None)
    n = len(lk.session.calls)
    lk.resolve_one("Amelie", None)  # same loose key: served from the cache
    assert len(lk.session.calls) == n
    assert all("test-key" not in path for path, _ in lk.session.calls)


def test_resolve_keeps_row_order_across_threads():
    table = {
        ("/search/movie", f"T{i}", None): [movie(i, f"T{i}", "2000-01-01", 10)] for i in range(30)
    }
    out = lookup(table).resolve([{"title": f"T{i}", "year": None} for i in range(30)])
    assert [h["tmdb_id"] for h in out] == list(range(30))
