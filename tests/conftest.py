"""Shared fixtures.

Fixtures here are the vocabulary both halves of the team write tests in. Adding one is
cheap; changing an existing one affects the other person's tests, so treat edits the
same way as edits to `cinewhy/schemas.py`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from cinewhy.absa.polarity import PolarityModel
from cinewhy.artifacts.manifest import build as build_manifest
from cinewhy.recsys.catalogue import Catalogue, FilmStats, write_catalogue
from cinewhy.schemas import (
    Aspect,
    AspectScore,
    EvidenceSentence,
    Movie,
    MovieAspectProfile,
    Reason,
    TasteProfile,
)


@pytest.fixture
def movie() -> Movie:
    """A film with every optional field populated."""
    return Movie(
        movie_id="cw-000042",
        title="Sequence of Events",
        year=2019,
        genres=("Drama", "Thriller"),
        poster_url="https://example.invalid/p/42.jpg",
    )


@pytest.fixture
def pacing_evidence() -> tuple[EvidenceSentence, ...]:
    """Two real-shaped evidence sentences, both about pacing."""
    return (
        EvidenceSentence(
            text="The middle hour drags badly and the film never recovers its momentum.",
            aspect=Aspect.PACING,
            polarity=-0.8,
            source_review_id="rv-1001",
        ),
        EvidenceSentence(
            text="Every scene earns its place; nothing is wasted.",
            aspect=Aspect.PACING,
            polarity=0.9,
            source_review_id="rv-1002",
            source_url="https://example.invalid/r/1002",
        ),
    )


@pytest.fixture
def pacing_reason(pacing_evidence: tuple[EvidenceSentence, ...]) -> Reason:
    """A well-formed reason: aspect, scores, and evidence that matches the aspect."""
    return Reason(
        aspect=Aspect.PACING,
        movie_score=0.71,
        user_weight=0.9,
        evidence=pacing_evidence,
    )


@pytest.fixture
def aspect_profile() -> MovieAspectProfile:
    """A film scored on three aspects with differing support."""
    return MovieAspectProfile(
        movie_id="cw-000042",
        scores=(
            AspectScore(aspect=Aspect.PACING, score=0.71, support=1240),
            AspectScore(aspect=Aspect.ACTING, score=0.44, support=980),
            AspectScore(aspect=Aspect.ENDING, score=-0.33, support=112),
        ),
        total_reviews=1500,
    )


@pytest.fixture
def warm_profile() -> TasteProfile:
    """A viewer who cares about pacing and endings."""
    return TasteProfile(
        aspect_weights={Aspect.PACING: 0.9, Aspect.ENDING: 0.7},
        liked_movie_ids=("cw-000001", "cw-000002"),
    )


@pytest.fixture
def cold_profile() -> TasteProfile:
    """A viewer we know nothing about."""
    return TasteProfile()


class KeywordScorer:
    """A deterministic stand-in for `PolarityModel`: polarity from a few marker words.

    It lets aggregation tests state their expected numbers by hand. It is NOT a model and
    is never used to claim anything about accuracy.
    """

    POSITIVE = ("superb", "brilliant", "great", "loved", "stunning", "wonderful")
    NEGATIVE = ("dull", "dragged", "terrible", "awful", "tedious", "boring")

    def score_many(self, texts: Sequence[str]) -> list[float]:
        """+0.9 if a positive marker appears, -0.9 if a negative one does, else 0.0."""
        out: list[float] = []
        for text in texts:
            lowered = text.lower()
            if any(w in lowered for w in self.NEGATIVE):
                out.append(-0.9)
            elif any(w in lowered for w in self.POSITIVE):
                out.append(0.9)
            else:
                out.append(0.0)
        return out


@pytest.fixture
def keyword_scorer() -> KeywordScorer:
    """Stand-in polarity scorer for aggregation tests."""
    return KeywordScorer()


@pytest.fixture
def negation_pair() -> tuple[str, str]:
    """Two reviews differing only by a negation.

    The witness for the audit's C-3 defect. In the original pipeline both of these
    normalised to 'movi good', produced identical vectors, and got the same prediction.
    """
    return ("This movie was not good at all.", "This movie was good.")


def _evidence(movie_id: str, aspect: Aspect, polarity: float = 0.8) -> tuple[EvidenceSentence, ...]:
    return tuple(
        EvidenceSentence(
            text=f"A real sentence number {n} praising the {aspect.value} of {movie_id}.",
            aspect=aspect,
            polarity=polarity,
            source_review_id=f"rv-{movie_id}-{aspect.value}-{n}",
        )
        for n in range(2)
    )


def make_catalogue(titles: tuple[str, ...] | None = None) -> Catalogue:
    """Six films. cw-5 has no aspect data at all; cw-6's pacing has support 2 (shrunk 0.257)."""
    names = titles or ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta")
    movies = tuple(Movie(movie_id=f"cw-{i + 1}", title=t) for i, t in enumerate(names))
    spec: dict[str, list[tuple[Aspect, float, int]]] = {
        "cw-1": [(Aspect.PACING, 0.8, 20), (Aspect.ENDING, 0.6, 20)],
        "cw-2": [(Aspect.PACING, 0.7, 20), (Aspect.ACTING, 0.5, 20)],
        "cw-3": [(Aspect.SOUNDTRACK, 0.9, 20)],
        "cw-4": [(Aspect.PACING, -0.6, 20), (Aspect.PLOT, 0.4, 20)],
        "cw-5": [],
        "cw-6": [(Aspect.PACING, 0.9, 2)],
    }
    profiles = {
        m.movie_id: MovieAspectProfile(
            movie_id=m.movie_id,
            scores=tuple(AspectScore(aspect=a, score=s, support=n) for a, s, n in spec[m.movie_id]),
            total_reviews=30,
        )
        for m in movies
    }
    evidence = {
        m.movie_id: by_aspect
        for m in movies
        # Canonical form: a film with nothing to quote has no entry (the loader agrees).
        if (by_aspect := {a: _evidence(m.movie_id, a, s) for a, s, _ in spec[m.movie_id] if s > 0})
    }
    sim = np.zeros((6, 6), dtype=np.float32)
    sim[0, 1] = sim[1, 0] = 0.8
    sim[0, 2] = sim[2, 0] = 0.1
    bayes = [4.0, 3.9, 4.5, 3.0, 4.8, 3.5]
    counts = [900, 800, 700, 600, 500, 400]
    stats = tuple(FilmStats(100 + i, counts[i], bayes[i], 30) for i in range(6))
    return Catalogue(movies, stats, profiles, evidence, sim)


