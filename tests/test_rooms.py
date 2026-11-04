"""Rooms: who can join, who can close, when a room is forgotten, and that leaving deletes data."""

from __future__ import annotations

from typing import Any

import pytest

from cinewhy.recsys.group import MAX_GROUP, Member
from cinewhy.recsys.rooms import (
    CODE_ALPHABET,
    CODE_LENGTH,
    HARD_MAX_MEMBERS,
    MAX_NAME_LENGTH,
    RoomError,
    RoomStore,
    clean_name,
    normalise_code,
)
from cinewhy.schemas import TasteProfile


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        """Start at an arbitrary non-zero time."""
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _member(name: str = "Ann", *liked: str) -> Member:
    return Member(name, TasteProfile(liked_movie_ids=liked), frozenset({"cw-9"}))


def _store(**kwargs: Any) -> tuple[RoomStore, Clock]:  # typing only: RoomStore also takes `wall`
    clock = Clock()
    return RoomStore(clock=clock, **kwargs), clock


# --- creating -----------------------------------------------------------------------------


def test_a_room_code_is_six_characters_from_an_alphabet_without_lookalikes() -> None:
    store, _ = _store()
    codes = {store.create().code for _ in range(50)}
    assert len(codes) == 50  # no two open rooms share a code
    for code in codes:
        assert len(code) == CODE_LENGTH and set(code) <= set(CODE_ALPHABET)
    assert not set("01OIL") & set(CODE_ALPHABET)


def test_the_default_size_is_the_working_limit_and_a_request_is_clamped_to_it() -> None:
    store, _ = _store()
    assert store.create().max_members == MAX_GROUP == 5
    assert store.create(3).max_members == 3
    assert store.create(1).max_members == 2  # a group is at least two people
    assert store.create(99).max_members == MAX_GROUP  # never above what this store allows


def test_the_limit_can_be_raised_to_the_owners_eventual_size_and_no_further() -> None:
    store, _ = _store(max_members=20)
    assert store.create().max_members == 20
    assert _store(max_members=500)[0].max_members == HARD_MAX_MEMBERS


def test_the_server_holds_only_so_many_rooms_and_says_so() -> None:
    store, clock = _store(max_rooms=2)
    store.create()
    store.create()
    with pytest.raises(RoomError) as busy:
        store.create()
    assert busy.value.kind == "busy"
    clock.now += store.ttl + 1  # both expire, so there is room again
    assert store.create() is not None


# --- joining ------------------------------------------------------------------------------


def test_the_first_to_join_is_the_host_and_every_join_changes_the_version() -> None:
    store, _ = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member())
    assert room.host_id == ann.member_id and room.version == 1
    ben = store.join(room.code, "Ben", _member("Ben"))
    assert room.host_id == ann.member_id and room.version == 2
    assert list(room.members) == [ann.member_id, ben.member_id]  # join order


def test_a_code_typed_with_spaces_dashes_or_lower_case_still_finds_the_room() -> None:
    store, _ = _store()
    room = store.create()
    typed = f" {room.code[:3].lower()}-{room.code[3:].lower()} "
    assert store.join(typed, "Ann", _member()).name == "Ann"
    assert normalise_code(" ab-c d ") == "ABCD"


def test_two_people_with_the_same_name_stay_tellable_apart() -> None:
    store, _ = _store()
    room = store.create()
    names = [store.join(room.code, "Ann", _member()).name for _ in range(3)]
    assert names == ["Ann", "Ann (2)", "Ann (3)"]


@pytest.mark.parametrize(
    ("typed", "shown"), [("", "Friend"), ("   ", "Friend"), (" Ann   Lee ", "Ann Lee")]
)
def test_a_name_is_tidied_and_never_empty(typed: str, shown: str) -> None:
    assert clean_name(typed) == shown


def test_a_long_name_is_cut() -> None:
    assert len(clean_name("x" * 200)) == MAX_NAME_LENGTH


def test_a_full_room_refuses_one_more() -> None:
    store, _ = _store()
    room = store.create(2)
    store.join(room.code, "Ann", _member())
    store.join(room.code, "Ben", _member())
    with pytest.raises(RoomError) as full:
        store.join(room.code, "Cy", _member())
    assert full.value.kind == "full" and len(room.members) == 2


