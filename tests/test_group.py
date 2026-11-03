"""Group recommendations: the seen/disliked rule, the penalties and bonus, and how members combine.

The rule tests use hand-made percentiles so every expected number can be checked on paper; the
integration tests run the whole path on the synthetic catalogue the shelves tests use.
"""

from __future__ import annotations

import numpy as np
import pytest

from cinewhy.recsys.group import (
    STRATEGIES,
    GroupConfig,
    Member,
    MemberVectors,
    combine,
    eligible_titles,
    group_scores,
    majority,
    percentiles,
    recommend_group,
)
from cinewhy.schemas import TasteProfile
from tests.test_shelves import _world


def _vectors(
    pct: list[float],
    *,
    seen: tuple[int, ...] = (),
    disliked: tuple[int, ...] = (),
    wants: tuple[int, ...] = (),
) -> MemberVectors:
    def mask(positions: tuple[int, ...]) -> np.ndarray:
        out = np.zeros(len(pct), dtype=bool)
        out[list(positions)] = True
        return out

    return MemberVectors(np.array(pct, dtype=float), mask(seen), mask(disliked), mask(wants))


def _flat(n_titles: int = 4, value: float = 0.5) -> list[float]:
    return [value] * n_titles


MEAN = GroupConfig(strategy="mean")  # every title scores 0.5, so only the rules move a score


# --- the majority --------------------------------------------------------------------------


@pytest.mark.parametrize(("n", "expected"), [(2, 1), (3, 2), (4, 3), (5, 3), (10, 6), (20, 11)])
def test_a_pair_needs_one_person_to_rule_a_title_out_and_a_bigger_group_a_majority(
    n: int, expected: int
) -> None:
    assert majority(n) == expected


# --- percentiles and combining -------------------------------------------------------------


def test_percentiles_run_from_zero_to_one_and_ties_share_a_rank() -> None:
    assert percentiles(np.array([10.0, 30.0, 20.0])).tolist() == [0.0, 1.0, 0.5]
    assert percentiles(np.array([1.0, 1.0, 3.0])).tolist() == [0.25, 0.25, 1.0]
    assert percentiles(np.array([7.0])).tolist() == [1.0]  # one title: nothing to rank against


_P = np.array([[1.0, 0.0, 0.6], [0.5, 0.5, 0.6]])  # two members, three titles


def test_the_strategies_give_the_numbers_a_hand_count_gives() -> None:
    assert combine(_P, "mean").tolist() == pytest.approx([0.75, 0.25, 0.6])
    assert combine(_P, "least_misery").tolist() == pytest.approx([0.5, 0.0, 0.6])
    assert combine(_P, "blend", blend=0.5).tolist() == pytest.approx([0.625, 0.125, 0.6])
    assert combine(_P, "blend", blend=1.0).tolist() == pytest.approx([0.75, 0.25, 0.6])  # = mean
    geometric = combine(_P, "geometric")
    assert geometric[0] == pytest.approx((1.0 * 0.5) ** 0.5, abs=1e-3)
    assert geometric[1] < 0.01  # a zero drags the geometric mean to the floor, unlike the mean
    assert combine(_P, "lower_quartile").tolist() == pytest.approx([0.5, 0.0, 0.6])  # one person


def test_the_lower_quartile_averages_the_unhappiest_quarter_of_a_bigger_group() -> None:
    column = [[0.0], [0.2], [0.4], [0.6], [0.8], [1.0], [1.0], [1.0]]  # eight members, one title
    # a quarter of eight is two people: the two least happy, 0.0 and 0.2
    assert combine(np.array(column), "lower_quartile").tolist() == pytest.approx([0.1])


def test_the_intersection_baseline_puts_titles_in_everyones_top_list_first() -> None:
    # Depth 2: A's top two are titles 0 and 2, B's are all three, so 0 and 2 are in both lists.
    scores = combine(_P, "intersection", depth=2)
    assert scores[0] > 10 and scores[2] > 10 and scores[1] < 10
    # Depth 1: A's top is title 0 and B's top is title 2: nothing is in both.
    assert combine(_P, "intersection", depth=1).max() < 10


def test_an_unknown_strategy_is_refused() -> None:
    with pytest.raises(ValueError):
        combine(_P, "vibes")  # type: ignore[arg-type]


def test_every_listed_strategy_runs_on_a_group_of_any_size() -> None:
    pct = np.random.default_rng(0).random((20, 50))
    for strategy in STRATEGIES:
        for size in (2, 3, 5, 20):
            assert combine(pct[:size], strategy).shape == (50,)


