"""Training and evaluation harness for the polarity classifier.

Built so the methodology rules are properties of the structure, not promises in a
docstring (CONSTRAINTS.md #1-#3):

* the vectorizer is fitted on training rows only, inside every fold and again for the
  final model, so a token that occurs only in test rows can never reach it;
* model selection (`cross_validate`, `pick_winner`) is handed the whole corpus but only
  ever *indexes* training positions; the test positions are read in exactly one place,
  `final_evaluation`, after selection is finished;
* a winner is named only when its lead is at least the larger of the two fold standard
  deviations; otherwise `pick_winner` says nobody won;
* exact-duplicate reviews are removed before the split (FEATURE-001).

Positions, not frames, cross every boundary: `texts` and `labels` are plain sequences
indexed by row, so tests can substitute a sequence that records which rows were read.

Run it: `python -m cinewhy.absa.train --sample 10000`
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.naive_bayes import BernoulliNB, MultinomialNB

from cinewhy.text import normalise, unique_review_indices

# Same vocabulary size as the original notebook, so results stay comparable to D-009.
_MAX_FEATURES = 1000


@dataclass(frozen=True)
class Candidate:
    """One vectorizer-plus-classifier combination under comparison."""

    name: str
    make_vectorizer: Callable[[], Any]
    make_model: Callable[[], Any]


DEFAULT_CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "MultinomialNB TF-IDF", lambda: TfidfVectorizer(max_features=_MAX_FEATURES), MultinomialNB
    ),
    Candidate(
        "MultinomialNB BoW", lambda: CountVectorizer(max_features=_MAX_FEATURES), MultinomialNB
    ),
    Candidate("BernoulliNB BoW", lambda: CountVectorizer(max_features=_MAX_FEATURES), BernoulliNB),
)


@dataclass(frozen=True)
class FoldSummary:
    """Accuracy across cross-validation folds."""

    mean: float
    std: float
    folds: tuple[float, ...]


@dataclass(frozen=True)
class ExperimentReport:
    """Everything a reader needs to judge a result, including its spread."""

    n_reviews: int
    n_unique: int
    n_train: int
    n_test: int
    cv: Mapping[str, FoldSummary]
    winner: str | None
    test_accuracy: Mapping[str, float]


def split_indices(
    reviews: Sequence[str],
    labels: Sequence[int],
    *,
    test_fraction: float = 0.2,
    seed: int = 42,
) -> tuple[list[int], list[int]]:
    """Deduplicate, then split row positions into train and test.

    Args:
        reviews: Raw review texts.
        labels: Label per review.
        test_fraction: Share of the unique rows held out.
        seed: Shuffle seed, so the split is reproducible.

    Returns:
        Ascending (train, test) positions. The split is random, not stratified.

    Raises:
        ValueError: If `test_fraction` is not strictly between 0 and 1.
    """
    if not 0.0 < test_fraction < 1.0:
        raise ValueError(f"test_fraction must be strictly between 0 and 1, got {test_fraction}")
    order = unique_review_indices(reviews, labels)
    random.Random(seed).shuffle(order)
    cut = round(len(order) * (1.0 - test_fraction))
    return sorted(order[:cut]), sorted(order[cut:])


def _gather[T](items: Sequence[T], positions: Sequence[int]) -> list[T]:
    """Read `items` at `positions`, and nowhere else."""
    return [items[i] for i in positions]


def _accuracy(predicted: Sequence[int], actual: Sequence[int]) -> float:
    return sum(p == a for p, a in zip(predicted, actual, strict=True)) / len(actual)


def fit_vectorizer_on_train(candidate: Candidate, train_texts: Sequence[str]) -> Any:
    """Fit a fresh vectorizer on training text only and return it.

    Args:
        candidate: Which vectorizer to build.
        train_texts: Training rows. Nothing else may be passed here.

    Returns:
        The fitted vectorizer.
    """
    vectorizer = candidate.make_vectorizer()
    vectorizer.fit(list(train_texts))
    return vectorizer


def _fit_predict(
    candidate: Candidate,
    train_texts: Sequence[str],
    train_labels: Sequence[int],
    eval_texts: Sequence[str],
) -> list[int]:
    vectorizer = fit_vectorizer_on_train(candidate, train_texts)
    model = candidate.make_model().fit(vectorizer.transform(list(train_texts)), list(train_labels))
    return [int(p) for p in model.predict(vectorizer.transform(list(eval_texts)))]


def fold_scores(
    candidate: Candidate,
    texts: Sequence[str],
    labels: Sequence[int],
    train_idx: Sequence[int],
    *,
    folds: int = 5,
    seed: int = 42,
) -> list[float]:
    """Cross-validate one candidate using only the given training positions.

    Args:
        candidate: The combination to score.
        texts: Normalised text for the whole corpus, indexed by row.
        labels: Label per row.
        train_idx: The only positions that may be read.
        folds: Number of folds.
        seed: Fold-assignment seed.

    Returns:
        One accuracy per fold, each measured on rows the fold's vectorizer never saw.

    Raises:
        ValueError: If there are fewer than 2 folds or fewer rows than folds.
    """
    if folds < 2 or len(train_idx) < folds:
        raise ValueError(f"need 2 <= folds <= rows, got folds={folds}, rows={len(train_idx)}")
    order = list(train_idx)
    random.Random(seed).shuffle(order)
    parts = [order[i::folds] for i in range(folds)]
    scores: list[float] = []
    for held in range(folds):
        fit = [i for j, part in enumerate(parts) if j != held for i in part]
        predicted = _fit_predict(
            candidate,
            _gather(texts, fit),
            _gather(labels, fit),
            _gather(texts, parts[held]),
        )
        scores.append(_accuracy(predicted, _gather(labels, parts[held])))
    return scores


def summarise(scores: Sequence[float]) -> FoldSummary:
    """Mean and sample standard deviation of per-fold scores.

    Args:
        scores: At least two per-fold accuracies.

    Returns:
        The summary, with the raw folds kept so the spread is auditable.
    """
    return FoldSummary(
        mean=statistics.fmean(scores), std=statistics.stdev(scores), folds=tuple(scores)
    )


def cross_validate(
    candidates: Sequence[Candidate],
    texts: Sequence[str],
    labels: Sequence[int],
    train_idx: Sequence[int],
    *,
    folds: int = 5,
    seed: int = 42,
) -> dict[str, FoldSummary]:
    """Score every candidate by cross-validation on the training positions only."""
    return {
        c.name: summarise(fold_scores(c, texts, labels, train_idx, folds=folds, seed=seed))
        for c in candidates
    }


def pick_winner(results: Mapping[str, FoldSummary]) -> str | None:
    """Name the best candidate, or None when the data cannot separate the leaders.

    The lead of first over second must be at least the larger of their two fold standard
    deviations. Anything smaller is noise and is reported as "no significant difference"
    instead of a name (CONSTRAINTS.md #3).

    Args:
        results: Cross-validation summary per candidate.

    Returns:
        The winning name, or None.

    Raises:
        ValueError: If `results` is empty.
    """
    if not results:
        raise ValueError("no results to choose from")
    ranked = sorted(results.items(), key=lambda item: item[1].mean, reverse=True)
    if len(ranked) == 1:
        return ranked[0][0]
    (first_name, first), (_, second) = ranked[0], ranked[1]
    margin = first.mean - second.mean
    return first_name if margin >= max(first.std, second.std) else None


def final_evaluation(
    candidate: Candidate,
    texts: Sequence[str],
    labels: Sequence[int],
    train_idx: Sequence[int],
    test_idx: Sequence[int],
) -> float:
    """Fit on all training rows and score once on the held-out rows.

    This is the only function that reads test positions. Call it after selection is done,
    and never use its result to choose between candidates.
    """
    predicted = _fit_predict(
        candidate, _gather(texts, train_idx), _gather(labels, train_idx), _gather(texts, test_idx)
    )
    return _accuracy(predicted, _gather(labels, test_idx))


def run_experiment(
    reviews: Sequence[str],
    labels: Sequence[int],
    *,
    candidates: Sequence[Candidate] = DEFAULT_CANDIDATES,
    folds: int = 5,
    seed: int = 42,
    test_fraction: float = 0.2,
) -> ExperimentReport:
    """Deduplicate, split, select by cross-validation, then evaluate on test once.

    Args:
        reviews: Raw review texts.
        labels: Label per review.
        candidates: Combinations to compare.
        folds: Cross-validation folds.
        seed: Seed for the split and the folds.
        test_fraction: Share held out.

    Returns:
        The report. `winner` comes from cross-validation alone; `test_accuracy` is
        reported for every candidate but was not used to choose.
    """
    train_idx, test_idx = split_indices(reviews, labels, test_fraction=test_fraction, seed=seed)
    texts = [normalise(review) for review in reviews]
    cv = cross_validate(candidates, texts, labels, train_idx, folds=folds, seed=seed)
    winner = pick_winner(cv)
    test = {c.name: final_evaluation(c, texts, labels, train_idx, test_idx) for c in candidates}
    return ExperimentReport(
        n_reviews=len(reviews),
        n_unique=len(train_idx) + len(test_idx),
        n_train=len(train_idx),
        n_test=len(test_idx),
        cv=cv,
        winner=winner,
        test_accuracy=test,
    )


def format_report(report: ExperimentReport) -> str:
    """Render a report as text, with every mean shown beside its spread."""
    lines = [
        f"rows {report.n_reviews}, unique {report.n_unique}, "
        f"train {report.n_train}, test {report.n_test}",
        "",
        "5-fold CV on train (mean +/- sample std), then the one test evaluation:",
    ]
    for name, summary in report.cv.items():
        lines.append(
            f"  {name:22} CV {summary.mean:.4f} +/- {summary.std:.4f}"
            f"   test {report.test_accuracy[name]:.4f}"
        )
    lines.append("")
    lines.append(
        f"winner by CV: {report.winner}"
        if report.winner
        else "winner by CV: none - the lead is inside the fold spread"
    )
    return "\n".join(lines)


def _load_csv(path: Path, sample: int, seed: int) -> tuple[list[str], list[int]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if sample:
        rows = random.Random(seed).sample(rows, sample)
    return [r["review"] for r in rows], [1 if r["sentiment"] == "positive" else 0 for r in rows]


def main() -> None:
    """Command line entry point: run the experiment on the IMDB csv and print the report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--csv", type=Path, default=Path("Data/IMDB Dataset.csv"))
    parser.add_argument("--sample", type=int, default=0, help="rows to sample; 0 means all")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    reviews, labels = _load_csv(args.csv, args.sample, args.seed)
    print(format_report(run_experiment(reviews, labels, seed=args.seed)))


if __name__ == "__main__":
    main()
