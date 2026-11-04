"""Open rooms survive a server restart (cinewhy/recsys/rooms.py: to_dict, restore, RoomSaver).

The file is only ever a copy of rooms that are open: closed and expired rooms are not in it, time
spent down counts as idle time, and a damaged file is ignored instead of trusted or crashed on.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from cinewhy.recsys import rooms as rooms_module
from cinewhy.recsys.group import Member, Quiz
from cinewhy.recsys.rooms import RoomSaver, RoomStore, read_state, write_state
from cinewhy.schemas import Aspect, TasteProfile


class Time:
    """A clock the test moves by hand (used for both the idle clock and the calendar clock)."""

    def __init__(self, start: float) -> None:
        """Start at `start`."""
        self.now = start

    def __call__(self) -> float:
        return self.now


def _store(mono: Time | None = None, wall: Time | None = None) -> tuple[RoomStore, Time, Time]:
    mono, wall = mono or Time(1000.0), wall or Time(1_700_000_040.0)  # a minute boundary + 0
    return RoomStore(clock=mono, wall=wall), mono, wall


def _library(name: str) -> Member:
    taste = TasteProfile(
        aspect_weights={Aspect.PACING: 0.5}, liked_movie_ids=("cw-1",), disliked_movie_ids=("cw-2",)
    )
    return Member(name, taste, frozenset({"cw-3"}), frozenset({"cw-4"}))


def _busy_room(store: RoomStore) -> tuple[str, str, str]:
    room = store.create()
    ann = store.join(room.code, "Ann", _library("a"))
    ben = store.join(room.code, "Ben", _library("b"))
    store.set_quiz(room.code, ann.token, Quiz(("film",), ("hi",), ("Drama", "Comedy")))
    for movie, action in [("cw-10", "want"), ("cw-11", "pass"), ("cw-12", "seen")]:
        store.swipe(room.code, ann.token, movie, action)
    store.swipe(room.code, ann.token, "cw-13", "top")
    store.swipe(room.code, ann.token, "cw-14", "top", replace=True)
    store.swipe(room.code, ben.token, "cw-10", "pass")
    return room.code, ann.token, ben.token


def _through_json(data: dict[str, Any]) -> Any:
    return json.loads(json.dumps(data))  # what a real file round trip does to the data


# --- the round trip ---------------------------------------------------------------------------


def test_a_room_comes_back_with_everything_in_it_and_every_secret_still_works() -> None:
    before, _, _ = _store()
    code, ann_token, ben_token = _busy_room(before)
    after, _, _ = _store()
    assert after.restore(_through_json(before.to_dict())) == 1

    old, new = before.get(code), after.get(code)
    assert (new.code, new.max_members, new.host_id) == (old.code, old.max_members, old.host_id)
    assert (new.version, new.activity) == (old.version, old.activity)
    assert RoomStore.members_of(new) == RoomStore.members_of(old)  # libraries, quiz, swipes, tops
    assert after.authenticate(code, ann_token)[1].name == "Ann"  # a reload does not log anyone out
    assert after.authenticate(code, ben_token)[1].name == "Ben"
    assert after.get(code).members[old.host_id or ""].name == "Ann"


def test_the_person_can_carry_on_where_they_were() -> None:
    before, _, _ = _store()
    code, ann_token, _ = _busy_room(before)
    after, _, _ = _store()
    after.restore(_through_json(before.to_dict()))
    with pytest.raises(rooms_module.RoomError) as asked:
        after.swipe(
            code, ann_token, "cw-20", "top"
        )  # the top pick set before the restart is still set
    assert asked.value.kind == "top_exists"
    after.swipe(code, ann_token, "cw-20", "top", replace=True)
    assert after.authenticate(code, ann_token)[1].top == "cw-20"


def test_nothing_is_restored_twice() -> None:
    before, _, _ = _store()
    _busy_room(before)
    data = _through_json(before.to_dict())
    after, _, _ = _store()
    assert after.restore(data) == 1 and after.restore(data) == 0 and len(after) == 1


# --- time -------------------------------------------------------------------------------------


def test_time_spent_down_counts_so_a_room_that_would_have_expired_does_not_come_back() -> None:
    before, mono, wall = _store()
    _busy_room(before)
    saved = _through_json(before.to_dict())
    fresh, _, fresh_wall = _store()
    fresh_wall.now = (
        wall.now + before.ttl + 120
    )  # the server was down longer than a room may sit idle
    assert fresh.restore(saved) == 0
    assert mono.now == 1000.0


def test_a_room_down_for_a_while_keeps_only_the_time_it_has_left() -> None:
    before, _, wall = _store()
    code, ann_token, _ = _busy_room(before)
    saved = _through_json(before.to_dict())
    mono, wall2 = (
        Time(5.0),
        Time(wall.now + before.ttl - 300),
    )  # down for almost the whole allowance
    after, _, _ = _store(mono, wall2)
    assert after.restore(saved) == 1
    mono.now += 200
    assert (
        after.authenticate(code, ann_token)[1].name == "Ann"
    )  # still inside the allowance (and used)
    mono.now += before.ttl + 1  # untouched for a whole allowance: gone
    with pytest.raises(rooms_module.RoomError):
        after.get(code)


def test_using_a_room_inside_the_same_minute_does_not_change_what_would_be_saved() -> None:
    store, mono, wall = _store()
    code, ann_token, _ = _busy_room(store)
    first = json.dumps(store.to_dict(), sort_keys=True)
    mono.now += 10
    wall.now += 10  # ten real seconds pass, inside the same minute
    store.authenticate(code, ann_token)  # a poll
    assert json.dumps(store.to_dict(), sort_keys=True) == first  # so polls do not rewrite the file


# --- a file that is not to be trusted ---------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "x",
        5,
        {},
        {"format": 999, "rooms": []},
        {"format": 1},
        {"format": 1, "rooms": "no"},
    ],
)
def test_a_file_with_the_wrong_shape_restores_nothing(bad: object) -> None:
    store, _, _ = _store()
    assert store.restore(bad) == 0 and len(store) == 0


def test_a_file_in_another_layout_is_left_alone_even_if_it_looks_like_ours() -> None:
    data = _valid()
    data["format"] = 999  # a future (or foreign) layout: its rooms are not guessed at
    store, _, _ = _store()
    assert store.restore(data) == 0


def _valid() -> dict[str, Any]:
    before, _, _ = _store()
    _busy_room(before)
    return _through_json(before.to_dict())  # type: ignore[no-any-return]


def _break(mutate: Any) -> dict[str, Any]:
    data = copy.deepcopy(_valid())
    mutate(data["rooms"][0])
    return data


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(code="abc"),  # not a room code
        lambda r: r.update(code="OOOOOO"),  # a look-alike letter the codes never use
        lambda r: r.update(host_id="nobody"),
        lambda r: r.update(members=[]),
        lambda r: r.update(max_members=1),
        lambda r: r["members"][0].update(token=""),
        lambda r: r["members"][0].update(token=5),
        lambda r: r["members"][0].update(swipes={"cw-1": "love"}),
        lambda r: r["members"][0].update(swipes={"cw-1": "top"}),  # the top pick is its own field
        lambda r: r["members"][0].update(swipes=[1, 2]),
        lambda r: r["members"][0].update(watched="cw-1"),
        lambda r: r["members"][0].update(top=7),
        lambda r: r["members"][0].update(taste={"aspect_weights": {"pacing": "heavy"}}),
        lambda r: r["members"][0].update(
            quiz={"kinds": ["a", "b", "c"], "languages": [], "genres": []}
        ),
        lambda r: r["members"][0].pop("token"),
        lambda r: r.pop("members"),
    ],
)
def test_a_damaged_room_is_skipped_and_never_crashes_the_server(mutate: Any) -> None:
    store, _, _ = _store()
    assert store.restore(_break(mutate)) == 0 and len(store) == 0


def test_one_bad_room_does_not_cost_the_good_ones_beside_it() -> None:
    data = _valid()
    bad = copy.deepcopy(data["rooms"][0])
    bad["code"] = "bad"
    data["rooms"].insert(0, bad)
    store, _, _ = _store()
    assert store.restore(data) == 1


def test_the_saved_swipes_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = _valid()  # built first: the smaller cap would stop the fixture itself
    monkeypatch.setattr(rooms_module, "MAX_SWIPES", 2)
    store, _, _ = _store()
    assert store.restore(saved) == 0  # the saved member has three: more than this server allows


def test_restoring_never_goes_past_the_servers_room_limit() -> None:
    store = RoomStore(clock=Time(1000.0), wall=Time(1_700_000_040.0), max_rooms=1)
    one = _valid()
    one["rooms"].append(copy.deepcopy(one["rooms"][0]) | {"code": "ABCDEF"})
    assert store.restore(one) == 1 and len(store) == 1


# --- the file and the saver -------------------------------------------------------------------


def test_a_missing_garbage_or_oversized_file_reads_as_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rooms.json"
    assert read_state(path) is None
    path.write_text("{not json", encoding="utf-8")
    assert read_state(path) is None
    path.write_text(json.dumps({"format": 1, "rooms": []}), encoding="utf-8")
    monkeypatch.setattr(rooms_module, "MAX_STATE_BYTES", 5)
    assert read_state(path) is None  # larger than anything this server would write


def test_a_write_is_all_or_nothing_and_leaves_no_half_file_behind(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "rooms.json"
    write_state(path, '{"a": 1}')
    write_state(path, '{"a": 2}')
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    assert [p.name for p in path.parent.iterdir()] == ["rooms.json"]


def test_the_saver_writes_when_something_changed_and_not_otherwise(tmp_path: Path) -> None:
    store, _, _ = _store()
    saver = RoomSaver(store, threading.Lock(), tmp_path / "rooms.json")
    assert saver.flush() is True  # the first write, even of an empty store
    assert saver.flush() is False  # nothing changed
    code, ann_token, _ = _busy_room(store)
    assert saver.flush() is True
    store.swipe(code, ann_token, "cw-30", "want")
    assert saver.flush() is True and saver.flush() is False


def test_the_file_holds_only_open_rooms(tmp_path: Path) -> None:
    store, _, _ = _store()
    code, ann_token, _ = _busy_room(store)
    saver = RoomSaver(store, threading.Lock(), tmp_path / "rooms.json")
    saver.flush()
    assert [r["code"] for r in json.loads(saver.path.read_text(encoding="utf-8"))["rooms"]] == [
        code
    ]
    store.close(code, ann_token)
    saver.flush()
    assert (
        json.loads(saver.path.read_text(encoding="utf-8"))["rooms"] == []
    )  # a closed room is gone


def test_a_new_process_reads_back_what_the_old_one_saved(tmp_path: Path) -> None:
    store, _, wall = _store()
    code, ann_token, _ = _busy_room(store)
    path = tmp_path / "rooms.json"
    RoomSaver(store, threading.Lock(), path).flush()
    reborn, _, _ = _store(Time(7.0), Time(wall.now + 30))
    assert RoomSaver(reborn, threading.Lock(), path).load() == 1
    assert reborn.authenticate(code, ann_token)[1].name == "Ann"


def test_a_failed_write_does_not_crash_and_is_retried(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where a folder is needed", encoding="utf-8")
    store, _, _ = _store()
    saver = RoomSaver(store, threading.Lock(), blocker / "rooms.json")
    assert (
        saver.flush() is False
    )  # no exception: the rooms stay in memory and the next tick retries
    blocker.unlink()
    assert saver.flush() is True


def test_the_background_writer_saves_by_itself_and_writes_once_more_on_stop(tmp_path: Path) -> None:
    store, _, _ = _store()
    saver = RoomSaver(store, threading.Lock(), tmp_path / "rooms.json", interval=0.01)
    saver.start()
    code, ann_token, _ = _busy_room(store)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not saver.path.exists():
        time.sleep(0.01)
    assert saver.path.exists()  # written without anyone asking
    store.swipe(code, ann_token, "cw-40", "want")
    saver.stop()  # a clean shutdown loses nothing
    saved = json.loads(saver.path.read_text(encoding="utf-8"))["rooms"][0]["members"][0]
    assert saved["swipes"]["cw-40"] == "want"
