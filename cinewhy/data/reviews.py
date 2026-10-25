"""Readers for the Rotten Tomatoes and ebD review dumps (FEATURE-004).

Both dumps are far larger than memory wants (RT 13.5 GB of CSV, ebD 7.8 GB of JSON) so everything
here streams. Both also contain rows the product must never quote:

* spoiler-flagged and profane reviews are excluded, because evidence sentences are shown to users;
* text under 40 characters is dropped: measured, 35.7M of RT's 55.1M rows clear that bar, and the
  rest are bare star ratings with no sentence to say anything about a film's acting or plot;
* ebD's TV series are skipped (see `linking.parse_ebd_movie`).

A review's id always starts with its source (`rt/`, `ebd/`, `acl/`) so any quoted sentence can be
traced to the dump it came from.
"""

from __future__ import annotations

import csv
import hashlib
import heapq
import io
import json
import re
import zipfile
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cinewhy.data.linking import film_key, parse_ebd_movie

MIN_TEXT_CHARS: Final[int] = 40
# Bounds profiling time and memory: 150 reviews per film per source is already far more than the
# few sentences per aspect the evidence panel can show.
MAX_REVIEWS_PER_SOURCE: Final[int] = 150

_RT_MOVIES_MEMBER: Final[str] = "movies.csv/movies.csv"
_RT_REVIEWS_MEMBER: Final[str] = "user_reviews.csv/user_reviews.csv"
_RT_VERDICT: Final[re.Pattern[str]] = re.compile(r"^\s*:(?:fresh|rotten):\s*")
# Reviewers edited old reviews years later: "[2004: pretty good is a 7.]". Not part of the review.
_RT_EDIT_NOTE: Final[re.Pattern[str]] = re.compile(r"\[\d{4}:[^\]]*\]")
_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
_RUNTIME: Final[re.Pattern[str]] = re.compile(r"(?:(\d+)h)?\s*(?:(\d+)m)?")
# Raw JSON text of a `"movie": "<title> (<year>)"` field; the value may hold \uXXXX escapes.
_EBD_MOVIE_FIELD: Final[re.Pattern[str]] = re.compile(r'"movie": "((?:[^"\\]|\\.)*)"')
_CHUNK: Final[int] = 1 << 26


@dataclass(frozen=True)
class SourceReview:
    """One review of one film, from one dump."""

    imdb_id: int
    review_id: str
    text: str


@dataclass(frozen=True)
class RtFilm:
    """A film as Rotten Tomatoes lists it."""

    movie_id: str
    title: str
    year: int
    runtime: float | None
    url: str


