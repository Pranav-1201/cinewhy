"""Aspect-based sentiment extraction — the component the product is built on.

Given review text for a film, decide which aspects each sentence talks about and how
positively. The output is `MovieAspectProfile` plus the `EvidenceSentence` objects the
UI quotes verbatim.

The IMDB 50k corpus trains the polarity half of this. It cannot supply the other half:
it has no movie identifiers (DECISIONS.md D-002), so aspect scores can only be attached
to films once Phase D lands an item-keyed corpus.

Phase C/D boundary. Owner: see CONTRIBUTING.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from cinewhy.schemas import Aspect, EvidenceSentence, MovieAspectProfile


def split_sentences(document: str) -> list[str]:
    """Split a review into candidate sentences.

    Aspect scoring is per sentence, not per review: one review routinely praises the
    acting and criticises the pacing, and collapsing it to a single document-level
    polarity throws away exactly the signal this product sells.

    Args:
        document: One full review.

    Returns:
        Sentences in source order. Never empty for non-empty input.
    """
    raise NotImplementedError("Phase C")


def detect_aspects(sentence: str) -> frozenset[Aspect]:
    """Return the aspects a sentence is talking about.

    May return an empty set — most sentences in a review are plot summary or
    throat-clearing and belong to no aspect. Returning nothing is the correct answer
    far more often than not, and forcing an assignment is how the evidence panel fills
    with irrelevant quotes.

    Args:
        sentence: One sentence.

    Returns:
        Zero or more aspects.
    """
    raise NotImplementedError("Phase C")


def score_polarity(sentence: str) -> float:
    """Score one sentence from -1 (negative) to +1 (positive).

    Must be trained and evaluated under the methodology rules: fit on train only,
    select on cross-validation, report with spread (CONSTRAINTS.md #1-#3).

    Args:
        sentence: One sentence.

    Returns:
        Polarity in [-1.0, 1.0].
    """
    raise NotImplementedError("Phase C")


def build_profile(
    movie_id: str,
    reviews: Iterable[tuple[str, str]],
    *,
    min_support: int = 3,
) -> tuple[MovieAspectProfile, Sequence[EvidenceSentence]]:
    """Aggregate per-sentence judgements into one film's aspect profile.

    Aspects with fewer than `min_support` supporting sentences are dropped rather than
    reported with a wide error bar the UI has no room to show. A missing aspect renders
    as "not enough reviews mention this", which is honest; a score computed from one
    sentence rendered identically to one computed from four hundred is not.

    Args:
        movie_id: CineWhy internal id.
        reviews: Pairs of (review_id, review_text).
        min_support: Minimum supporting sentences for an aspect to be reported.

    Returns:
        The profile, and the evidence sentences selected to justify it.
    """
    raise NotImplementedError("Phase D")
