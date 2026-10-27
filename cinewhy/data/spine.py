"""Choose which films enter the catalogue, from the TMDB export.

The catalogue is a *selection*, not everything we can find: per language and release year, the
films audiences voted on most. Votes measure how many people have seen and rated a film, so the
selection favours films a visitor has heard of. The quotas are the product decision made on
2026-10-26: depth after 2000, where the audience is, and only the best known before.

The IMDb number stays the key (`cw-<imdb>` ids of existing films do not change), so a row with
no IMDb number is unusable and is dropped BEFORE ranking, otherwise it would burn a quota slot.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

LANGUAGES: Final[tuple[str, ...]] = ("en", "hi")
MIN_YEAR: Final[int] = 1950
MAX_YEAR: Final[int] = 2025
_IMDB_ID: Final[re.Pattern[str]] = re.compile(r"tt(\d+)")


@dataclass(frozen=True)
class SpineFilm:
    """One selected film with the TMDB fields later stages need."""

    tmdb_id: int
    imdb_id: int
    title: str
    year: int
    release_date: str
    language: str
    vote_count: int
    popularity: float
    runtime: float
    poster_path: str | None
    genres: tuple[str, ...]
    overview: str
    # Audience scores that exist for every film, unlike MovieLens ratings: IMDb's rating (0-10)
    # and vote count, and TMDB's own vote average. 0 means the export had none.
    imdb_rating: float = 0.0
    imdb_votes: int = 0
    vote_average: float = 0.0
    # The title in the film's own language (TMDB `original_title`), "" when the export had none.
    original_title: str = ""


@dataclass(frozen=True)
class SpineSelection:
    """The selected films plus what was thrown away, so a build can print the losses."""

    films: tuple[SpineFilm, ...]
    dropped_no_imdb: int
    dropped_duplicate_imdb: int


def quota(language: str, year: int) -> int:
    """How many films to keep for one language and release year.

    Before 2000 only the best known films: 75 English, 25 Hindi. From 2000: 300 English and
    70 Hindi. The Hindi figures follow the supply (TMDB lists 100-390 Hindi films a year but
    only 18-36 have 50+ votes), not the English ones.
    """
    if year < 2000:
        return 75 if language == "en" else 25
    return 300 if language == "en" else 70


def parse_imdb_id(raw: str) -> int | None:
    """`"tt0094675"` -> 94675; None for anything that is not a title number."""
    found = _IMDB_ID.fullmatch(raw.strip())
    return int(found.group(1)) if found else None


def _number(raw: str, default: float = 0.0) -> float:
    try:
        return float(raw)
    except ValueError:
        return default


def _film(row: Mapping[str, str], imdb_id: int, year: int) -> SpineFilm:
    return SpineFilm(
        tmdb_id=int(row["id"]),
        imdb_id=imdb_id,
        title=row["title"],
        year=year,
        release_date=row["release_date"],
        language=row["original_language"],
        vote_count=int(_number(row["vote_count"])),
        popularity=_number(row["popularity"]),
        runtime=_number(row["runtime"]),
        poster_path=row["poster_path"] or None,
        genres=tuple(g for g in row["genres"].split(", ") if g),
        overview=row["overview"],
        imdb_rating=_number(row["imdb_rating"]),
        imdb_votes=int(_number(row["imdb_votes"])),
        vote_average=_number(row["vote_average"]),
        original_title=row.get("original_title", ""),
    )


def select_spine(
    rows: Iterable[Mapping[str, str]],
    quota_for: Callable[[str, int], int] = quota,
) -> SpineSelection:
    """Pick the catalogue candidates from TMDB rows.

    Rules, in order: released films in a wanted language and year range; a usable IMDb number;
    one row per IMDb number (the most voted wins); then per (language, year) the top
    `quota_for` films by votes, ties broken by TMDB id so the result never depends on file order.

    Args:
        rows: TMDB CSV rows (see `read_tmdb_rows`).
        quota_for: Films to keep per (language, year); injectable so tests can use tiny quotas.

    Returns:
        The selection, ordered by IMDb number, with counts of what was dropped.
    """
    best: dict[int, SpineFilm] = {}
    dropped_no_imdb = dropped_duplicate = 0
    for row in rows:
        year_text = row["release_date"][:4]
        if (
            row["original_language"] not in LANGUAGES
            or row["status"] != "Released"
            or not year_text.isdigit()
            or not MIN_YEAR <= int(year_text) <= MAX_YEAR
        ):
            continue
        imdb_id = parse_imdb_id(row["imdb_id"])
        if imdb_id is None:
            dropped_no_imdb += 1
            continue
        film = _film(row, imdb_id, int(year_text))
        held = best.get(imdb_id)
        if held is None:
            best[imdb_id] = film
            continue
        dropped_duplicate += 1
        if (film.vote_count, -film.tmdb_id) > (held.vote_count, -held.tmdb_id):
            best[imdb_id] = film

    groups: dict[tuple[str, int], list[SpineFilm]] = defaultdict(list)
    for film in best.values():
        groups[(film.language, film.year)].append(film)
    kept: list[SpineFilm] = []
    for (language, year), films in groups.items():
        films.sort(key=lambda f: (-f.vote_count, f.tmdb_id))
        kept.extend(films[: quota_for(language, year)])
    kept.sort(key=lambda f: f.imdb_id)
    return SpineSelection(tuple(kept), dropped_no_imdb, dropped_duplicate)


def read_tmdb_rows(path: Path) -> Iterator[dict[str, str]]:
    """Stream the TMDB export. Its cast and overview fields exceed the csv default limit."""
    csv.field_size_limit(10**9)
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)
