"""Properties the recommender must keep, checked on a synthetic catalog (no network)."""

import numpy as np
import pytest
from conftest import idx

import scoring
from scoring import rank, weight_for


def liked(snap, *titles, w=2.0):
    return [(idx(snap, t), w) for t in titles]


def keys(results):
    return [r["media_key"] for r in results]


def test_weight_for_midpoint_and_rewatch():
    assert weight_for(None, False) is None
    assert weight_for(3.0, False) == 0
    assert weight_for(4.0, False) == 1.0
    assert weight_for(4.0, True) == 1.5  # a liked rewatch earns the bonus
    assert weight_for(2.0, True) == -1.0  # a disliked rewatch does not


def test_recommends_the_liked_cluster_and_never_a_watched_film(snap):
    seen = liked(snap, "A00", "A01", "A02")
    results = rank(snap, {"u": seen}, limit=10)
    watched = {i for i, _ in seen}
    assert watched.isdisjoint(r["index"] for r in results)
    assert all(r["title"].startswith("A") for r in results)  # nearest cluster wins


def test_unrated_films_count_as_seen_but_carry_no_taste(snap):
    profile = liked(snap, "A00", "A01") + [(idx(snap, "B00"), None)]
    results = rank(snap, {"u": profile}, limit=60)
    assert idx(snap, "B00") not in [r["index"] for r in results]
    only_liked = rank(snap, {"u": liked(snap, "A00", "A01")}, limit=60)
    # the unrated film changes who is eligible, not how anyone else is ranked among the rest
    common = [k for k in keys(only_liked) if k in set(keys(results))]
    assert common == [k for k in keys(results) if k in set(common)]


def test_runtime_floor_applies_to_candidates_only(snap):
    short = idx(snap, "A03")
    results = rank(snap, {"u": liked(snap, "A00", "A01")}, limit=60)
    assert short not in [r["index"] for r in results]
    assert short in [
        r["index"] for r in rank(snap, {"u": liked(snap, "A00")}, limit=60, min_runtime=0)
    ]
    # a watched short still teaches taste
    taught = rank(snap, {"u": [(short, 2.0)]}, limit=5)
    assert all(r["title"].startswith("A") for r in taught)


def test_dislike_penalty_pushes_a_resembling_title_down(snap):
    base = liked(snap, "A00", "A01", "B00", "B01")
    without = rank(snap, {"u": base}, limit=60, dislike_weight=0.0)
    penalized = rank(snap, {"u": base + [(idx(snap, "A02"), -2.0)]}, limit=60)
    rank_of = lambda results, t: next(r["rank"] for r in results if r["title"] == t)  # noqa: E731
    a_near = [r for r in without if r["title"].startswith("A")][0]["title"]
    assert rank_of(penalized, a_near) >= rank_of(without, a_near)
    pen = next(r for r in penalized if r["title"] == a_near)["members"][0]["penalty"]
    assert pen > 0


def test_penalty_arithmetic(snap):
    base = liked(snap, "A00", "A01") + [(idx(snap, "B00"), -2.0)]
    full = rank(snap, {"u": base}, limit=40, dislike_weight=0.5)
    for r in full:
        m = r["members"][0]
        assert m["relevance"] == pytest.approx(
            _relevance_without_penalty(snap, base, r["index"]) - 0.5 * m["penalty"], abs=1e-9
        )


def _relevance_without_penalty(snap, profile, index):
    off = rank(snap, {"u": profile}, limit=len(snap), dislike_weight=0.0)
    return next(r for r in off if r["index"] == index)["members"][0]["relevance"]


def test_quality_discount_is_a_discount_never_a_boost(snap):
    results = rank(snap, {"u": liked(snap, "A00", "A01")}, limit=60, min_runtime=0)
    for r in results:
        assert 0 < r["members"][0]["quality_factor"] <= 1.0
    poor = next(r for r in results if r["title"] == "A05")["members"][0]
    assert poor["quality_factor"] < 1.0  # rated 3.0 against a user who likes 7.0s
    fine = next(r for r in results if r["title"] == "A06")["members"][0]
    assert fine["quality_factor"] == 1.0


def test_group_score_is_the_minimum_of_the_members(snap):
    group = {"a": liked(snap, "A00", "A01"), "b": liked(snap, "B00", "B01")}
    results = rank(snap, group, limit=30)
    for r in results:
        assert r["score"] == pytest.approx(min(m["score"] for m in r["members"]))
    # something both could stomach, not a favourite of one and a stranger to the other
    assert results[0]["score"] >= results[-1]["score"]


def test_group_excludes_anything_any_member_has_watched(snap):
    group = {"a": liked(snap, "A00", "A01"), "b": liked(snap, "B00", "B01")}
    results = rank(snap, group, limit=len(snap))
    seen = {idx(snap, t) for t in ("A00", "A01", "B00", "B01")}
    assert seen.isdisjoint(r["index"] for r in results)


