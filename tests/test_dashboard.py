"""The private dashboard page: correct numbers, accessible, self-contained, nothing injected."""

from datetime import UTC, datetime

import dashboard as db
import usage_report as ur

LOG = """\
2026-11-20 10:00:01,000 INFO plotpoints.api POST /recommend 200 80ms
2026-11-20 10:00:01,001 INFO plotpoints.api.events event=recommend members=1 facets=none multi=0 any_mode=0 providers=0 paged=0 wildcard=1 empty=0 liked=15-49
2026-11-20 10:01:00,000 INFO plotpoints.api POST /recommend 200 200ms
2026-11-20 10:01:00,001 INFO plotpoints.api.events event=recommend members=2 facets=none multi=0 any_mode=0 providers=0 paged=0 wildcard=0 empty=0 liked=5-14
2026-11-20 10:03:00,000 INFO plotpoints.api POST /import/letterboxd 200 900ms
2026-11-20 10:03:00,001 INFO plotpoints.api.events event=import kind=username entries=15-49
2026-11-20 10:04:01,000 INFO plotpoints.api POST /consent 200 30ms
2026-11-20 10:04:01,001 INFO plotpoints.api.events event=consent source=export films=200+
2026-11-21 09:00:00,000 INFO plotpoints.api POST /recommend 500 9ms
"""  # noqa: E501
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def page(status=None, text=LOG):
    return db.render_html(ur.parse(text.splitlines()), status, NOW)


def test_the_page_has_the_headline_numbers():
    html = page()
    assert "<title>PlotPoints dashboard</title>" in html
    assert "Built 2026-11-21 12:00 UTC" in html
    assert (
        '<div class="n">5</div><div class="t">Requests</div>' in html
    )  # 4 on the 20th, 1 on the 21st
    assert '<div class="n">1</div><div class="t">Server errors</div>' in html
    assert "100% kept their ratings" in html  # one import, one kept copy
    assert '<div class="n">1</div><div class="t">Group lists</div>' in html


def test_every_chart_has_a_label_and_a_table_alternative():
    html = page()
    assert html.count('role="img"') == 3
    assert 'aria-label="Requests per day"' in html
    assert "<caption>Numbers per day (the charts above, as a table)</caption>" in html


def test_it_is_self_contained():
    html = page()
    assert "<script" not in html and "src=" not in html
    assert "http://" not in html and "https://" not in html


def test_live_check_results_are_shown_with_words_not_just_colour():
    html = page(
        [("api health", "PASS", "ok in 40 ms"), ("https certificates", "WARN", "api 10 days")]
    )
    assert "Live checks" in html and ">PASS<" in html and ">WARN<" in html


def test_nothing_from_the_log_or_checks_can_inject_markup():
    html = page([("x", "FAIL", "<script>alert(1)</script>")])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_an_empty_log_says_so_instead_of_breaking():
    html = db.render_html({}, None, NOW)
    assert "No log lines with a date were found" in html and "<svg" not in html


def test_only_the_recent_days_are_charted():
    lines = [
        f"2026-{m:02d}-{d:02d} 10:00:00,000 INFO plotpoints.api GET /meta 200 3ms"
        for m in (9, 10) for d in range(1, 29)
    ]  # fmt: skip
    html = db.render_html(ur.parse(lines), None, NOW)
    assert html.count("<tr>") - 1 <= db.RECENT_DAYS  # header row aside, at most 30 day rows
