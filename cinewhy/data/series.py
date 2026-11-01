"""TV series for the catalogue: IMDb's list of them, TMDB's details, and the join between the two.

Films come from one TMDB export that carries everything (`spine`). Series do not have one:
IMDb's dumps say which titles are series, how well they are voted and what genres they have, but
carry no language, poster or description; TMDB's API does, keyed by IMDb number. So a series is
IMDb's row plus TMDB's row, joined on the IMDb number, which is exact (no title matching).

Reviews of series exist in only one dump, ebD (`linking.parse_ebd_series`), so a series reaches
full receipts only through that, and the rest are listed with ratings only like films are.

Pure functions and one cache reader. The network step is `cinewhy.data.fetch_series`.
"""

from __future__ import annotations

import csv
import gzip
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from cinewhy.data.spine import SpineFilm

SERIES_TYPES: Final[frozenset[str]] = frozenset({"tvSeries", "tvMiniSeries"})
# IMDb's genre names where TMDB's (and so the films') differ; anything not listed here and not in
# `_DROPPED_GENRES` keeps its IMDb name, which matches (Drama, Comedy, Action, Animation, ...).
_GENRE_RENAMES: Final[dict[str, str]] = {"Sci-Fi": "Science Fiction", "Musical": "Music"}
# Not genres a viewer picks a film by, and not ones the films carry.
_DROPPED_GENRES: Final[frozenset[str]] = frozenset(
    {"Reality-TV", "Talk-Show", "Game-Show", "News", "Short", "Adult", "Biography", "Sport"}
)


@dataclass(frozen=True)
class ImdbSeries:
    """One series as IMDb's dumps describe it."""

    imdb_id: int
    title: str
    original_title: str
    start_year: int
    genres: tuple[str, ...]
    votes: int
    rating: float
    miniseries: bool


def series_genres(raw: str) -> tuple[str, ...]:
    """IMDb's comma-separated genres as the names the films use, minus ones nobody filters by."""
    names = [g for g in raw.split(",") if g and g != "\\N" and g not in _DROPPED_GENRES]
    return tuple(_GENRE_RENAMES.get(g, g) for g in names)


def imdb_number(tconst: str) -> int | None:
    """`"tt0903747"` -> 903747; None for anything else."""
    return int(tconst[2:]) if tconst.startswith("tt") and tconst[2:].isdigit() else None


def read_imdb_series(basics: Path, ratings: Path, *, min_votes: int) -> list[ImdbSeries]:
    """Series and miniseries with a start year and at least `min_votes` IMDb votes.

    Args:
        basics: `title.basics.tsv.gz` from IMDb's non-commercial dumps.
        ratings: `title.ratings.tsv.gz`.
        min_votes: Fewest votes a series may have.

    Returns:
        The series ordered by IMDb number, so every later stage is deterministic.
    """
    scores: dict[str, tuple[float, int]] = {}
    with gzip.open(ratings, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["numVotes"].isdigit() and int(row["numVotes"]) >= min_votes:
                scores[row["tconst"]] = (float(row["averageRating"]), int(row["numVotes"]))
    found: list[ImdbSeries] = []
    with gzip.open(basics, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
            number = imdb_number(row["tconst"])
            if (
                number is None
                or row["titleType"] not in SERIES_TYPES
                or not row["startYear"].isdigit()
                or row["tconst"] not in scores
            ):
                continue
            rating, votes = scores[row["tconst"]]
            found.append(
                ImdbSeries(
                    imdb_id=number,
                    title=row["primaryTitle"],
                    original_title=row["originalTitle"],
                    start_year=int(row["startYear"]),
                    genres=series_genres(row["genres"]),
                    votes=votes,
                    rating=rating,
                    miniseries=row["titleType"] == "tvMiniSeries",
                )
            )
    found.sort(key=lambda s: s.imdb_id)
    return found


def read_tmdb_tv(path: Path) -> dict[int, dict[str, Any]]:
    """The downloader's cache: IMDb number -> TMDB's record, for series TMDB knew.

    Series TMDB did not know (`"found": false`) are left out. A damaged last line, which is what an
    interrupted download leaves, is ignored rather than failing the build.
    """
    records: dict[int, dict[str, Any]] = {}
    if not path.is_file():
        return records
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("found") and isinstance(record.get("imdb"), int):
                records[record["imdb"]] = record
    return records


def to_spine_film(series: ImdbSeries, tmdb: Mapping[str, Any]) -> SpineFilm:
    """A series as the build's film record: IMDb's numbers and genres, TMDB's language and looks.

    `kind` is "series"; `runtime` is 0 (TMDB's find answer has none, and nothing joins on it).
    """
    date = str(tmdb.get("first_air_date") or "")
    return SpineFilm(
        tmdb_id=int(tmdb.get("tmdb_id") or 0),
        imdb_id=series.imdb_id,
        title=series.title,
        year=series.start_year,
        release_date=date if date[:4].isdigit() else f"{series.start_year}-01-01",
        language=str(tmdb.get("original_language") or ""),
        vote_count=int(tmdb.get("vote_count") or 0),
        popularity=float(tmdb.get("popularity") or 0.0),
        runtime=0.0,
        poster_path=str(tmdb["poster_path"]) if tmdb.get("poster_path") else None,
        genres=series.genres,
        overview=str(tmdb.get("overview") or ""),
        imdb_rating=series.rating,
        imdb_votes=series.votes,
        vote_average=float(tmdb.get("vote_average") or 0.0),
        original_title=series.original_title,
        kind="series",
    )


def iter_series_films(
    series: list[ImdbSeries], tmdb: Mapping[int, Mapping[str, Any]]
) -> Iterator[SpineFilm]:
    """Every series TMDB knows, as build records, in IMDb-number order."""
    for item in series:
        record = tmdb.get(item.imdb_id)
        if record is not None:
            yield to_spine_film(item, record)
