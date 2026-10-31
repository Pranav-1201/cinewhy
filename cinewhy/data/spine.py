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
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
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
    # "film", or "series" for a TV series (`cinewhy.data.series`); the rest of the build treats both
    # alike except where it must not (reviews come from different dumps).
    kind: str = "film"


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


def wide_quota(language: str, year: int) -> int:
    """A much wider candidate list, for the build that asks for 50 reviews and adds languages.

    The shipped quotas keep the 300 best-known English films a year, then require only 5 reviews.
    Asking for 50 needs more candidates to find the ones that reach it: 1,000 English films a year
    from 2000 (250 before), and 300 a year in every other language. Measured on 2026-10-27
    (`experiments/spine_reach.py`): this reaches 9,706 English, 322 Hindi, 33 Telugu, 147 Japanese
    and 171 French films at 50 reviews from the dumps on disk.
    """
    if language == "en":
        return 1000 if year >= 2000 else 250
    return 300


# Films wanted per original language, English and the three others in the ratio 4:3:2:1 that the
# owner set (English 10,000; Hindi and Telugu 7,500 split 70/30; Japanese 5,000; French 2,500).
# These are MINIMUMS the owner wants and the supply cannot always meet: the ratings-only selection
# below fills what it can, and the build reports the shortfall rather than hiding it.
CATALOGUE_TARGETS: Final[dict[str, int]] = {
    "en": 10_000,
    "hi": 5_250,
    "te": 2_250,
    "ja": 5_000,
    "fr": 2_500,
}


def _best_by_imdb(
    rows: Iterable[Mapping[str, str]], languages: Collection[str], max_year: int
) -> tuple[dict[int, SpineFilm], int, int]:
    """One film per IMDb number from released rows in the wanted languages and years.

    Returns the films, how many rows had no usable IMDb number, and how many were duplicates of a
    number already held (the most-voted row wins, ties broken by TMDB id).
    """
    best: dict[int, SpineFilm] = {}
    dropped_no_imdb = dropped_duplicate = 0
    for row in rows:
        year_text = row["release_date"][:4]
        if (
            row["original_language"] not in languages
            or row["status"] != "Released"
            or not year_text.isdigit()
            or not MIN_YEAR <= int(year_text) <= max_year
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
    return best, dropped_no_imdb, dropped_duplicate


def select_ratings_only(
    rows: Iterable[Mapping[str, str]],
    taken: Collection[int],
    targets: Mapping[str, int],
    *,
    min_votes: int,
    fallback_min_votes: int | None = None,
    max_year: int | None = None,
) -> tuple[SpineFilm, ...]:
    """Films we will list with their IMDb numbers only, to bring each language up to its target.

    For each language, the best-known films (by IMDb votes) that are not already in the full-receipt
    catalogue, have at least `min_votes` IMDb votes and a rating, until the language has
    `targets[language]` films counting those already `taken`. A language already at its target gets
    none; one that runs out of qualifying films simply gets fewer (the caller reports the gap).

    With `fallback_min_votes`, a language still short after that is filled, best-known first, from
    films with at least that many votes but fewer than `min_votes`. Their ratings rest on little,
    so they come only after every film above the main floor, and only as far as the target needs.

    Args:
        rows: TMDB CSV rows (see `read_tmdb_rows`).
        taken: IMDb numbers of the films that already have full receipts.
        targets: Wanted films per original language, full-receipt films included.
        min_votes: Fewest IMDb votes a film may have; below it a rating means little.
        fallback_min_votes: A lower floor used only to fill a language that is still short.
        max_year: Latest release year (default `MAX_YEAR`).

    Returns:
        The chosen films, ordered by IMDb number so the artifact is deterministic.
    """
    best, _, _ = _best_by_imdb(rows, set(targets), MAX_YEAR if max_year is None else max_year)
    held = set(taken)
    have: dict[str, int] = defaultdict(int)
    for imdb_id in held:
        film = best.get(imdb_id)
        if film is not None:
            have[film.language] += 1
    # The lowest floor any film may pass. Films are taken best-voted first, so those below
    # `min_votes` are reached only after every film above it, and only if the target is still unmet.
    floor = min_votes if fallback_min_votes is None else min(min_votes, fallback_min_votes)
    pool: dict[str, list[SpineFilm]] = defaultdict(list)
    for film in best.values():
        if film.imdb_id not in held and film.imdb_votes >= floor and film.imdb_rating > 0:
            pool[film.language].append(film)
    chosen: list[SpineFilm] = []
    for language, films in pool.items():
        films.sort(key=lambda f: (-f.imdb_votes, f.tmdb_id))
        chosen.extend(films[: max(0, targets[language] - have[language])])
    chosen.sort(key=lambda f: f.imdb_id)
    return tuple(chosen)


def select_spine(
    rows: Iterable[Mapping[str, str]],
    quota_for: Callable[[str, int], int] = quota,
    *,
    languages: Collection[str] | None = None,
    max_year: int | None = None,
) -> SpineSelection:
    """Pick the catalogue candidates from TMDB rows.

    Rules, in order: released films in a wanted language and year range; a usable IMDb number;
    one row per IMDb number (the most voted wins); then per (language, year) the top
    `quota_for` films by votes, ties broken by TMDB id so the result never depends on file order.

    Args:
        rows: TMDB CSV rows (see `read_tmdb_rows`).
        quota_for: Films to keep per (language, year); injectable so tests can use tiny quotas.
        languages: Original languages wanted (default `LANGUAGES`).
        max_year: Latest release year (default `MAX_YEAR`).

    Returns:
        The selection, ordered by IMDb number, with counts of what was dropped.
    """
    best, dropped_no_imdb, dropped_duplicate = _best_by_imdb(
        rows,
        LANGUAGES if languages is None else languages,
        MAX_YEAR if max_year is None else max_year,
    )

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
