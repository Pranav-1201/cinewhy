"""What a room adds to the group engine: the mood quiz, swipes as signals, and the top pick.

Every number is checked by hand on the synthetic world the shelves tests use (genres cycle
Drama, Comedy, Action; every fourth film is Hindi).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from cinewhy.recsys import group as group_module
from cinewhy.recsys import rank
from cinewhy.recsys.discover import language_codes
from cinewhy.recsys.group import (
    GroupConfig,
    Member,
    Quiz,
    member_vectors,
    quiz_penalties,
    recommend_group,
)
from cinewhy.schemas import TasteProfile
from tests.test_shelves import _world

CONFIG = GroupConfig()


def _member(name: str, quiz: Quiz | None = None, **kwargs: object) -> Member:
    return Member(name, TasteProfile(), quiz=quiz or Quiz(), **kwargs)  # type: ignore[arg-type]


def _first(world: object, genre: str) -> int:
    return next(i for i, m in enumerate(world.all_movies) if genre in m.genres)  # type: ignore[attr-defined]


def _penalties(members: list[Member]) -> np.ndarray:
    world = _world(60)
    return quiz_penalties(world, members, np.arange(len(world.all_movies)), CONFIG)


def _ids(result: object) -> list[str]:
    return [g.item.movie.movie_id for g in result.items]  # type: ignore[attr-defined]


# --- the mood quiz: weighted by how many of the group chose it -----------------------------------


def test_nobody_answering_the_quiz_costs_nothing() -> None:
    assert not _penalties([_member("A"), _member("B"), _member("C")]).any()


def test_a_genre_two_of_three_chose_costs_a_third_of_the_penalty_and_one_of_three_two_thirds() -> (
    None
):
    world = _world(60)
    people = [
        _member("A", Quiz(genres=("Drama",))),
        _member("B", Quiz(genres=("Drama",))),
        _member("C", Quiz(genres=("Comedy",))),
    ]
    penalties = _penalties(people)
    drama, comedy, action = (_first(world, g) for g in ("Drama", "Comedy", "Action"))
    assert penalties[drama] == pytest.approx(CONFIG.quiz_penalty / 3)
    assert penalties[comedy] == pytest.approx(CONFIG.quiz_penalty * 2 / 3)
    assert penalties[action] == pytest.approx(CONFIG.quiz_penalty)  # nobody's choice: all of it


def test_only_the_people_who_answered_a_category_count_towards_it() -> None:
    world = _world(60)
    people = [_member("A", Quiz(genres=("Drama",))), _member("B"), _member("C")]  # B and C skipped
    assert (
        _penalties(people)[_first(world, "Drama")] == 0
    )  # the one who answered chose it: all agree


def test_a_title_with_several_genres_takes_its_best_liked_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(60)
    drama = _first(world, "Drama")
    both = np.zeros(len(world.all_movies), dtype=bool)
    both[drama] = True  # one film that is a Drama AND a Comedy (the synthetic world has none)
    masks = {"Drama": both.copy(), "Comedy": both.copy()}
    monkeypatch.setattr(group_module, "genre_masks", lambda _catalogue: masks)
    people = [
        _member("A", Quiz(genres=("Drama",))),
        _member("B", Quiz(genres=("Drama",))),
        _member("C", Quiz(genres=("Comedy",))),
    ]
    assert _penalties(people)[drama] == pytest.approx(CONFIG.quiz_penalty / 3)  # Drama's 2 of 3


def test_language_and_kind_choices_are_weighted_the_same_way() -> None:
    world = _world(60)
    codes = language_codes(world)
    hindi = int(np.flatnonzero(codes == "hi")[0])
    english = int(np.flatnonzero(codes == "en")[0])
    people = [_member("A", Quiz(languages=("hi",))), _member("B", Quiz(languages=("en",)))]
    penalties = _penalties(people)
    assert penalties[hindi] == pytest.approx(CONFIG.quiz_penalty / 2)
    assert penalties[english] == pytest.approx(CONFIG.quiz_penalty / 2)
    only_films = [_member("A", Quiz(kinds=("film",))), _member("B", Quiz(kinds=("film",)))]
    assert _penalties(only_films)[hindi] == 0  # a film, and every answerer chose films
    only_series = [_member("A", Quiz(kinds=("series",))), _member("B", Quiz(kinds=("series",)))]
    assert _penalties(only_series)[hindi] == pytest.approx(CONFIG.quiz_penalty)  # a film: no one's


def test_the_quiz_lowers_titles_but_never_removes_them() -> None:
    world = _world(60)
    people = [_member("A", Quiz(genres=("Drama",))), _member("B", Quiz(genres=("Drama",)))]
    shown = recommend_group(world, people, limit=60)
    genres = {g for r in shown.items for g in r.item.movie.genres}
    assert {"Drama", "Comedy", "Action"} <= genres  # every genre is still on offer
    order = [next(iter(r.item.movie.genres)) for r in shown.items]
    assert order.index("Drama") < order.index("Action")  # but the chosen one comes first


# --- swipes: signals for the room, never "seen" ------------------------------------------------


def test_a_right_swipe_steers_similarity_but_is_not_treated_as_seen() -> None:
    world = _world(60)
    candidates = np.arange(len(world.all_movies))
    swiped = _member("A", signals_liked=("cw-5",), want=frozenset({"cw-5"}))
    vectors, _ = member_vectors(world, swiped, candidates, recency=0.5)
    assert not vectors.seen[world.all_index["cw-5"]]  # a real like would make it "seen"
    assert vectors.wants[world.all_index["cw-5"]]
    plain, _ = member_vectors(world, _member("A"), candidates, recency=0.5)
    assert not np.array_equal(plain.pct, vectors.pct)  # but the swipe does steer what is similar


def test_a_left_swipe_counts_as_a_dislike_and_a_pass_by_one_of_two_rules_it_out() -> None:
    world = _world(60)
    candidates = np.arange(len(world.all_movies))
    vectors, _ = member_vectors(
        world, _member("A", passed=frozenset({"cw-7"})), candidates, recency=0.5
    )
    assert vectors.disliked[world.all_index["cw-7"]]
    pair = recommend_group(
        world, [_member("A", passed=frozenset({"cw-7"})), _member("B")], limit=60
    )
    assert "cw-7" not in _ids(pair)  # with two people either one's no is final


def test_an_already_watched_swipe_rules_the_title_out_for_a_pair() -> None:
    world = _world(60)
    pair = recommend_group(
        world, [_member("A", watched=frozenset({"cw-8"})), _member("B")], limit=60
    )
    assert "cw-8" not in _ids(pair)


# --- the top pick ---------------------------------------------------------------------------------


def _score(result: object, movie_id: str) -> float:
    found = next(g for g in result.items if g.item.movie.movie_id == movie_id)  # type: ignore[attr-defined]
    return float(found.item.score)


def test_a_top_pick_lifts_a_title_four_times_as_much_as_a_plain_want() -> None:
    world = _world(60)
    base = recommend_group(world, [_member("A"), _member("B")], limit=60)
    wanted = recommend_group(
        world, [_member("A", want=frozenset({"cw-30"})), _member("B")], limit=60
    )
    topped = recommend_group(world, [_member("A", top="cw-30"), _member("B")], limit=60)
    lift_want = _score(wanted, "cw-30") - _score(base, "cw-30")
    lift_top = _score(topped, "cw-30") - _score(base, "cw-30")
    assert lift_want == pytest.approx(CONFIG.want_bonus / 2)
    assert lift_top == pytest.approx(CONFIG.top_bonus / 2)
    assert lift_top == pytest.approx(4 * lift_want)


def test_a_replaced_top_pick_sits_between_a_plain_want_and_the_new_top_pick() -> None:
    world = _world(60)
    base = recommend_group(world, [_member("A"), _member("B")], limit=60)
    member = _member("A", top="cw-31", former_tops=frozenset({"cw-30"}), want=frozenset({"cw-32"}))
    result = recommend_group(world, [member, _member("B")], limit=60)
    lift = {i: _score(result, i) - _score(base, i) for i in ("cw-30", "cw-31", "cw-32")}
    assert lift["cw-31"] > lift["cw-30"] > lift["cw-32"] > 0  # new top > former top > plain want
    assert lift["cw-30"] == pytest.approx(CONFIG.former_top_bonus / 2)
    assert lift["cw-31"] > 2 * lift["cw-30"]  # "way less" than the new top pick


def test_the_member_whose_top_pick_it_is_is_marked_on_that_title() -> None:
    world = _world(60)
    result = recommend_group(world, [_member("Ann", top="cw-30"), _member("Ben")], limit=60)
    fits = next(g.members for g in result.items if g.item.movie.movie_id == "cw-30")
    assert [(f.name, f.top) for f in fits] == [("Ann", True), ("Ben", False)]
    other = next(g.members for g in result.items if g.item.movie.movie_id == "cw-31")
    assert not any(f.top for f in other)


def test_a_nominated_title_stays_in_the_list_even_when_there_is_nothing_to_say_about_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The usual filter drops a title with no aspect evidence once a list is personalised.

    Someone's top pick (and only that) is exempt: it is the title they most want to watch.
    """
    world = _world(60)
    real = rank.reasons_for

    def silent(catalogue: Any, movie_id: str, weights: Any, **kwargs: Any) -> Any:
        if movie_id in {"cw-30", "cw-31"}:
            return ()
        return real(catalogue, movie_id, weights, **kwargs)

    monkeypatch.setattr(rank, "reasons_for", silent)
    taste = TasteProfile(liked_movie_ids=("cw-1",))
    liker = Member("Ann", taste, top="cw-30", signals_liked=("cw-30",))
    result = recommend_group(world, [liker, _member("Ben")], limit=60)
    shown = _ids(result)
    assert "cw-30" in shown  # her top pick is there
    assert "cw-31" not in shown  # an ordinary title with nothing to say still is not
    top = next(g for g in result.items if g.item.movie.movie_id == "cw-30")
    assert [m.top for m in top.members] == [True, False]


def test_a_top_pick_the_group_rules_out_is_not_forced_back_in() -> None:
    world = _world(60)
    pair = [_member("Ann", top="cw-30"), _member("Ben", watched=frozenset({"cw-30"}))]
    assert "cw-30" not in _ids(recommend_group(world, pair, limit=60))  # Ben has seen it
