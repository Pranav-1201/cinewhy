"""Retrain the polarity model on a mix of sources, and decide in advance whether to ship it.

DECISIONS D-017. The shipped model learned from 2011-era IMDb text (aclImdb) and is right on 75%
of Rotten Tomatoes reviews against 88-89% on IMDb text. Rotten Tomatoes supplies most of the
post-2011 evidence the product quotes, so the weak spot matters.

The experiment, with its rules fixed before any number was seen:

* **Training pool.** aclImdb train, plus labelled Rotten Tomatoes and later IMDb (ebD) reviews whose
  *film* hashes to the training side. Labels come from each review's own star rating, with the
  aclImdb convention (clearly positive against clearly negative, the middle left out).
* **Film-level split.** One film in five (by hash) is held out with ALL its reviews. A film in both
  training and test lets the model learn the film's name, which flatters the test.
* **Same test text for both models.** The old model (aclImdb only) and the new one are scored on
  identical held-out samples: aclImdb's official test split, and class-balanced samples of the
  held-out Rotten Tomatoes and ebD films. Differences are paired (same items) with a bootstrap
  interval.
* **Ship rule.** Ship the new model only if its accuracy on Rotten Tomatoes beats the old one with
  the whole interval above zero AND neither aclImdb nor ebD drops by more than `MAX_DROP` (one
  point). Otherwise the shipped model stays and the result is recorded.

Choosing between the two regularisation strengths still goes through `train.run_experiment`
(cross-validation on the training pool), so CONSTRAINTS.md #1-#3 stay structural. Cross-validation
folds there are by review, so they are optimistic about film names for the new sources; that
only affects choosing C, and every claim below is made on the film-disjoint test samples.

Run: `python -m cinewhy.absa.polarity_mixed` (needs the RT and ebD dumps, aclImdb, the old model).
"""

from __future__ import annotations

import argparse
import json
import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from cinewhy.absa.domain_check import LabelledReview, sample_ebd, sample_rt, wilson_interval
from cinewhy.absa.polarity import (
    PolarityModel,
    format_polarity_report,
    report_to_dict,
    train_polarity,
)
from cinewhy.data.sources import iter_reviews

# One film in this many, chosen by hash, is held out with all of its reviews.
TEST_FILM_MODULUS: Final[int] = 5
# The new model may lose at most this much accuracy on a source it was not meant to improve.
MAX_DROP: Final[float] = 0.01
# Per class per source: the training pool matches aclImdb's 12,500 per class at twice the size.
TRAIN_PER_CLASS: Final[int] = 25_000
TEST_PER_CLASS: Final[int] = 3_000
_BOOTSTRAPS: Final[int] = 2000


@dataclass(frozen=True)
class PairedDiff:
    """New minus old accuracy over the same items, with a 95% bootstrap interval."""

    mean: float
    lo: float
    hi: float


@dataclass(frozen=True)
class Verdict:
    """Whether the new model clears the pre-declared ship rule, and why."""

    ship: bool
    reasons: tuple[str, ...]


def film_side(source: str, film: str, text: str = "") -> str:
    """'test' for one film in `TEST_FILM_MODULUS` (by hash), else 'train'.

    A review with no film name falls back to its own text, so it still lands on a stable side.
    """
    key = f"{source}/{film or text}"
    return "test" if zlib.crc32(key.encode("utf-8")) % TEST_FILM_MODULUS == 0 else "train"


def split_by_film(reviews: Iterable[LabelledReview]) -> dict[str, list[LabelledReview]]:
    """Partition reviews so every film's reviews are on one side. Keys: 'train' and 'test'."""
    sides: dict[str, list[LabelledReview]] = {"train": [], "test": []}
    for review in reviews:
        sides[film_side(review.source, review.film, review.text)].append(review)
    return sides


def balanced_cap(reviews: Sequence[LabelledReview], per_class: int) -> list[LabelledReview]:
    """Up to `per_class` of each class, equal in both, chosen by a stable hash of the text.

    The same input always gives the same sample, whatever order it arrives in.
    """
    by_label: dict[int, list[LabelledReview]] = {0: [], 1: []}
    for review in reviews:
        by_label[review.label].append(review)
    k = min(per_class, len(by_label[0]), len(by_label[1]))
    out: list[LabelledReview] = []
    for label in (0, 1):
        ranked = sorted(by_label[label], key=lambda r: (zlib.crc32(r.text.encode("utf-8")), r.text))
        out.extend(ranked[:k])
    return out


def correct_flags(
    model: PolarityModel, reviews: Sequence[LabelledReview]
) -> npt.NDArray[np.float64]:
    """1.0 where the model is right (a score above zero counts as positive), else 0.0."""
    scores = model.score_many([r.text for r in reviews])
    return np.array(
        [float((s > 0.0) == bool(r.label)) for s, r in zip(scores, reviews, strict=True)]
    )


def paired_difference(
    old: npt.NDArray[np.float64], new: npt.NDArray[np.float64], seed: int = 7
) -> PairedDiff:
    """Bootstrap the mean of `new - old` over items scored by both models."""
    diffs = new - old
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(diffs), size=(_BOOTSTRAPS, len(diffs)))
    means = diffs[picks].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return PairedDiff(float(diffs.mean()), float(lo), float(hi))


