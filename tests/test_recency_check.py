"""The recency checks that go into eval.json: the lift itself, the cold-start mix, and the cost.

The cost is only believable if it moves when the lift hurts: a lift that is zero must cost exactly
nothing, and a lift that buries the films a user liked must show a clearly negative interval. Both
are planted here on clusters where the right answer is known by construction.
"""

from __future__ import annotations

import numpy as np
import pytest

from cinewhy.recsys.catalogue import aspect_order
from cinewhy.recsys.discover import RECENCY_MAX, recency_lift
from cinewhy.recsys.evaluate import RecEvalReport, evaluate_recommenders
from cinewhy.recsys.recency_check import cold_start_mix
from tests.test_discover import _world
from tests.test_recsys import TestEvaluationProtocol as _Protocol  # alias: not collected twice


def test_the_lift_is_zero_before_1980_then_linear_to_the_newest_film() -> None:
    years = np.array([1950, 1980, 2000, 2020, 0], dtype=np.int64)
    lift = recency_lift(years, 1.0)
    assert lift[0] == 0.0 and lift[1] == 0.0
    assert lift[2] == pytest.approx(RECENCY_MAX * 0.5)  # (2000 - 1980) / (2020 - 1980)
    assert lift[3] == pytest.approx(RECENCY_MAX)
    assert lift[4] == 0.0  # an unknown year gets no lift rather than a negative one
    assert np.all(recency_lift(years, 0.0) == 0.0)
    assert recency_lift(years, 0.5)[3] == pytest.approx(RECENCY_MAX * 0.5)


def test_cold_start_mix_counts_the_first_page_by_era() -> None:
    mix = cold_start_mix(_world(), recencies=(0.0, 1.0), limit=2)
    assert mix["page_size"] == 2
    assert mix["catalogue_share_from_2000"] == pytest.approx(4 / 6)  # 2022, 2019, 2021, 2020
    none, full = mix["by_recency"]
    assert (none["recency"], full["recency"]) == (0.0, 1.0)
    assert none["films"] == full["films"] == 2
    assert full["from_2012"] == 2  # at full recency both places go to recent films
    assert full["from_2000"] >= none["from_2000"]
    assert full["median_year"] >= none["median_year"]
    assert 0 <= none["hindi"] <= 2


def test_cold_start_mix_counts_are_exact_when_the_page_holds_every_film() -> None:
    world = _world()
    # "No Scores" becomes a 2005 film so one film sits between the 2000 and 2012 thresholds.
    world.movies = tuple(
        m.model_copy(update={"year": 2005}) if m.movie_id == "cw-6" else m for m in world.movies
    )
    row = cold_start_mix(world, recencies=(0.5,), limit=6)["by_recency"][0]
    assert row["films"] == 6
    assert row["from_2000"] == 4  # 2022, 2019, 2021, 2005
    assert row["from_2012"] == 3  # 2022, 2019, 2021
    assert row["hindi"] == 2  # Hindi Hit and Hindi Obscure
    assert row["median_year"] == 2012  # 1949, 1995, 2005, 2019, 2021, 2022: (2005 + 2019) / 2


def _evaluate(lifts: dict[str, np.ndarray]) -> RecEvalReport:
    report, _ = evaluate_recommenders(
        *_Protocol._planted(),
        60,
        np.zeros((60, len(aspect_order())), dtype=np.float32),
        min_likes=5,
        n_seeds=3,
        max_eval_users=150,
        recency_lifts=lifts,
    )
    return report


def test_a_zero_lift_costs_exactly_nothing() -> None:
    report = _evaluate({"none": np.zeros(60)})
    row = next(d for d in report.differences if (d.a, d.b, d.k) == ("hybrid_none", "hybrid", 10))
    assert row.diff.mean == 0.0 and row.diff.lo == 0.0 and row.diff.hi == 0.0


def test_a_lift_that_buries_liked_films_shows_as_a_clear_cost() -> None:
    # Half the users like items 0-29; +10 on items 30-59 puts all of those above every liked film.
    buried = np.concatenate([np.zeros(30), np.full(30, 10.0)])
    report = _evaluate({"buried": buried})
    methods = {m.name: m for m in report.methods}
    assert methods["hybrid_buried"].hit_rate[10].mean < methods["hybrid"].hit_rate[10].mean
    row = next(d for d in report.differences if (d.a, d.b, d.k) == ("hybrid_buried", "hybrid", 10))
    assert row.diff.hi < 0 and row.significant  # the whole interval is below zero


def test_without_lifts_the_report_has_the_same_four_methods_as_before() -> None:
    report, _ = evaluate_recommenders(
        *_Protocol._planted(),
        60,
        np.zeros((60, len(aspect_order())), dtype=np.float32),
        min_likes=5,
        n_seeds=3,
        max_eval_users=150,
    )
    assert [m.name for m in report.methods] == ["popularity", "cf", "aspect", "hybrid"]
