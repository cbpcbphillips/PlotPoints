# ruff: noqa: E501  (the page template is HTML and CSS, whose lines are not worth wrapping)
"""A private, local dashboard: how the live site is doing, from the API's own anonymous log.

Builds one self-contained HTML file (no scripts, no external requests, light and dark, every chart
also a table) at data/reports/dashboard.html. Nothing is hosted: the file lives on your machine, so
there is nothing to log in to and nothing to leak.

    just dashboard --gcloud                      # pull the live log with gcloud, then build
    just dashboard --log api.log --open          # or build from a saved log; open it when done
    just dashboard --gcloud --status --open      # also run the live health checks

Traffic and usage come from the log (see api/events.py and usage_report.py): requests, errors,
speed, imports, kept ratings, group and browse use. Visits, countries and devices are in
Cloudflare Web Analytics, and uptime and alerts are in Google Cloud's console (docs/deploy.md);
this page links to where they live instead of pretending to hold them.
"""

from __future__ import annotations

import argparse
import html
import os
import shutil
import subprocess
import sys
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from paths import DATA_DIR
from usage_report import Day, parse, summarize

OUT = DATA_DIR / "reports" / "dashboard.html"
RECENT_DAYS = 30


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def bar_chart(title: str, series: list[tuple[str, list[int]]], labels: list[str]) -> str:
    """Stacked bars, one per day, as inline SVG. The numbers are in the table below it."""
    if not labels:
        return ""
    width, height, left, bottom = 640, 150, 34, 22
    totals = [sum(s[1][i] for s in series) for i in range(len(labels))]
    top = max(max(totals), 1)
    slot = (width - left) / len(labels)
    bar = max(2.0, slot * 0.7)
    colors = ["var(--c1)", "var(--c2)", "var(--c3)"]
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}" class="chart">',
        f'<text x="2" y="12" class="axis">{top}</text>',
        f'<line x1="{left}" y1="{height - bottom}" x2="{width}" y2="{height - bottom}" class="rule"/>',
    ]
    for i, label in enumerate(labels):
        x = left + i * slot + (slot - bar) / 2
        y = height - bottom
        for (name, values), color in zip(series, colors, strict=False):
            h = (height - bottom - 16) * values[i] / top
            if h > 0:
                y -= h
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar:.1f}" height="{h:.1f}" '
                    f'fill="{color}"><title>{esc(label)}: {esc(name)} {values[i]}</title></rect>'
                )
        if len(labels) <= 12 or i % 5 == 0:
            parts.append(
                f'<text x="{x + bar / 2:.1f}" y="{height - 6}" text-anchor="middle" '
                f'class="axis">{esc(label[5:])}</text>'
            )
    parts.append("</svg>")
    legend = " ".join(
        f'<span class="key"><i style="background:{c}"></i>{esc(n)}</span>'
        for (n, _), c in zip(series, colors, strict=False)
    )
    return (
        f"<figure><figcaption>{esc(title)}</figcaption>{''.join(parts)}<div>{legend}</div></figure>"
    )


