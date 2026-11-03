"""The group evaluation protocol: how profiles are split, groups drawn and a winner chosen.

The real run needs the MovieLens archive and the build; these pin the logic around it on tiny
arrays.
"""

from __future__ import annotations

import numpy as np
import pytest

from cinewhy.recsys.group import GroupConfig, MemberVectors
from cinewhy.recsys.group_eval import (
    VARIANTS,
    EvalUser,
    bootstrap_interval,
    choose_strategy,
    draw_groups,
    evaluate_group,
    friends_group,
    run,
    solo_hit,
    split_profile,
    top_k,
)


def _vectors(pct: np.ndarray, seen: tuple[int, ...] = ()) -> MemberVectors:
    mask = np.zeros(pct.size, dtype=bool)
    mask[list(seen)] = True
    none = np.zeros(pct.size, dtype=bool)
    return MemberVectors(pct, mask, none, none)


# --- splitting a profile -------------------------------------------------------------------


def test_the_targets_are_never_in_the_profile_and_never_watched() -> None:
    rng = np.random.default_rng(0)
    liked, low, rated = np.arange(0, 30), np.arange(30, 40), np.arange(0, 60)
    seeds, dislikes, watched, targets = split_profile(rng, liked, low, rated)
    assert len(seeds) == 10 and len(dislikes) == 10
    assert not set(seeds) & targets and not set(dislikes) & targets
    assert not watched & targets  # a member has not seen what we are about to recommend
    assert targets == set(range(30)) - set(seeds)  # every liked film that is not a seed
    assert set(seeds) <= watched and set(dislikes) <= watched
    assert watched == set(range(60)) - targets  # all else they rated counts as watched


def test_a_user_with_no_low_ratings_simply_has_no_dislikes() -> None:
    rng = np.random.default_rng(0)
    _, dislikes, _, _ = split_profile(rng, np.arange(20), np.array([], dtype=int), np.arange(25))
    assert dislikes == []


def test_the_split_is_reproducible_from_the_seed() -> None:
    args = (np.arange(40), np.arange(40, 50), np.arange(60))
    first = split_profile(np.random.default_rng(5), *args)
    second = split_profile(np.random.default_rng(5), *args)
    assert first == second


# --- the top list and the solo baseline ---------------------------------------------------


def test_top_k_returns_the_best_finite_scores_and_skips_the_ruled_out() -> None:
    scores = np.array([0.1, -np.inf, 0.9, 0.5, 0.7])
    assert set(top_k(scores, 2).tolist()) == {2, 4}
    assert set(top_k(scores, 10).tolist()) == {0, 2, 3, 4}  # fewer finite than asked for


def test_a_solo_hit_needs_a_target_in_the_members_own_top_list() -> None:
    pct = np.linspace(0, 1, 50)  # position 49 is their favourite
    assert solo_hit(_vectors(pct), frozenset({49})) is True
    assert solo_hit(_vectors(pct), frozenset({0})) is False


def test_a_title_the_member_has_seen_cannot_be_their_solo_hit() -> None:
    pct = np.linspace(0, 1, 50)
    assert solo_hit(_vectors(pct, seen=(49,)), frozenset({49})) is False


# --- drawing groups -------------------------------------------------------------------------


_SIM = np.array(
    [[1.0, 0.9, 0.1, 0.2], [0.9, 1.0, 0.3, 0.1], [0.1, 0.3, 1.0, 0.8], [0.2, 0.1, 0.8, 1.0]]
)


def test_friends_are_the_anchor_and_the_users_most_like_them() -> None:
    assert friends_group(_SIM, 0, 2) == [0, 1]
    assert friends_group(_SIM, 2, 3) == [2, 3, 1]
    assert friends_group(_SIM, 3, 1) == [3]


def test_random_groups_have_the_right_size_and_no_repeated_member() -> None:
    groups = draw_groups(np.random.default_rng(1), _SIM, 3, "random", 50)
    assert len(groups) == 50 and all(len(set(g)) == 3 for g in groups)


def test_friend_groups_start_from_their_anchor() -> None:
    groups = draw_groups(np.random.default_rng(1), _SIM, 2, "friends", 20)
    assert all(len(g) == 2 and g[0] != g[1] for g in groups)


# --- scoring a group -------------------------------------------------------------------------

_MEAN = {"mean": GroupConfig(strategy="mean")}


def _user(targets: set[int]) -> EvalUser:
    return EvalUser(_vectors(np.linspace(0, 1, 50)), frozenset(targets), False)


def test_a_member_is_hit_when_one_of_their_targets_is_in_the_groups_top_twenty() -> None:
    users = [_user({49}), _user({0})]  # both rank title 49 best; only the first wants it
    assert evaluate_group(users, [0, 1], _MEAN)["mean"] == (0.5, False)
    both = evaluate_group([_user({49}), _user({40})], [0, 1], _MEAN)
    assert both["mean"] == (1.0, True)


def test_run_gathers_a_value_per_group_for_every_strategy() -> None:
    users = [_user({49}), _user({0}), _user({45})]
    cells = {(2, "random"): [[0, 1], [0, 2], [1, 2]]}
    out = run(cells, users, _MEAN)
    member_hit, all_hit = out[(2, "random")]["mean"]
    assert member_hit.tolist() == [0.5, 1.0, 0.5] and all_hit.tolist() == [0.0, 1.0, 0.0]


# --- intervals and the choice ---------------------------------------------------------------


def test_a_constant_has_a_zero_width_interval_and_the_interval_brackets_the_mean() -> None:
    constant = bootstrap_interval(np.full(30, 0.4), np.random.default_rng(0))
    assert constant == pytest.approx((0.4, 0.4, 0.4))
    values = np.random.default_rng(2).random(200)
    mean, low, high = bootstrap_interval(values, np.random.default_rng(3))
    assert low < mean < high and high - low < 0.2


def _noisy(mean: float, n: int = 100, seed: int = 0) -> np.ndarray:
    """Values with EXACTLY this mean and a standard deviation of 0.1 (so a near-tie is a tie)."""
    z = np.random.default_rng(seed).normal(size=n)
    return np.asarray(mean + (z - z.mean()) / z.std() * 0.1, dtype=np.float64)


def test_a_clear_winner_is_chosen() -> None:
    per = {"mean": _noisy(0.30), "blend50": _noisy(0.31, seed=1), "geometric": _noisy(0.60, seed=2)}
    assert choose_strategy(per) == "geometric"


def test_within_one_standard_error_of_the_best_the_simplest_is_chosen() -> None:
    # The best is 0.52 with a standard error of 0.01; "mean" at 0.515 is within it and simpler.
    per = {
        "mean": _noisy(0.515),
        "geometric": _noisy(0.52, seed=1),
        "least_misery": _noisy(0.40, seed=2),
    }
    assert choose_strategy(per) == "mean"


def test_a_strategy_clearly_behind_the_best_is_not_chosen_for_being_simple() -> None:
    per = {"mean": _noisy(0.40), "geometric": _noisy(0.52, seed=1)}
    assert choose_strategy(per) == "geometric"


def test_every_compared_strategy_is_a_real_one_and_the_simplest_is_first() -> None:
    assert next(iter(VARIANTS)) == "mean"  # first, so it wins a tie
    real = {"mean", "blend", "least_misery", "lower_quartile", "geometric", "intersection"}
    assert {c.strategy for c in VARIANTS.values()} <= real
    with pytest.raises(KeyError):
        VARIANTS["vibes"]
