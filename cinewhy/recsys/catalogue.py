"""The in-memory catalogue the API serves from: films, aspect profiles, evidence, similarity.

Built offline by `cinewhy.build`, written as plain JSON and one `.npy` (no pickle: nothing
here executes code on load), and read once at boot after `artifacts.verify` has checked
every hash. Nothing in this module trains or fits anything (CONSTRAINTS.md #5).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from cinewhy.schemas import Aspect, EvidenceSentence, Movie, MovieAspectProfile

CATALOGUE_FILE: Final[str] = "catalogue.json"
PROFILES_FILE: Final[str] = "profiles.json"
EVIDENCE_FILE: Final[str] = "evidence.json"
SIMILARITY_FILE: Final[str] = "item_sim.npy"
META_FILE: Final[str] = "meta.json"
RATINGS_ONLY_FILE: Final[str] = "ratings_only.json"

# Where TMDB serves poster images, at a width that suits a card (342 px). TMDB's terms require
# attribution wherever these are shown (docs/FEATURE-004.md, step 2).
POSTER_BASE: Final[str] = "https://image.tmdb.org/t/p/w342"
# A poster path lands inside a URL the browser loads, so only the shape TMDB actually uses is
# accepted: one segment of letters, digits, `_` and `-`, then an image extension. Anything else
# (a `..`, a second slash, a query string) is dropped, not repaired.
_POSTER_PATH: Final[re.Pattern[str]] = re.compile(r"/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp)")


def poster_url(path: object) -> str | None:
    """The browser URL for a TMDB poster path, or None when there is no safe one."""
    if isinstance(path, str) and _POSTER_PATH.fullmatch(path):
        return POSTER_BASE + path
    return None


# An aspect score from 3 sentences is a hint, from 300 a measurement. Shrinking by
# `support / (support + K)` keeps a lightly-supported +0.9 from outranking a well-supported
# +0.5. K = 5 means five supporting sentences earn half their raw score.
SHRINK_K: Final[float] = 5.0

_ASPECTS: Final[tuple[Aspect, ...]] = tuple(Aspect)


@dataclass(frozen=True)
class FilmStats:
    """Rating and review volume for one film, as measured in the source data."""

    imdb_id: int
    rating_count: int
    bayes_mean: float
    review_count: int


@dataclass(frozen=True)
class RatingsOnlyFilm:
    """A film we hold ratings for but have not read reviews of (roadmap section 15, "Tier B").

    These have an IMDb rating and vote count and TMDB's description, but fewer than 50 reviews,
    so there is no aspect profile, no quotes and no row in the similarity matrix. They are ranked
    on how well known and well rated they are and on genre, and the page says so.
    """

    movie: Movie
    imdb_id: int
    language: str | None
    imdb_rating: float
    imdb_votes: int
    overview: str | None = None
    release_date: str | None = None
    runtime: int | None = None


@dataclass
class Catalogue:
    """Everything the ranker needs, indexed by catalogue position.

    Positions `0 .. len(movies) - 1` are the full-receipt films, which alone have rows in
    `similarity` and `aspect_matrix`. Ratings-only films follow, so the position of the i-th one
    is `len(movies) + i`; `film_at` and `all_movies` hide that offset from callers.
    """

    movies: tuple[Movie, ...]
    stats: tuple[FilmStats, ...]
    profiles: dict[str, MovieAspectProfile]
    evidence: dict[str, dict[Aspect, tuple[EvidenceSentence, ...]]]
    similarity: npt.NDArray[np.float32]
    # Values chosen by the offline build (e.g. "inferred_fit_weight"), carried with the data
    # they were tuned on so a rollback restores both together.
    settings: dict[str, float] = field(default_factory=dict)
    # TMDB fields per movie id (overview, language, runtime, ...), read from the verified
    # `meta.json`. Empty when the artifact set has none.
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    ratings_only: tuple[RatingsOnlyFilm, ...] = ()
    # Id to position for full-receipt films only: every row of `similarity` and `aspect_matrix`
    # is one of these, so code indexing them with `index[...]` can never reach a ratings-only film.
    index: dict[str, int] = field(init=False)
    # Id to position over BOTH kinds of film (see the class docstring).
    all_index: dict[str, int] = field(init=False)
    # (n_films, n_aspects): support-shrunk aspect score, 0.0 where an aspect was not reported.
    aspect_matrix: npt.NDArray[np.float32] = field(init=False)
    # True at the position of every TV series (both tiers), so a "series only" filter is one array
    # lookup per shelf, not a loop over every title.
    is_series: npt.NDArray[np.bool_] = field(init=False)

    def __post_init__(self) -> None:
        """Derive the id index and the shrunk aspect matrix; validate shapes."""
        n = len(self.movies)
        if self.similarity.shape != (n, n):
            raise ValueError(f"similarity is {self.similarity.shape}, expected {(n, n)}")
        if len(self.stats) != n:
            raise ValueError("stats and movies differ in length")
        self.index = {m.movie_id: i for i, m in enumerate(self.movies)}
        self.all_index = dict(self.index)
        for offset, film in enumerate(self.ratings_only):
            if film.movie.movie_id in self.all_index:
                raise ValueError(f"{film.movie.movie_id} is in both tiers")
            self.all_index[film.movie.movie_id] = n + offset
        matrix = np.zeros((n, len(_ASPECTS)), dtype=np.float32)
        for movie_id, profile in self.profiles.items():
            row = self.index[movie_id]
            for score in profile.scores:
                shrunk = score.score * score.support / (score.support + SHRINK_K)
                matrix[row, _ASPECTS.index(score.aspect)] = shrunk
        self.aspect_matrix = matrix
        self.is_series = np.array([m.kind == "series" for m in self.all_movies], dtype=bool)

    @property
    def all_movies(self) -> tuple[Movie, ...]:
        """Every film, full-receipt first then ratings-only, in position order."""
        return self.movies + tuple(f.movie for f in self.ratings_only)

    def is_ratings_only(self, position: int) -> bool:
        """True when this position belongs to a ratings-only film."""
        return position >= len(self.movies)

    def ratings_only_at(self, position: int) -> RatingsOnlyFilm:
        """The ratings-only film at a position (the caller checked `is_ratings_only`)."""
        return self.ratings_only[position - len(self.movies)]

    def shrunk(self, movie_id: str, aspect: Aspect) -> float:
        """Support-shrunk score of one film on one aspect (0.0 when not reported)."""
        return float(self.aspect_matrix[self.index[movie_id], _ASPECTS.index(aspect)])


def aspect_order() -> tuple[Aspect, ...]:
    """Column order of `Catalogue.aspect_matrix`."""
    return _ASPECTS


def write_catalogue(directory: Path, catalogue: Catalogue) -> None:
    """Write the four catalogue files. The format is whatever `load_catalogue` reads.

    Args:
        directory: Existing directory to write into.
        catalogue: The catalogue to persist.
    """
    movies = [
        {
            "movie_id": m.movie_id,
            "title": m.title,
            "year": m.year,
            "genres": list(m.genres),
            "kind": m.kind,
            "imdb_id": s.imdb_id,
            "rating_count": s.rating_count,
            "bayes_mean": s.bayes_mean,
            "review_count": s.review_count,
        }
        for m, s in zip(catalogue.movies, catalogue.stats, strict=True)
    ]
    (directory / CATALOGUE_FILE).write_text(
        _dumps({"movies": movies, "settings": catalogue.settings}), encoding="utf-8"
    )
    profiles = {k: v.model_dump(mode="json") for k, v in sorted(catalogue.profiles.items())}
    (directory / PROFILES_FILE).write_text(_dumps(profiles), encoding="utf-8")
    evidence = {
        movie_id: [e.model_dump(mode="json") for a in Aspect for e in by_aspect.get(a, ())]
        for movie_id, by_aspect in sorted(catalogue.evidence.items())
    }
    (directory / EVIDENCE_FILE).write_text(_dumps(evidence), encoding="utf-8")
    np.save(directory / SIMILARITY_FILE, catalogue.similarity, allow_pickle=False)
    if catalogue.ratings_only:
        (directory / RATINGS_ONLY_FILE).write_text(
            _dumps([_ratings_only_record(f) for f in catalogue.ratings_only]), encoding="utf-8"
        )


def _ratings_only_record(film: RatingsOnlyFilm) -> dict[str, Any]:
    """One ratings-only film as plain JSON; the poster is stored as TMDB's path, not a full URL."""
    url = film.movie.poster_url
    return {
        "movie_id": film.movie.movie_id,
        "title": film.movie.title,
        "year": film.movie.year,
        "genres": list(film.movie.genres),
        "kind": film.movie.kind,
        "poster_path": url.removeprefix(POSTER_BASE) if url else None,
        "imdb_id": film.imdb_id,
        "language": film.language,
        "imdb_rating": film.imdb_rating,
        "imdb_votes": film.imdb_votes,
        "overview": film.overview,
        "release_date": film.release_date,
        "runtime": film.runtime,
    }


