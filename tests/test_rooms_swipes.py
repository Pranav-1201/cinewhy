"""What happens inside a room: the quiz, the four swipes, the one top pick (recsys/rooms.py).

Nothing here may reach a person's own library: the store keeps these answers on the room's member
entry, and `members_of` layers them onto the engine's view of the member for one request.
"""

from __future__ import annotations

import pytest

from cinewhy.recsys import rooms as rooms_module
from cinewhy.recsys.group import Member, Quiz
from cinewhy.recsys.rooms import RoomError, RoomMember, RoomStore
from cinewhy.schemas import TasteProfile


def _store_with_two() -> tuple[RoomStore, str, RoomMember, RoomMember]:
    store = RoomStore()
    room = store.create()
    library = Member(
        "x",
        TasteProfile(liked_movie_ids=("cw-1",), disliked_movie_ids=("cw-2",)),
        frozenset({"cw-3"}),
    )
    ann = store.join(room.code, "Ann", library)
    ben = store.join(room.code, "Ben", Member("y", TasteProfile()))
    return store, room.code, ann, ben


def _effective(store: RoomStore, code: str) -> list[Member]:
    return RoomStore.members_of(store.get(code))


# --- the four swipes --------------------


def test_each_swipe_lands_in_its_own_bucket_in_the_engines_view() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-10", "want")
    store.swipe(code, ann.token, "cw-11", "pass")
    store.swipe(code, ann.token, "cw-12", "seen")
    member = _effective(store, code)[0]
    assert "cw-10" in member.want and "cw-10" in member.signals_liked  # steers similarity
    assert member.passed == {"cw-11"}
    assert "cw-12" in member.watched and "cw-12" not in member.signals_liked
    assert member.quiz == Quiz()  # nothing answered yet: no preference


def test_a_swipe_never_changes_the_library_the_person_shared() -> None:
    store, code, ann, _ = _store_with_two()
    for movie, action in [
        ("cw-10", "want"),
        ("cw-11", "pass"),
        ("cw-12", "seen"),
        ("cw-13", "top"),
    ]:
        store.swipe(code, ann.token, movie, action)
    shared = ann.member
    assert shared.taste.liked_movie_ids == ("cw-1",) and shared.taste.disliked_movie_ids == (
        "cw-2",
    )
    assert shared.watched == {"cw-3"} and shared.want == frozenset()


def test_swiping_a_title_again_changes_the_answer_instead_of_adding_a_second_one() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-10", "want")
    store.swipe(code, ann.token, "cw-10", "pass")
    member = _effective(store, code)[0]
    assert "cw-10" in member.passed and "cw-10" not in member.want


def test_an_unknown_action_is_refused() -> None:
    store, code, ann, _ = _store_with_two()
    with pytest.raises(RoomError) as refused:
        store.swipe(code, ann.token, "cw-10", "love")
    assert refused.value.kind == "bad_action"


def test_swipes_need_the_members_own_secret() -> None:
    store, code, _, ben = _store_with_two()
    with pytest.raises(RoomError) as refused:
        store.swipe(code, "guess", "cw-10", "want")
    assert refused.value.kind == "not_found"
    store.swipe(code, ben.token, "cw-10", "want")
    assert "cw-10" not in _effective(store, code)[0].want  # Ben's answer is Ben's alone


def test_one_persons_answers_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rooms_module, "MAX_SWIPES", 3)
    store, code, ann, _ = _store_with_two()
    for n in range(3):
        store.swipe(code, ann.token, f"cw-{n + 20}", "want")
    store.swipe(code, ann.token, "cw-20", "pass")  # changing an answer is still allowed
    with pytest.raises(RoomError):
        store.swipe(code, ann.token, "cw-99", "want")


# --- the one top pick --------------------


def test_the_first_top_pick_is_taken_without_asking() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-13", "top")
    member = _effective(store, code)[0]
    assert member.top == "cw-13" and "cw-13" in member.signals_liked
    assert member.former_tops == frozenset()


def test_a_second_top_pick_is_refused_until_the_person_confirms() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-13", "top")
    with pytest.raises(RoomError) as asked:
        store.swipe(code, ann.token, "cw-14", "top")
    assert asked.value.kind == "top_exists"
    assert _effective(store, code)[0].top == "cw-13"  # nothing changed while the question stood


def test_confirming_replaces_the_top_pick_and_keeps_the_old_one_as_a_former_top() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-13", "top")
    store.swipe(code, ann.token, "cw-14", "top", replace=True)
    member = _effective(store, code)[0]
    assert member.top == "cw-14" and member.former_tops == {"cw-13"}
    assert {"cw-13", "cw-14"} <= set(member.signals_liked)


def test_naming_the_same_title_as_top_again_is_a_no_op_not_a_question() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-13", "top")
    store.swipe(code, ann.token, "cw-13", "top")
    assert _effective(store, code)[0].former_tops == frozenset()


def test_swiping_the_top_pick_another_way_frees_the_slot() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-13", "top")
    store.swipe(code, ann.token, "cw-13", "pass")
    store.swipe(code, ann.token, "cw-14", "top")  # no question: the slot was free
    assert _effective(store, code)[0].top == "cw-14"


def test_a_former_top_pick_brought_back_is_no_longer_former() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-13", "top")
    store.swipe(code, ann.token, "cw-14", "top", replace=True)
    store.swipe(code, ann.token, "cw-13", "top", replace=True)
    member = _effective(store, code)[0]
    assert member.top == "cw-13" and member.former_tops == {"cw-14"}


def test_each_person_has_their_own_top_pick() -> None:
    store, code, ann, ben = _store_with_two()
    store.swipe(code, ann.token, "cw-13", "top")
    store.swipe(code, ben.token, "cw-14", "top")  # no conflict: it is per person
    first, second = _effective(store, code)
    assert (first.top, second.top) == ("cw-13", "cw-14")


# --- the quiz and the activity counter --------------------


def test_the_quiz_is_stored_per_member_and_reaches_the_engine() -> None:
    store, code, ann, _ = _store_with_two()
    store.set_quiz(code, ann.token, Quiz(genres=("Comedy",), languages=("hi",)))
    first, second = _effective(store, code)
    assert first.quiz == Quiz(genres=("Comedy",), languages=("hi",)) and second.quiz == Quiz()
    assert first.languages == () and first.kinds == ()  # the quiz weights; it is not a hard filter


def test_every_answer_moves_the_activity_counter_and_a_join_moves_the_version() -> None:
    store, code, ann, _ = _store_with_two()
    room = store.get(code)
    version, before = room.version, room.activity
    store.set_quiz(code, ann.token, Quiz())
    store.swipe(code, ann.token, "cw-10", "want")
    assert room.activity == before + 2 and room.version == version  # answers are not membership


def test_a_members_deck_leaves_out_what_they_swiped_and_what_is_in_their_library() -> None:
    store, code, ann, _ = _store_with_two()
    store.swipe(code, ann.token, "cw-10", "pass")
    store.swipe(code, ann.token, "cw-13", "top")
    left_out = RoomStore.seen_by(ann)
    assert {
        "cw-10",
        "cw-13",
        "cw-1",
        "cw-2",
        "cw-3",
    } <= left_out  # swipes, top, likes, dislikes, watched


def test_leaving_removes_the_members_answers_with_them() -> None:
    store, code, _, ben = _store_with_two()
    store.swipe(code, ben.token, "cw-10", "want")
    store.leave(code, ben.token)
    assert len(_effective(store, code)) == 1 and "cw-10" not in _effective(store, code)[0].want
