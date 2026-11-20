"""Browsing by genre, director, actor and decade: masks, facet lists, and the filtered ranking."""

import numpy as np
import pytest
from conftest import idx, make_snapshot
from fastapi.testclient import TestClient

from api.app import create_app
from api.inbox import Inbox
from api.tmdb_lookup import TmdbLookup


def decorated():
    snap = make_snapshot()
    for i in range(60):
        name = "ABC"[i // 20]
        snap.genres[i] = {"A": ["Drama"], "B": ["Comedy"], "C": ["Drama", "Crime"]}[name]
        snap.year[i] = 1980 + (i % 3) * 10 + 4  # 1984, 1994, 2004 in rotation
    for i in range(0, 60, 4):
        snap.directors[i] = ["Ada Director"]
    for i in range(0, 60, 6):
        snap.directors[i] = [*snap.directors[i], "Bo Maker"]
    for i in range(0, 20):
        snap.cast[i] = [["Ann Actor", "Lead"], ["Cy Extra", None]]
    return snap


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    monkeypatch.setenv("PLOTPOINTS_DATA_DIR", str(tmp_path))
    snap = decorated()
    with TestClient(create_app(snap=snap, inbox=Inbox(), lookup=TmdbLookup(api_key=""))) as c:
        c.snap = snap
        yield c


def body(*facets, **extra):
    """Each facet is (kind, value), or (kind, [values], mode) for several values of one kind."""
    films = [{"tmdb_id": 1000 + i, "rating": 4.5} for i in (0, 1, 20, 21)]
    out = {"members": [{"name": "me", "films": films}], **extra}
    if facets:
        out["facets"] = [
            {
                "kind": f[0],
                "values": [f[1]] if isinstance(f[1], str) else f[1],
                "mode": f[2] if len(f) > 2 else "all",
            }
            for f in facets
        ]
    return out


# ------------------------------------------------------------------ masks


def test_genre_mask_ignores_case_and_spacing():
    snap = decorated()
    plain = snap.facet_mask("genre", "Drama")
    assert plain.sum() == 40  # clusters A and C
    assert (snap.facet_mask("genre", "  drAMA ") == plain).all()
    assert snap.facet_mask("genre", "Nope").sum() == 0


def test_director_and_actor_masks():
    snap = decorated()
    assert snap.facet_mask("director", "ada director").sum() == 15
    assert snap.facet_mask("actor", "Ann Actor").sum() == 20
    assert snap.facet_mask("actor", "Lead").sum() == 0  # a character name is not an actor


def test_era_mask_takes_a_decade_or_a_year():
    snap = decorated()
    by_decade = snap.facet_mask("era", "1990")
    assert by_decade.sum() == 20
    assert (snap.facet_mask("era", "1990s") == by_decade).all()
    assert (snap.facet_mask("era", "1994") == by_decade).all()
    assert snap.facet_mask("era", "soon").sum() == 0


def test_unknown_kind_is_an_error():
    with pytest.raises(ValueError):
        decorated().facet_mask("mood", "x")


def test_facet_name_gives_the_catalog_spelling():
    snap = decorated()
    assert snap.facet_name("director", "ada DIRECTOR") == "Ada Director"
    assert snap.facet_name("era", "1994") == "1990s"
    assert snap.facet_name("genre", "zzz") is None


# ------------------------------------------------------------------ lists


def test_facets_endpoint_counts_genres_and_decades(client):
    r = client.get("/facets").json()
    counts = {g["name"]: g["count"] for g in r["genres"]}
    assert counts == {"Drama": 40, "Comedy": 20, "Crime": 20}
    assert r["genres"][0]["name"] == "Drama"  # most films first
    assert [d["decade"] for d in r["decades"]] == [1980, 1990, 2000]


def test_people_search_by_name_and_count(client):
    r = client.get("/people", params={"kind": "director"}).json()["people"]
    assert r[0] == {"name": "Ada Director", "count": 15}
    hit = client.get("/people", params={"kind": "director", "q": "maker"}).json()["people"]
    assert [p["name"] for p in hit] == ["Bo Maker"]
    actors = client.get("/people", params={"kind": "actor", "q": "ann"}).json()["people"]
    assert actors == [{"name": "Ann Actor", "count": 20}]
    assert client.get("/people", params={"kind": "mood"}).status_code == 422


def test_people_limit(client):
    r = client.get("/people", params={"kind": "actor", "limit": 1}).json()["people"]
    assert len(r) == 1


# ------------------------------------------------------------------ filtered ranking


def test_genre_page_only_has_that_genre_and_no_watched_films(client):
    r = client.post("/recommend", json=body(("genre", "comedy"), limit=20)).json()
    assert r["facet"] == {
        "facets": [{"kind": "genre", "values": ["Comedy"], "mode": "all"}],
        "total": 20,
    }
    assert r["results"] and all(x["genres"] == ["Comedy"] for x in r["results"])
    assert not {1020, 1021} & {x["tmdb_id"] for x in r["results"]}  # watched B films


def test_filtering_never_changes_a_score(client):
    flat = client.post("/recommend", json=body(limit=50)).json()["results"]
    flat += client.post("/recommend", json=body(limit=50, offset=50)).json()["results"]
    flat_scores = {x["tmdb_id"]: x["score"] for x in flat}
    filtered = client.post("/recommend", json=body(("genre", "Crime"), limit=50)).json()["results"]
    assert filtered
    for x in filtered:
        assert x["score"] == pytest.approx(flat_scores[x["tmdb_id"]])
    # and the filtered list is the flat one with the other genres taken out, in the same order
    keep = [x["tmdb_id"] for x in flat if "Crime" in x["genres"]]
    assert [x["tmdb_id"] for x in filtered][: len(keep)] == keep[: len(filtered)]


def test_decade_director_and_actor_pages(client):
    era = client.post("/recommend", json=body(("era", "1990"), limit=50)).json()
    assert era["results"] and all(x["year"] == 1994 for x in era["results"])
    director = client.post("/recommend", json=body(("director", "Bo Maker"), limit=50)).json()
    ids = {x["tmdb_id"] for x in director["results"]}
    assert ids and ids <= {1000 + i for i in range(0, 60, 6)}
    actor = client.post("/recommend", json=body(("actor", "Cy Extra"), limit=50)).json()
    assert actor["facet"]["total"] == 20


def test_unknown_facet_is_404_and_bad_kind_422(client):
    assert client.post("/recommend", json=body(("genre", "Western"))).status_code == 404
    bad = body()
    bad["facets"] = [{"kind": "mood", "values": ["x"]}]
    assert client.post("/recommend", json=bad).status_code == 422


def test_facet_page_has_no_extras_and_combines_with_providers(client):
    r = client.post(
        "/recommend", json=body(("genre", "Drama"), bundle=True, branch_out=6, limit=10)
    ).json()
    assert r["enjoyed"] is None and r["branch_out"] is None and r["wildcard"] is None
    both = client.post(
        "/recommend", json=body(("genre", "Drama"), providers=["Netflix"], limit=50)
    ).json()
    assert both["results"]
    assert all("Netflix" in x["providers"] and "Drama" in x["genres"] for x in both["results"])


def test_masks_are_numpy_bool_arrays():
    m = decorated().facet_mask("genre", "Drama")
    assert isinstance(m, np.ndarray) and m.dtype == bool and idx(decorated(), "A00") == 0


# ------------------------------------------------------------------ combined filters


def test_two_filters_combine_with_and(client):
    r = client.post("/recommend", json=body(("genre", "Drama"), ("era", "1990"), limit=50)).json()
    assert r["facet"]["facets"] == [
        {"kind": "genre", "values": ["Drama"], "mode": "all"},
        {"kind": "era", "values": ["1990s"], "mode": "any"},
    ]
    snap = client.snap
    both = snap.facet_mask("genre", "Drama") & snap.facet_mask("era", "1990")
    assert r["facet"]["total"] == int(both.sum())
    assert r["results"] and all("Drama" in x["genres"] and x["year"] == 1994 for x in r["results"])


def test_combined_filters_never_change_a_score(client):
    flat = client.post("/recommend", json=body(limit=50)).json()["results"]
    flat += client.post("/recommend", json=body(limit=50, offset=50)).json()["results"]
    scores = {x["tmdb_id"]: x["score"] for x in flat}
    r = client.post("/recommend", json=body(("genre", "Drama"), ("era", "2000"), limit=50)).json()
    assert r["results"]
    for x in r["results"]:
        assert x["score"] == pytest.approx(scores[x["tmdb_id"]])


def test_filters_that_never_meet_give_an_empty_page_not_an_error(client):
    # every film in cluster B is a comedy and Ann Actor is only in cluster A
    r = client.post("/recommend", json=body(("genre", "Comedy"), ("actor", "Ann Actor"))).json()
    assert r["results"] == [] and r["facet"]["total"] == 0


def test_one_filter_of_each_kind_at_most(client):
    two_genres = body(("genre", "Drama"), ("genre", "Crime"))
    assert client.post("/recommend", json=two_genres).status_code == 422


def test_a_filter_the_catalog_lacks_is_still_a_404_among_others(client):
    assert (
        client.post("/recommend", json=body(("genre", "Drama"), ("era", "1850"))).status_code == 404
    )


# ------------------------------------------------------------------ several values of one kind


def test_all_of_two_genres_means_films_that_are_both():
    snap = decorated()  # Drama = A and C, Crime = C only
    both = snap.facet_values_mask("genre", ["Drama", "Crime"], "all")
    assert both.sum() == 20 and not both[:20].any() and both[40:].all()


def test_any_of_two_genres_means_films_that_are_either():
    snap = decorated()
    either = snap.facet_values_mask("genre", ["Comedy", "Crime"], "any")
    assert either.sum() == 40 and not either[:20].any()  # B and C


def test_decades_are_always_any():
    snap = decorated()
    both = snap.facet_values_mask("era", ["1980", "2000"], "all")
    assert both.sum() == 40  # "all" of two decades would be nothing, so it means either


def test_one_value_is_the_same_in_either_mode():
    snap = decorated()
    assert (
        snap.facet_values_mask("genre", ["Drama"], "all")
        == snap.facet_values_mask("genre", ["Drama"], "any")
    ).all()


def test_romance_and_comedy_through_the_api(client):
    r = client.post("/recommend", json=body(("genre", ["Drama", "Crime"], "all"), limit=50)).json()
    assert r["facet"]["facets"] == [{"kind": "genre", "values": ["Drama", "Crime"], "mode": "all"}]
    assert r["facet"]["total"] == 20
    assert r["results"] and all({"Drama", "Crime"} <= set(x["genres"]) for x in r["results"])


def test_drama_or_comedy_through_the_api(client):
    r = client.post("/recommend", json=body(("genre", ["Comedy", "Crime"], "any"), limit=50)).json()
    assert r["facet"]["total"] == 40
    assert r["results"] and all({"Comedy", "Crime"} & set(x["genres"]) for x in r["results"])


def test_one_unknown_value_among_several_is_a_404(client):
    assert (
        client.post("/recommend", json=body(("genre", ["Drama", "Western"], "any"))).status_code
        == 404
    )


def test_too_many_values_or_a_bad_mode_is_rejected(client):
    many = body(("genre", [f"g{i}" for i in range(9)]))
    assert client.post("/recommend", json=many).status_code == 422
    bad = body(("genre", ["Drama"]))
    bad["facets"][0]["mode"] = "some"
    assert client.post("/recommend", json=bad).status_code == 422
    empty = body(("genre", []))
    assert client.post("/recommend", json=empty).status_code == 422


# ------------------------------------------------------------------ keywords


def with_keywords(snap):
    for i in range(0, 20):
        snap.keywords[i] = ["time travel", "heist"] if i % 2 == 0 else ["time travel"]
    for i in range(40, 50):
        snap.keywords[i] = ["heist"]
    return snap


def test_keyword_mask_and_modes():
    snap = with_keywords(decorated())
    assert snap.facet_mask("keyword", "Time Travel").sum() == 20
    both = snap.facet_values_mask("keyword", ["time travel", "heist"], "all")
    assert both.sum() == 10
    either = snap.facet_values_mask("keyword", ["time travel", "heist"], "any")
    assert either.sum() == 30
    assert snap.facet_name("keyword", "HEIST") == "heist"


def test_keywords_endpoint_counts_and_searches(client):
    with_keywords(client.snap)
    r = client.get("/keywords").json()["keywords"]
    assert {(k["name"], k["count"]) for k in r} == {("heist", 20), ("time travel", 20)}
    assert r[0]["name"] == "heist"  # equal counts sort by name
    hit = client.get("/keywords", params={"q": "heis"}).json()["keywords"]
    assert [k["name"] for k in hit] == ["heist"]


def test_keyword_page_through_the_api(client):
    with_keywords(client.snap)
    r = client.post("/recommend", json=body(("keyword", "heist"), limit=50)).json()
    assert r["facet"]["total"] == 20
    ids = {x["tmdb_id"] for x in r["results"]}
    assert ids and ids <= {1000 + i for i in [*range(0, 20, 2), *range(40, 50)]}
    both = client.post(
        "/recommend", json=body(("keyword", ["heist", "time travel"], "all"), limit=50)
    ).json()
    assert both["facet"]["total"] == 10
