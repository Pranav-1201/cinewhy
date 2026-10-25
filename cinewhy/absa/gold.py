"""Measure the aspect detector and the clause-level polarity against hand-labelled clauses.

The review-level accuracy of the polarity model says little about clauses, and the aspect
lexicon had never been measured at all (extract.py header). This module scores both against
a labelled sample so the numbers the product shows come from an experiment.

**The labels were written by the assistant (Claude Sonnet 5.5), not by an independent human**,
and each row says so (`labelled_by`). Treat the figures as a careful audit by a single
labeller: good enough to catch a broken lexicon or a sign-flipped model, not a substitute
for inter-annotator agreement. A reader who disagrees with a row can read it and say so.

Two quantities are reported, with Wilson 95% intervals because the samples are small:

* **detector precision** — of clauses the lexicon flagged for an aspect, the share that are
  really about that aspect of the film. Recall is not measurable here: the sample was drawn
  from what the detector flagged, so it contains nothing the detector missed.
* **polarity accuracy** — on on-topic clauses whose label is positive or negative, the
  share where the sign of the model's score matches. Neutral and mixed rows are excluded.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cinewhy.absa.extract import PolarityScorer, aspect_polarity, detect_aspects
from cinewhy.schemas import Aspect

_Z95 = 1.96
# Matches the threshold evidence selection uses: a clause nearer neutral than this is never
# quoted, so accuracy at this threshold is the accuracy of what the user actually reads.
EVIDENCE_THRESHOLD = 0.3


@dataclass(frozen=True)
class GoldRow:
    """One hand-labelled clause."""

    id: int
    aspect: str
    text: str
    on_topic: bool
    polarity: int | None


@dataclass(frozen=True)
class Proportion:
    """A rate with its sample size and Wilson 95% interval."""

    hits: int
    n: int

    @property
    def rate(self) -> float:
        """Observed rate, or 0.0 when there are no samples."""
        return self.hits / self.n if self.n else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        """Wilson 95% interval; (0, 1) when there are no samples."""
        if not self.n:
            return (0.0, 1.0)
        p, n = self.rate, self.n
        centre = (p + _Z95**2 / (2 * n)) / (1 + _Z95**2 / n)
        half = _Z95 * math.sqrt(p * (1 - p) / n + _Z95**2 / (4 * n**2)) / (1 + _Z95**2 / n)
        return (max(0.0, centre - half), min(1.0, centre + half))

    def __str__(self) -> str:
        """Render as `0.826 [0.720, 0.898] (n=69)`."""
        lo, hi = self.interval
        return f"{self.rate:.3f} [{lo:.3f}, {hi:.3f}] (n={self.n})"


@dataclass(frozen=True)
class GoldReport:
    """Detector precision and polarity accuracy on a labelled sample."""

    detector_precision: Proportion
    polarity_accuracy: Proportion
    polarity_accuracy_confident: Proportion
    n_rows: int


def load_gold(path: Path) -> list[GoldRow]:
    """Read a gold JSONL file.

    Raises:
        ValueError: If a row is malformed (so a typo cannot silently shrink the sample).
    """
    rows: list[GoldRow] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        polarity = raw["polarity"]
        if raw["on_topic"] != (polarity is not None) or polarity not in (None, -1, 0, 1):
            raise ValueError(f"{path}:{line_no}: on_topic and polarity disagree or are invalid")
        rows.append(GoldRow(raw["id"], raw["aspect"], raw["text"], raw["on_topic"], polarity))
    return rows


@dataclass(frozen=True)
class RandomRow:
    """One clause from a uniform random sample, with every aspect it genuinely discusses."""

    id: int
    text: str
    aspects: dict[Aspect, int]


@dataclass(frozen=True)
class RandomReport:
    """Recall, precision and polarity from a uniform random sample of clauses.

    Unlike `GoldReport`, the sample was drawn from ALL clauses, flagged or not, so recall is
    measurable: a real aspect mention the lexicon misses appears here as a miss.
    """

    detector_recall: Proportion
    detector_precision: Proportion
    polarity_accuracy: Proportion
    n_clauses: int


def load_random_gold(path: Path) -> list[RandomRow]:
    """Read a uniform-random-sample gold JSONL file."""
    rows: list[RandomRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            aspects = {Aspect(k): int(v) for k, v in raw["aspects"].items()}
            rows.append(RandomRow(raw["id"], raw["text"], aspects))
    return rows


def evaluate_random(rows: Sequence[RandomRow], scorer: PolarityScorer) -> RandomReport:
    """Score the detector's recall and precision and the polarity on a random sample.

    Args:
        rows: Labelled random clauses.
        scorer: Polarity scorer under test.

    Returns:
        Recall over real mentions, precision over flagged mentions, and sign accuracy over
        real mentions that were flagged and carry a clear polarity.
    """
    real = flagged_total = real_flagged = 0
    signed: list[tuple[RandomRow, Aspect]] = []
    for row in rows:
        found = detect_aspects(row.text)
        truth = set(row.aspects)
        real += len(truth)
        flagged_total += len(found)
        real_flagged += len(truth & found)
        signed.extend((row, a) for a in truth & found if row.aspects[a] in (-1, 1))
    scores = scorer.score_many([row.text for row, _ in signed])
    correct = [
        (aspect_polarity(a, row.text, s) > 0) == (row.aspects[a] == 1)
        for (row, a), s in zip(signed, scores, strict=True)
    ]
    return RandomReport(
        detector_recall=Proportion(real_flagged, real),
        detector_precision=Proportion(real_flagged, flagged_total),
        polarity_accuracy=Proportion(sum(correct), len(correct)),
        n_clauses=len(rows),
    )


def evaluate_gold(rows: Sequence[GoldRow], scorer: PolarityScorer) -> GoldReport:
    """Score the detector and the polarity model against labelled clauses.

    Args:
        rows: Labelled clauses.
        scorer: Polarity scorer under test.

    Returns:
        The report. `polarity_accuracy_confident` restricts to clauses the model scores
        at or beyond the evidence threshold, i.e. the ones the UI would quote.
    """
    on_topic = sum(r.on_topic for r in rows)
    signed = [r for r in rows if r.polarity in (-1, 1)]
    # Same path as build_profile: the model's score, then the per-aspect rule.
    scores = [
        aspect_polarity(Aspect(r.aspect), r.text, s)
        for r, s in zip(signed, scorer.score_many([r.text for r in signed]), strict=True)
    ]
    correct = [(s > 0) == (r.polarity == 1) for s, r in zip(scores, signed, strict=True)]
    confident = [ok for ok, s in zip(correct, scores, strict=True) if abs(s) >= EVIDENCE_THRESHOLD]
    return GoldReport(
        detector_precision=Proportion(on_topic, len(rows)),
        polarity_accuracy=Proportion(sum(correct), len(correct)),
        polarity_accuracy_confident=Proportion(sum(confident), len(confident)),
        n_rows=len(rows),
    )