def decide(diffs: dict[str, PairedDiff]) -> Verdict:
    """Apply the pre-declared ship rule to the per-source paired differences.

    Args:
        diffs: Paired difference per source; needs 'rt', 'acl' and 'ebd'.

    Returns:
        `ship` is True only if Rotten Tomatoes improves with the whole interval above zero and
        neither other source loses more than `MAX_DROP` on average. `reasons` says which parts held.
    """
    rt = diffs["rt"]
    gain = rt.lo > 0.0
    verb = "improves" if gain else "does not clearly improve"
    reasons = [f"rt {verb}: {rt.mean * 100:+.2f} points [{rt.lo * 100:+.2f}, {rt.hi * 100:+.2f}]"]
    keeps = True
    for source in ("acl", "ebd"):
        ok = diffs[source].mean >= -MAX_DROP
        keeps = keeps and ok
        word = "holds" if ok else "drops too much"
        reasons.append(f"{source} {word}: {diffs[source].mean * 100:+.2f} points")
    return Verdict(gain and keeps, tuple(reasons))


def compare(
    old: PolarityModel,
    new: PolarityModel,
    test_sets: Mapping[str, Sequence[LabelledReview]],
) -> dict[str, Any]:
    """Score both models on identical test sets: accuracy with a Wilson interval, paired diff."""
    report: dict[str, Any] = {}
    diffs: dict[str, PairedDiff] = {}
    for source, reviews in test_sets.items():
        old_right, new_right = correct_flags(old, reviews), correct_flags(new, reviews)
        n = len(reviews)
        entry: dict[str, Any] = {"n": n}
        for name, right in (("old", old_right), ("new", new_right)):
            hits = int(right.sum())
            low, high = wilson_interval(hits, n)
            entry[name] = {"accuracy": hits / n, "ci95": [low, high]}
        diffs[source] = paired_difference(old_right, new_right)
        entry["diff"] = {"mean": diffs[source].mean, "lo": diffs[source].lo, "hi": diffs[source].hi}
        report[source] = entry
    verdict = decide(diffs)
    report["ship"] = verdict.ship
    report["reasons"] = list(verdict.reasons)
    return report


def write_cache(path: Path, modulus: dict[str, int], reviews: Sequence[LabelledReview]) -> None:
    """Keep the sampled reviews: scanning both dumps takes about half an hour."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        out.write(json.dumps({"modulus": modulus}) + "\n")
        for r in reviews:
            row = {"s": r.source, "t": r.text, "l": r.label, "f": r.film}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_cache(path: Path, modulus: dict[str, int]) -> list[LabelledReview] | None:
    """The cached sample, or None when it is missing or was made with other sampling rates."""
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        if json.loads(handle.readline()).get("modulus") != modulus:
            return None
        rows = [json.loads(line) for line in handle]
    return [LabelledReview(r["s"], r["t"], r["l"], r["f"]) for r in rows]


def main() -> None:
    """Train on the mixed pool, compare with the shipped model, and save it only if it clears."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--acl", type=Path, default=Path("Data/raw/aclImdb_v1.tar.gz"))
    parser.add_argument("--rt", type=Path, default=Path("Data/raw/rt_mother/rt_mother.zip"))
    parser.add_argument("--ebd", type=Path, default=Path("Data/raw/imdb_ebd/imdb_ebd.zip"))
    parser.add_argument("--old-model", type=Path, default=Path("artifacts/v2/polarity.joblib"))
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/polarity_mixed"))
    parser.add_argument("--rt-modulus", type=int, default=40)
    parser.add_argument("--ebd-modulus", type=int, default=20)
    parser.add_argument("--cache", type=Path, default=Path("Data/raw/_cache/polarity_mixed.jsonl"))
    args = parser.parse_args()

    modulus = {"rt": args.rt_modulus, "ebd": args.ebd_modulus}
    sampled = read_cache(args.cache, modulus)
    if sampled is None:
        print("scanning the dumps (about half an hour) ...", flush=True)
        sampled = [*sample_rt(args.rt, args.rt_modulus), *sample_ebd(args.ebd, args.ebd_modulus)]
        write_cache(args.cache, modulus, sampled)
    print(f"{len(sampled)} labelled reviews sampled", flush=True)

    train_texts: list[str] = []
    train_labels: list[int] = []
    acl_test: list[LabelledReview] = []
    for review in iter_reviews(args.acl):
        if review.label is None:
            continue
        if review.split == "train":
            train_texts.append(review.text)
            train_labels.append(review.label)
        else:
            acl_test.append(LabelledReview("acl", review.text, review.label))

    test_sets: dict[str, Sequence[LabelledReview]] = {"acl": acl_test}
    for source in ("rt", "ebd"):
        sides = split_by_film(r for r in sampled if r.source == source)
        pool = balanced_cap(sides["train"], TRAIN_PER_CLASS)
        train_texts += [r.text for r in pool]
        train_labels += [r.label for r in pool]
        test_sets[source] = balanced_cap(sides["test"], TEST_PER_CLASS)
        print(f"{source}: {len(pool)} train, {len(test_sets[source])} test reviews", flush=True)

    new, report = train_polarity(
        train_texts, train_labels, [r.text for r in acl_test], [r.label for r in acl_test]
    )
    print(format_polarity_report(report), flush=True)
    result = compare(PolarityModel.load(args.old_model), new, test_sets)
    result["training"] = {"reviews": len(train_texts), "shipped": report.chosen}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "polarity_mixed_report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["ship"]:
        new.save(args.out_dir / "polarity.joblib")
        (args.out_dir / "polarity_report.json").write_text(
            json.dumps(report_to_dict(report), indent=2), encoding="utf-8"
        )
        print(f"SHIP: saved the new model in {args.out_dir}")
    else:
        print("KEEP the shipped model: the new one did not clear the rule")


if __name__ == "__main__":
    main()
