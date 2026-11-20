"""Anonymous, count-only usage events, written to the log as one line each.

The point is to show demand (how many imports, how many group sessions, which features get used)
without recording anyone. So an event carries only small numbers, buckets and a handful of fixed
words, never a title, a film id, a name, a username, a token, an IP address or any free text.
`log_event` enforces that: a field whose value is not a number, a boolean or a short lower-case
word is dropped, not logged. Logging can never break a request.

A line looks like:  event=recommend members=2 facets=genre,era providers=0 paged=0 liked=15-49
`src/usage_report.py` turns the log into daily counts.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("plotpoints.api.events")

# What may appear as an event name, and a field value that is a word: lower-case letters, digits and
# a few separators. A film title, a username or a token will not survive this.
EVENTS = frozenset({"recommend", "import", "consent", "delete"})
_WORD = re.compile(r"^[a-z0-9_,<>+-]{1,40}$")
_KEY = re.compile(r"^[a-z_]{1,20}$")

# Bucket edges: a count like "a history of exactly 1,234 films" could single someone out.
_EDGES = (1, 5, 15, 50, 200)


def bucket(n: int) -> str:
    """A count as a coarse range: 0, 1-4, 5-14, 15-49, 50-199, 200+."""
    if n <= 0:
        return "0"
    lo = max((e for e in _EDGES if e <= n), default=None)
    if lo is None:
        return "0"
    hi = next((e for e in _EDGES if e > n), None)
    return f"{lo}+" if hi is None else f"{lo}-{hi - 1}"


def _clean(value: object) -> str | None:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and _WORD.match(value):
        return value
    return None


def log_event(name: str, **fields: object) -> None:
    """Log one event. Unknown event names and unsafe field values are dropped silently."""
    try:
        if name not in EVENTS:
            return
        parts = [f"event={name}"]
        for key, value in fields.items():
            clean = _clean(value)
            if clean is not None and _KEY.match(key):
                parts.append(f"{key}={clean}")
        log.info(" ".join(parts))
    except Exception:  # noqa: BLE001 - a logging problem must never fail a request
        pass
