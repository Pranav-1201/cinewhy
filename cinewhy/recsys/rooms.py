"""Temporary rooms where a few people combine their libraries to decide what to watch together.

A room lives in this process's memory. It holds a copy of what each member chose to share, and
nothing else: no account, no database. It disappears when the host closes it, when its last member
leaves, or after `ROOM_TTL_SECONDS` without anyone using it (so a forgotten room does not keep
people's libraries around). A member can leave at any time and their data goes with them.

So that a server restart does not end a room, `RoomSaver` keeps a copy of the open rooms in one JSON
file on the computer that runs the server, written every couple of seconds when something changed
and once more at shutdown, and read back at start. The file holds only OPEN rooms: a room that ends
or expires is gone from the next write, and an empty store writes an empty list. Time spent down
counts as idle time, so a room that would have expired still does. A damaged, oversized or
unknown-format file is ignored (the server starts with no rooms), never a crash.

This module is the store and its rules only (who may join, who may close, when a room expires). The
combining of libraries is `cinewhy.recsys.group`; the HTTP side is in `api.main`, which is where
consent is enforced: a join request is refused unless it says the member agreed to share.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from cinewhy.recsys.group import MAX_GROUP, MIN_GROUP, Member, Quiz
from cinewhy.schemas import TasteProfile

log = logging.getLogger("cinewhy.rooms")

# No 0, O, 1, I or L: a code read aloud or typed from a screenshot is not mistaken for another.
CODE_ALPHABET: Final[str] = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH: Final[int] = 6
ROOM_TTL_SECONDS: Final[int] = 3 * 60 * 60  # idle time after which a room is forgotten
MAX_ROOMS: Final[int] = 200  # a bound on memory: this server holds what it can hold, then says so
HARD_MAX_MEMBERS: Final[int] = (
    20  # the owner's eventual size; the working limit is lower (MAX_GROUP)
)
MAX_NAME_LENGTH: Final[int] = 30
MAX_SWIPES: Final[int] = 5000  # a bound on memory: one person's answers in one room
ACTIONS: Final[frozenset[str]] = frozenset({"want", "pass", "seen", "top"})
STATE_FORMAT: Final[int] = (
    1  # the saved file's layout; a different number is ignored, not guessed at
)
MAX_STATE_BYTES: Final[int] = 64 * 1024 * 1024  # a larger file is not ours: left unread
_CODE = re.compile(f"[{CODE_ALPHABET}]{{{CODE_LENGTH}}}")
_STAMP_SECONDS: Final[int] = (
    60  # last-used time is saved to the minute so idle rooms do not rewrite
)


class RoomError(Exception):
    """A room request that cannot be done. `kind` is one of not_found, full, forbidden, busy."""

    def __init__(self, kind: str) -> None:
        """Remember what kind of refusal this is."""
        super().__init__(kind)
        self.kind = kind


@dataclass
class RoomMember:
    """One person in a room: who they are in it, their secret, and the library they shared."""

    member_id: str
    name: str
    token: str
    member: Member
    # What this person did INSIDE the room. It never leaves the room and never touches their own
    # profile: `swipes` maps a title to "want", "pass" or "seen"; `top` is the one title they put
    # above all others and `former_tops` the ones it replaced (they keep a smaller bonus).
    quiz: Quiz | None = None
    swipes: dict[str, str] = field(default_factory=dict)
    top: str | None = None
    former_tops: list[str] = field(default_factory=list)

    @property
    def answers(self) -> int:
        """Titles this member has answered: swipes, the top pick, and the top picks it replaced."""
        return len(self.swipes) + len(self.former_tops) + (1 if self.top else 0)


@dataclass
class Room:
    """A room: its code, its members in join order, and a version that changes when they do."""

    code: str
    max_members: int
    touched: float
    members: dict[str, RoomMember] = field(default_factory=dict)
    host_id: str | None = None
    version: int = 0  # changes when the membership does
    activity: int = (
        0  # changes with every quiz answer and swipe, so a results screen knows it is stale
    )


def normalise_code(text: str) -> str:
    """A room code as typed: upper case, without spaces or dashes."""
    return re.sub(r"[\s-]+", "", text).upper()


def clean_name(name: str) -> str:
    """A display name: spaces collapsed, cut to length, and never empty."""
    cleaned = " ".join(name.split())[:MAX_NAME_LENGTH].strip()
    return cleaned or "Friend"


class RoomStore:
    """All the rooms this process holds.

    Not thread-safe by itself: the app runs one worker and its handlers do not yield between
    reading a room and changing it.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        max_rooms: int = MAX_ROOMS,
        ttl: float = ROOM_TTL_SECONDS,
        max_members: int = MAX_GROUP,
    ) -> None:
        """A store with clocks (so tests can move time) and caps on rooms, idle time and size.

        `clock` measures idle time inside this process; `wall` is calendar time, used only to carry
        a room's last use across a restart.
        """
        self._clock = clock
        self._wall = wall
        self._rooms: dict[str, Room] = {}
        self.max_rooms = max_rooms
        self.ttl = ttl
        self.max_members = max(MIN_GROUP, min(max_members, HARD_MAX_MEMBERS))

    def __len__(self) -> int:
        """How many rooms are open right now."""
        self.purge()
        return len(self._rooms)

    def purge(self) -> None:
        """Forget every room nobody has used for `ttl` seconds."""
        now = self._clock()
        for code in [c for c, r in self._rooms.items() if now - r.touched > self.ttl]:
            del self._rooms[code]

    def create(self, max_members: int | None = None) -> Room:
        """A new, empty room; `RoomError("busy")` when the server holds as many as it will."""
        self.purge()
        if len(self._rooms) >= self.max_rooms:
            raise RoomError("busy")
        size = self.max_members if max_members is None else max_members
        room = Room(
            code=self._new_code(),
            max_members=max(MIN_GROUP, min(size, self.max_members)),
            touched=self._clock(),
        )
        self._rooms[room.code] = room
        return room

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._rooms:
                return code

    def get(self, code: str) -> Room:
        """The room with this code; `RoomError("not_found")` for an unknown or expired one."""
        self.purge()
        room = self._rooms.get(normalise_code(code))
        if room is None:
            raise RoomError("not_found")
        return room

    def join(self, code: str, name: str, member: Member) -> RoomMember:
        """Add a member who has agreed to share. The first to join is the host."""
        room = self.get(code)
        if len(room.members) >= room.max_members:
            raise RoomError("full")
        taken = {m.name for m in room.members.values()}
        base = clean_name(name)
        display, n = base, 2
        while display in taken:  # two Anns in one room stay tellable apart
            display, n = f"{base} ({n})", n + 1
        member_id = secrets.token_hex(4)
        entry = RoomMember(member_id, display, secrets.token_urlsafe(16), member)
        room.members[member_id] = entry
        room.host_id = room.host_id or member_id
        room.version += 1
        room.touched = self._clock()
        return entry

    def authenticate(self, code: str, token: str) -> tuple[Room, RoomMember]:
        """The room and the member this secret belongs to; anything else is `not_found`.

        Both an unknown room and a wrong secret give the same answer, so a guess about a room code
        learns nothing about whether the room exists.
        """
        room = self.get(code)
        for entry in room.members.values():
            if hmac.compare_digest(entry.token, token):
                room.touched = self._clock()
                return room, entry
        raise RoomError("not_found")

    def leave(self, code: str, token: str) -> None:
        """Remove a member and everything they shared.

        An emptied room is deleted; if the host leaves, the longest-standing member becomes host.
        """
        room, entry = self.authenticate(code, token)
        del room.members[entry.member_id]
        room.version += 1
        if not room.members:
            del self._rooms[room.code]
        elif room.host_id == entry.member_id:
            room.host_id = next(iter(room.members))

    def close(self, code: str, token: str) -> None:
        """End a room for everyone. Only the host may."""
        room, entry = self.authenticate(code, token)
        if entry.member_id != room.host_id:
            raise RoomError("forbidden")
        del self._rooms[room.code]

    def set_quiz(self, code: str, token: str, quiz: Quiz) -> RoomMember:
        """Record what this member feels like watching tonight (empty means no preference)."""
        room, entry = self.authenticate(code, token)
        entry.quiz = quiz
        room.activity += 1
        return entry

    def swipe(
        self, code: str, token: str, movie_id: str, action: str, *, replace: bool = False
    ) -> RoomMember:
        """Record one swipe: "want", "pass", "seen" or "top".

        A member has ONE top pick. Naming a different title while they already have one is refused
        with `RoomError("top_exists")` unless `replace` is true (the page asks first); the replaced
        title keeps a smaller bonus as a former top pick. Swiping the current top pick any other way
        takes it off the top slot.
        """
        if action not in ACTIONS:
            raise RoomError("bad_action")
        room, entry = self.authenticate(code, token)
        is_new = movie_id not in entry.swipes and movie_id != entry.top
        if is_new and len(entry.swipes) >= MAX_SWIPES:
            raise RoomError("full")
        if action == "top":
            if entry.top == movie_id:
                return entry
            if entry.top is not None:
                if not replace:
                    raise RoomError("top_exists")
                if entry.top not in entry.former_tops:
                    entry.former_tops.append(entry.top)
            entry.top = movie_id
            entry.swipes.pop(movie_id, None)
        else:
            if entry.top == movie_id:
                entry.top = None
            entry.swipes[movie_id] = action
        if movie_id in entry.former_tops:
            entry.former_tops.remove(movie_id)  # a title swiped again is no longer "former"
        room.activity += 1
        return entry

    # --- carrying open rooms across a restart --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Every open room as plain data (the saved file's contents); expired rooms are left out."""
        self.purge()
        now_clock, now_wall = self._clock(), self._wall()
        rooms = []
        for room in self._rooms.values():
            last_used = now_wall - (now_clock - room.touched)
            rooms.append(
                {
                    "code": room.code,
                    "max_members": room.max_members,
                    "host_id": room.host_id,
                    "version": room.version,
                    "activity": room.activity,
                    "last_used": int(last_used // _STAMP_SECONDS * _STAMP_SECONDS),
                    "members": [_entry_to_dict(e) for e in room.members.values()],
                }
            )
        return {"format": STATE_FORMAT, "rooms": rooms}

    def restore(self, data: object) -> int:
        """Load rooms written by `to_dict`; returns how many were restored.

        Anything malformed is skipped rather than trusted: a wrong layout restores nothing, a bad
        room is dropped and the rest kept. Time spent down counts as idle time, so a room unused
        for longer than `ttl` by now is not brought back.
        """
        if not isinstance(data, dict) or data.get("format") != STATE_FORMAT:
            return 0
        rooms = data.get("rooms")
        if not isinstance(rooms, list):
            return 0
        now_clock, now_wall = self._clock(), self._wall()
        restored = 0
        for raw in rooms:
            if len(self._rooms) >= self.max_rooms:
                break
            try:
                room = _room_from_dict(raw, self.max_members, now_clock, now_wall)
            except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
                log.warning("skipped a saved room that could not be read")
                continue
            if now_clock - room.touched > self.ttl or room.code in self._rooms:
                continue
            self._rooms[room.code] = room
            restored += 1
        return restored

    @staticmethod
    def seen_by(entry: RoomMember) -> frozenset[str]:
        """Every title this member should not be shown again in their own deck."""
        library = entry.member.taste
        mine = {*entry.swipes, *entry.former_tops, *library.liked_movie_ids}
        mine |= {*library.disliked_movie_ids, *entry.member.watched}
        if entry.top:
            mine.add(entry.top)
        return frozenset(mine)

    @staticmethod
    def members_of(room: Room) -> list[Member]:
        """The members as the group engine sees them: shared library plus what they did here.

        Right swipes become wants and similarity seeds, left swipes dislikes, "already watched"
        swipes watched titles; the top pick and the ones it replaced carry their own bonuses. The
        quiz replaces the old language and kind filters (it weights, it does not exclude).
        """
        out: list[Member] = []
        for e in room.members.values():
            by = e.swipes
            wanted = tuple(m for m, a in by.items() if a == "want")
            top = (e.top,) if e.top else ()
            out.append(
                Member(
                    e.name,
                    e.member.taste,
                    watched=e.member.watched | {m for m, a in by.items() if a == "seen"},
                    want=e.member.want | frozenset(wanted),
                    quiz=e.quiz or Quiz(),
                    signals_liked=(*wanted, *top, *e.former_tops),
                    passed=frozenset(m for m, a in by.items() if a == "pass"),
                    top=e.top,
                    former_tops=frozenset(e.former_tops),
                )
            )
        return out


# --- saving and reading the open rooms ------------------------------------------------------------


def _entry_to_dict(entry: RoomMember) -> dict[str, Any]:
    quiz = entry.quiz
    return {
        "member_id": entry.member_id,
        "name": entry.name,
        "token": entry.token,
        "taste": entry.member.taste.model_dump(mode="json"),
        "watched": sorted(entry.member.watched),
        "want": sorted(entry.member.want),
        "quiz": None
        if quiz is None
        else {
            "kinds": list(quiz.kinds),
            "languages": list(quiz.languages),
            "genres": list(quiz.genres),
        },
        "swipes": dict(entry.swipes),
        "top": entry.top,
        "former_tops": list(entry.former_tops),
    }


def _strings(value: object, limit: int) -> list[str]:
    """A list of at most `limit` strings, or a ValueError (the saved file is not trusted)."""
    if (
        not isinstance(value, list)
        or len(value) > limit
        or not all(isinstance(v, str) for v in value)
    ):
        raise ValueError("expected a list of strings")
    return value


def _entry_from_dict(raw: dict[str, Any]) -> RoomMember:
    taste = TasteProfile.model_validate(raw["taste"])
    member = Member(
        str(raw["name"]),
        taste,
        frozenset(_strings(raw["watched"], 50_000)),
        frozenset(_strings(raw["want"], 50_000)),
    )
    quiz = raw["quiz"]
    swipes = raw["swipes"]
    if not isinstance(swipes, dict) or len(swipes) > MAX_SWIPES:
        raise ValueError("bad swipes")
    if not all(isinstance(k, str) and v in ACTIONS - {"top"} for k, v in swipes.items()):
        raise ValueError("bad swipe")
    top = raw["top"]
    if top is not None and not isinstance(top, str):
        raise ValueError("bad top pick")
    token = raw["token"]
    if not isinstance(token, str) or not token:
        raise ValueError("bad secret")
    return RoomMember(
        member_id=str(raw["member_id"]),
        name=str(raw["name"])[:MAX_NAME_LENGTH],
        token=token,
        member=member,
        quiz=None
        if quiz is None
        else Quiz(
            tuple(_strings(quiz["kinds"], 2)),
            tuple(_strings(quiz["languages"], 4)),
            tuple(_strings(quiz["genres"], 10)),
        ),
        swipes=dict(swipes),
        top=top,
        former_tops=_strings(raw["former_tops"], MAX_SWIPES),
    )


def _room_from_dict(raw: object, size_cap: int, now_clock: float, now_wall: float) -> Room:
    if not isinstance(raw, dict):
        raise TypeError("a room is a mapping")
    code = raw["code"]
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise ValueError("bad room code")
    members = {}
    for entry_raw in raw["members"]:
        entry = _entry_from_dict(entry_raw)
        members[entry.member_id] = entry
    size = int(raw["max_members"])
    if (
        not members
        or len(members) > size
        or not MIN_GROUP <= size <= max(size_cap, HARD_MAX_MEMBERS)
    ):
        raise ValueError("bad room size")
    host = raw["host_id"]
    if host not in members:
        raise ValueError("the host is not a member")
    idle = max(0.0, now_wall - float(raw["last_used"]))  # includes the time the server was down
    return Room(
        code=code,
        max_members=size,
        touched=now_clock - idle,
        members=members,
        host_id=host,
        version=int(raw["version"]),
        activity=int(raw["activity"]),
    )


def read_state(path: Path) -> object | None:
    """The saved file's contents, or None when it is missing, too large or not JSON."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
            return None
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    except (OSError, ValueError):
        log.warning("the saved rooms file could not be read; starting with no rooms")
        return None


def write_state(path: Path, text: str) -> None:
    """Write `text` to `path` in one step: a reader sees the old file or the new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)


