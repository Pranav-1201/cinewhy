"""Does the polarity model still work on the newer review dumps?

Part of FEATURE-004.

It was trained on 2011-era IMDb text (aclImdb). Rotten Tomatoes and later IMDb reviews are
written differently, so its published accuracy cannot be assumed for them. Both dumps carry a
per-review star rating, which supplies labels with the same convention aclImdb used (clearly
positive vs clearly negative, the middle left out).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from cinewhy.absa.domain_check import (
    LabelledReview,
    accuracy_report,
    label_from_ebd_rating,
    label_from_rt_stars,
    sample_ebd,
    sample_rt,
    wilson_interval,
)
from tests.conftest import KeywordScorer
from tests.dumps import rt_zip

_EN_DASH = chr(0x2013)
_POS = "A superb film with brilliant acting and a wonderful ending that I loved."
_NEG = "A dull film that dragged terribly with awful acting and a boring ending."
_MID = "A film with acting and an ending, about which I have no strong feeling at all."


def test_ebd_ratings_map_to_labels_with_the_aclimdb_convention() -> None:
    # aclImdb: 7 or more of 10 is positive, 4 or less is negative, 5 and 6 are left out.
    assert label_from_ebd_rating("7") == 1
    assert label_from_ebd_rating("10") == 1
    assert label_from_ebd_rating("4") == 0
    assert label_from_ebd_rating("1") == 0
    assert label_from_ebd_rating("5") is None
    assert label_from_ebd_rating("6") is None
    assert label_from_ebd_rating(None) is None
    assert label_from_ebd_rating("not a number") is None
    # Outside 1-10 is junk, not "very positive" or "very negative".
    assert label_from_ebd_rating("11") is None
    assert label_from_ebd_rating("0") is None
    assert label_from_ebd_rating("-3") is None


def test_rt_stars_map_to_labels_on_the_same_proportions() -> None:
    # The same proportions on RT's 0.5-5 star scale: 3.5 or more positive, 2 or less negative.
    assert label_from_rt_stars(3.5) == 1
    assert label_from_rt_stars(5.0) == 1
    assert label_from_rt_stars(2.0) == 0
    assert label_from_rt_stars(0.5) == 0
    assert label_from_rt_stars(2.5) is None
    assert label_from_rt_stars(3.0) is None


def _ebd_zip(path: Path, records: list[dict[str, object]]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("part-01.json", json.dumps(records))
    return path


def _ebd(
    movie: str, rid: str, text: str, rating: str | None, spoiler: int = 0
) -> dict[str, object]:
    return {
        "movie": movie,
        "review_id": rid,
        "review_detail": text,
        "rating": rating,
        "spoiler_tag": spoiler,
    }


def test_ebd_sample_keeps_only_clean_labelled_film_reviews(tmp_path: Path) -> None:
    records = [
        _ebd("Heat (1995)", "r1", _POS, "9"),
        _ebd("Heat (1995)", "r2", _NEG, "2"),
        _ebd("Heat (1995)", "r3", _MID, "5"),  # middle of the scale: no label
        # The two below have texts of their own: if one were wrongly admitted it must show up as
        # an extra entry, not hide behind a legitimate review with the same words.
        _ebd("Heat (1995)", "r4", _POS + " Spoiler.", "9", spoiler=1),  # never quoted: spoilers
        _ebd(f"Some Show (1968{_EN_DASH} )", "r5", _POS + " Series.", "9"),  # a series, not a film
        _ebd("Heat (1995)", "r6", "great", "9"),  # too short to carry a judgement
        _ebd("Heat (1995)", "r7", _POS, None),  # unrated
    ]
    got = {r.text: r.label for r in sample_ebd(_ebd_zip(tmp_path / "e.zip", records))}
    assert got == {_POS: 1, _NEG: 0}


def test_rt_sample_strips_the_verdict_prefix_and_leaves_out_the_middle(tmp_path: Path) -> None:
    films = [("a1", 1995, "Heat", "2h 50m")]
    reviews = [("a1", ":fresh: " + _POS, 5.0), ("a1", ":rotten: " + _NEG, 1.0), ("a1", _MID, 3.0)]
    got = {r.text: r.label for r in sample_rt(rt_zip(tmp_path / "r.zip", films, reviews))}
    # The prefix is itself a function of the rating, so leaving it in would leak the label.
    assert got == {_POS: 1, _NEG: 0}


def test_samples_record_which_film_each_review_is_about(tmp_path: Path) -> None:
    # The mixed-source retraining keeps every film wholly on one side of its split. If a sampler
    # stopped reporting the film, the split would quietly fall back to hashing each review's text
    # and one film's reviews would land on both sides: that leak is what this pins.
    ebd = {
        r.text: r.film
        for r in sample_ebd(
            _ebd_zip(
                tmp_path / "e.zip",
                [_ebd("Heat (1995)", "r1", _POS, "9"), _ebd("Se7en (1995)", "r2", _NEG, "2")],
            )
        )
    }
    assert ebd == {_POS: "Heat (1995)", _NEG: "Se7en (1995)"}
    films = [("a1", 1995, "Heat", "2h 50m"), ("b2", 1995, "Se7en", "2h 7m")]
    reviews = [("a1", _POS, 5.0), ("b2", _NEG, 1.0)]
    rt = {r.text: r.film for r in sample_rt(rt_zip(tmp_path / "r.zip", films, reviews))}
    assert rt == {_POS: "a1", _NEG: "b2"}


def test_rt_sample_leaves_out_spoilers_and_profanity(tmp_path: Path) -> None:
    header = (
        "movieId,rating,quote,reviewId,isVerified,isSuperReviewer,hasSpoilers,hasProfanity,"
        "score,creationDate,userDisplayName,userRealm,userId\n"
    )
    rows = (
        f'a1,5.0,"{_POS}",,False,False,True,False,5.0,2020-01-01,,RT,u1\n'  # spoiler
        f'a1,5.0,"{_POS} Again.",,False,False,False,True,5.0,2020-01-01,,RT,u2\n'  # profanity
        f'a1,5.0,"{_POS} Clean.",,False,False,False,False,5.0,2020-01-01,,RT,u3\n'
    )
    path = tmp_path / "r.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("movies.csv/movies.csv", "movieId\n")
        z.writestr("user_reviews.csv/user_reviews.csv", header + rows)
    assert [r.text for r in sample_rt(path)] == [f"{_POS} Clean."]


def test_sampling_is_a_deterministic_subset(tmp_path: Path) -> None:
    records = [_ebd("Heat (1995)", f"r{i}", f"{_POS} Take number {i}.", "9") for i in range(60)]
    archive = _ebd_zip(tmp_path / "e.zip", records)
    everything = [r.text for r in sample_ebd(archive, modulus=1)]
    fewer = [r.text for r in sample_ebd(archive, modulus=4)]
    again = [r.text for r in sample_ebd(archive, modulus=4)]
    assert len(everything) == 60
    assert 0 < len(fewer) < 60
    assert fewer == again
    assert set(fewer) <= set(everything)


def test_wilson_interval_behaves_at_the_edges() -> None:
    low, high = wilson_interval(50, 100)
    assert low < 0.5 < high
    assert high - low == pytest.approx(0.19, abs=0.02)
    low, high = wilson_interval(100, 100)
    assert high == pytest.approx(1.0)
    assert 0.95 < low < 0.98  # not 1.0: a perfect sample of 100 is not a perfect model
    assert wilson_interval(0, 0) == (0.0, 1.0)


def _review(source: str, label: int, text: str) -> LabelledReview:
    return LabelledReview(source=source, text=text, label=label)


def test_accuracy_is_balanced_and_reported_per_source(keyword_scorer: KeywordScorer) -> None:
    reviews = [
        _review("ebd", 1, _POS),
        _review("ebd", 1, _POS + " Again."),
        _review("ebd", 1, _POS + " A third."),  # beyond the per-class cap of 2
        _review("ebd", 0, _NEG),
        _review("ebd", 0, _POS + " Sarcasm."),  # a negative review the scorer gets wrong
        _review("ebd", 0, _NEG + " A third."),  # beyond the per-class cap of 2
        _review("rt", 1, _POS),
        _review("rt", 0, _NEG),
    ]
    report = accuracy_report(keyword_scorer, reviews, per_class=2)
    assert report["ebd"]["n"] == 4  # two positive and two negative
    assert report["ebd"]["accuracy"] == pytest.approx(0.75)  # three of four right
    assert report["ebd"]["positive_recall"] == pytest.approx(1.0)
    assert report["ebd"]["negative_recall"] == pytest.approx(0.5)
    assert report["rt"]["n"] == 2
    assert report["rt"]["accuracy"] == pytest.approx(1.0)
    low, high = report["ebd"]["ci95"]
    assert low < 0.75 < high


def test_a_score_of_exactly_zero_counts_as_negative(keyword_scorer: KeywordScorer) -> None:
    # A review with nothing to say scores 0.0. Positive needs a score ABOVE zero, so a
    # positive review the model has no opinion on is a miss, and a negative one a hit.
    reviews = [_review("ebd", 1, _MID), _review("ebd", 0, _MID + " Again.")]
    report = accuracy_report(keyword_scorer, reviews, per_class=5)["ebd"]
    assert report["n"] == 2
    assert report["positive_recall"] == pytest.approx(0.0)
    assert report["negative_recall"] == pytest.approx(1.0)
    assert report["accuracy"] == pytest.approx(0.5)


def test_a_source_with_only_one_class_cannot_be_scored(keyword_scorer: KeywordScorer) -> None:
    report = accuracy_report(keyword_scorer, [_review("rt", 1, _POS)], per_class=5)
    assert report["rt"]["n"] == 0
    assert report["rt"]["accuracy"] is None
