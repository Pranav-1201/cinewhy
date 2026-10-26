"""Gather the catalogue's films and reviews from four dumps (FEATURE-004).

TMDB chooses the films (`spine`); aclImdb joins by exact IMDb number; Rotten Tomatoes and ebD
join by title and year under the rules in `linking`. This module only gathers and merges; it
scores nothing and fits nothing.

Merging keeps three guarantees the product relies on:

* every review id starts with its source (`acl/`, `ebd/`, `rt/`), so a quoted sentence is traceable;
* a review present in two dumps is kept once, because aclImdb and ebD are both IMDb scrapes and
  counting a review twice would inflate a film's support and could quote it twice;
* nothing is guessed: ambiguous or unconfirmed matches contribute no reviews at all.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cinewhy.data.linking import (
    Candidate,
    MatchResult,
    ambiguous_candidate_keys,
    film_key,
    match_film,
    title_key,
)
from cinewhy.data.reviews import (
    MAX_REVIEWS_PER_SOURCE,
    Capped,
    RtFilm,
    SourceReview,
    iter_ebd_reviews,
    iter_rt_reviews,
    read_rt_films,
    scan_ebd_keys,
)
from cinewhy.data.sources import iter_reviews
from cinewhy.data.spine import SpineFilm, quota, read_tmdb_rows, select_spine

# Where a duplicated review is kept from: the older, exact-id source first.
_SOURCE_ORDER = ("acl", "ebd", "rt")


@dataclass(frozen=True)
class SourcePaths:
    """Where the four raw dumps live (all gitignored; see docs/DATASET.md)."""

    tmdb_csv: Path = Path("Data/raw/tmdb1m/TMDB_all_movies.csv")
    rt_zip: Path = Path("Data/raw/rt_mother/rt_mother.zip")
    ebd_zip: Path = Path("Data/raw/imdb_ebd/imdb_ebd.zip")
    acl_archive: Path = Path("Data/raw/aclImdb_v1.tar.gz")


@dataclass(frozen=True)
class Gathered:
    """The selected films and their merged, capped, de-duplicated reviews."""

    films: tuple[SpineFilm, ...]
    # IMDb number -> (source-prefixed review id, text), sorted by review id.
    reviews: dict[int, list[tuple[str, str]]]
    # IMDb number -> the film's Rotten Tomatoes page, for films that linked to RT.
    rt_url: dict[int, str]
    # JSON-serialisable counts that go into eval.json: what linked, what was refused, and why.
    report: dict[str, Any]


def _silent(_message: str) -> None:
    return None


# Bump when selection, linking, cleaning or merging changes: a cache written by older logic
# would otherwise hide the change behind stale data.
GATHER_VERSION = 2  # 2: films carry imdb_rating, imdb_votes and vote_average


def _cache_key(paths: SourcePaths, cap: int) -> dict[str, Any]:
    """Everything the gathered result depends on: logic version, cap, and each dump's identity."""
    files: dict[str, list[int]] = {}
    for name, path in (
        ("tmdb", paths.tmdb_csv),
        ("rt", paths.rt_zip),
        ("ebd", paths.ebd_zip),
        ("acl", paths.acl_archive),
    ):
        stat = path.stat()
        files[name] = [stat.st_size, stat.st_mtime_ns]
    return {"version": GATHER_VERSION, "cap": cap, "files": files}


def _write_cache(cache_file: Path, key: dict[str, Any], gathered: Gathered) -> None:
    """Write JSON lines: a header (key, films, links, report), then one line per film.

    One line per film keeps memory flat for about half a gigabyte of review text, and writing to
    a temporary file first means a crash mid-write never leaves a cache that looks complete.
    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "key": key,
        "films": [asdict(f) for f in gathered.films],
        "rt_url": {str(imdb): url for imdb, url in gathered.rt_url.items()},
        "report": gathered.report,
        "entries": len(gathered.reviews),
    }
    temporary = cache_file.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        for imdb_id, reviews in gathered.reviews.items():
            handle.write(json.dumps({"imdb": imdb_id, "reviews": reviews}, ensure_ascii=False))
            handle.write("\n")
    temporary.replace(cache_file)


def _read_cache(cache_file: Path, key: dict[str, Any]) -> Gathered | None:
    """The cached result, or None when it is absent, for other inputs, or damaged."""
    if not cache_file.is_file():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            if header["key"] != key:
                return None
            reviews: dict[int, list[tuple[str, str]]] = {}
            for line in handle:
                entry = json.loads(line)
                reviews[int(entry["imdb"])] = [(r[0], r[1]) for r in entry["reviews"]]
            if len(reviews) != header["entries"]:
                return None
            films = tuple(SpineFilm(**{**f, "genres": tuple(f["genres"])}) for f in header["films"])
            rt_url = {int(imdb): url for imdb, url in header["rt_url"].items()}
            return Gathered(films, reviews, rt_url, header["report"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError):
        return None


def gather_cached(
    paths: SourcePaths,
    cache_file: Path,
    *,
    cap: int = MAX_REVIEWS_PER_SOURCE,
    on_progress: Callable[[str], None] = _silent,
) -> Gathered:
    """`gather`, reusing a cached result when nothing it depends on has changed.

    Args:
        paths: Locations of the four dumps.
        cache_file: Where the result is kept between runs.
        cap: Most reviews kept per film per source.
        on_progress: Called with a status line at each stage.

    Returns:
        The same result `gather` would return.
    """
    key = _cache_key(paths, cap)
    cached = _read_cache(cache_file, key)
    if cached is not None:
        on_progress(f"using the cached gather result at {cache_file}")
        return cached
    gathered = gather(paths, cap=cap, on_progress=on_progress)
    _write_cache(cache_file, key, gathered)
    return gathered


def _claim_rt_film(
    owners: dict[str, tuple[int, str]], movie_id: str, imdb_id: int, status: str
) -> None:
    """Record that a TMDB film claims an RT film, resolving two claims on the same RT film.

    An exact-year claim beats an adjacent-year one; two claims of the same strength cannot be
    told apart, so neither film gets that RT film's reviews.
    """
    held = owners.get(movie_id)
    if held is None or held[0] == imdb_id or (held[1] == "adjacent" and status == "exact"):
        owners[movie_id] = (imdb_id, status)
    elif held[1] == status:
        owners[movie_id] = (-1, "conflict")  # a sentinel no film has; removed by the caller


def _text_key(text: str) -> str:
    """Identity of a review's wording, ignoring case, punctuation and spacing."""
    return hashlib.sha1(title_key(text).encode("utf-8")).hexdigest()