# --- the seen and disliked rule -----------------------------------------------------------


def test_with_two_people_a_title_either_has_seen_is_out() -> None:
    scores = group_scores([_vectors(_flat(), seen=(0,)), _vectors(_flat())], MEAN)
    assert scores[0] == -np.inf
    assert np.isfinite(scores[1:]).all()


def test_with_two_people_a_title_either_dislikes_is_out() -> None:
    scores = group_scores([_vectors(_flat()), _vectors(_flat(), disliked=(1,))], MEAN)
    assert scores[1] == -np.inf and np.isfinite(scores[[0, 2, 3]]).all()


def test_with_three_a_title_one_person_has_seen_stays_in_with_a_small_penalty() -> None:
    # majority(3) is 2: one person who has seen it is below it. Penalty 0.10 x (1 of 3).
    members = [_vectors(_flat(), seen=(0,)), _vectors(_flat()), _vectors(_flat())]
    scores = group_scores(members, MEAN)
    assert scores[0] == pytest.approx(0.5 - 0.10 / 3)
    assert scores[1] == pytest.approx(0.5)


def test_with_three_a_title_two_people_have_seen_is_out() -> None:
    members = [_vectors(_flat(), seen=(0,)), _vectors(_flat(), seen=(0,)), _vectors(_flat())]
    assert group_scores(members, MEAN)[0] == -np.inf


def test_a_dislike_counts_towards_the_majority_alongside_having_seen_it() -> None:
    # One has seen it and one dislikes it: two people against, which is a majority of three.
    members = [_vectors(_flat(), seen=(0,)), _vectors(_flat(), disliked=(0,)), _vectors(_flat())]
    assert group_scores(members, MEAN)[0] == -np.inf


def test_a_dislike_costs_more_than_having_seen_it() -> None:
    members = [_vectors(_flat(), disliked=(0,)), _vectors(_flat()), _vectors(_flat())]
    assert group_scores(members, MEAN)[0] == pytest.approx(0.5 - 0.20 / 3)


def test_someone_who_both_saw_and_disliked_a_title_is_counted_once_as_a_dislike() -> None:
    members = [_vectors(_flat(), seen=(0,), disliked=(0,)), _vectors(_flat()), _vectors(_flat())]
    assert group_scores(members, MEAN)[0] == pytest.approx(0.5 - 0.20 / 3)  # not 0.30/3


def test_the_majority_line_moves_with_the_size_of_the_group() -> None:
    # Five people: two who have seen it is below the majority of three, three is at it.
    two = [_vectors(_flat(), seen=(0,))] * 2 + [_vectors(_flat())] * 3
    three = [_vectors(_flat(), seen=(0,))] * 3 + [_vectors(_flat())] * 2
    assert group_scores(two, MEAN)[0] == pytest.approx(0.5 - 0.10 * 2 / 5)
    assert group_scores(three, MEAN)[0] == -np.inf


def test_a_title_on_a_want_list_gets_a_bonus_that_grows_with_how_many_want_it() -> None:
    one = group_scores([_vectors(_flat(), wants=(3,)), _vectors(_flat()), _vectors(_flat())], MEAN)
    assert one[3] == pytest.approx(0.5 + 0.15 / 3)
    two = [_vectors(_flat(), wants=(2,)), _vectors(_flat(), wants=(2,)), _vectors(_flat())]
    assert group_scores(two, MEAN)[2] == pytest.approx(0.5 + 0.15 * 2 / 3)


def test_the_penalty_is_a_little_not_enough_to_bury_a_clearly_better_title() -> None:
    # Title 0 is the clear favourite of all three; one person has seen it. It still comes first.
    pct = [0.95, 0.5, 0.4, 0.3]
    members = [_vectors(pct, seen=(0,)), _vectors(pct), _vectors(pct)]
    scores = group_scores(members, MEAN)
    assert scores.argmax() == 0


def test_a_cold_member_with_flat_scores_does_not_change_which_title_wins() -> None:
    keen = _vectors([0.9, 0.5, 0.1, 0.3])
    flat = _vectors([0.5, 0.5, 0.5, 0.5])
    assert group_scores([keen, flat], GroupConfig(strategy="blend")).argmax() == 0


# --- the whole path on a catalogue --------------------------------------------------------


def _member(name: str, *liked: str, watched: tuple[str, ...] = (), **kwargs: object) -> Member:
    taste = TasteProfile(liked_movie_ids=liked)
    return Member(name, taste, frozenset(watched), **kwargs)  # type: ignore[arg-type]