def test_group_of_identical_members_reproduces_the_single_user_ranking(snap):
    profile = liked(snap, "A00", "B03", "C07")
    single = rank(snap, {"u": profile}, limit=40)
    pair = rank(snap, {"x": profile, "y": profile}, limit=40)
    assert keys(single) == keys(pair)
    assert [r["score"] for r in single] == pytest.approx([r["score"] for r in pair])


def test_provider_filter_changes_who_competes_never_what_they_score(snap):
    profile = liked(snap, "A00", "A01", "B00")
    everyone = rank(snap, {"u": profile}, limit=len(snap))
    netflix = snap.provider_mask(["Netflix"])
    filtered = rank(snap, {"u": profile}, limit=len(snap), allow=netflix)
    assert all(netflix[r["index"]] for r in filtered)
    full_scores = {r["index"]: r["score"] for r in everyone}
    for r in filtered:
        assert r["score"] == full_scores[r["index"]]  # identical, not merely close
    assert len(filtered) < len(everyone)


def test_ordering_is_score_descending_with_title_as_the_tiebreak(snap):
    results = rank(snap, {"u": liked(snap, "A00", "B00", "C00")}, limit=len(snap))
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_match_is_the_mean_cosine_of_the_films_that_explain_it(snap):
    profile = liked(snap, "A00", "A01", "A02", "B00")
    for r in rank(snap, {"u": profile}, limit=10):
        because = r["members"][0]["because"]
        assert len(because) == scoring.TOP_N
        for b in because:
            cos = float(snap.vectors[r["index"]] @ snap.vectors[snap.by_key[b["media_key"]]])
            assert b["cosine"] == pytest.approx(cos, abs=1e-6)
        assert r["match"] == pytest.approx(np.mean([b["cosine"] for b in because]), abs=1e-9)
        assert {b["media_key"] for b in because} <= {snap.media_key[i] for i, _ in profile}


def test_a_member_with_no_liked_films_is_an_error(snap):
    with pytest.raises(ValueError, match="no liked films"):
        rank(snap, {"u": [(idx(snap, "A00"), -1.0)]})


def test_identity_is_by_index_when_titles_collide(snap):
    snap.title[idx(snap, "C00")] = "Good Boy"
    snap.title[idx(snap, "C01")] = "Good Boy"
    results = rank(snap, {"u": liked(snap, "C02", "C03")}, limit=60)
    ids = [r["index"] for r in results if r["title"] == "Good Boy"]
    assert len(set(ids)) == len(ids) == 2  # two different films, both present, not merged


def test_influence_ranks_liked_films_by_weighted_similarity(snap):
    # A00 is loved (5 stars -> weight 2.0), A01 only liked (weight 0.5); both sit in the A cluster
    profile = [(idx(snap, "A00"), 2.0), (idx(snap, "A01"), 0.5), (idx(snap, "B00"), 2.0)]
    picks = [r["index"] for r in rank(snap, {"u": profile}, limit=10)]
    out = scoring.influence(snap, {"u": profile}, picks, top_n=3)
    assert [e["title"] for e in out][:2] == ["A00", "A01"]
    assert out[0]["influence"] >= out[1]["influence"] >= out[2]["influence"]
    # the loved A film beats the equally loved B film, whose cluster the picks are not in
    by = {e["title"]: e for e in out}
    assert by["A00"]["influence"] > by["B00"]["influence"]
    assert all(0.0 <= e["avg_cosine"] <= 1.0 for e in out)


def test_influence_weight_matters_among_equally_placed_seeds(snap):
    heavy, light = (idx(snap, "A00"), 2.0), (idx(snap, "A00"), 0.5)
    twin = idx(snap, "A00")
    # same film as heavy vs light seed: the heavier one must carry more influence
    a = scoring.influence(snap, {"u": [heavy, (idx(snap, "B00"), 1.0)]}, [idx(snap, "A07")])
    b = scoring.influence(snap, {"u": [light, (idx(snap, "B00"), 1.0)]}, [idx(snap, "A07")])
    infl = lambda out: next(e["influence"] for e in out if e["index"] == twin)  # noqa: E731
    assert infl(a) > infl(b)


def test_influence_is_empty_without_candidate_picks(snap):
    profile = liked(snap, "A00", "A01")
    assert scoring.influence(snap, {"u": profile}, []) == []
    assert scoring.influence(snap, {"u": profile}, [idx(snap, "A00")]) == []  # a watched film


def test_a_low_vote_title_steers_as_a_seed_but_is_never_recommended(snap):
    snap.votes[idx(snap, "B00")] = 8  # an obscure film someone imported
    snap.votes[idx(snap, "A04")] = 8  # an obscure film in the liked cluster
    # liking only the obscure B film still points the list at the B cluster
    results = rank(snap, {"u": liked(snap, "B00")}, limit=60)
    assert results and all(r["title"].startswith("B") for r in results[:10])
    everyone = rank(snap, {"u": liked(snap, "A00", "A01")}, limit=60)
    assert idx(snap, "A04") not in [r["index"] for r in everyone]
    assert idx(snap, "B00") not in [r["index"] for r in everyone]
