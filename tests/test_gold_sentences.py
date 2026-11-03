"""The sentence-level gold set: loader, scores and the real file.

The loader refuses bad rows, the scores are what a hand count says, and the real file is the
fresh, blind-labelled sample it claims to be.

Expected numbers come from `KeywordScorer` (+0.9 / -0.9 / 0.0), so a wrong rate shows as a wrong
integer. The scorer is a stand-in, never used to claim anything about accuracy.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from cinewhy.absa.gold import (
    SentenceRow,
    evaluate_sentences,
    load_sentence_gold,
    predict_sentence,
)
from cinewhy.schemas import Aspect
from tests.conftest import KeywordScorer

_DATA = Path(__file__).parent / "data"


def _row(i: int, stratum: str, text: str, **aspects: int) -> SentenceRow:
    return SentenceRow(i, stratum, text, {Aspect(k): v for k, v in aspects.items()})


# A: both aspects found, both signs right. B: the labelled aspect (ending) is never flagged, and
# a different one (soundtrack) is. C: flagged but the scorer gives 0.0, so no opinion. D: flagged
# with the wrong sign. E: nothing to find. F: a labelled 0 (discussed, no direction).
_ROWS = [
    _row(0, "M", "The acting was great and the plot was dull.", acting=1, plot=-1),
    _row(1, "U", "The soundtrack was superb.", ending=1),
    _row(2, "U", "The pacing was fine.", pacing=1),
    _row(3, "U", "The ending was awful.", ending=1),
    _row(4, "U", "I watched it on Tuesday."),
    _row(5, "U", "The plot was brilliant.", plot=0),
]


def test_the_rates_are_what_a_hand_count_says() -> None:
    report = evaluate_sentences(_ROWS, KeywordScorer())
    assert report.n_sentences == 6
    # truth aspects 6 (A2, B1, C1, D1, F1); flagged 6 (A2, soundtrack, pacing, ending, plot); both 5
    assert (report.mention_recall.hits, report.mention_recall.n) == (5, 6)
    assert (report.mention_precision.hits, report.mention_precision.n) == (5, 6)
    # labelled +-1: A2, B1, C1, D1 = 5; decided (an opinion was counted): A2 and D = 3; right: 2
    assert (report.sign_accuracy.hits, report.sign_accuracy.n) == (2, 3)
    assert (report.end_to_end.hits, report.end_to_end.n) == (2, 5)


def test_a_stratum_is_scored_on_its_own_rows_only() -> None:
    report = evaluate_sentences(_ROWS, KeywordScorer(), stratum="M")
    assert report.n_sentences == 1
    assert (report.mention_recall.hits, report.mention_recall.n) == (2, 2)
    assert (report.end_to_end.hits, report.end_to_end.n) == (2, 2)
    unique = evaluate_sentences(_ROWS, KeywordScorer(), stratum="U")
    assert unique.n_sentences == 5
    assert (unique.end_to_end.hits, unique.end_to_end.n) == (0, 3)


def test_staying_silent_counts_against_end_to_end_but_not_sign_accuracy() -> None:
    silent = [_row(0, "U", "The pacing was fine.", pacing=1)]
    report = evaluate_sentences(silent, KeywordScorer())
    assert report.sign_accuracy.n == 0  # nothing was decided, so there is no sign to be right about
    assert (report.end_to_end.hits, report.end_to_end.n) == (0, 1)


def test_a_sentence_is_split_before_it_is_scored() -> None:
    # Whole, "great" and "dull" would blend into one score for both aspects; split, each has one.
    prediction = predict_sentence("The acting was great and the plot was dull.", KeywordScorer())
    assert prediction == {Aspect.ACTING: pytest.approx(0.9), Aspect.PLOT: pytest.approx(-0.9)}


def test_a_flagged_aspect_with_no_counted_opinion_is_reported_as_none() -> None:
    assert predict_sentence("The pacing was fine.", KeywordScorer()) == {Aspect.PACING: None}


@pytest.mark.parametrize(
    "row",
    [
        {"stratum": "X", "aspects": {"acting": 1}},  # unknown stratum
        {"stratum": "U", "aspects": {"acting": 2}},  # polarity out of range
        {"stratum": "U", "aspects": {"direction": 1}},  # not one of the seven aspects
    ],
)
def test_the_loader_refuses_a_malformed_row_rather_than_shrinking_the_set(
    tmp_path: Path, row: dict[str, object]
) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text(json.dumps({"id": 0, "review_id": "r", "text": "x", **row}) + "\n", "utf-8")
    with pytest.raises(ValueError):
        load_sentence_gold(path)


# --- the real file -----------------------------------------------------------------------------


def test_the_real_file_is_two_hundred_rows_in_the_stated_strata() -> None:
    rows = load_sentence_gold(_DATA / "aspect_gold_sentences.jsonl")
    assert Counter(r.stratum for r in rows) == {"U": 150, "M": 50}
    assert sorted(r.id for r in rows) == list(range(200))
    assert sum(len(r.aspects) for r in rows) == 151  # labelled aspect mentions
    assert sum(1 for r in rows if r.aspects) == 91  # sentences with at least one


def test_every_row_says_who_labelled_it() -> None:
    lines = (_DATA / "aspect_gold_sentences.jsonl").read_text(encoding="utf-8").splitlines()
    assert {json.loads(line)["labelled_by"] for line in lines} == {"assistant"}


def test_the_sample_is_fresh_no_sentence_overlaps_an_older_gold_file() -> None:
    new = [r.text.lower() for r in load_sentence_gold(_DATA / "aspect_gold_sentences.jsonl")]
    old: list[str] = []
    for path in _DATA.glob("aspect_gold_*.jsonl"):
        if path.name != "aspect_gold_sentences.jsonl":
            old += [
                json.loads(line)["text"].lower()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
    clashes = [t for t in new if any(t in o or o in t for o in old)]
    assert clashes == []
    assert len(set(new)) == len(new)  # and no sentence appears twice