def test_joining_a_room_that_does_not_exist_is_not_found() -> None:
    store, _ = _store()
    with pytest.raises(RoomError) as missing:
        store.join("ZZZZZZ", "Ann", _member())
    assert missing.value.kind == "not_found"


# --- who you are --------------------------------------------------------------------------


def test_a_members_secret_finds_them_and_a_wrong_one_finds_nothing() -> None:
    store, _ = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member())
    assert store.authenticate(room.code, ann.token)[1].name == "Ann"
    for bad in ("", "nope", ann.token + "x", ann.token[:-1]):
        with pytest.raises(RoomError) as wrong:
            store.authenticate(room.code, bad)
        assert wrong.value.kind == "not_found"


def test_a_wrong_secret_and_a_wrong_room_give_the_same_answer() -> None:
    store, _ = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member())
    with pytest.raises(RoomError) as wrong_secret:
        store.authenticate(room.code, "guess")
    with pytest.raises(RoomError) as wrong_room:
        store.authenticate("ZZZZZZ", ann.token)
    assert wrong_secret.value.kind == wrong_room.value.kind == "not_found"


def test_one_members_secret_does_not_open_another_room() -> None:
    store, _ = _store()
    first, second = store.create(), store.create()
    ann = store.join(first.code, "Ann", _member())
    store.join(second.code, "Ben", _member())
    with pytest.raises(RoomError):
        store.authenticate(second.code, ann.token)


# --- leaving and closing ------------------------------------------------------------------


def test_leaving_removes_the_member_and_what_they_shared() -> None:
    store, _ = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member("Ann", "cw-1"))
    ben = store.join(room.code, "Ben", _member("Ben", "cw-2"))
    before = room.version
    store.leave(room.code, ben.token)
    assert list(room.members) == [ann.member_id] and room.version == before + 1
    assert all(m.name != "Ben" for m in RoomStore.members_of(room))
    with pytest.raises(RoomError):
        store.authenticate(room.code, ben.token)  # their secret is dead


def test_if_the_host_leaves_the_longest_standing_member_takes_over() -> None:
    store, _ = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member())
    ben = store.join(room.code, "Ben", _member())
    store.join(room.code, "Cy", _member())
    store.leave(room.code, ann.token)
    assert room.host_id == ben.member_id


def test_when_the_last_member_leaves_the_room_is_deleted() -> None:
    store, _ = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member())
    store.leave(room.code, ann.token)
    assert len(store) == 0
    with pytest.raises(RoomError):
        store.get(room.code)


def test_only_the_host_can_close_a_room_and_closing_ends_it_for_everyone() -> None:
    store, _ = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member())
    ben = store.join(room.code, "Ben", _member())
    with pytest.raises(RoomError) as refused:
        store.close(room.code, ben.token)
    assert refused.value.kind == "forbidden" and len(store) == 1
    store.close(room.code, ann.token)
    assert len(store) == 0
    for token in (ann.token, ben.token):
        with pytest.raises(RoomError):
            store.authenticate(room.code, token)


# --- forgetting ---------------------------------------------------------------------------


def test_a_room_nobody_uses_is_forgotten_after_the_idle_limit() -> None:
    store, clock = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member())
    clock.now += store.ttl - 1
    assert store.get(room.code) is room  # still there just inside the limit
    clock.now += 2
    with pytest.raises(RoomError):
        store.authenticate(room.code, ann.token)
    assert len(store) == 0  # and its libraries are gone from memory, not merely hidden


def test_using_a_room_keeps_it_alive() -> None:
    store, clock = _store()
    room = store.create()
    ann = store.join(room.code, "Ann", _member())
    for _ in range(5):  # five visits, each inside the idle limit, together far past it
        clock.now += store.ttl - 10
        store.authenticate(room.code, ann.token)
    assert len(store) == 1


# --- what the engine receives -------------------------------------------------------------


def test_the_members_come_out_in_join_order_under_their_room_names() -> None:
    store, _ = _store()
    room = store.create()
    store.join(room.code, "Ann", _member("ignored", "cw-1"))
    store.join(room.code, "Ann", _member("ignored", "cw-2"))
    members = RoomStore.members_of(room)
    assert [m.name for m in members] == ["Ann", "Ann (2)"]
    assert members[0].taste.liked_movie_ids == ("cw-1",) and members[1].watched == {"cw-9"}
