"""The contract, enforced.

These tests pass today. They are the one part of the scaffold that is fully implemented,
because the contract is what keeps two people building compatible halves.

If you change `cinewhy/schemas.py` and one of these fails, the test is the finding —
the contract is shared, and loosening it here silently breaks the other half of the
project (CONSTRAINTS.md #11).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cinewhy.schemas import (
    Aspect,
    AspectScore,
    EvidenceSentence,
    Movie,
    MovieAspectProfile,
    Reason,
    Recommendation,
    TasteProfile,
)

pytestmark = pytest.mark.contract


class TestReasonRequiresEvidence:
    """The product's central promise, made structurally unbreakable."""

    def test_reason_without_evidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Reason(aspect=Aspect.PACING, movie_score=0.7, user_weight=0.9, evidence=())

    def test_reason_with_evidence_is_accepted(self, pacing_reason: Reason) -> None:
        assert len(pacing_reason.evidence) == 2

    def test_evidence_must_match_the_reasons_aspect(self) -> None:
        """A pacing reason may not cite an acting sentence."""
        mismatched = EvidenceSentence(
            text="The lead gives the performance of her career.",
            aspect=Aspect.ACTING,
            polarity=0.9,
            source_review_id="rv-2001",
        )
        with pytest.raises(ValidationError, match="cites evidence for"):
            Reason(
                aspect=Aspect.PACING,
                movie_score=0.7,
                user_weight=0.9,
                evidence=(mismatched,),
            )


class TestRecommendationHonesty:
    """A personalised result explains itself; a fallback admits what it is."""

    def test_personalised_recommendation_needs_reasons(self, movie: Movie) -> None:
        with pytest.raises(ValidationError, match="no reasons"):
            Recommendation(movie=movie, score=0.8)

    def test_fallback_may_have_no_reasons(self, movie: Movie) -> None:
        rec = Recommendation(movie=movie, score=0.8, is_fallback=True)
        assert rec.reasons == ()

    def test_personalised_recommendation_with_reasons_is_valid(
        self, movie: Movie, pacing_reason: Reason
    ) -> None:
        rec = Recommendation(movie=movie, score=0.8, reasons=(pacing_reason,))
        assert rec.is_fallback is False


class TestBounds:
    """Polarity and weight ranges are enforced, not merely documented."""

    @pytest.mark.parametrize("bad", [-1.01, 1.01, 42.0])
    def test_polarity_outside_range_is_rejected(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            AspectScore(aspect=Aspect.PLOT, score=bad, support=10)

    @pytest.mark.parametrize("ok", [-1.0, 0.0, 1.0])
    def test_polarity_at_the_boundary_is_accepted(self, ok: float) -> None:
        assert AspectScore(aspect=Aspect.PLOT, score=ok, support=10).score == ok

    def test_negative_support_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AspectScore(aspect=Aspect.PLOT, score=0.5, support=-1)

    def test_weight_above_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TasteProfile(aspect_weights={Aspect.PACING: 1.5})


class TestProfileIntegrity:
    """Duplicates and typos are caught at construction, not at render time."""

    def test_duplicate_aspects_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate aspect"):
            MovieAspectProfile(
                movie_id="cw-1",
                scores=(
                    AspectScore(aspect=Aspect.PACING, score=0.1, support=5),
                    AspectScore(aspect=Aspect.PACING, score=0.9, support=5),
                ),
                total_reviews=10,
            )

    def test_unknown_field_is_rejected(self, movie: Movie) -> None:
        """extra="forbid" turns a typo into an error instead of a silently ignored field."""
        with pytest.raises(ValidationError):
            Movie(movie_id="cw-1", title="X", genre=("Drama",))  # type: ignore[call-arg]

    def test_value_objects_are_immutable(self, movie: Movie) -> None:
        with pytest.raises(ValidationError):
            movie.title = "Something Else"


class TestColdStart:
    """Cold start is a state, not an error."""

    def test_empty_profile_is_cold(self, cold_profile: TasteProfile) -> None:
        assert cold_profile.is_cold_start is True

    def test_profile_with_weights_is_warm(self, warm_profile: TasteProfile) -> None:
        assert warm_profile.is_cold_start is False


def test_every_aspect_has_a_stable_string_value() -> None:
    """Aspect values are persisted in artifacts; renaming one invalidates them all."""
    assert {a.value for a in Aspect} == {
        "acting",
        "plot",
        "pacing",
        "visuals",
        "ending",
        "soundtrack",
        "rewatchability",
    }
