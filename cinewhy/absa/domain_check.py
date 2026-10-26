"""Does the polarity model still work on the newer review dumps?

Part of FEATURE-004.

The polarity model was trained on 2011-era IMDb text (aclImdb). Rotten Tomatoes and later IMDb
reviews are written differently, so its published accuracy cannot be assumed for them. Both
dumps carry a per-review star rating, which supplies labels with the convention aclImdb used:
clearly positive against clearly negative, the middle of the scale left out.

Nothing here trains or tunes anything. It scores a fixed, deterministic sample and reports the
accuracy with an interval, per source, on a class-balanced set.

Run: `python -m cinewhy.absa.domain_check` (needs the RT and ebD dumps and a trained model).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import zipfile
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from cinewhy.absa.extract import PolarityScorer
from cinewhy.absa.polarity import PolarityModel
from cinewhy.data.linking import parse_ebd_movie
from cinewhy.data.reviews import (
    RT_REVIEWS_MEMBER,
    clean_ebd_text,
    clean_rt_quote,
    iter_ebd_records,
)

# aclImdb's convention on a 10-point scale: 7+ positive, 4- negative, 5-6 left out. RT stars run
# 0.5-5, the same proportions: 3.5+ positive, 2.0- negative.
_EBD_POSITIVE_FROM: Final[int] = 7
_EBD_NEGATIVE_TO: Final[int] = 4
_RT_POSITIVE_FROM: Final[float] = 3.5
_RT_NEGATIVE_TO: Final[float] = 2.0


@dataclass(frozen=True)
class LabelledReview:
    """One review with the label its own star rating implies (1 positive, 0 negative)."""

    source: str
    text: str
    label: int


def label_from_ebd_rating(rating: object) -> int | None:
    """Label for an ebD rating string ("1" to "10"); None for the middle, a gap or junk."""
    try:
        value = int(str(rating))
    except ValueError:
        return None
    if not 1 <= value <= 10:
        return None
    if value >= _EBD_POSITIVE_FROM:
        return 1
    return 0 if value <= _EBD_NEGATIVE_TO else None


def label_from_rt_stars(stars: float) -> int | None:
    """Label for an RT star rating (0.5 to 5); None for the middle."""
    if stars >= _RT_POSITIVE_FROM:
        return 1
    return 0 if stars <= _RT_NEGATIVE_TO else None


def _in_sample(key: str, modulus: int) -> bool:
    """A stable pseudo-random subset: the same review is in or out on every run."""
    return zlib.crc32(key.encode("utf-8")) % modulus == 0


def sample_ebd(archive: Path, modulus: int = 1) -> Iterator[LabelledReview]:
    """Labelled ebD film reviews, one in `modulus`, that the product could also quote.

    Spoiler-flagged reviews and TV series are left out for the same reason the catalogue leaves
    them out, so the sample resembles the text the model meets in the product.

    Args:
        archive: Path to `imdb_ebd.zip`.
        modulus: Keep roughly one review in this many (1 keeps all).
    """
    for record in iter_ebd_records(archive):
        if record.get("spoiler_tag") or parse_ebd_movie(str(record.get("movie") or "")) is None:
            continue
        label = label_from_ebd_rating(record.get("rating"))
        if label is None or not _in_sample(str(record.get("review_id")), modulus):
            continue
        if text := clean_ebd_text(str(record.get("review_detail") or "")):
            yield LabelledReview("ebd", text, label)


def sample_rt(archive: Path, modulus: int = 1) -> Iterator[LabelledReview]:
    """Labelled RT user reviews, one in `modulus`, with the verdict prefix removed.

    RT writes `:fresh:` or `:rotten:` before each quote; that prefix is a function of the rating,
    so it is stripped before scoring (leaving it in would leak the label).

    Args:
        archive: Path to `rt_mother.zip`.
        modulus: Keep roughly one review in this many (1 keeps all).
    """
    csv.field_size_limit(10**9)
    with zipfile.ZipFile(archive) as z, z.open(RT_REVIEWS_MEMBER) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
        header = next(reader)
        movie_i, user_i, date_i = (
            header.index("movieId"),
            header.index("userId"),
            header.index("creationDate"),
        )
        rating_i, quote_i = header.index("rating"), header.index("quote")
        spoil_i, prof_i = header.index("hasSpoilers"), header.index("hasProfanity")
        for row in reader:
            if len(row) <= max(user_i, rating_i, quote_i, spoil_i, prof_i):
                continue
            if row[spoil_i] == "True" or row[prof_i] == "True":
                continue
            if not _in_sample(f"{row[movie_i]}/{row[user_i]}-{row[date_i]}", modulus):
                continue
            try:
                label = label_from_rt_stars(float(row[rating_i]))
            except ValueError:
                continue
            if label is not None and (text := clean_rt_quote(row[quote_i])):
                yield LabelledReview("rt", text, label)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion; (0, 1) when there are no trials.

    Unlike the plain normal interval it stays inside [0, 1] and does not collapse to a point
    when every trial succeeds, which matters for a model that is right on a small sample.
    """
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def accuracy_report(
    scorer: PolarityScorer, reviews: Iterable[LabelledReview], per_class: int
) -> dict[str, dict[str, Any]]:
    """Accuracy per source on a class-balanced sample, with a 95% interval.

    Args:
        scorer: The polarity model under test. A score above zero counts as positive.
        reviews: Labelled reviews from any number of sources.
        per_class: Most reviews of each class to score per source.

    Returns:
        Per source: `n` (reviews scored, equal numbers of each class), `accuracy`, `ci95`,
        and the recall of each class. A source with only one class available gets `n` 0 and
        no accuracy: a one-sided sample cannot say how well the model separates the classes.
    """
    by_source: dict[str, dict[int, list[str]]] = {}
    for review in reviews:
        by_source.setdefault(review.source, {0: [], 1: []})[review.label].append(review.text)
    report: dict[str, dict[str, Any]] = {}
    for source, classes in sorted(by_source.items()):
        k = min(per_class, len(classes[0]), len(classes[1]))
        if k == 0:
            report[source] = {"n": 0, "accuracy": None, "ci95": None}
            continue
        positives = scorer.score_many(classes[1][:k])
        negatives = scorer.score_many(classes[0][:k])
        right_positive = sum(1 for s in positives if s > 0)
        right_negative = sum(1 for s in negatives if s <= 0)
        right = right_positive + right_negative
        low, high = wilson_interval(right, 2 * k)
        report[source] = {
            "n": 2 * k,
            "accuracy": right / (2 * k),
            "ci95": [low, high],
            "positive_recall": right_positive / k,
            "negative_recall": right_negative / k,
        }
    return report


def main() -> None:
    """Score a sample of each dump and write `polarity_domain.json` next to the model."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--model", type=Path, default=Path("artifacts/polarity.joblib"))
    parser.add_argument("--rt", type=Path, default=Path("Data/raw/rt_mother/rt_mother.zip"))
    parser.add_argument("--ebd", type=Path, default=Path("Data/raw/imdb_ebd/imdb_ebd.zip"))
    parser.add_argument("--modulus", type=int, default=400, help="keep about 1 review in N")
    parser.add_argument("--per-class", type=int, default=3000)
    parser.add_argument("--out", type=Path, default=Path("artifacts/polarity_domain.json"))
    args = parser.parse_args()
    model = PolarityModel.load(args.model)
    reviews = [*sample_ebd(args.ebd, args.modulus), *sample_rt(args.rt, args.modulus)]
    report = accuracy_report(model, reviews, args.per_class)
    document = {
        "note": "polarity model trained on aclImdb only; labels from each source's own star "
        "rating (aclImdb convention, middle left out); class-balanced; deterministic sample",
        "modulus": args.modulus,
        "per_class_cap": args.per_class,
        "by_source": report,
    }
    args.out.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