def _squash(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def clean_rt_quote(raw: str) -> str:
    """Strip RT's verdict prefix and later edit notes; '' when too little text remains."""
    text = _squash(_RT_EDIT_NOTE.sub(" ", _RT_VERDICT.sub("", raw)))
    return text if len(text) >= MIN_TEXT_CHARS else ""


def clean_ebd_text(raw: str) -> str:
    """Collapse whitespace; '' when the review is too short to say anything."""
    text = _squash(raw)
    return text if len(text) >= MIN_TEXT_CHARS else ""


def rt_runtime_minutes(raw: str) -> float | None:
    """`"2h 50m"` -> 170.0, `"14m"` -> 14.0, `"3h"` -> 180.0; None if unparseable."""
    found = _RUNTIME.fullmatch(raw.strip())
    if not found or not (found.group(1) or found.group(2)):
        return None
    return float(int(found.group(1) or 0) * 60 + int(found.group(2) or 0))


def read_rt_films(archive: Path) -> list[RtFilm]:
    """Every film in the RT dump that has a numeric year.

    Args:
        archive: Path to the zip downloaded from Kaggle (`rt_mother.zip`).
    """
    csv.field_size_limit(10**9)
    films: list[RtFilm] = []
    with zipfile.ZipFile(archive) as z, z.open(_RT_MOVIES_MEMBER) as raw:
        for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
            if row["movieYear"].isdigit():
                films.append(
                    RtFilm(
                        movie_id=row["movieId"],
                        title=row["movieTitle"],
                        year=int(row["movieYear"]),
                        runtime=rt_runtime_minutes(row["runtime"]),
                        url=row["movieURL"],
                    )
                )
    return films


def iter_rt_reviews(archive: Path, imdb_of: Mapping[str, int]) -> Iterator[SourceReview]:
    """Stream RT user reviews of the wanted films that are safe and long enough to quote.

    Args:
        archive: Path to `rt_mother.zip`.
        imdb_of: RT movie id -> IMDb number, for the films the catalogue wants.

    Yields:
        Reviews with a source-prefixed id. RT leaves `reviewId` blank, so the id is built from
        film, user and date, which is unique for one user's review of one film.
    """
    csv.field_size_limit(10**9)
    with zipfile.ZipFile(archive) as z, z.open(_RT_REVIEWS_MEMBER) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
        header = next(reader)
        col = {name: header.index(name) for name in header}
        movie_i, quote_i, spoil_i, prof_i = (
            col["movieId"],
            col["quote"],
            col["hasSpoilers"],
            col["hasProfanity"],
        )
        user_i, date_i = col["userId"], col["creationDate"]
        for row in reader:
            if len(row) <= user_i:
                continue
            imdb_id = imdb_of.get(row[movie_i])
            if imdb_id is None or row[spoil_i] == "True" or row[prof_i] == "True":
                continue
            text = clean_rt_quote(row[quote_i])
            if text:
                review_id = f"rt/{row[movie_i]}/{row[user_i]}-{row[date_i]}"
                yield SourceReview(imdb_id, review_id, text)


def _ebd_parts(z: zipfile.ZipFile) -> list[str]:
    # `sample.json` is a slice of part-01; reading it too would double-count those reviews.
    return sorted(n for n in z.namelist() if n.startswith("part-") and n.endswith(".json"))


def scan_ebd_keys(archive: Path) -> Counter[str]:
    """Reviews per film key in ebD, counting films only (series are skipped).

    Uses a regex on the raw text instead of parsing JSON, which is several times faster and is
    all the join needs.

    Args:
        archive: Path to `imdb_ebd.zip`.

    Returns:
        `film_key(title, year)` -> number of reviews, whatever their length or spoiler flag.
    """
    counts: Counter[str] = Counter()
    with zipfile.ZipFile(archive) as z:
        for name in _ebd_parts(z):
            carry = ""
            with z.open(name) as raw:
                while chunk := raw.read(_CHUNK):
                    text = carry + chunk.decode("utf-8", errors="ignore")
                    for found in _EBD_MOVIE_FIELD.finditer(text):
                        if found.end() <= len(carry):
                            continue  # already counted while it sat at the end of the last chunk
                        movie = parse_ebd_movie(json.loads(f'"{found.group(1)}"'))
                        if movie is not None:
                            counts[film_key(*movie)] += 1
                    carry = text[-600:]
    return counts


def _iter_json_array(handle: io.TextIOBase) -> Iterator[dict[str, object]]:
    """Yield the objects of a huge JSON array without loading it.

    Raises:
        ValueError: If the stream ends in the middle of a record (a truncated download).
    """
    decoder = json.JSONDecoder()
    buffer = ""
    while chunk := handle.read(_CHUNK // 8):
        buffer += chunk
        pos = 0
        while True:
            while pos < len(buffer) and buffer[pos] in " \n\r\t[,":
                pos += 1
            if pos >= len(buffer) or buffer[pos] == "]":
                break
            try:
                record, end = decoder.raw_decode(buffer, pos)
            except json.JSONDecodeError:
                break  # the record continues in the next chunk
            yield record
            pos = end
        buffer = buffer[pos:]
    if buffer.strip(" \n\r\t,]"):
        raise ValueError("ebD part ends inside a record: the file looks truncated")


def iter_ebd_reviews(archive: Path, imdb_of_key: Mapping[str, int]) -> Iterator[SourceReview]:
    """Stream ebD reviews of the wanted films that are safe and long enough to quote.

    Args:
        archive: Path to `imdb_ebd.zip`.
        imdb_of_key: `film_key` -> IMDb number for the films the catalogue wants.
    """
    with zipfile.ZipFile(archive) as z:
        for name in _ebd_parts(z):
            with z.open(name) as raw:
                text_stream = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                for record in _iter_json_array(text_stream):
                    movie = parse_ebd_movie(str(record.get("movie") or ""))
                    if movie is None or record.get("spoiler_tag"):
                        continue
                    imdb_id = imdb_of_key.get(film_key(*movie))
                    text = clean_ebd_text(str(record.get("review_detail") or ""))
                    if imdb_id is not None and text:
                        yield SourceReview(imdb_id, f"ebd/{record['review_id']}", text)


class Capped:
    """Keep at most `cap` reviews per film, chosen by hash of the review id.

    Hash order is arbitrary but fixed, so the kept set never depends on the order a dump was
    read in, and it is a fair sample across years (a "first N" rule would keep the oldest).
    A repeated review id is ignored.
    """

    def __init__(self, cap: int = MAX_REVIEWS_PER_SOURCE) -> None:
        """Create an empty collector.

        Args:
            cap: Most reviews kept per film.
        """
        self._cap = cap
        # Per film: max-heap on hash (negated) so the review to evict is always at the root.
        self._heaps: dict[int, list[tuple[int, str]]] = {}
        self._reviews: dict[int, dict[str, SourceReview]] = {}

    def add(self, review: SourceReview) -> None:
        """Offer a review; it is kept only if its hash ranks within the film's cap."""
        held = self._reviews.setdefault(review.imdb_id, {})
        if review.review_id in held:
            return
        digest = hashlib.sha1(review.review_id.encode("utf-8")).digest()
        entry = (-int.from_bytes(digest[:8], "big"), review.review_id)
        heap = self._heaps.setdefault(review.imdb_id, [])
        if len(heap) < self._cap:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            evicted = heapq.heapreplace(heap, entry)
            del held[evicted[1]]
        else:
            return
        held[review.review_id] = review

    def by_film(self) -> dict[int, list[SourceReview]]:
        """Kept reviews per IMDb number, each list sorted by review id."""
        return {
            imdb_id: sorted(reviews.values(), key=lambda r: r.review_id)
            for imdb_id, reviews in self._reviews.items()
        }
