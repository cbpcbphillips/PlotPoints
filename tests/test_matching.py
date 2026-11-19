"""Export-row matching: the tiers, and the edge cases a real Letterboxd history throws at it."""

import time

import numpy as np
import pytest

import snapshot
from api.matching import loose_title, match_rows

# (title, year, votes, original_title)
FILMS = [
    ("The School of Rock", 2003, 6480, None),
    ("The Fall", 2008, 1658, None),
    ("The Fall", 2019, 110, None),
    ("Amélie", 2001, 11000, "Le Fabuleux Destin d'Amélie Poulain"),
    ("Fast & Furious", 2009, 7000, None),
    ("Rocky II", 1979, 4000, None),
    ("Suspiria", 1977, 2500, None),
    ("Suspiria", 2018, 2700, None),
    ("Good Boy", 2025, 300, None),
    ("Good Boy", 2025, 900, None),
    ("Kill Bill: Vol. 1", 2003, 17000, None),
    ("千と千尋の神隠し", 2001, 16000, None),
    ("Schindler's List", 1993, 16000, None),
    ("Mission: Impossible", 1996, 9000, None),
    ("Parasite", 2019, 19000, "기생충"),
    ("X", 2022, 2400, None),
]


def make(films=FILMS) -> snapshot.Snapshot:
    n = len(films)
    return snapshot.Snapshot(
        version="m",
        embedding_model="t",
        created_at="",
        providers_as_of="",
        catalog_mean_rating=6.5,
        vectors=np.eye(n, dtype=np.float32),
        media_key=[f"k{i}" for i in range(n)],
        media_type=["movie"] * n,
        tmdb_id=np.arange(1, n + 1, dtype=np.int64),
        title=[f[0] for f in films],
        year=np.asarray([f[1] for f in films], dtype=np.int32),
        runtime=np.full(n, 100, dtype=np.float32),
        rating=np.full(n, 7, dtype=np.float32),
        votes=np.asarray([f[2] for f in films], dtype=np.int64),
        poster=[None] * n,
        franchise=[None] * n,
        genres=[[] for _ in range(n)],
        providers=[[] for _ in range(n)],
        provider_names=[],
        original_title=[f[3] for f in films],
    )


@pytest.fixture(scope="module")
def snap():
    return make()


def one(snap, title, year=None):
    r = match_rows(snap, [{"title": title, "year": year}])
    return r["films"][0] if r["films"] else None


def test_loose_title_rules():
    assert loose_title("The School of Rock") == loose_title("School of Rock")
    assert loose_title("Amélie") == loose_title("Amelie")
    assert loose_title("Fast & Furious") == loose_title("Fast and Furious")
    assert loose_title("Rocky II") == loose_title("Rocky 2")
    assert loose_title("Kill Bill: Vol. 1") == loose_title("Kill Bill Volume 1")
    assert loose_title("L'Avventura") == loose_title("Avventura")
    assert loose_title("The") == "the"  # a lone article is the title
    assert loose_title("千と千尋の神隠し") == "千と千尋の神隠し"  # non-Latin passes through


@pytest.mark.parametrize(
    ("title", "year", "want", "method"),
    [
        ("The School of Rock", 2003, ("The School of Rock", 2003), "strict"),
        ("School of Rock", 2003, ("The School of Rock", 2003), "loose"),  # article missing
        ("Amelie", 2001, ("Amélie", 2001), "loose"),  # diacritics
        ("Fast and Furious", 2009, ("Fast & Furious", 2009), "loose"),
        ("Rocky 2", 1979, ("Rocky II", 1979), "loose"),
        ("Kill Bill Volume 1", 2003, ("Kill Bill: Vol. 1", 2003), "loose"),
        ("Mission Impossible", 1996, ("Mission: Impossible", 1996), "strict"),  # punctuation
        ("Schindler’s List", 1993, ("Schindler's List", 1993), "strict"),  # curly apostrophe
        ("Le Fabuleux Destin d'Amélie Poulain", 2001, ("Amélie", 2001), "strict"),  # original title
        ("기생충", 2019, ("Parasite", 2019), "strict"),
        ("千と千尋の神隠し", 2002, ("千と千尋の神隠し", 2001), "strict"),  # +-1
        ("The Fall", 2006, ("The Fall", 2008), "wide"),  # +-2, and 2008 is closer than 2019
        ("X", 2022, ("X", 2022), "strict"),  # a one-letter title stays itself
    ],
)
def test_tiers(snap, title, year, want, method):
    f = one(snap, title, year)
    assert f is not None, title
    assert (f["title"], f["year"]) == want
    assert f["method"] == method


def test_remake_exact_year_never_drifts(snap):
    assert one(snap, "Suspiria", 1977)["year"] == 1977
    assert one(snap, "Suspiria", 2018)["year"] == 2018
    assert one(snap, "Suspiria", 2016)["year"] == 2018  # two years off is the +-2 tier
    assert one(snap, "Suspiria", 1975)["year"] == 1977
    # ...but nothing reaches across to a film three or more years away
    assert one(snap, "The Fall", 2004) is None
    assert one(snap, "Suspiria", 1997) is None


def test_two_films_same_title_and_year_are_ambiguous_and_most_voted_wins(snap):
    f = one(snap, "Good Boy", 2025)
    assert f["ambiguous"] and f["tmdb_id"] == 10  # the 900-vote one


def test_no_year_takes_the_most_voted(snap):
    f = one(snap, "Suspiria")
    assert f["year"] == 2018 and f["ambiguous"]


def test_blank_titles_are_skipped_and_duplicates_kept_once(snap):
    rows = [
        {"title": "  ", "year": 2000},
        {"title": "Amélie", "year": 2001, "rating": 5},
        {"title": "Amelie", "year": 2001, "rating": 3},
    ]
    r = match_rows(snap, rows)
    assert [f["title"] for f in r["films"]] == ["Amélie"] and r["films"][0]["rating"] == 5
    assert r["unmatched"] == []


def test_unmatched_rows_keep_rating_and_rewatch_for_later_steps(snap):
    r = match_rows(snap, [{"title": "No Such Film", "year": 1999, "rating": 4.5, "rewatch": True}])
    assert r["unmatched"] == [
        {"title": "No Such Film", "year": 1999, "rating": 4.5, "rewatch": True}
    ]


def test_a_large_export_is_fast_because_the_index_is_built_once():
    s = make([(f"Film {i}", 1950 + i % 70, i, None) for i in range(20000)])
    rows = [{"title": f"Film {i}", "year": 1950 + i % 70} for i in range(0, 20000, 2)]
    start = time.perf_counter()
    r = match_rows(s, rows)
    assert len(r["films"]) == 10000
    assert time.perf_counter() - start < 5
