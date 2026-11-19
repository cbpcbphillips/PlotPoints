"""Match Letterboxd export rows (title + year, no TMDB id) to catalog titles.

Titles are not unique: two different films are each called "Good Boy" and "The Killer". So a match
is on (title, year), widened in tiers only when the narrower tier finds nothing. That ordering is
the whole point: a remake's exact year must always beat the original one window over, and a looser
spelling must never outrank an exact one.

  1. strict title, exact year      "Dune" 2021 -> Dune (2021), never Dune (1984)
  2. strict title, year +-1        festival premiere vs release year
  3. loose title, exact year       "School of Rock" -> "The School of Rock"; "Amelie" -> "Amélie"
  4. loose title, year +-1
  5. strict or loose, year +-2     "The Fall" 2006 (Letterboxd) -> The Fall 2008 (TMDB)
  6. no year in the row            title alone, most-voted wins

Within a tier the closest year wins, then the most-voted film. When several films still tie, the
row is flagged `ambiguous` so the UI can say so; silently picking would be a guess presented as a
fact. Both the TMDB title and the original-language title are indexed.

What this cannot catch (TMDB re-dating a film by years, as it did Hamilton 2020 -> 2025; a film
that is not in the catalog at all) is left for the TMDB lookup in api/tmdb_lookup.py.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from snapshot import Snapshot, normalize_title

# One leading article is dropped, in the languages Letterboxd titles most often carry. Only when
# something follows it, so a film called "The" or "A" keeps its title.
ARTICLES = frozenset("the a an le la les l el los las der die das il lo gli o os as".split())
# Word-level roman numerals to digits ("Rocky II" == "Rocky 2"). I, V and X are left alone: they
# are also words and titles in their own right ("X", "V for Vendetta").
ROMAN = dict(
    zip(
        "ii iii iv vi vii viii ix xi xii xiii xiv xv xvi xvii xviii xix xx".split(),
        "2 3 4 6 7 8 9 11 12 13 14 15 16 17 18 19 20".split(),
        strict=True,
    )
)
SYNONYMS = {"vol": "volume"}
_WORD = re.compile(r"\w+")


def loose_title(title: str) -> str:
    """A forgiving key: no accents, '&' == 'and', II == 2, no leading article, alphanumerics only.

    Non-Latin scripts pass through (\\w is Unicode-aware), so a Japanese title still has a key.
    """
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    t = t.replace("&", " and ").replace("'", " ").replace("’", " ")
    words = [SYNONYMS.get(w, ROMAN.get(w, w)) for w in _WORD.findall(t.replace("_", " "))]
    if len(words) > 1 and words[0] in ARTICLES:
        words = words[1:]
    return "".join(words)


class MatchIndex:
    """Lookup tables for one snapshot: (key, year) -> rows, and key -> rows for year-less rows."""

    def __init__(self, snap: Snapshot) -> None:
        self.snap = snap
        self.strict: dict[tuple[str, int], set[int]] = defaultdict(set)
        self.loose: dict[tuple[str, int], set[int]] = defaultdict(set)
        self.strict_any: dict[str, set[int]] = defaultdict(set)
        self.loose_any: dict[str, set[int]] = defaultdict(set)
        for i, mt in enumerate(snap.media_type):
            if mt != "movie":
                continue
            year = int(snap.year[i])
            for name in {snap.title[i], snap.original_title[i]} - {None, ""}:
                s, lo = normalize_title(name), loose_title(name)
                if s:
                    self.strict[(s, year)].add(i)
                    self.strict_any[s].add(i)
                if lo:
                    self.loose[(lo, year)].add(i)
                    self.loose_any[lo].add(i)

    def _window(self, table, key: str, year: int, delta: int) -> list[tuple[int, int]]:
        out = []
        for y in range(year - delta, year + delta + 1):
            out.extend((abs(y - year), i) for i in table.get((key, y), ()))
        return out

    def _pick(self, hits: list[tuple[int, int]]) -> tuple[int, bool] | None:
        """Closest year, then most votes. Ambiguous when more than one film is that close."""
        if not hits:
            return None
        best_dist = min(d for d, _ in hits)
        closest = {i for d, i in hits if d == best_dist}
        best = max(closest, key=lambda i: (int(self.snap.votes[i]), -i))
        return best, len(closest) > 1

    def find(self, title: str, year: int | None) -> tuple[int, bool, str] | None:
        """(catalog row, ambiguous, method) or None."""
        s, lo = normalize_title(title), loose_title(title)
        if not s and not lo:
            return None
        if year:
            tiers = [
                ("strict", [(self.strict, s, 0)]),
                ("strict", [(self.strict, s, 1)]),
                ("loose", [(self.loose, lo, 0)]),
                ("loose", [(self.loose, lo, 1)]),
                ("wide", [(self.strict, s, 2), (self.loose, lo, 2)]),
            ]
            for method, lookups in tiers:
                hits = [
                    h for table, key, d in lookups if key for h in self._window(table, key, year, d)
                ]
                picked = self._pick(hits)
                if picked:
                    return picked[0], picked[1], method
            return None
        for method, table, key in (("strict", self.strict_any, s), ("loose", self.loose_any, lo)):
            rows = table.get(key) if key else None
            if rows:
                best = max(rows, key=lambda i: (int(self.snap.votes[i]), -i))
                return best, len(rows) > 1, method
        return None


def index_for(snap: Snapshot) -> MatchIndex:
    """One index per snapshot object, built on first use (about a quarter second for 24k titles)."""
    idx = snap.__dict__.get("_match_index")
    if idx is None:
        idx = snap.__dict__["_match_index"] = MatchIndex(snap)
    return idx


def match_rows(snap: Snapshot, rows: list[dict], index: MatchIndex | None = None) -> dict:
    """Match export rows against the catalog.

    Returns matched `films` (with the `method` that found them), the `unmatched` rows in full
    (title, year, rating, rewatch, so a later step can still use them), and the `ambiguous` count.
    """
    index = index or index_for(snap)
    films, unmatched, ambiguous = [], [], 0
    seen: set[int] = set()
    for row in rows:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        year = row.get("year")
        found = index.find(title, year)
        if found is None:
            unmatched.append(
                {
                    "title": title,
                    "year": year,
                    "rating": row.get("rating"),
                    "rewatch": bool(row.get("rewatch")),
                }
            )
            continue
        best, flagged, method = found
        if best in seen:  # the same film listed twice (e.g. a rewatch row): keep the first
            continue
        seen.add(best)
        ambiguous += flagged
        films.append(
            {
                "tmdb_id": int(snap.tmdb_id[best]),
                "media_type": snap.media_type[best],
                "title": snap.title[best],
                "year": int(snap.year[best]) or None,
                "rating": row.get("rating"),
                "rewatch": bool(row.get("rewatch")),
                "ambiguous": flagged,
                "method": method,
            }
        )
    return {"films": films, "unmatched": unmatched, "ambiguous": ambiguous}
