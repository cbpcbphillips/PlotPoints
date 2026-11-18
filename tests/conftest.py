"""Shared fixtures: a small synthetic snapshot, so scoring tests need no network or database."""

import numpy as np
import pytest

import snapshot

N_PER_CLUSTER = 20
DIM = 16


def make_snapshot(seed: int = 0) -> snapshot.Snapshot:
    """Three well-separated taste clusters (A, B, C) of 20 titles each, plus awkward cases.

    Titles are named A00..A19, B00.., C00..; unique except for two deliberate pairs that exist to
    check that identity is by index and never by title.
    """
    rng = np.random.default_rng(seed)
    centers = np.eye(DIM)[:3] * 3.0
    rows, titles = [], []
    for c, name in enumerate("ABC"):
        for i in range(N_PER_CLUSTER):
            rows.append(centers[c] + rng.normal(0, 0.6, DIM))
            titles.append(f"{name}{i:02d}")
    vectors = snapshot.normalize_rows(np.asarray(rows))
    n = len(titles)
    runtime = np.full(n, 110.0, dtype=np.float32)
    runtime[3] = 18.0  # A03 is a short: must never be recommended
    rating = np.full(n, 7.0, dtype=np.float32)
    rating[5] = 3.0  # A05: poorly rated
    votes = np.full(n, 5000, dtype=np.int64)
    providers = [[0] if i % 2 == 0 else [1] for i in range(n)]  # even -> Netflix, odd -> Hulu
    return snapshot.Snapshot(
        version="test",
        embedding_model="synthetic",
        created_at="2026-01-01T00:00:00+00:00",
        providers_as_of="2026-01-01",
        catalog_mean_rating=6.5,
        vectors=vectors,
        media_key=[f"k{i}" for i in range(n)],
        media_type=["movie"] * n,
        tmdb_id=np.arange(1000, 1000 + n, dtype=np.int64),
        title=titles,
        year=np.full(n, 2000, dtype=np.int32),
        runtime=runtime,
        rating=rating,
        votes=votes,
        poster=[None] * n,
        franchise=[None] * n,
        genres=[[] for _ in range(n)],
        providers=providers,
        provider_names=["Netflix", "Hulu"],
    )


@pytest.fixture
def snap() -> snapshot.Snapshot:
    return make_snapshot()


def idx(snap: snapshot.Snapshot, title: str) -> int:
    return snap.title.index(title)
