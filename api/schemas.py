"""Request and response shapes. Every size is capped here, at the edge, before any work happens."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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


class RecommendRequest(BaseModel):
    members: list[Member] = Field(min_length=1, max_length=MAX_MEMBERS)
    providers: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=350)


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
