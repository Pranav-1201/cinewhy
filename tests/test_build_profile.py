"""Behaviour of clause splitting and per-film aspect aggregation.

Expected numbers are derived by hand from `KeywordScorer` (+0.9 / -0.9 / 0.0), so a wrong
mean, support or evidence choice is visible as a wrong integer, not a vague "looks fine".
"""

from __future__ import annotations

import pytest

from cinewhy.absa.extract import build_profile, split_clauses
from cinewhy.schemas import Aspect
from tests.conftest import KeywordScorer


class TestSplitClauses:
    def test_splits_at_a_contrast_marker(self) -> None:
        sentence = "The acting was brilliant but the plot was dull and tedious."
        assert split_clauses(sentence) == [
            "The acting was brilliant",
            "the plot was dull and tedious.",
        ]

    def test_every_clause_is_a_verbatim_substring(self) -> None:
        sentence = "Great soundtrack, however the pacing dragged badly; the ending was fine."
        assert all(clause in sentence for clause in split_clauses(sentence))

    def test_does_not_split_when_a_side_is_too_short(self) -> None:
        assert split_clauses("Good, but.") == ["Good, but."]

    def test_a_sentence_without_a_marker_is_one_clause(self) -> None:
        assert split_clauses("The pacing was slow.") == ["The pacing was slow."]

    def test_while_is_not_a_contrast_marker(self) -> None:
        sentence = "I was bored while watching the slow second act."
        assert split_clauses(sentence) == [sentence]


def _reviews(*texts: str) -> list[tuple[str, str]]:
    return [(f"rv-{i}", t) for i, t in enumerate(texts)]


class TestBuildProfile:
    def test_score_is_the_mean_and_support_is_the_count(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        reviews = _reviews(
            "The pacing was superb throughout the whole film.",
            "The pacing was brilliant and kept me hooked.",
            "The pacing dragged badly in the middle hour of it.",
        )
        profile, _ = build_profile("m", reviews, model=keyword_scorer)
        (pacing,) = [s for s in profile.scores if s.aspect is Aspect.PACING]
        assert pacing.support == 3
        assert pacing.score == pytest.approx((0.9 + 0.9 - 0.9) / 3)
        assert profile.total_reviews == 3

    def test_contrast_gives_each_aspect_its_own_polarity(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        reviews = _reviews(*(["The acting was brilliant but the plot was dull and tedious."] * 3))
        profile, _ = build_profile("m", reviews, model=keyword_scorer)
        by_aspect = {s.aspect: s.score for s in profile.scores}
        assert by_aspect[Aspect.ACTING] == pytest.approx(0.9)
        assert by_aspect[Aspect.PLOT] == pytest.approx(-0.9)

    def test_aspects_below_min_support_are_dropped(self, keyword_scorer: KeywordScorer) -> None:
        reviews = _reviews("The pacing was superb throughout.", "The pacing was brilliant today.")
        profile, evidence = build_profile("m", reviews, min_support=3, model=keyword_scorer)
        assert profile.scores == ()
        assert list(evidence) == []

    def test_evidence_is_verbatim_and_agrees_with_the_score_sign(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        reviews = _reviews(
            "The pacing was superb and never let up for a second.",
            "The pacing was brilliant from the opening scene on.",
            "The pacing was wonderful and kept every scene tight.",
            "The pacing dragged terribly in the dull middle hour.",
        )
        profile, evidence = build_profile("m", reviews, model=keyword_scorer)
        (pacing,) = [s for s in profile.scores if s.aspect is Aspect.PACING]
        assert pacing.score > 0
        assert evidence, "a supported aspect must come with evidence"
        sources = dict(reviews)
        for e in evidence:
            assert e.text in sources[e.source_review_id]
            assert e.polarity > 0, "negative sentence cited for a positive aspect"

    def test_at_most_one_evidence_sentence_per_review(self, keyword_scorer: KeywordScorer) -> None:
        one_review = (
            "The pacing was superb and never let up for a second. "
            "The pacing was brilliant from the opening scene on. "
            "The pacing was wonderful and kept every scene tight."
        )
        reviews = _reviews(one_review, one_review, one_review)
        _, evidence = build_profile("m", reviews, model=keyword_scorer)
        ids = [e.source_review_id for e in evidence]
        assert len(ids) == len(set(ids))

    def test_fragments_too_short_to_quote_are_not_evidence(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        reviews = _reviews("Superb pacing.", "Brilliant pacing.", "Wonderful pacing.")
        profile, evidence = build_profile("m", reviews, model=keyword_scorer)
        assert profile.scores, "the aspect is still scored"
        assert list(evidence) == []

    def test_output_is_deterministic(self, keyword_scorer: KeywordScorer) -> None:
        reviews = _reviews(
            *(f"The pacing was superb in take number {i} of them." for i in range(5))
        )
        first = build_profile("m", reviews, model=keyword_scorer)
        second = build_profile("m", reviews, model=keyword_scorer)
        assert first == second

    def test_source_url_is_attached_to_evidence(self, keyword_scorer: KeywordScorer) -> None:
        reviews = _reviews(
            *(f"The pacing was superb in take number {i} of them." for i in range(3))
        )
        _, evidence = build_profile(
            "m", reviews, model=keyword_scorer, source_url="https://x.test/"
        )
        assert evidence and all(e.source_url == "https://x.test/" for e in evidence)

    def test_no_reviews_is_an_empty_profile_not_an_error(
        self, keyword_scorer: KeywordScorer
    ) -> None:
        profile, evidence = build_profile("m", [], model=keyword_scorer)
        assert profile.scores == () and profile.total_reviews == 0 and list(evidence) == []
