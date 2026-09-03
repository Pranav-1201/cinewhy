"""Shared fixtures.

Fixtures here are the vocabulary both halves of the team write tests in. Adding one is
cheap; changing an existing one affects the other person's tests, so treat edits the
same way as edits to `cinewhy/schemas.py`.
"""

from __future__ import annotations

import pytest

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


@pytest.fixture
def negation_pair() -> tuple[str, str]:
    """Two reviews differing only by a negation.

    The witness for the audit's C-3 defect. In the original pipeline both of these
    normalised to 'movi good', produced identical vectors, and got the same prediction.
    """
    return ("This movie was not good at all.", "This movie was good.")
