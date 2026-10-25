"""Readers for the two raw sources and the join between them.

* **aclImdb v1** (Maas et al., 2011) — 100,000 IMDb reviews. Unlike the Kaggle CSV that
  Data/ already holds, the original archive ships `urls_*.txt`: line N of each file is the
  IMDb title page of review file `N_<stars>.txt`. That is the item key the 2-column CSV
  lost (DECISIONS.md D-002), and it resolves audit item H-1 without any fuzzy matching.
* **MovieLens 25M** — ratings plus `links.csv`, which carries each film's IMDb number.

The join is therefore exact integer equality on the IMDb title number, not a title match.
Nothing here trains, scores or ranks; it only reads and joins (ARCHITECTURE.md §5).
"""

from __future__ import annotations

import csv
import io
import re
import tarfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt

# `aclImdb/train/pos/123_9.txt` -> split, kind, line number in the matching urls file, stars.
_REVIEW_MEMBER: Final[re.Pattern[str]] = re.compile(
    r"^(?:\./)?aclImdb/(train|test)/(pos|neg|unsup)/(\d+)_(\d+)\.txt$"
)
_URLS_MEMBER: Final[re.Pattern[str]] = re.compile(
    r"^(?:\./)?aclImdb/(train|test)/urls_(pos|neg|unsup)\.txt$"
)
_IMDB_TITLE: Final[re.Pattern[str]] = re.compile(r"/title/tt(\d+)/")
_YEAR_SUFFIX: Final[re.Pattern[str]] = re.compile(r"\s*\((\d{4})\)\s*$")
# "Matrix, The" -> "The Matrix". MovieLens files articles after the title.
_TRAILING_ARTICLE: Final[re.Pattern[str]] = re.compile(r"^(.*), (The|A|An)$")

_LABELS: Final[dict[str, int | None]] = {"pos": 1, "neg": 0, "unsup": None}


@dataclass(frozen=True)
class RawReview:
    """One IMDb review with the film it is about.

    `review_id` is `<split>/<kind>/<n>`, the archive path minus the star suffix, so a
    quoted sentence can always be traced back to one file in the source archive.
    """

    review_id: str
    imdb_id: int
    text: str
    label: int | None
    stars: int
    split: str


@dataclass(frozen=True)
class MovieLensFilm:
    """A film as MovieLens describes it, keyed by its IMDb number."""

    movielens_id: int
    imdb_id: int
    title: str
    year: int | None
    genres: tuple[str, ...]


def parse_title(raw: str) -> tuple[str, int | None]:
    """Split a MovieLens title into display title and release year.

    Args:
        raw: e.g. `"Matrix, The (1999)"`.

    Returns:
        `("The Matrix", 1999)`. The year is None when the title carries none.
    """
    year: int | None = None
    if match := _YEAR_SUFFIX.search(raw):
        year = int(match.group(1))
        raw = raw[: match.start()]
    if article := _TRAILING_ARTICLE.match(raw):
        raw = f"{article.group(2)} {article.group(1)}"
    return raw.strip(), year


def read_review_films(archive: Path) -> dict[tuple[str, str, int], int]:
    """Map each review file to the IMDb number of the film it reviews.

    Args:
        archive: Path to `aclImdb_v1.tar.gz`.

    Returns:
        `{(split, kind, n): imdb_id}` for every line of every `urls_*.txt`.
    """
    mapping: dict[tuple[str, str, int], int] = {}
    with tarfile.open(archive) as tar:
        for member in tar:
            found = _URLS_MEMBER.match(member.name)
            if not found or (handle := tar.extractfile(member)) is None:
                continue
            split, kind = found.groups()
            for n, line in enumerate(handle.read().decode("utf-8").splitlines()):
                if title := _IMDB_TITLE.search(line):
                    mapping[(split, kind, n)] = int(title.group(1))
    return mapping


def iter_reviews(archive: Path, keep_films: frozenset[int] | None = None) -> Iterator[RawReview]:
    """Stream the archive's reviews, joined to their film.

    Two passes over the gzip stream: the first reads the small URL files, the second reads
    review text. Holding the URL table first means reviews of films outside `keep_films`
    are skipped without being decoded.

    Args:
        archive: Path to `aclImdb_v1.tar.gz`.
        keep_films: IMDb numbers to keep. None keeps every review.

    Yields:
        One `RawReview` per kept review. Reviews whose file has no URL line are skipped,
        never guessed.
    """
    film_of = read_review_films(archive)
    with tarfile.open(archive) as tar:
        for member in tar:
            found = _REVIEW_MEMBER.match(member.name)
            if not found:
                continue
            split, kind, number, stars = found.groups()
            imdb_id = film_of.get((split, kind, int(number)))
            if imdb_id is None or (keep_films is not None and imdb_id not in keep_films):
                continue
            if (handle := tar.extractfile(member)) is None:
                continue
            yield RawReview(
                review_id=f"{split}/{kind}/{number}",
                imdb_id=imdb_id,
                text=handle.read().decode("utf-8"),
                label=_LABELS[kind],
                stars=int(stars),
                split=split,
            )


def load_films(archive: Path) -> dict[int, MovieLensFilm]:
    """Read MovieLens films that carry an IMDb number.

    Args:
        archive: Path to `ml-25m.zip`.

    Returns:
        `{imdb_id: film}`. Films with no IMDb link cannot be joined to a review and are
        omitted.
    """
    with zipfile.ZipFile(archive) as z:
        with z.open("ml-25m/links.csv") as raw:
            imdb_of = {
                int(r["movieId"]): int(r["imdbId"])
                for r in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
                if r["imdbId"]
            }
        films: dict[int, MovieLensFilm] = {}
        with z.open("ml-25m/movies.csv") as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8")):
                movielens_id = int(row["movieId"])
                imdb_id = imdb_of.get(movielens_id)
                if imdb_id is None:
                    continue
                title, year = parse_title(row["title"])
                no_genres = row["genres"] == "(no genres listed)"
                genres = () if no_genres else tuple(row["genres"].split("|"))
                films[imdb_id] = MovieLensFilm(movielens_id, imdb_id, title, year, genres)
    return films


def load_ratings(
    archive: Path, movielens_ids: frozenset[int]
) -> tuple[npt.NDArray[np.int32], npt.NDArray[np.int32], npt.NDArray[np.float32]]:
    """Read ratings for the given films only.

    The full file is 25 million rows; the catalogue is a few thousand films, so filtering
    while reading keeps peak memory in the low hundreds of MB.

    Args:
        archive: Path to `ml-25m.zip`.
        movielens_ids: MovieLens film ids to keep.

    Returns:
        Parallel arrays `(user_ids, movie_ids, ratings)`.
    """
    import pandas as pd

    keep = np.fromiter(movielens_ids, dtype=np.int64)
    users: list[npt.NDArray[np.int32]] = []
    movies: list[npt.NDArray[np.int32]] = []
    stars: list[npt.NDArray[np.float32]] = []
    with zipfile.ZipFile(archive) as z, z.open("ml-25m/ratings.csv") as raw:
        for chunk in pd.read_csv(
            raw,
            usecols=["userId", "movieId", "rating"],
            dtype={"userId": "int32", "movieId": "int32", "rating": "float32"},
            chunksize=2_000_000,
        ):
            hit = chunk[chunk["movieId"].isin(keep)]
            users.append(hit["userId"].to_numpy())
            movies.append(hit["movieId"].to_numpy())
            stars.append(hit["rating"].to_numpy())
    return np.concatenate(users), np.concatenate(movies), np.concatenate(stars)