def _read_ratings_only(path: Path) -> tuple[RatingsOnlyFilm, ...]:
    """Ratings-only films from `ratings_only.json`; the caller has verified the file's hash."""
    return tuple(
        RatingsOnlyFilm(
            movie=Movie(
                movie_id=r["movie_id"],
                title=r["title"],
                year=r["year"],
                genres=tuple(r["genres"]),
                poster_url=poster_url(r.get("poster_path")),
                kind=r.get("kind", "film"),
            ),
            imdb_id=int(r["imdb_id"]),
            language=r.get("language") or None,
            imdb_rating=float(r["imdb_rating"]),
            imdb_votes=int(r["imdb_votes"]),
            overview=r.get("overview") or None,
            release_date=r.get("release_date") or None,
            runtime=int(r["runtime"]) if r.get("runtime") else None,
        )
        for r in json.loads(path.read_text(encoding="utf-8"))
    )


def _dumps(obj: object) -> str:
    """Stable JSON: sorted keys so identical content always hashes identically."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def load_catalogue(
    directory: Path, *, with_meta: bool = False, with_ratings_only: bool = False
) -> Catalogue:
    """Read a catalogue from a verified artifact directory.

    Args:
        directory: Directory holding the four catalogue files. The caller must have run
            `artifacts.verify` on it first.
        with_meta: Also read `meta.json` and give each film its poster URL. The caller passes
            True only when the verified manifest lists that file: a `meta.json` that is merely
            sitting in the directory is unverified and must not change what browsers are told.
        with_ratings_only: Also read `ratings_only.json`, on the same condition: only when the
            verified manifest lists it.

    Returns:
        The catalogue.

    Raises:
        ValueError: If the files disagree with each other (a film with a profile but no
            catalogue entry, or evidence for an unknown film).
    """
    document = json.loads((directory / CATALOGUE_FILE).read_text(encoding="utf-8"))
    raw = document["movies"]
    settings = {k: float(v) for k, v in document.get("settings", {}).items()}
    meta: dict[str, dict[str, Any]] = (
        json.loads((directory / META_FILE).read_text(encoding="utf-8")) if with_meta else {}
    )
    movies = tuple(
        Movie(
            movie_id=r["movie_id"],
            title=r["title"],
            year=r["year"],
            genres=tuple(r["genres"]),
            poster_url=poster_url(meta.get(r["movie_id"], {}).get("poster_path")),
            kind=r.get("kind", "film"),
        )
        for r in raw
    )
    stats = tuple(
        FilmStats(r["imdb_id"], r["rating_count"], r["bayes_mean"], r["review_count"]) for r in raw
    )
    profiles = {
        movie_id: MovieAspectProfile.model_validate(p)
        for movie_id, p in json.loads(
            (directory / PROFILES_FILE).read_text(encoding="utf-8")
        ).items()
    }
    grouped: dict[str, dict[Aspect, list[EvidenceSentence]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for movie_id, sentences in json.loads(
        (directory / EVIDENCE_FILE).read_text(encoding="utf-8")
    ).items():
        for s in sentences:
            sentence = EvidenceSentence.model_validate(s)
            grouped[movie_id][sentence.aspect].append(sentence)
    evidence = {m: {a: tuple(v) for a, v in by.items()} for m, by in grouped.items()}

    known = {m.movie_id for m in movies}
    stray = (set(profiles) | set(evidence)) - known
    if stray:
        raise ValueError(f"profiles/evidence for films not in the catalogue: {sorted(stray)[:3]}")
    similarity = np.load(directory / SIMILARITY_FILE, allow_pickle=False)
    ratings_only = _read_ratings_only(directory / RATINGS_ONLY_FILE) if with_ratings_only else ()
    return Catalogue(movies, stats, profiles, evidence, similarity, settings, meta, ratings_only)