def _toy_polarity_model() -> PolarityModel:
    """A tiny model fitted on a dozen sentences. It exists to exercise the endpoints."""
    texts = [
        "superb brilliant wonderful great", "loved it great fun", "stunning beautiful superb",
        "great acting wonderful story", "brilliant and moving", "a joy wonderful",
        "dull boring awful terrible", "tedious dull waste", "awful acting terrible plot",
        "boring and bad", "terrible dull mess", "not good at all boring",
    ]  # fmt: skip
    labels = [1] * 6 + [0] * 6
    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    classifier = LogisticRegression(C=10.0).fit(vectorizer.fit_transform(texts), labels)
    return PolarityModel(vectorizer, classifier)


@pytest.fixture
def artifact_dir(tmp_path: Path) -> Path:
    """A complete, hash-verified artifact directory built from the six-film catalogue."""
    write_catalogue(tmp_path, make_catalogue())
    _toy_polarity_model().save(tmp_path / "polarity.joblib")
    (tmp_path / "eval.json").write_text(json.dumps({"catalogue": {"films": 6}}), encoding="utf-8")
    build_manifest(tmp_path)
    return tmp_path


@pytest.fixture
def loaded_api(artifact_dir: Path) -> Iterator[Path]:
    """`api.main` with the six-film artifacts loaded, reset afterwards."""
    import api.main as api_main

    api_main.load_artifacts(artifact_dir)
    yield artifact_dir
    api_main._state = None
