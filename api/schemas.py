"""Request and response shapes. Every size is capped here, at the edge, before any work happens."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

MAX_FILMS = 20000  # a heavy Letterboxd history is ~10k films; the payload is ~1 MB
MAX_MEMBERS = 6

MediaType = Literal["movie", "tv"]


class Film(BaseModel):
    """One film in someone's history. `rating` is Letterboxd's 0.5-5 scale; null = seen, unrated."""

    tmdb_id: int = Field(gt=0)
    media_type: MediaType = "movie"
    rating: float | None = Field(default=None, ge=0.5, le=5)
    rewatch: bool = False


class Member(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    films: list[Film] = Field(max_length=MAX_FILMS)


FacetValue = Annotated[str, Field(min_length=1, max_length=80)]


class Facet(BaseModel):
    """Restrict the ranking to some genres, keywords, directors, billed actors or decades.

    `mode` says how the values of one kind combine: "all" (Romance AND Comedy: films that are both)
    or "any" (Drama OR Thriller: films that are either). Decades are always "any".
    """

    kind: Literal["genre", "keyword", "director", "actor", "era"]
    values: list[FacetValue] = Field(min_length=1, max_length=8)
    mode: Literal["all", "any"] = "all"


class RecommendRequest(BaseModel):
    members: list[Member] = Field(min_length=1, max_length=MAX_MEMBERS)
    providers: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=350)
    # One entry per franchise (its best film, with a count of the rest) instead of every film.
    bundle: bool = False
    # Size of the varied second row; only returned with the first page, and only unfiltered.
    branch_out: int = Field(default=0, ge=0, le=24)
    # Browse: only titles that match EVERY facet here (one facet per kind; each can hold several
    # values, combined all-of or any-of).
    facets: list[Facet] = Field(default_factory=list, max_length=5)

    @field_validator("facets")
    @classmethod
    def one_facet_per_kind(cls, v: list[Facet]) -> list[Facet]:
        if len({f.kind for f in v}) != len(v):
            raise ValueError("Use at most one filter of each kind.")
        return v


class ProfileRequest(BaseModel):
    films: list[Film] = Field(max_length=MAX_FILMS)


class LetterboxdRequest(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")


class CsvRow(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    year: int | None = Field(default=None, ge=1870, le=2100)
    rating: float | None = Field(default=None, ge=0.5, le=5)
    rewatch: bool = False


class MatchRequest(BaseModel):
    rows: list[CsvRow] = Field(max_length=MAX_FILMS)


class ConsentRequest(BaseModel):
    """What gets stored if (and only if) the person ticked the consent box."""

    source: Literal["letterboxd-username", "letterboxd-export"]
    username: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,40}$")
    films: list[Film] = Field(max_length=MAX_FILMS)


class DeleteRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