def _ids(result: object) -> list[str]:
    return [g.item.movie.movie_id for g in result.items]  # type: ignore[attr-defined]


def test_a_group_needs_at_least_two_people() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        recommend_group(_world(40), [_member("Ann", "cw-1")])


def test_a_pair_is_never_shown_a_title_either_has_watched() -> None:
    world = _world(60)
    ann = _member("Ann", "cw-1", watched=("cw-5", "cw-6"))
    ben = _member("Ben", "cw-2", watched=("cw-6", "cw-7"))
    shown = set(_ids(recommend_group(world, [ann, ben], limit=50)))
    assert shown and not shown & {"cw-5", "cw-6", "cw-7"}
    assert not shown & {"cw-1", "cw-2"}  # a liked title is one they know


def test_with_three_a_title_one_person_watched_can_appear_with_its_penalty_on_view() -> None:
    world = _world(60)
    a = _member("A", "cw-1", watched=("cw-5",))
    b, c = _member("B", "cw-2"), _member("C", "cw-3")
    result = recommend_group(world, [a, b, c], limit=60)
    by_id = {g.item.movie.movie_id: g for g in result.items}
    assert "cw-5" in by_id  # below the majority of two, so it is still offered
    assert by_id["cw-5"].seen_by == 1 and by_id["cw-5"].penalty == pytest.approx(0.10 / 3)
    assert by_id["cw-5"].members[0].saw_it and not by_id["cw-5"].members[1].saw_it
    assert result.majority == 2 and result.members == 3


def test_a_title_a_majority_of_three_watched_is_not_offered() -> None:
    world = _world(60)
    a = _member("A", "cw-1", watched=("cw-5",))
    b = _member("B", "cw-2", watched=("cw-5",))
    result = recommend_group(world, [a, b, _member("C", "cw-3")], limit=60)
    assert "cw-5" not in _ids(result)


def test_the_list_is_ranked_best_first_and_every_item_says_where_each_member_stands() -> None:
    world = _world(60)
    result = recommend_group(world, [_member("Ann", "cw-1"), _member("Ben", "cw-2")], limit=10)
    scores = [g.item.score for g in result.items]
    assert scores == sorted(scores, reverse=True) and len(result.items) == 10
    for g in result.items:
        assert [f.name for f in g.members] == ["Ann", "Ben"]
        assert all(0.0 <= f.percentile <= 1.0 for f in g.members)


def test_the_same_request_gives_the_same_list() -> None:
    world = _world(60)
    members = [_member("Ann", "cw-1"), _member("Ben", "cw-2")]
    assert _ids(recommend_group(world, members, limit=15)) == _ids(
        recommend_group(world, members, limit=15)
    )


def test_titles_already_shown_in_the_session_are_left_out() -> None:
    world = _world(60)
    members = [_member("Ann", "cw-1"), _member("Ben", "cw-2")]
    shown = _ids(recommend_group(world, members, limit=5))
    again = recommend_group(world, members, limit=5, exclude=shown)
    assert not set(shown) & set(_ids(again))


def test_every_title_is_a_candidate_when_nothing_narrows_the_group() -> None:
    world = _world(60)
    allowed, notes = eligible_titles(world, [_member("A"), _member("B")], GroupConfig())
    assert allowed.sum() == 60 and not notes


def test_a_member_who_wants_a_title_lifts_it() -> None:
    world = _world(60)
    plain = recommend_group(world, [_member("A", "cw-1"), _member("B", "cw-2")], limit=60)
    wanting = recommend_group(
        world,
        [_member("A", "cw-1", want=frozenset({"cw-30"})), _member("B", "cw-2")],
        limit=60,
    )
    before = _ids(plain).index("cw-30")
    after = _ids(wanting).index("cw-30")
    assert after <= before
    assert next(g for g in wanting.items if g.item.movie.movie_id == "cw-30").wanted_by == 1


def test_a_group_with_no_shared_language_still_gets_titles_and_a_note() -> None:
    world = _world(60)
    english = _member("Ann", "cw-1", languages=("en",))
    hindi = _member("Ben", "cw-2", languages=("hi",))
    result = recommend_group(world, [english, hindi], limit=60)
    assert {g.item.language for g in result.items} == {"en", "hi"}
    assert any("shares no language" in note for note in result.notes)


def test_a_shared_language_narrows_the_list_to_it() -> None:
    world = _world(60)
    both = _member("Ann", "cw-1", languages=("en", "hi"))
    english = _member("Ben", "cw-2", languages=("en",))
    result = recommend_group(world, [both, english], limit=60)
    assert {g.item.language for g in result.items} == {"en"} and not result.notes
