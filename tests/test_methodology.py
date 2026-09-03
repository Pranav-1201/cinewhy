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

import pytest

from cinewhy.text import NEGATION_TOKENS, build_stoplist, normalise

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
# Measured: fitting on all 10,000 rows before the split inflated BernoulliNB accuracy
# from a true 0.8185 to a reported 0.8350 (+0.0165). See DECISIONS.md D-004, FLOW.md F-1.


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
# Measured 5-fold CV on train: MultinomialNB TF-IDF 0.8383 ± 0.0091, MultinomialNB BoW
# 0.8293 ± 0.0126, BernoulliNB BoW 0.8285 ± 0.0117. The notebook's declared winner
# (BernoulliNB, chosen on a 0.0020 test-set margin) finishes last.


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
# labels). Under a random split a duplicate can land on both sides. HANDOVER.md H-2 asks
# whether they actually do; this guard makes the answer permanently moot.


@pytest.mark.xfail(strict=True, reason="Phase C: split helper not implemented")
def test_no_review_text_appears_in_both_splits() -> None:
    """Train and test review texts must be disjoint."""
    pytest.fail("implement alongside the dataset split helper")
