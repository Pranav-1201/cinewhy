"""Compare an independent human's labels with the assistant's, and re-score against the human.

Every accuracy figure in this project rests on labels written by the assistant that built the
system. This module turns "have a second person label a sample" into a computed result:

* **agreement** between the two labellers (Cohen's kappa on "is this aspect discussed in
  this clause?", plus raw agreement and polarity agreement on mentions both found), and
* the **detector's recall, precision and polarity re-measured against the human's labels**,
  which are the independent numbers the assistant cannot produce.

Run: `python -m cinewhy.absa.agreement tests/data/aspect_label_sheet.csv`
(see docs/LABELLING.md for how to fill the sheet in).
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cinewhy.absa.gold import Proportion, RandomRow, evaluate_random, load_random_gold
from cinewhy.schemas import Aspect

LETTERS = {
    "a": Aspect.ACTING,
    "p": Aspect.PLOT,
    "c": Aspect.PACING,
    "v": Aspect.VISUALS,
    "e": Aspect.ENDING,
    "s": Aspect.SOUNDTRACK,
    "r": Aspect.REWATCHABILITY,
}
_SIGNS = {"+": 1, "-": -1, "0": 0}


def parse_labels(cell: str) -> dict[Aspect, int]:
    """Parse a label cell such as `a+ p-` into `{ACTING: 1, PLOT: -1}`.

    Args:
        cell: Space-separated tokens, each an aspect letter then `+`, `-` or `0`. Empty
            means "no aspect is discussed".

    Raises:
        ValueError: On an unknown letter or sign, or a repeated aspect. A typo must stop the
            run, not silently turn a mention into a non-mention.
    """
    labels: dict[Aspect, int] = {}
    for token in cell.split():
        if len(token) != 2 or token[0].lower() not in LETTERS or token[1] not in _SIGNS:
            raise ValueError(
                f"bad label token {token!r}; use e.g. a+ p- (letters: {sorted(LETTERS)})"
            )
        aspect = LETTERS[token[0].lower()]
        if aspect in labels:
            raise ValueError(f"aspect {aspect.value} labelled twice in {cell!r}")
        labels[aspect] = _SIGNS[token[1]]
    return labels


def load_sheet(path: Path) -> list[RandomRow]:
    """Read a filled-in label sheet. Only rows marked `done` = y count.

    A blank `labels` cell on a done row means "no aspect"; on a row that is not done it means
    "not looked at yet" and the row is ignored.
    """
    rows: list[RandomRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for record in csv.DictReader(handle):
            if record["done"].strip().lower() == "y":
                rows.append(
                    RandomRow(int(record["id"]), record["text"], parse_labels(record["labels"]))
                )
    return rows


def cohen_kappa(first: Sequence[bool], second: Sequence[bool]) -> float:
    """Cohen's kappa for two raters' yes/no decisions; 1.0 is perfect, 0.0 is chance level."""
    if len(first) != len(second) or not first:
        raise ValueError("need two equal-length, non-empty decision lists")
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / n
    p1, p2 = sum(first) / n, sum(second) / n
    expected = p1 * p2 + (1 - p1) * (1 - p2)
    return 1.0 if expected == 1.0 else (observed - expected) / (1.0 - expected)


@dataclass(frozen=True)
class Agreement:
    """How closely two labellers agree on the same clauses."""

    n_clauses: int
    presence_kappa: float
    presence_agreement: Proportion
    polarity_agreement: Proportion


def compare(human: Sequence[RandomRow], assistant: Sequence[RandomRow]) -> Agreement:
    """Agreement between a human's and the assistant's labels on the clauses both labelled.

    Args:
        human: The human's rows.
        assistant: The assistant's rows for the same clause ids.

    Returns:
        Presence agreement over every (clause, aspect) cell, and polarity agreement over the
        mentions both labellers found where both gave a clear + or -.
    """
    mine = {row.id: row for row in assistant}
    pairs = [(h, mine[h.id]) for h in human if h.id in mine]
    if not pairs:
        raise ValueError("no clause ids in common between the two label sets")
    seen_human: list[bool] = []
    seen_assistant: list[bool] = []
    both_signed = same_sign = 0
    for h, a in pairs:
        for aspect in Aspect:
            seen_human.append(aspect in h.aspects)
            seen_assistant.append(aspect in a.aspects)
            if aspect in h.aspects and aspect in a.aspects:
                hs, asg = h.aspects[aspect], a.aspects[aspect]
                if hs in (-1, 1) and asg in (-1, 1):
                    both_signed += 1
                    same_sign += hs == asg
    return Agreement(
        n_clauses=len(pairs),
        presence_kappa=cohen_kappa(seen_human, seen_assistant),
        presence_agreement=Proportion(
            sum(x == y for x, y in zip(seen_human, seen_assistant, strict=True)), len(seen_human)
        ),
        polarity_agreement=Proportion(same_sign, both_signed),
    )


def main() -> None:
    """Print agreement and the system's accuracy against the human labels."""
    from cinewhy.absa.polarity import PolarityModel

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("sheet", type=Path, help="the filled-in CSV label sheet")
    parser.add_argument(
        "--assistant", type=Path, default=Path("tests/data/aspect_gold_random_c.jsonl")
    )
    parser.add_argument("--model", type=Path, default=Path("artifacts/polarity.joblib"))
    args = parser.parse_args()

    human = load_sheet(args.sheet)
    agreement = compare(human, load_random_gold(args.assistant))
    print(f"clauses labelled by both: {agreement.n_clauses}")
    print(f"presence kappa: {agreement.presence_kappa:.3f}  (0.6+ is substantial agreement)")
    print(f"presence agreement: {agreement.presence_agreement}")
    print(f"polarity agreement on shared mentions: {agreement.polarity_agreement}")
    report = evaluate_random(human, PolarityModel.load(args.model))
    print("--- the system scored against the HUMAN's labels")
    print(f"recall:    {report.detector_recall}")
    print(f"precision: {report.detector_precision}")
    print(f"polarity:  {report.polarity_accuracy}")


if __name__ == "__main__":
    main()
