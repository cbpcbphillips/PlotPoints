# ruff: noqa: E501  (the sample log lines are as long as real ones)
"""The usage report: daily counts from the API log, with nothing that identifies anyone."""

import usage_report as ur

LOG = """\
2026-11-20 10:00:01,000 INFO plotpoints.api POST /recommend 200 80ms
2026-11-20 10:00:01,001 INFO plotpoints.api.events event=recommend members=1 facets=none multi=0 any_mode=0 providers=0 paged=0 wildcard=1 empty=0 liked=15-49
2026-11-20 10:00:05,000 INFO plotpoints.api POST /recommend 200 120ms
2026-11-20 10:00:05,001 INFO plotpoints.api.events event=recommend members=1 facets=none multi=0 any_mode=0 providers=0 paged=1 wildcard=0 empty=0 liked=15-49
2026-11-20 10:01:00,000 INFO plotpoints.api POST /recommend 200 200ms
2026-11-20 10:01:00,001 INFO plotpoints.api.events event=recommend members=2 facets=none multi=0 any_mode=0 providers=0 paged=0 wildcard=0 empty=0 liked=5-14
2026-11-20 10:02:00,000 INFO plotpoints.api POST /recommend 200 90ms
2026-11-20 10:02:00,001 INFO plotpoints.api.events event=recommend members=1 facets=genre,era multi=1 any_mode=1 providers=0 paged=0 wildcard=0 empty=0 liked=50-199
2026-11-20 10:03:00,000 INFO plotpoints.api POST /import/letterboxd 200 900ms
2026-11-20 10:03:00,001 INFO plotpoints.api.events event=import kind=username entries=15-49
2026-11-20 10:04:00,000 INFO plotpoints.api POST /match 200 300ms
2026-11-20 10:04:00,001 INFO plotpoints.api.events event=import kind=export rows=200+ matched=200+
2026-11-20 10:04:01,000 INFO plotpoints.api POST /consent 200 30ms
2026-11-20 10:04:01,001 INFO plotpoints.api.events event=consent source=export films=200+
2026-11-20 10:05:00,000 INFO plotpoints.api GET /film/{tmdb_id} 200 5ms
2026-11-20 10:05:01,000 INFO plotpoints.api GET /film/{tmdb_id} 404 4ms
2026-11-20 10:06:00,000 INFO plotpoints.api POST /recommend 500 9ms
2026-11-21 09:00:00,000 INFO plotpoints.api GET /health 200 1ms
snapshot 5b07b4a5e390 loaded: 28555 titles
not a log line at all
"""


def test_lines_are_grouped_by_day_and_noise_is_ignored():
    days = ur.parse(LOG.splitlines())
    assert list(days) == ["2026-11-20", "2026-11-21"]
    assert days["2026-11-21"].requests == 1


def test_one_days_numbers():
    s = ur.summarize(ur.parse(LOG.splitlines())["2026-11-20"])
    assert s["requests"] == 10 and s["errors"] == 1
    assert s["recommend_calls"] == 4 and s["group_requests"] == 1
    assert s["browse_requests"] == 1 and s["facet_kinds"] == {"genre": 1, "era": 1}
    assert s["multi_value_browses"] == 1 and s["paged_requests"] == 1
    assert s["imports"] == {"username": 1, "export": 1}
    assert s["consents"] == 1 and s["deletions"] == 0
    assert s["liked_buckets"] == {"15-49": 1, "5-14": 1, "50-199": 1}  # first pages only


def test_the_comfort_zone_share_counts_main_single_person_lists_only():
    s = ur.summarize(ur.parse(LOG.splitlines())["2026-11-20"])
    assert s["wildcard_shown_pct"] == "100%"  # the one single-person, unfiltered first page had it


def test_latency_comes_from_successful_recommends():
    s = ur.summarize(ur.parse(LOG.splitlines())["2026-11-20"])
    assert s["recommend_p50"] == 105  # 80, 90, 120, 200 -> median of the middle two
    assert s["recommend_p95"] == 200


def test_the_rendered_report_is_readable_and_has_no_identifiers():
    text = ur.render(ur.parse(LOG.splitlines()))
    assert "== 2026-11-20 ==" in text and "== 2026-11-21 ==" in text
    assert "consent) 1 = 50% of imports" in text
    assert "group 1, browse 1 (era 1, genre 1)" in text
    assert "/recommend" in text


def test_empty_input_says_so():
    assert "No log lines" in ur.render(ur.parse([]))