def gather(
    paths: SourcePaths,
    *,
    cap: int = MAX_REVIEWS_PER_SOURCE,
    quota_for: Callable[[str, int], int] = quota,
    on_progress: Callable[[str], None] = _silent,
) -> Gathered:
    """Select the films and collect their reviews from every source.

    Args:
        paths: Locations of the four dumps.
        cap: Most reviews kept per film per source.
        quota_for: Films kept per (language, year); injectable for tests.
        on_progress: Called with a status line at each stage (the streams take minutes).

    Returns:
        The films, merged reviews, Rotten Tomatoes links, and a report of every join outcome.
    """
    selection = select_spine(read_tmdb_rows(paths.tmdb_csv), quota_for)
    films = selection.films
    on_progress(f"selected {len(films)} films from TMDB")
    candidates = [Candidate(f.imdb_id, f.title, f.year, f.language, f.runtime) for f in films]
    collisions = ambiguous_candidate_keys(candidates)
    linkable = [c for c in candidates if film_key(c.title, c.year) not in collisions]

    rt_index: dict[str, list[RtFilm]] = defaultdict(list)
    for rt_film in read_rt_films(paths.rt_zip):
        rt_index[film_key(rt_film.title, rt_film.year)].append(rt_film)
    rt_status: Counter[str] = Counter()
    owners: dict[str, tuple[int, str]] = {}
    rt_urls_by_movie: dict[str, str] = {}
    for c in linkable:
        result: MatchResult[RtFilm] = match_film(c, rt_index, lambda f: f.runtime)
        rt_status[f"{c.language}/{result.status}"] += 1
        if result.item is not None:
            _claim_rt_film(owners, result.item.movie_id, c.imdb_id, result.status)
            rt_urls_by_movie[result.item.movie_id] = result.item.url
    conflicts = sum(1 for imdb_id, _ in owners.values() if imdb_id == -1)
    rt_imdb_of = {m: imdb_id for m, (imdb_id, _) in owners.items() if imdb_id != -1}
    rt_url = {imdb_id: rt_urls_by_movie[m] for m, imdb_id in rt_imdb_of.items()}
    on_progress(f"RT: {len(rt_imdb_of)} films linked ({conflicts} contested)")

    ebd_keys = scan_ebd_keys(paths.ebd_zip)
    ebd_index = {key: [key] for key in ebd_keys}
    ebd_status: Counter[str] = Counter()
    ebd_imdb_of: dict[str, int] = {}
    for c in linkable:
        found = match_film(c, ebd_index, lambda _key: None)
        ebd_status[f"{c.language}/{found.status}"] += 1
        if found.item is not None:
            ebd_imdb_of[found.item] = c.imdb_id
    on_progress(f"ebD: {len(ebd_imdb_of)} films linked")

    capped = {name: Capped(cap) for name in _SOURCE_ORDER}
    for acl_review in iter_reviews(paths.acl_archive, frozenset(f.imdb_id for f in films)):
        capped["acl"].add(
            SourceReview(acl_review.imdb_id, f"acl/{acl_review.review_id}", acl_review.text)
        )
    on_progress("aclImdb reviews read")
    for ebd_review in iter_ebd_reviews(paths.ebd_zip, ebd_imdb_of):
        capped["ebd"].add(ebd_review)
    on_progress("ebD reviews read")
    for rt_review in iter_rt_reviews(paths.rt_zip, rt_imdb_of):
        capped["rt"].add(rt_review)
    on_progress("RT reviews read")

    per_source = {name: c.by_film() for name, c in capped.items()}
    reviews: dict[int, list[tuple[str, str]]] = {}
    duplicates = 0
    for film in films:
        seen: set[str] = set()
        merged: list[tuple[str, str]] = []
        for name in _SOURCE_ORDER:
            for review in per_source[name].get(film.imdb_id, []):
                key = _text_key(review.text)
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                merged.append((review.review_id, review.text))
        if merged:
            reviews[film.imdb_id] = sorted(merged)

    report: dict[str, Any] = {
        "films_selected": len(films),
        "dropped_no_imdb_number": selection.dropped_no_imdb,
        "dropped_duplicate_imdb_number": selection.dropped_duplicate_imdb,
        "candidate_title_collisions": len(candidates) - len(linkable),
        "rt_link": dict(sorted(rt_status.items())),
        "rt_contested_films": conflicts,
        "ebd_link": dict(sorted(ebd_status.items())),
        "reviews_per_source_after_cap": {
            name: sum(len(v) for v in by_film.values()) for name, by_film in per_source.items()
        },
        "duplicates_dropped": duplicates,
        "films_with_reviews": len(reviews),
    }
    return Gathered(films, reviews, rt_url, report)
