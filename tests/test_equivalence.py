"""The numpy scorer (served) must agree with the SQL scorer (batch). Needs live Snowflake.

Run with:  uv run pytest -m snowflake

The two implementations exist twice on purpose (roadmap decision 8), so this is the guard that
keeps that safe. They are not bit-identical: the snapshot stores float16 vectors, so scores differ
in the third decimal. What must hold is the *ranking* at the top, which is what a user sees.
"""

import pytest

pytestmark = pytest.mark.snowflake

import snapshot  # noqa: E402
from connection.snowflake import get_snowflake_connection  # noqa: E402
from publish_snapshot import latest_directory  # noqa: E402
from recommend import build_profiles, score_profiles  # noqa: E402
from scoring import rank  # noqa: E402

USER = "VetOW"
TOP = 50


@pytest.fixture(scope="module")
def snap():
    return snapshot.load(latest_directory())


@pytest.fixture(scope="module")
def conn():
    with get_snowflake_connection() as c:
        yield c


def _numpy_profiles(snap, sql_profiles):
    return {
        member: [
            (snap.by_key[f["media_key"]], f["weight"])
            for f in films
            if f["media_key"] in snap.by_key
        ]
        for member, films in sql_profiles.items()
    }


def _compare(snap, conn, sql_profiles, **kwargs):
    sql = score_profiles(conn, sql_profiles, k=TOP, **kwargs)
    py = rank(snap, _numpy_profiles(snap, sql_profiles), limit=TOP, **kwargs)
    return sql, py


def _assert_close(sql, py):
    sql_keys = [r["media_key"] for r in sql]
    py_keys = [r["media_key"] for r in py]
    # float16 may swap two near-ties; the SETS of the top 50 and the top 10's order must agree
    assert set(sql_keys) == set(py_keys), set(sql_keys) ^ set(py_keys)
    assert sql_keys[:10] == py_keys[:10]
    by_key = {r["media_key"]: r["score"] for r in py}
    for r in sql:
        assert by_key[r["media_key"]] == pytest.approx(r["score"], abs=0.02)


def test_single_user_matches_sql(snap, conn):
    profiles = build_profiles(conn, [USER])
    _assert_close(*_compare(snap, conn, profiles))


def test_dislike_penalty_off_matches_sql(snap, conn):
    profiles = build_profiles(conn, [USER])
    _assert_close(*_compare(snap, conn, profiles, dislike_weight=0.0))


def test_group_matches_sql(snap, conn):
    films = build_profiles(conn, [USER])[USER]
    rated = [f for f in films if f["weight"] is not None]
    half = len(rated) // 2
    group = {"a": rated[:half] + [f for f in films if f["weight"] is None], "b": rated[half:]}
    # each member needs a liked film for the split to be valid
    if not all(any(f["weight"] > 0 for f in g if f["weight"] is not None) for g in group.values()):
        pytest.skip("diary too small to split into two members who each like something")
    _assert_close(*_compare(snap, conn, group))
