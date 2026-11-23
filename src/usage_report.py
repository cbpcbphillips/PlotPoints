"""Turn the API's log into daily usage numbers: the evidence of demand.

The API logs one count-only line per request ("POST /recommend 200 84ms") and one anonymous event
line per notable action ("event=recommend members=2 facets=genre liked=15-49"); see api/events.py.
Neither holds anything that identifies a person, so this report cannot either. It cannot count
unique people or returning visitors (there is nothing to count them by); Cloudflare Web Analytics
covers visits, countries and devices.

Usage (any log text on stdin, or a file):

    gcloud run services logs read plotpoints-api --region REGION --limit 20000 | just usage
    just usage api.log
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
ACCESS = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD) (\S+) (\d{3}) (\d+)ms\b")
EVENT = re.compile(r"\bevent=([a-z_]+)((?: [a-z_]+=[a-z0-9_,<>+-]+)*)")
PAIR = re.compile(r"([a-z_]+)=([a-z0-9_,<>+-]+)")


@dataclass
class Day:
    requests: int = 0
    errors: int = 0  # 5xx
    routes: Counter = field(default_factory=Counter)
    recommend_ms: list[int] = field(default_factory=list)
    events: list[tuple[str, dict[str, str]]] = field(default_factory=list)


def parse(lines) -> dict[str, Day]:
    """Group log lines by the first date on each line. Lines without a date, or neither an access
    line nor an event, are ignored."""
    days: dict[str, Day] = defaultdict(Day)
    for line in lines:
        date = DATE.search(line)
        if not date:
            continue
        day = days[date.group(1)]
        access = ACCESS.search(line)
        if access:
            _, route, status, ms = access.groups()
            if route == "/health":  # the keep-warm ping and platform health checks, not visitors
                continue
            day.requests += 1
            day.routes[route] += 1
            if status.startswith("5"):
                day.errors += 1
            if route == "/recommend" and status == "200":
                day.recommend_ms.append(int(ms))
        event = EVENT.search(line)
        if event:
            day.events.append((event.group(1), dict(PAIR.findall(event.group(2)))))
    return dict(sorted(days.items()))


def _pct(part: int, whole: int) -> str:
    return "n/a" if not whole else f"{100 * part / whole:.0f}%"


def summarize(day: Day) -> dict:
    """The numbers for one day, as plain values (also what `--json`-style callers can reuse)."""
    rec = [f for name, f in day.events if name == "recommend"]
    first_pages = [f for f in rec if f.get("paged") == "0"]
    solo_main = [f for f in first_pages if f.get("members") == "1" and f.get("facets") == "none"]
    imports = Counter(f.get("kind", "?") for name, f in day.events if name == "import")
    consents = sum(1 for name, _ in day.events if name == "consent")
    liked = Counter(f.get("liked", "?") for f in first_pages)
    facet_kinds: Counter = Counter()
    for f in rec:
        if f.get("facets", "none") != "none":
            facet_kinds.update(f["facets"].split(","))
    ms = sorted(day.recommend_ms)
    return {
        "requests": day.requests,
        "errors": day.errors,
        "recommend_p50": int(statistics.median(ms)) if ms else None,
        "recommend_p95": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else None,
        "recommend_calls": len(rec),
        "group_requests": sum(1 for f in rec if int(f.get("members", "1")) > 1),
        "browse_requests": sum(1 for f in rec if f.get("facets", "none") != "none"),
        "facet_kinds": dict(facet_kinds),
        "multi_value_browses": sum(1 for f in rec if f.get("multi") == "1"),
        "paged_requests": sum(1 for f in rec if f.get("paged") == "1"),
        "imports": dict(imports),
        "consents": consents,
        "deletions": sum(1 for name, _ in day.events if name == "delete"),
        "wildcard_shown_pct": _pct(
            sum(1 for f in solo_main if f.get("wildcard") == "1"), len(solo_main)
        ),
        "liked_buckets": dict(liked),
        "top_routes": day.routes.most_common(8),
    }


def render(days: dict[str, Day]) -> str:
    if not days:
        return "No log lines with a date were found."
    out: list[str] = []
    for date, day in days.items():
        s = summarize(day)
        imports = s["imports"]
        total_imports = sum(imports.values())
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(imports.items())) or "none"
        kept = f"{s['consents']} = {_pct(s['consents'], total_imports)} of imports"
        out.append(f"== {date} ==")
        out.append(f"  requests {s['requests']}   server errors {s['errors']}")
        if s["recommend_p50"] is not None:
            out.append(f"  /recommend  p50 {s['recommend_p50']} ms   p95 {s['recommend_p95']} ms")
        out.append(
            f"  imports {total_imports} ({kinds})   kept ratings (consent) {kept}"
            f"   deletions {s['deletions']}"
        )
        facets = ", ".join(f"{k} {v}" for k, v in sorted(s["facet_kinds"].items()))
        out.append(
            f"  recommendation requests {s['recommend_calls']}: group {s['group_requests']},"
            f" browse {s['browse_requests']}"
            + (f" ({facets})" if facets else "")
            + f", multi-value {s['multi_value_browses']}, paging {s['paged_requests']}"
        )
        out.append(f"  comfort-zone pick shown on {s['wildcard_shown_pct']} of main lists")
        if s["liked_buckets"]:
            buckets = ", ".join(f"{k}: {v}" for k, v in sorted(s["liked_buckets"].items()))
            out.append(f"  liked films per list: {buckets}")
        out.append("  busiest routes: " + ", ".join(f"{r} {n}" for r, n in s["top_routes"]))
        out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily usage numbers from the API log.")
    parser.add_argument("file", nargs="?", help="a log file (default: read standard input)")
    args = parser.parse_args()
    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            print(render(parse(fh)))
    else:
        print(render(parse(sys.stdin)))


if __name__ == "__main__":
    main()
