"""Guards against the three defects found in the 2026-08-26 audit.

Each test here corresponds to a measured defect. They are marked `xfail(strict=True)`
because the code they guard does not exist yet — CI stays green, and the moment someone
implements the function correctly the test XPASSes, which *fails* the suite and prompts
you to delete the marker. That is the intended handshake: the marker is a to-do that
removes itself.

**These are guard tests.** If your change makes one fail, the change is wrong — revert
it. Never loosen an assertion to get to green (CONSTRAINTS.md #11).

Before deleting an xfail marker, watch the test FAIL against the pre-fix code first. A
guard test that was never observed failing proves nothing.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

import pytest

from cinewhy.text import NEGATION_TOKENS, build_stoplist, normalise
from cinewhy.text.dedupe import unique_review_indices

pytestmark = pytest.mark.methodology


# ── C-3 · negation must survive preprocessing ───────────────────────────
# Measured 2026-08-26: "This movie was not good at all." and "This movie was good."
# both normalised to 'movi good', produced byte-identical TF-IDF vectors, and were both
# predicted negative. See DECISIONS.md D-003.


@pytest.mark.xfail(strict=True, reason="Phase C: build_stoplist() not implemented")
def test_negation_tokens_are_never_in_the_stoplist() -> None:
    """The stoplist builder must strip every negation carrier.

    This is the root-cause guard: NLTK's English list contains "not", "no" and "nor",
    and using it unmodified is what destroyed the signal.
    """
    assert build_stoplist() & NEGATION_TOKENS == frozenset()


@pytest.mark.xfail(strict=True, reason="Phase C: normalise() not implemented")
def test_negation_survives_preprocessing(negation_pair: tuple[str, str]) -> None:
    """Two documents differing only by a negation must not normalise identically."""
    negated, plain = negation_pair
    assert normalise(negated) != normalise(plain)


@pytest.mark.xfail(strict=True, reason="Phase C: normalise() not implemented")
def test_negation_token_is_present_in_output(negation_pair: tuple[str, str]) -> None:
    """Stronger form: the negation carrier itself must reach the vectoriser."""
    negated, _ = negation_pair
    assert "not" in normalise(negated).split()


# ── C-1 · the vectoriser must never see the test split ──────────────────
# The notebook fits on all 10,000 rows before the split. The earlier claim that this cost
# 1.65 points did not reproduce (ten seeds: -0.0010 to +0.0000, spread 0.0013 to 0.0031),
# so this guard rests on correctness, not on a measured inflation. DECISIONS.md D-009.


@pytest.mark.xfail(strict=True, reason="Phase C: training pipeline not implemented")
def test_vectorizer_vocabulary_is_a_subset_of_train_tokens() -> None:
    """Every term in the fitted vocabulary must occur in the training split.

    A vocabulary term that appears only in test rows is proof the vectoriser was fit on
    data it should never have seen. This is the assertion that would have caught the
    original bug on the day it was written.

    Implementation note for whoever takes Phase C: split first, fit on train, transform
    test. Then compare `vectorizer.vocabulary_` against the token set of the train rows.
    """
    pytest.fail("implement alongside cinewhy.absa training pipeline")


@pytest.mark.xfail(strict=True, reason="Phase C: training pipeline not implemented")
def test_model_selection_never_receives_test_data() -> None:
    """Selection runs on cross-validation over train only; test is touched once.

    The original notebook chose its winner by comparing test accuracies, which makes the
    reported number an optimistic estimate rather than a generalisation estimate.
    """
    pytest.fail("implement alongside cinewhy.absa training pipeline")


# ── C-2 · a difference smaller than its spread is not a result ──────────
# Re-measured 2026-09-29, 5-fold CV on train: MultinomialNB TF-IDF 0.8345 ± 0.0063,
# MultinomialNB BoW 0.8297 ± 0.0095, BernoulliNB BoW 0.8294 ± 0.0065. The notebook's
# declared winner (BernoulliNB, chosen on a 0.0020 test-set margin) is indistinguishable
# from the rest: every gap is inside a fold std. See DECISIONS.md D-009.


@pytest.mark.xfail(strict=True, reason="Phase C: evaluation harness not implemented")
def test_declared_winner_margin_exceeds_fold_spread() -> None:
    """Refuse to declare a winner whose lead is inside the noise.

    The evaluation harness must expose mean and std per candidate, and the reporting
    helper must decline to name a winner when the margin over second place is smaller
    than one standard deviation — returning "no significant difference" instead.
    """
    pytest.fail("implement alongside the evaluation harness")


# ── Data hygiene: the 418 duplicates ────────────────────────────────────
# Measured: the raw IMDB file holds 418 exact duplicate review texts (0 with conflicting
# labels). Under a random split a duplicate can land on both sides. H-2 measured it on
# the notebook's own split: 5 of 2,000 test rows had a twin in train. This guard makes
# the question permanently moot for anything that goes through `unique_review_indices`.


def _split_is_disjoint(reviews: Sequence[str], rows: Sequence[int], seed: int) -> bool:
    """Randomly split `rows` 80/20; True when no review text lands on both sides."""
    order = list(rows)
    random.Random(seed).shuffle(order)
    cut = int(len(order) * 0.8)
    train = {reviews[i] for i in order[:cut]}
    test = {reviews[i] for i in order[cut:]}
    return train.isdisjoint(test)


def test_no_review_text_appears_in_both_splits() -> None:
    """Train and test review texts must be disjoint once duplicates are removed."""
    # 300 distinct reviews; every fifth one is repeated twice more at scattered rows,
    # mirroring the corpus (824 rows belong to 418 duplicated texts) at a higher rate so
    # a handful of seeds is enough to exercise the hazard.
    distinct = [f"review number {n}" for n in range(300)]
    reviews = list(distinct)
    for n in range(0, 300, 5):
        reviews.insert((n * 7) % len(reviews), distinct[n])
        reviews.insert((n * 13 + 3) % len(reviews), distinct[n])
    labels = [int(text.rsplit(" ", 1)[1]) % 2 for text in reviews]
    everything = range(len(reviews))
    kept = unique_review_indices(reviews, labels)
    seeds = range(25)

    # Control: without dedupe the same splits DO straddle. If this ever stops holding the
    # fixture no longer contains the hazard and the assertion below proves nothing.
    assert any(not _split_is_disjoint(reviews, everything, seed) for seed in seeds)

    for seed in seeds:
        assert _split_is_disjoint(reviews, kept, seed), f"seed {seed} straddles the split"
