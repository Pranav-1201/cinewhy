"""Mixed-source polarity retraining (DECISIONS D-017): the split, the sampling and the ship rule.

What must hold for the result to be believable: a film is never on both sides of the split, the
test samples are balanced and reproducible, both models are scored on identical items, and the
ship rule is exactly the one declared in advance (Rotten Tomatoes must improve with the whole
interval above zero, the other two sources may lose at most one point).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from cinewhy.absa.domain_check import LabelledReview
from cinewhy.absa.polarity import PolarityModel
from cinewhy.absa.polarity_mixed import (
    MAX_DROP,
    TEST_FILM_MODULUS,
    PairedDiff,
    balanced_cap,
    compare,
    decide,
    domain_document,
    film_side,
    paired_difference,
    read_cache,
    split_by_film,
    write_cache,
)


def _review(source: str, film: str, text: str, label: int) -> LabelledReview:
    return LabelledReview(source, text, label, film)


def test_about_one_film_in_five_is_held_out_and_the_choice_is_stable() -> None:
    sides = [film_side("rt", f"film-{i}") for i in range(2000)]
    share = sides.count("test") / len(sides)
    assert 0.15 < share < 0.25  # 1 / TEST_FILM_MODULUS = 0.2, within sampling noise
    assert sides == [film_side("rt", f"film-{i}") for i in range(2000)]
    assert TEST_FILM_MODULUS == 5


def test_a_review_with_no_film_name_still_lands_on_a_stable_side() -> None:
    assert film_side("rt", "", "some text") == film_side("rt", "", "some text")
    texts = [f"unnamed review number {i}" for i in range(500)]
    assert {film_side("rt", "", t) for t in texts} == {"train", "test"}


def test_every_film_is_wholly_on_one_side_and_no_review_is_lost() -> None:
    reviews = [
        _review("rt", f"film-{i % 40}", f"review {i} of film {i % 40}", i % 2) for i in range(400)
    ]
    sides = split_by_film(reviews)
    train_films = {r.film for r in sides["train"]}
    test_films = {r.film for r in sides["test"]}
    assert train_films.isdisjoint(test_films)  # the leak this split exists to prevent
    assert len(sides["train"]) + len(sides["test"]) == 400
    assert train_films and test_films


def test_the_same_film_name_in_two_sources_is_split_independently() -> None:
    flips = sum(film_side("rt", f"f{i}") != film_side("ebd", f"f{i}") for i in range(300))
    assert flips > 50  # source is part of the key, so the two sources do not move in lockstep


def test_balanced_cap_gives_equal_classes_and_ignores_input_order() -> None:
    pos = [_review("rt", "a", f"positive review {i}", 1) for i in range(30)]
    neg = [_review("rt", "a", f"negative review {i}", 0) for i in range(12)]
    first = balanced_cap(pos + neg, per_class=20)
    second = balanced_cap(list(reversed(neg + pos)), per_class=20)
    assert [r.text for r in first] == [r.text for r in second]
    assert sum(r.label for r in first) == 12 and len(first) == 24  # limited by the rarer class
    assert len(balanced_cap(pos + neg, per_class=5)) == 10  # and by the cap


def test_balanced_cap_with_a_missing_class_returns_nothing() -> None:
    only_positive = [_review("rt", "a", f"great {i}", 1) for i in range(10)]
    assert balanced_cap(only_positive, per_class=5) == []


def test_paired_difference_is_zero_for_identical_models_and_one_for_a_clean_win() -> None:
    right = np.ones(50)
    wrong = np.zeros(50)
    same = paired_difference(right, right)
    assert (same.mean, same.lo, same.hi) == (0.0, 0.0, 0.0)
    win = paired_difference(wrong, right)
    assert (win.mean, win.lo, win.hi) == (1.0, 1.0, 1.0)


def _diffs(rt: tuple[float, float, float], acl: float, ebd: float) -> dict[str, PairedDiff]:
    return {
        "rt": PairedDiff(*rt),
        "acl": PairedDiff(acl, acl - 0.005, acl + 0.005),
        "ebd": PairedDiff(ebd, ebd - 0.005, ebd + 0.005),
    }


def test_ship_when_rt_clearly_improves_and_the_others_hold() -> None:
    verdict = decide(_diffs((0.10, 0.08, 0.12), acl=-0.004, ebd=0.01))
    assert verdict.ship and len(verdict.reasons) == 3


def test_do_not_ship_when_the_rt_gain_could_be_noise() -> None:
    verdict = decide(_diffs((0.02, -0.003, 0.04), acl=0.0, ebd=0.0))
    assert not verdict.ship
    assert "does not clearly improve" in verdict.reasons[0]


def test_do_not_ship_when_another_source_loses_more_than_a_point() -> None:
    assert not decide(_diffs((0.10, 0.08, 0.12), acl=-0.02, ebd=0.0)).ship
    assert not decide(_diffs((0.10, 0.08, 0.12), acl=0.0, ebd=-0.0101)).ship
    # exactly the allowed drop is fine: the rule is "no more than", declared as MAX_DROP
    assert decide(_diffs((0.10, 0.08, 0.12), acl=-MAX_DROP, ebd=-MAX_DROP)).ship


def _model(pairs: list[tuple[str, int]]) -> PolarityModel:
    texts, labels = zip(*pairs, strict=True)
    vectorizer = TfidfVectorizer(min_df=1)
    features = vectorizer.fit_transform(texts)
    classifier = LogisticRegression(C=10.0, max_iter=500).fit(features, labels)
    return PolarityModel(vectorizer, classifier)


_CLASSIC = [
    ("brilliant wonderful superb film", 1),
    ("lovely moving superb story", 1),
    ("dull awful boring film", 0),
    ("terrible tedious boring story", 0),
] * 5
_SLANG = [
    ("slay iconic banger watch", 1),
    ("goated masterpiece slay", 1),
    ("mid trash cringe skip", 0),
    ("cringe snooze trash mid", 0),
] * 5


def _set(source: str, rows: list[tuple[str, int]]) -> list[LabelledReview]:
    return [_review(source, f"{source}-{i}", text, label) for i, (text, label) in enumerate(rows)]


def _all_sets() -> dict[str, list[LabelledReview]]:
    return {"acl": _set("acl", _CLASSIC), "rt": _set("rt", _SLANG), "ebd": _set("ebd", _CLASSIC)}


def test_a_model_that_learned_the_new_vocabulary_wins_on_it_and_ships() -> None:
    old, new = _model(_CLASSIC), _model(_CLASSIC + _SLANG)
    result = compare(old, new, _all_sets())
    assert result["rt"]["new"]["accuracy"] == 1.0
    assert result["rt"]["old"]["accuracy"] < 0.8  # never saw this vocabulary
    assert result["rt"]["diff"]["lo"] > 0
    assert result["acl"]["diff"]["mean"] == 0.0 and result["ebd"]["diff"]["mean"] == 0.0
    assert result["ship"] is True


def test_the_same_model_twice_never_ships() -> None:
    model = _model(_CLASSIC)
    result = compare(model, model, _all_sets())
    assert result["ship"] is False
    assert result["rt"]["diff"]["mean"] == 0.0


def test_both_models_are_scored_on_exactly_the_same_items() -> None:
    result = compare(_model(_CLASSIC), _model(_CLASSIC + _SLANG), _all_sets())
    for source in ("acl", "rt", "ebd"):
        assert result[source]["n"] == 20  # one n per source, shared by old and new


def test_the_sample_cache_round_trips_and_is_discarded_for_other_sampling_rates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache" / "mix.jsonl"
    reviews = [
        _review("rt", "f1", f"A fine film {chr(0x2013)} really.", 1),
        _review("ebd", "f2", "Bad.", 0),
    ]
    assert read_cache(path, {"rt": 40, "ebd": 20}) is None  # nothing cached yet
    write_cache(path, {"rt": 40, "ebd": 20}, reviews)
    assert read_cache(path, {"rt": 40, "ebd": 20}) == reviews
    assert read_cache(path, {"rt": 400, "ebd": 20}) is None  # made at another rate: not reusable


def test_the_domain_document_scores_both_models_on_the_same_held_out_reviews() -> None:
    old, new = _model(_CLASSIC), _model(_CLASSIC + _SLANG)
    held_out = {"rt": _set("rt", _SLANG), "ebd": _set("ebd", _CLASSIC)}
    document = domain_document(old, new, held_out)
    assert set(document["by_source"]) == set(document["before_retraining"]) == {"rt", "ebd"}
    for source in ("rt", "ebd"):  # same reviews for both models: same n, class-balanced
        assert (
            document["by_source"][source]["n"] == document["before_retraining"][source]["n"] == 20
        )
    assert document["by_source"]["rt"]["accuracy"] == 1.0
    assert document["before_retraining"]["rt"]["accuracy"] < 0.8
    assert "held out" in document["note"] and document["held_out_film_modulus"] == 5
