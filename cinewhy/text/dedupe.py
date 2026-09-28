"""Exact-duplicate removal for the review corpus, run BEFORE any split.

The raw IMDB file holds 418 exact duplicate review texts, none with conflicting labels
(measured 2026-08-26, re-confirmed 2026-09-29). Under a random split a copy can land on
both sides, so the model is scored on text it was trained on. In the notebook's own
10,000-row sample, 5 of the 2,000 test rows had a twin in train (HANDOVER.md H-2): a
small effect on that sample, but a permanent hazard for any corpus that is larger or
split differently, and a double-counted review distorts aspect statistics downstream.

This helper returns row *positions* rather than a filtered frame. That keeps it free of
pandas (the CI environment installs neither pandas nor sklearn) and lets a caller
subset any number of parallel arrays with one index list.

Matching is deliberately exact. The audit's number is a count of exact duplicates;
normalising first would quietly change what the helper claims to remove.
"""

from __future__ import annotations

from collections.abc import Sequence


class ConflictingLabelsError(ValueError):
    """The same review text was given more than one label.

    Raised instead of picking one, because either choice would be a labelling decision
    nobody made. The message carries row positions only: reviews run to ~14,000
    characters and are not something to paste into a log line.
    """


def unique_review_indices(reviews: Sequence[str], labels: Sequence[int]) -> list[int]:
    """Return the positions of the first occurrence of every distinct review text.

    Args:
        reviews: Raw review texts, one per row.
        labels: The label of each row, aligned with `reviews`.

    Returns:
        Ascending row positions to keep. Later copies of a text are dropped, so the
        order of the surviving rows is the order they first appeared in.

    Raises:
        ValueError: If `reviews` and `labels` differ in length.
        ConflictingLabelsError: If two rows share a text but disagree on the label.
    """
    if len(reviews) != len(labels):
        raise ValueError(
            f"reviews and labels must have the same length, got {len(reviews)} and {len(labels)}"
        )

    first_seen: dict[str, int] = {}
    keep: list[int] = []
    for position, (text, label) in enumerate(zip(reviews, labels, strict=True)):
        original = first_seen.get(text)
        if original is None:
            first_seen[text] = position
            keep.append(position)
        elif labels[original] != label:
            raise ConflictingLabelsError(
                f"rows {original} and {position} have identical text but labels "
                f"{labels[original]!r} and {label!r}"
            )
    return keep
