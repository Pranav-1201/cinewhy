"""Behaviour of the training and evaluation harness in `cinewhy.absa.train`.

Uses a small synthetic corpus with a known signal so every expectation can be derived by
hand: positive reviews contain great/superb/loved, negative ones awful/boring/hated, and
each carries a unique tag so no two texts are equal unless a test makes them so.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any, overload

import pytest
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB

from cinewhy.absa.train import (
    DEFAULT_CANDIDATES,
    Candidate,
    ExperimentReport,
    FoldSummary,
    cross_validate,
    final_evaluation,
    fold_scores,
    format_report,
    pick_winner,
    run_experiment,
    split_indices,
    summarise,
)
from cinewhy.text import normalise

pytestmark = pytest.mark.methodology


def make_corpus(per_class: int = 60) -> tuple[list[str], list[int]]:
    """Return (reviews, labels), shuffled, with two exact duplicates appended."""
    pos = [f"great superb loved film number{i} scene{i % 7}" for i in range(per_class)]
    neg = [f"awful boring hated film number{i} scene{i % 7}" for i in range(per_class)]
    pairs = [(t, 1) for t in pos] + [(t, 0) for t in neg]
    random.Random(0).shuffle(pairs)
    pairs += [(pos[0], 1), (neg[3], 0)]
    return [t for t, _ in pairs], [y for _, y in pairs]


class RecordingSequence(Sequence[Any]):
    """A read-only sequence that remembers which positions were read."""

    def __init__(self, items: Sequence[Any]) -> None:
        """Wrap `items`; `reads` starts empty."""
        self._items = list(items)
        self.reads: set[int] = set()

    def __len__(self) -> int:
        """Number of rows."""
        return len(self._items)

    @overload
    def __getitem__(self, index: int) -> Any: ...
    @overload
    def __getitem__(self, index: slice) -> Sequence[Any]: ...
    def __getitem__(self, index: int | slice) -> Any:
        """Return one row and record that it was read; slices are refused."""
        if isinstance(index, slice):
            raise TypeError("the harness must read rows one position at a time")
        self.reads.add(index)
        return self._items[index]


class RecordingVectorizer:
    """Delegates to CountVectorizer and logs every document it is asked to fit on."""

    def __init__(self, log: list[str], batches: list[list[str]] | None = None) -> None:
        """Log fitted documents into `log`, and each fit call's documents into `batches`."""
        self._log = log
        self._batches = batches
        self._inner = CountVectorizer()

    def fit(self, documents: list[str]) -> RecordingVectorizer:
        self._log.extend(documents)
        if self._batches is not None:
            self._batches.append(list(documents))
        self._inner.fit(documents)
        return self

    def transform(self, documents: list[str]) -> Any:
        return self._inner.transform(documents)


# ── split ────────────────────────────────────────────────────────────────


def test_split_is_disjoint_covers_the_unique_rows_and_drops_duplicates() -> None:
    reviews, labels = make_corpus()
    train, test = split_indices(reviews, labels)
    kept = train + test
    assert set(train).isdisjoint(test)
    assert len(kept) == len(reviews) - 2  # the two appended duplicates are dropped
    assert len(reviews) - 1 not in kept
    assert len(reviews) - 2 not in kept
    assert len({reviews[i] for i in kept}) == len(kept)


def test_split_sizes_follow_the_fraction_and_the_seed_is_deterministic() -> None:
    reviews, labels = make_corpus()
    train, test = split_indices(reviews, labels, test_fraction=0.25, seed=7)
    assert len(test) == 30  # 120 unique rows, round(120 * 0.75) = 90 train
    assert (train, test) == split_indices(reviews, labels, test_fraction=0.25, seed=7)
    assert (train, test) != split_indices(reviews, labels, test_fraction=0.25, seed=8)


@pytest.mark.parametrize("fraction", [0.0, 1.0, 1.5, -0.1])
def test_split_rejects_a_fraction_outside_the_open_unit_interval(fraction: float) -> None:
    with pytest.raises(ValueError, match="strictly between"):
        split_indices(["a", "b"], [0, 1], test_fraction=fraction)


# ── folds and summaries ──────────────────────────────────────────────────


def test_fold_scores_are_deterministic_and_the_classifier_actually_learns() -> None:
    reviews, labels = make_corpus()
    train, _ = split_indices(reviews, labels)
    candidate = DEFAULT_CANDIDATES[0]
    first = fold_scores(candidate, reviews, labels, train, folds=5, seed=1)
    assert first == fold_scores(candidate, reviews, labels, train, folds=5, seed=1)
    assert len(first) == 5
    assert all(0.0 <= s <= 1.0 for s in first)
    assert min(first) > 0.9  # the signal words are perfectly predictive


@pytest.mark.parametrize(("folds", "rows"), [(1, 10), (0, 10), (5, 3)])
def test_fold_scores_refuses_impossible_fold_counts(folds: int, rows: int) -> None:
    with pytest.raises(ValueError, match="folds"):
        fold_scores(DEFAULT_CANDIDATES[0], ["a"] * rows, [0] * rows, list(range(rows)), folds=folds)