class RoomSaver:
    """Keeps a file copy of a `RoomStore`: load at start, write when changed, write at shutdown.

    `lock` is the lock every route holds while it touches the store; the file is written outside it.
    """

    def __init__(
        self,
        store: RoomStore,
        lock: AbstractContextManager[Any],
        path: Path,
        *,
        interval: float = 2.0,
    ) -> None:
        """Watch `store` and keep `path` in step with it every `interval` seconds."""
        self._store, self._lock, self.path, self._interval = store, lock, path, interval
        self._last: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def load(self) -> int:
        """Bring back the rooms in the file; returns how many."""
        data = read_state(self.path)
        with self._lock:
            return self._store.restore(data)

    def flush(self) -> bool:
        """Write the open rooms if they changed since the last write; True when a write happened."""
        with self._lock:
            text = json.dumps(self._store.to_dict(), separators=(",", ":"), sort_keys=True)
        if text == self._last:
            return False
        try:
            write_state(self.path, text)
        except OSError:
            log.warning("could not save the open rooms to %s; will try again", self.path)
            return False
        self._last = text
        return True

    def start(self) -> None:
        """Begin writing in the background."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="room-saver", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.flush()

    def stop(self) -> None:
        """Stop the background writer and write once more, so a clean shutdown loses nothing."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.flush()