def table(headers: list[str], rows: list[list[object]], caption: str) -> str:
    head = "".join(f"<th scope='col'>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><caption>{esc(caption)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_html(
    days: dict[str, Day],
    status: list[tuple[str, str, str]] | None = None,
    generated: datetime | None = None,
) -> str:
    """The whole page. `status` is (label, PASS|WARN|FAIL, detail) rows, if the checks were run."""
    generated = generated or datetime.now(UTC)
    recent = list(days.items())[-RECENT_DAYS:]
    labels = [d for d, _ in recent]
    sums = [summarize(day) for _, day in recent]

    def col(key: str) -> list[int]:
        return [s[key] or 0 for s in sums]

    requests, errors = sum(col("requests")), sum(col("errors"))
    imports = sum(sum(s["imports"].values()) for s in sums)
    consents = sum(col("consents"))
    group, browse = sum(col("group_requests")), sum(col("browse_requests"))
    p95s = [s["recommend_p95"] for s in sums if s["recommend_p95"] is not None]
    err_pct = f"{100 * errors / requests:.1f}%" if requests else "n/a"
    consent_pct = f"{100 * consents / imports:.0f}%" if imports else "n/a"

    cards = [
        ("Requests", requests, f"{len(labels)} days"),
        ("Server errors", errors, f"{err_pct} of requests"),
        ("Slowest day, /recommend p95", f"{max(p95s)} ms" if p95s else "n/a", "milliseconds"),
        ("Imports", imports, f"{consent_pct} kept their ratings"),
        ("Group lists", group, "recommendation requests for 2+ people"),
        ("Browse lists", browse, "genre, theme, director, actor, decade"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="n">{esc(v)}</div><div class="t">{esc(t)}</div>'
        f'<div class="s">{esc(s)}</div></div>'
        for t, v, s in cards
    )

    status_html = ""
    if status:
        rows = [[label, result, detail] for label, result, detail in status]
        status_html = "<h2>Live checks</h2>" + table(
            ["Check", "Result", "Detail"], rows, "Results of the live health checks"
        )

    daily = [
        [
            d,
            s["requests"],
            s["errors"],
            "" if s["recommend_p50"] is None else f"{s['recommend_p50']} / {s['recommend_p95']}",
            sum(s["imports"].values()),
            s["consents"],
            s["recommend_calls"],
            s["group_requests"],
            s["browse_requests"],
            s["wildcard_shown_pct"],
        ]
        for d, s in zip(labels, sums, strict=True)
    ]
    main_only = [
        max(0, s["recommend_calls"] - s["group_requests"] - s["browse_requests"]) for s in sums
    ]
    charts = (
        bar_chart("Requests per day", [("requests", col("requests"))], labels)
        + bar_chart(
            "Imports per day (kept = ratings kept anonymously)",
            [
                ("kept", [min(s["consents"], sum(s["imports"].values())) for s in sums]),
                (
                    "not kept",
                    [max(0, sum(s["imports"].values()) - s["consents"]) for s in sums],
                ),
            ],
            labels,
        )
        + bar_chart(
            "Recommendation requests per day",
            [
                ("main list", main_only),
                ("group", col("group_requests")),
                ("browse", col("browse_requests")),
            ],
            labels,
        )
    )
    empty = (
        "<p>No log lines with a date were found. Pull the log first (see the top of this file).</p>"
    )
    body = (
        (f"<section>{card_html}</section>" if recent else empty)
        + status_html
        + ("<h2>Per day</h2>" + charts if recent else "")
        + (
            table(
                [
                    "Day",
                    "Requests",
                    "5xx",
                    "/recommend p50 / p95 ms",
                    "Imports",
                    "Kept",
                    "Rec. requests",
                    "Group",
                    "Browse",
                    "Comfort-zone shown",
                ],
                daily,
                "Numbers per day (the charts above, as a table)",
            )
            if recent
            else ""
        )
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlotPoints dashboard</title>
<style>
:root {{ --bg:#f6f4ee; --fg:#14172a; --muted:#4a5070; --card:#ffffff; --line:#8a8f9e; --c1:#3d4bd6; --c2:#8f5a0f; --c3:#137a52; --ok:#1b6b43; --warn:#8a5a00; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1e2338; --fg:#eceaf4; --muted:#b9bed6; --card:#272d47; --line:#7c86a8; --c1:#8fa0ff; --c2:#f5b84b; --c3:#4ade9a; --ok:#4ade9a; --warn:#f5b84b; --bad:#ff8a7e; }} }}
body {{ margin:0 auto; max-width:980px; padding:24px 16px 64px; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,sans-serif; }}
h1 {{ margin:0 0 4px; }} h2 {{ margin:32px 0 8px; }} p.sub {{ margin:0; color:var(--muted); }}
section {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-top:20px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }}
.n {{ font-size:1.9rem; font-weight:700; }} .t {{ font-weight:600; }} .s {{ color:var(--muted); font-size:.9rem; }}
figure {{ margin:16px 0; }} figcaption {{ font-weight:600; }} .chart {{ width:100%; height:auto; }}
.axis {{ fill:var(--muted); font-size:10px; }} .rule {{ stroke:var(--line); }}
.key {{ margin-right:14px; font-size:.9rem; }} .key i {{ display:inline-block; width:10px; height:10px; margin-right:5px; }}
table {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:.92rem; }}
caption {{ text-align:left; color:var(--muted); padding:4px 0; }}
th,td {{ border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; }} th {{ font-weight:600; }}
a {{ color:var(--fg); }}
</style></head><body>
<h1>PlotPoints dashboard</h1>
<p class="sub">Built {esc(generated.strftime("%Y-%m-%d %H:%M UTC"))} from the API's anonymous log. Private: this file stays on your machine.</p>
{body}
<h2>Where the rest lives</h2>
<ul>
<li><b>Visits, countries, devices:</b> Cloudflare dashboard, Web Analytics.</li>
<li><b>Uptime and alerts:</b> Google Cloud console, Monitoring, Uptime checks (set up as in docs/deploy.md).</li>
<li><b>Live instances, memory, latency:</b> Google Cloud console, Cloud Run, the service's Metrics tab.</li>
<li><b>Spend:</b> Google Cloud console, Billing, Budgets.</li>
</ul>
<p class="sub">Not measurable here, by design: unique or returning people. Nothing in the log can tell two visitors apart.</p>
</body></html>
"""


def read_log(args: argparse.Namespace) -> list[str]:
    if args.gcloud:
        exe = shutil.which("gcloud")
        if not exe:
            raise SystemExit("gcloud is not installed or not on PATH (see docs/deploy.md).")
        region = (
            args.region or os.environ.get("GCP_REGION") or dotenv_values(".env").get("GCP_REGION")
        )
        cmd = [exe, "run", "services", "logs", "read", args.service, "--limit", str(args.limit)]
        if region:
            cmd += ["--region", region]
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise SystemExit(f"gcloud failed: {done.stderr.strip()[:300]}")
        lines = done.stdout.splitlines()
        if not lines:
            raise SystemExit(
                "gcloud returned no log lines. Check GCP_REGION in .env (or pass --region) "
                "and that the service name is right."
            )
        return lines
    if args.log:
        return Path(args.log).read_text(encoding="utf-8", errors="replace").splitlines()
    return sys.stdin.read().splitlines()


def run_status() -> list[tuple[str, str, str]]:
    """The live checks as rows, using the same probes as `just status`."""
    from check_common import CheckWarning
    from status_check import build_checks, setting

    api, site = setting("PLOTPOINTS_API_URL", None), setting("PLOTPOINTS_SITE_URL", None)
    if not api or not site:
        return [("configuration", "WARN", "Set PLOTPOINTS_API_URL and PLOTPOINTS_SITE_URL in .env")]
    rows = []
    for label, probe in build_checks(api, site):
        try:
            rows.append((label, "PASS", probe() or ""))
        except CheckWarning as exc:
            rows.append((label, "WARN", str(exc)))
        except Exception as exc:  # noqa: BLE001 - a failing probe is a result, not a crash
            rows.append((label, "FAIL", f"{type(exc).__name__}: {exc}"))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the private PlotPoints dashboard.")
    parser.add_argument("--log", help="a saved log file (default: standard input)")
    parser.add_argument("--gcloud", action="store_true", help="pull the live Cloud Run log first")
    parser.add_argument("--service", default="plotpoints-api")
    parser.add_argument("--region", help="Cloud Run region (default: GCP_REGION)")
    parser.add_argument("--limit", type=int, default=20000, help="log lines to pull")
    parser.add_argument("--status", action="store_true", help="also run the live health checks")
    parser.add_argument("--open", action="store_true", help="open the page in a browser")
    args = parser.parse_args()

    days = parse(read_log(args))
    page = render_html(days, run_status() if args.status else None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT} ({len(days)} day(s) of log)")
    if args.open:
        webbrowser.open(OUT.resolve().as_uri())


if __name__ == "__main__":
    main()