def test_summarise_reports_mean_and_sample_std() -> None:
    summary = summarise([0.8, 0.9, 1.0])
    assert summary.mean == pytest.approx(0.9)
    assert summary.std == pytest.approx(0.1)
    assert summary.folds == (0.8, 0.9, 1.0)


# ── winner ───────────────────────────────────────────────────────────────


def _summary(mean: float, std: float) -> FoldSummary:
    return FoldSummary(mean=mean, std=std, folds=())


def test_a_clear_lead_names_a_winner() -> None:
    assert pick_winner({"a": _summary(0.90, 0.01), "b": _summary(0.80, 0.01)}) == "a"


def test_a_lead_inside_the_spread_names_nobody() -> None:
    """The real numbers from D-009: TF-IDF leads by 0.0048, inside a 0.0095 fold std."""
    results = {
        "tfidf": _summary(0.8345, 0.0063),
        "bow": _summary(0.8297, 0.0095),
        "bernoulli": _summary(0.8294, 0.0065),
    }
    assert pick_winner(results) is None


def test_a_lead_exactly_equal_to_the_larger_std_counts_as_a_win() -> None:
    assert pick_winner({"a": _summary(0.75, 0.25), "b": _summary(0.50, 0.125)}) == "a"


def test_the_larger_of_the_two_stds_sets_the_bar() -> None:
    """A tight leader does not win against a noisy runner-up."""
    assert pick_winner({"a": _summary(0.85, 0.001), "b": _summary(0.84, 0.05)}) is None


def test_a_single_candidate_wins_by_default_and_none_at_all_is_an_error() -> None:
    assert pick_winner({"only": _summary(0.7, 0.1)}) == "only"
    with pytest.raises(ValueError, match="no results"):
        pick_winner({})


# ── selection never sees test, vocabulary never sees test ────────────────


def test_cross_validation_reads_only_training_positions_and_final_evaluation_reads_test() -> None:
    reviews, labels = make_corpus()
    train, test = split_indices(reviews, labels)
    texts, ys = RecordingSequence(reviews), RecordingSequence(labels)

    cross_validate(DEFAULT_CANDIDATES, texts, ys, train, folds=3)
    assert texts.reads, "the recorder saw nothing, so this test proves nothing"
    assert texts.reads <= set(train)
    assert ys.reads <= set(train)

    final_evaluation(DEFAULT_CANDIDATES[0], texts, ys, train, test)
    assert set(test) <= texts.reads


def test_no_vectorizer_is_ever_fitted_on_a_test_row() -> None:
    reviews, labels = make_corpus()
    log: list[str] = []
    spy = Candidate("spy", lambda: RecordingVectorizer(log), MultinomialNB)
    train, test = split_indices(reviews, labels)

    run_experiment(reviews, labels, candidates=[spy], folds=3)

    assert log, "the spy vectorizer was never fitted, so this test proves nothing"
    train_docs = {normalise(reviews[i]) for i in train}
    test_docs = {normalise(reviews[i]) for i in test}
    assert set(log) <= train_docs
    assert set(log).isdisjoint(test_docs)


def test_each_fold_vectorizer_is_fitted_on_a_strict_subset_of_the_training_rows() -> None:
    """Within cross-validation the held-out fold must not shape the vocabulary either."""
    reviews, labels = make_corpus()
    train, _ = split_indices(reviews, labels)
    batches: list[list[str]] = []
    spy = Candidate("spy", lambda: RecordingVectorizer([], batches), MultinomialNB)

    fold_scores(spy, reviews, labels, train, folds=4)

    assert len(batches) == 4
    assert all(len(batch) < len(train) for batch in batches)


# ── the whole experiment ─────────────────────────────────────────────────


def test_run_experiment_reports_counts_spreads_and_one_test_score_each() -> None:
    reviews, labels = make_corpus()
    report = run_experiment(reviews, labels, folds=3)
    assert report.n_reviews == 122
    assert report.n_unique == 120
    assert report.n_train + report.n_test == 120
    names = {c.name for c in DEFAULT_CANDIDATES}
    assert set(report.cv) == names
    assert set(report.test_accuracy) == names
    assert all(0.0 <= a <= 1.0 for a in report.test_accuracy.values())
    assert all(len(s.folds) == 3 for s in report.cv.values())
    assert report.winner is None or report.winner in names


def _report(winner: str | None) -> ExperimentReport:
    return ExperimentReport(
        n_reviews=10,
        n_unique=10,
        n_train=8,
        n_test=2,
        cv={"m": _summary(0.8, 0.02)},
        winner=winner,
        test_accuracy={"m": 0.75},
    )


def test_format_report_puts_a_spread_beside_every_mean() -> None:
    text = format_report(_report("m"))
    assert "0.8000 +/- 0.0200" in text
    assert "winner by CV: m" in text


def test_format_report_says_plainly_when_nobody_won() -> None:
    assert "none - the lead is inside the fold spread" in format_report(_report(None))
