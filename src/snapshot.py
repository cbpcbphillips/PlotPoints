"""The serving snapshot: everything the API needs, in a form that loads in about a second.

Pure numpy + json, no Snowflake and no Airflow, so the API image can import it. The pipeline half
(reading MART and writing this) lives in publish_snapshot.py.

Layout of one snapshot directory:

  vectors.npy    float16 (N, D), each row L2-normalized in float32 before the cast, so a dot
                 product of two rows IS the cosine similarity Snowflake's VECTOR_COSINE_SIMILARITY
                 returns (float16 costs ~1e-3 of absolute error, far below the per-seed spread of
                 ~0.05 the scorer standardizes by)
  catalog.json   columnar metadata, row-aligned with vectors.npy
  details.json   optional, columnar and row-aligned: overview, tagline, directors, cast (name,
                 character) for the film page. Older snapshots lack it and serve empty text.
  manifest.json  version (a content hash), embedding model, counts, when the provider data is from
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

VECTORS = "vectors.npy"
CATALOG = "catalog.json"
MANIFEST = "manifest.json"
DETAILS = "details.json"


@dataclass
class Snapshot:
    version: str
    embedding_model: str
    created_at: str
    providers_as_of: str
    catalog_mean_rating: float
    vectors: np.ndarray  # float32 (N, D), unit rows
    media_key: list[str]
    media_type: list[str]
    tmdb_id: np.ndarray  # int64
    title: list[str]
    year: np.ndarray  # int32, 0 = unknown
    runtime: np.ndarray  # float32, nan = unknown
    rating: np.ndarray  # float32, nan = unknown
    votes: np.ndarray  # int64
    poster: list[str | None]
    franchise: list[str | None]
    genres: list[list[str]]
    providers: list[list[int]]  # per title: indices into provider_names
    provider_names: list[str]  # normalized groups, most-available first
    # Added after the first snapshots shipped; older snapshots load with these all None.
    original_title: list[str | None] = field(default_factory=list)
    backdrop: list[str | None] = field(default_factory=list)
    # Film-page text, from details.json. Older snapshots have no such file; these pad to empty.
    overview: list[str | None] = field(default_factory=list)
    tagline: list[str | None] = field(default_factory=list)
    directors: list[list[str]] = field(default_factory=list)
    cast: list[list[list[str | None]]] = field(default_factory=list)  # per title: [name, character]
    by_key: dict[str, int] = field(default_factory=dict)
    by_tmdb: dict[tuple[str, int], int] = field(default_factory=dict)
    by_title_year: dict[tuple[str, int], list[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.media_key)
        if len(self.original_title) != n:
            self.original_title = [None] * n
        if len(self.backdrop) != n:
            self.backdrop = [None] * n
        if len(self.overview) != n:
            self.overview = [None] * n
        if len(self.tagline) != n:
            self.tagline = [None] * n
        if len(self.directors) != n:
            self.directors = [[] for _ in range(n)]
        if len(self.cast) != n:
            self.cast = [[] for _ in range(n)]
        self.by_key = {k: i for i, k in enumerate(self.media_key)}
        self.by_tmdb = {
            (t, int(i)): n
            for n, (t, i) in enumerate(zip(self.media_type, self.tmdb_id, strict=True))
        }
        for n, (title, year) in enumerate(zip(self.title, self.year, strict=True)):
            self.by_title_year.setdefault((normalize_title(title), int(year)), []).append(n)

    def __len__(self) -> int:
        return len(self.media_key)

    def facet_mask(self, kind: str, value: str) -> np.ndarray:
        """Boolean mask of the titles with this genre, director, cast member or decade.

        Names match ignoring case and extra spaces. Cast is the top-billed ten per film (the
        snapshot keeps no more), so an actor's page lists the films they were billed in.
        """
        if kind == "era":
            decade = parse_decade(value)
            if decade is None:
                return np.zeros(len(self), dtype=bool)
            return (self.year >= decade) & (self.year < decade + 10)
        want = _fold(value)
        if kind == "genre":
            rows = (any(_fold(g) == want for g in gs) for gs in self.genres)
        elif kind == "director":
            rows = (any(_fold(d) == want for d in ds) for ds in self.directors)
        elif kind == "actor":
            rows = (any(_fold(c[0] or "") == want for c in cs) for cs in self.cast)
        else:
            raise ValueError(f"Unknown facet kind {kind!r}")
        return np.fromiter(rows, dtype=bool, count=len(self))

    def facet_name(self, kind: str, value: str) -> str | None:
        """The properly-cased name for a facet value as the catalog spells it (None if absent)."""
        if kind == "era":
            decade = parse_decade(value)
            return None if decade is None else f"{decade}s"
        want = _fold(value)
        if kind == "genre":
            names = (g for gs in self.genres for g in gs)
        elif kind == "director":
            names = (d for ds in self.directors for d in ds)
        else:
            names = (c[0] or "" for cs in self.cast for c in cs)
        return next((n for n in names if _fold(n) == want), None)

    def facets(self) -> dict:
        """Genres and decades with their film counts, for the browse page."""
        genres = Counter(g for gs in self.genres for g in set(gs))
        decades = Counter(decade_of(int(y)) for y in self.year if y > 0)
        return {
            "genres": [{"name": n, "count": c} for n, c in sorted(genres.items(), key=_by_count)],
            "decades": [{"decade": d, "count": decades[d]} for d in sorted(decades)],
        }

    def people(self, kind: str, query: str = "", limit: int = 12) -> list[dict]:
        """Directors or billed cast, by how many films they have here, filtered by a name search."""
        cache = self.__dict__.setdefault("_people_counts", {})  # built on first use, per kind
        if kind not in cache:
            if kind == "director":
                names = (d for ds in self.directors for d in set(ds))
            elif kind == "actor":
                names = (n for cs in self.cast for n in {c[0] for c in cs if c[0]})
            else:
                raise ValueError(f"Unknown people kind {kind!r}")
            cache[kind] = Counter(names)
        counts = cache[kind]
        q = _fold(query)
        hits = [(n, c) for n, c in counts.items() if not q or q in _fold(n)]
        hits.sort(key=lambda nc: (-nc[1], nc[0]))
        return [{"name": n, "count": c} for n, c in hits[:limit]]

    def provider_mask(self, groups: list[str]) -> np.ndarray:
        """Boolean mask of titles streaming on ANY of the named provider groups."""
        wanted = {self.provider_names.index(g) for g in groups if g in self.provider_names}
        return np.fromiter(
            (bool(wanted.intersection(p)) for p in self.providers), dtype=bool, count=len(self)
        )


FACET_KINDS = ("genre", "director", "actor", "era")


def decade_of(year: int) -> int:
    return year // 10 * 10


def parse_decade(value: str) -> int | None:
    """'1990', '1990s' or '1994' -> 1990. None when it is not a year."""
    digits = value.strip().lower().rstrip("s")
    return decade_of(int(digits)) if digits.isdigit() and len(digits) == 4 else None


def _fold(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _by_count(item: tuple[str, int]) -> tuple[int, str]:
    return (-item[1], item[0])


def normalize_title(title: str) -> str:
    """Lowercase alphanumerics only, so "Spider-Man: Homecoming" matches "Spider Man Homecoming"."""
    return "".join(ch for ch in (title or "").lower() if ch.isalnum())


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    m = matrix.astype(np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


def content_version(vectors16: np.ndarray, catalog: dict, details: dict | None = None) -> str:
    h = hashlib.sha256()
    h.update(vectors16.tobytes())
    h.update(json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    if details:  # absent details leave the hash exactly as before, so old versions stay valid
        h.update(json.dumps(details, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()[:12]


def save(
    directory: Path,
    *,
    vectors: np.ndarray,
    catalog: dict,
    embedding_model: str,
    created_at: str,
    providers_as_of: str,
    details: dict | None = None,
) -> dict:
    """Write a snapshot directory and return its manifest. `vectors` need not be normalized."""
    directory.mkdir(parents=True, exist_ok=True)
    v16 = normalize_rows(vectors).astype(np.float16)
    version = content_version(v16, catalog, details)
    np.save(directory / VECTORS, v16)
    (directory / CATALOG).write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    if details:
        (directory / DETAILS).write_text(
            json.dumps(details, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    manifest = {
        "version": version,
        "embedding_model": embedding_model,
        "created_at": created_at,
        "providers_as_of": providers_as_of,
        "titles": int(v16.shape[0]),
        "dimension": int(v16.shape[1]),
        "providers": len(catalog["provider_names"]),
    }
    (directory / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load(directory: Path) -> Snapshot:
    directory = Path(directory)
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    cat = json.loads((directory / CATALOG).read_text(encoding="utf-8"))
    vectors = np.load(directory / VECTORS).astype(np.float32)
    details_path = directory / DETAILS
    det = json.loads(details_path.read_text(encoding="utf-8")) if details_path.exists() else {}
    nan = float("nan")
    return Snapshot(
        version=manifest["version"],
        embedding_model=manifest["embedding_model"],
        created_at=manifest["created_at"],
        providers_as_of=manifest["providers_as_of"],
        catalog_mean_rating=float(cat["catalog_mean_rating"]),
        vectors=vectors,
        media_key=cat["media_key"],
        media_type=cat["media_type"],
        tmdb_id=np.asarray(cat["tmdb_id"], dtype=np.int64),
        title=cat["title"],
        year=np.asarray([y or 0 for y in cat["year"]], dtype=np.int32),
        runtime=np.asarray([nan if r is None else r for r in cat["runtime"]], dtype=np.float32),
        rating=np.asarray([nan if r is None else r for r in cat["rating"]], dtype=np.float32),
        votes=np.asarray([v or 0 for v in cat["votes"]], dtype=np.int64),
        poster=cat["poster"],
        franchise=cat["franchise"],
        genres=cat["genres"],
        providers=cat["providers"],
        provider_names=cat["provider_names"],
        original_title=cat.get("original_title") or [],
        backdrop=cat.get("backdrop") or [],
        overview=det.get("overview") or [],
        tagline=det.get("tagline") or [],
        directors=det.get("directors") or [],
        cast=det.get("cast") or [],
    )
