"""The in-memory catalogue the API serves from: films, aspect profiles, evidence, similarity.

Built offline by `cinewhy.build`, written as plain JSON and one `.npy` (no pickle: nothing
here executes code on load), and read once at boot after `artifacts.verify` has checked
every hash. Nothing in this module trains or fits anything (CONSTRAINTS.md #5).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt

from cinewhy.schemas import Aspect, EvidenceSentence, Movie, MovieAspectProfile

CATALOGUE_FILE: Final[str] = "catalogue.json"
PROFILES_FILE: Final[str] = "profiles.json"
EVIDENCE_FILE: Final[str] = "evidence.json"
SIMILARITY_FILE: Final[str] = "item_sim.npy"

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


@dataclass
class Catalogue:
    """Everything the ranker needs, indexed by catalogue position."""

    movies: tuple[Movie, ...]
    stats: tuple[FilmStats, ...]
    profiles: dict[str, MovieAspectProfile]
    evidence: dict[str, dict[Aspect, tuple[EvidenceSentence, ...]]]
    similarity: npt.NDArray[np.float32]
    # Values chosen by the offline build (e.g. "inferred_fit_weight"), carried with the data
    # they were tuned on so a rollback restores both together.
    settings: dict[str, float] = field(default_factory=dict)
    index: dict[str, int] = field(init=False)
    # (n_films, n_aspects): support-shrunk aspect score, 0.0 where an aspect was not reported.
    aspect_matrix: npt.NDArray[np.float32] = field(init=False)

    def __post_init__(self) -> None:
        """Derive the id index and the shrunk aspect matrix; validate shapes."""
        n = len(self.movies)
        if self.similarity.shape != (n, n):
            raise ValueError(f"similarity is {self.similarity.shape}, expected {(n, n)}")
        if len(self.stats) != n:
            raise ValueError("stats and movies differ in length")
        self.index = {m.movie_id: i for i, m in enumerate(self.movies)}
        matrix = np.zeros((n, len(_ASPECTS)), dtype=np.float32)
        for movie_id, profile in self.profiles.items():
            row = self.index[movie_id]
            for score in profile.scores:
                shrunk = score.score * score.support / (score.support + SHRINK_K)
                matrix[row, _ASPECTS.index(score.aspect)] = shrunk
        self.aspect_matrix = matrix

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


def _dumps(obj: object) -> str:
    """Stable JSON: sorted keys so identical content always hashes identically."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def load_catalogue(directory: Path) -> Catalogue:
    """Read a catalogue from a verified artifact directory.

    Args:
        directory: Directory holding the four catalogue files. The caller must have run
            `artifacts.verify` on it first.

    Returns:
        The catalogue.

    Raises:
        ValueError: If the files disagree with each other (a film with a profile but no
            catalogue entry, or evidence for an unknown film).
    """
    document = json.loads((directory / CATALOGUE_FILE).read_text(encoding="utf-8"))
    raw = document["movies"]
    settings = {k: float(v) for k, v in document.get("settings", {}).items()}
    movies = tuple(
        Movie(
            movie_id=r["movie_id"],
            title=r["title"],
            year=r["year"],
            genres=tuple(r["genres"]),
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
    return Catalogue(movies, stats, profiles, evidence, similarity, settings)
