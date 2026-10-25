"""Polarity model: how positive or negative is a piece of review text?

Trained on the 25,000 labelled reviews in the aclImdb *train* split and evaluated once on
its 25,000-review *test* split, which shares no films with train (that is how Maas et al.
built the corpus). Model comparison goes through `train.run_experiment`, so the three
methodology rules in CONSTRAINTS.md #1-#3 are structural here, not promised.

Known limitation, stated where it can be seen: the labels are per *review*, but the product
scores *clauses*. A review-level classifier applied to a short clause is out of its training
distribution. The clause-level accuracy is therefore measured separately against a
hand-labelled sample (tests/data/aspect_gold.jsonl, DECISIONS.md D-012) rather than
assumed to match the review-level number.

Run it: `python -m cinewhy.absa.polarity --archive Data/raw/aclImdb_v1.tar.gz`
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from cinewhy.absa.train import Candidate, ExperimentReport, format_report, run_experiment
from cinewhy.data.sources import iter_reviews
from cinewhy.text import normalise, unique_review_indices

# Unigrams and bigrams: "not good" and "not bad" are different features, which is the whole
# point of keeping negation tokens (CONSTRAINTS.md #4).
_NGRAMS = (1, 2)
_MIN_DF = 3
_MAX_FEATURES = 200_000


def _vectorizer() -> Any:
    return TfidfVectorizer(ngram_range=_NGRAMS, min_df=_MIN_DF, max_features=_MAX_FEATURES)


def _logreg(c: float) -> Callable[[], Any]:
    """A factory for a fresh LogisticRegression at strength `c` (a closure per candidate)."""
    return lambda: LogisticRegression(C=c, max_iter=2000)


CANDIDATES: tuple[Candidate, ...] = tuple(
    Candidate(f"LogReg C={c:g}", _vectorizer, _logreg(c)) for c in (1.0, 10.0)
)

# A text with fewer informative tokens than this carries no polarity evidence.
_MIN_TOKENS = 2


@dataclass(frozen=True)
class PolarityModel:
    """A fitted vectorizer and classifier, with the one scoring entry point."""

    vectorizer: Any
    classifier: Any

    def score_many(self, texts: Sequence[str]) -> list[float]:
        """Score texts from -1 (negative) to +1 (positive).

        Args:
            texts: Raw clauses, sentences or reviews. Normalised here with the same
                `normalise` the model was trained through (no train/serve skew).

        Returns:
            One polarity per text: `2 * P(positive) - 1`. A text left with fewer than
            two informative tokens after normalisation scores 0.0 (no evidence), not a
            confident guess from an empty vector.
        """
        cleaned = [normalise(t) for t in texts]
        usable = [i for i, t in enumerate(cleaned) if len(t.split()) >= _MIN_TOKENS]
        scores = [0.0] * len(cleaned)
        if usable:
            proba = self.classifier.predict_proba(
                self.vectorizer.transform([cleaned[i] for i in usable])
            )[:, 1]
            for i, p in zip(usable, proba, strict=True):
                scores[i] = float(2.0 * p - 1.0)
        return scores

    def save(self, path: Path) -> None:
        """Write the model with joblib. Its hash is recorded by `artifacts.build`."""
        joblib.dump({"vectorizer": self.vectorizer, "classifier": self.classifier}, path)

    @classmethod
    def load(cls, path: Path) -> PolarityModel:
        """Load a model written by `save`. The caller must have verified its hash first."""
        blob = joblib.load(path)
        return cls(vectorizer=blob["vectorizer"], classifier=blob["classifier"])


@dataclass(frozen=True)
class PolarityReport:
    """Everything needed to judge the shipped polarity model."""

    experiment: ExperimentReport
    chosen: str
    chosen_reason: str
    official_test_accuracy: float
    official_test_n: int

    @property
    def official_test_ci95(self) -> float:
        """Half-width of a normal-approximation 95% interval on the test accuracy."""
        p = self.official_test_accuracy
        return 1.96 * math.sqrt(p * (1.0 - p) / self.official_test_n)


def train_polarity(
    train_texts: Sequence[str],
    train_labels: Sequence[int],
    test_texts: Sequence[str],
    test_labels: Sequence[int],
    *,
    candidates: Sequence[Candidate] = CANDIDATES,
    seed: int = 42,
) -> tuple[PolarityModel, PolarityReport]:
    """Compare candidates by cross-validation, fit the chosen one, test it once.

    Args:
        train_texts: Raw training reviews.
        train_labels: 1 positive / 0 negative.
        test_texts: Raw reviews from the official held-out split.
        test_labels: Their labels.
        candidates: Models to compare. The first is the default when CV cannot separate
            them, chosen before any result was seen.
        seed: Seed for the split and folds.

    Returns:
        The fitted model and the report. The official test split is read exactly once,
        after the choice is made, and never feeds back into it.
    """
    experiment = run_experiment(train_texts, train_labels, candidates=candidates, seed=seed)
    by_name = {c.name: c for c in candidates}
    if experiment.winner is not None:
        chosen, reason = by_name[experiment.winner], "cross-validation winner"
    else:
        chosen = candidates[0]
        reason = "no CV winner (lead inside the fold spread); pre-declared default used"

    unique = unique_review_indices(train_texts, train_labels)
    texts = [normalise(train_texts[i]) for i in unique]
    labels = [train_labels[i] for i in unique]
    vectorizer = chosen.make_vectorizer().fit(texts)
    classifier = chosen.make_model().fit(vectorizer.transform(texts), labels)
    model = PolarityModel(vectorizer, classifier)

    scores = model.score_many(list(test_texts))
    hits = sum((s > 0.0) == bool(y) for s, y in zip(scores, test_labels, strict=True))
    return model, PolarityReport(experiment, chosen.name, reason, hits / len(scores), len(scores))


def format_polarity_report(report: PolarityReport) -> str:
    """Render the report with every figure beside its spread or interval."""
    return "\n".join(
        [
            format_report(report.experiment),
            "",
            f"shipped: {report.chosen} ({report.chosen_reason})",
            f"official aclImdb test split, evaluated once: {report.official_test_accuracy:.4f} "
            f"+/- {report.official_test_ci95:.4f} (95% CI, n={report.official_test_n})",
        ]
    )


def report_to_dict(report: PolarityReport) -> dict[str, Any]:
    """JSON-ready form of the report, so downstream code reads numbers rather than text."""
    experiment = report.experiment
    return {
        "n_reviews": experiment.n_reviews,
        "n_unique": experiment.n_unique,
        "n_train": experiment.n_train,
        "cv": {
            name: {"mean": s.mean, "std": s.std, "folds": list(s.folds)}
            for name, s in experiment.cv.items()
        },
        "cv_winner": experiment.winner,
        "shipped": report.chosen,
        "shipped_reason": report.chosen_reason,
        "official_test_accuracy": report.official_test_accuracy,
        "official_test_ci95": report.official_test_ci95,
        "official_test_n": report.official_test_n,
    }


def main() -> None:
    """Train on the aclImdb train split, report, and save the model."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--archive", type=Path, default=Path("Data/raw/aclImdb_v1.tar.gz"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/polarity.joblib"))
    args = parser.parse_args()

    train: tuple[list[str], list[int]] = ([], [])
    test: tuple[list[str], list[int]] = ([], [])
    for review in iter_reviews(args.archive):
        if review.label is None:
            continue
        bucket = train if review.split == "train" else test
        bucket[0].append(review.text)
        bucket[1].append(review.label)

    model, report = train_polarity(*train, *test)
    print(format_polarity_report(report))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    model.save(args.out)
    report_path = args.out.with_name("polarity_report.json")
    report_path.write_text(json.dumps(report_to_dict(report), indent=2), encoding="utf-8")
    print(f"saved {args.out} and {report_path}")


if __name__ == "__main__":
    main()
