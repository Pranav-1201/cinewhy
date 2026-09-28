"""Behaviour of `cinewhy.text.dedupe` (audit item M4).

The guard that proves duplicates cannot straddle a split lives in
`test_methodology.py`; this file pins the helper's own contract so a refactor cannot
quietly change which copy survives or stop refusing contradictory labels.
"""

from __future__ import annotations

import pytest

from cinewhy.text.dedupe import ConflictingLabelsError, unique_review_indices

pytestmark = pytest.mark.methodology


def test_keeps_the_first_occurrence_and_preserves_order() -> None:
    reviews = ["a", "b", "a", "c", "b"]
    labels = [1, 0, 1, 1, 0]
    assert unique_review_indices(reviews, labels) == [0, 1, 3]


def test_input_without_duplicates_is_returned_whole() -> None:
    assert unique_review_indices(["x", "y", "z"], [0, 1, 0]) == [0, 1, 2]


def test_empty_input_gives_empty_output() -> None:
    assert unique_review_indices([], []) == []


def test_matching_is_exact_not_fuzzy() -> None:
    """Case and whitespace differences are different reviews.

    The audit measured 418 *exact* duplicates. Normalising first would silently widen the
    definition, so a stray trailing space must keep a review distinct.
    """
    reviews = ["Good film", "good film", "Good film "]
    assert unique_review_indices(reviews, [1, 1, 1]) == [0, 1, 2]


def test_same_text_with_conflicting_labels_is_refused() -> None:
    """Silently keeping one label would pick a winner nobody chose."""
    with pytest.raises(ConflictingLabelsError):
        unique_review_indices(["same", "other", "same"], [1, 1, 0])


def test_conflict_message_names_indices_but_not_the_review_text() -> None:
    body = "a very long private review body " * 20
    with pytest.raises(ConflictingLabelsError) as info:
        unique_review_indices([body, body], [1, 0])
    message = str(info.value)
    assert "0" in message and "1" in message
    assert body not in message


def test_length_mismatch_is_refused() -> None:
    with pytest.raises(ValueError, match="same length"):
        unique_review_indices(["a", "b"], [1])
