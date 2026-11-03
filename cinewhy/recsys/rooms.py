"""Temporary rooms where a few people combine their libraries to decide what to watch together.

A room lives only in this process's memory. It holds a copy of what each member chose to share, and
nothing else: no account, no database, no file. It disappears when the host closes it, when its last
member leaves, or after `ROOM_TTL_SECONDS` without anyone using it (so a forgotten room does not
keep people's libraries in memory). A member can leave at any time and their data goes with them.

This module is the store and its rules only (who may join, who may close, when a room expires). The
combining of libraries is `cinewhy.recsys.group`; the HTTP side is in `api.main`, which is where
consent is enforced: a join request is refused unless it says the member agreed to share.
"""

from __future__ import annotations

import hmac
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from cinewhy.recsys.group import MAX_GROUP, MIN_GROUP, Member

# No 0, O, 1, I or L: a code read aloud or typed from a screenshot is not mistaken for another.
CODE_ALPHABET: Final[str] = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH: Final[int] = 6
ROOM_TTL_SECONDS: Final[int] = 3 * 60 * 60  # idle time after which a room is forgotten
MAX_ROOMS: Final[int] = 200  # a bound on memory: this server holds what it can hold, then says so
HARD_MAX_MEMBERS: Final[int] = (
    20  # the owner's eventual size; the working limit is lower (MAX_GROUP)
)
MAX_NAME_LENGTH: Final[int] = 30


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


@dataclass
class Room:
    """A room: its code, its members in join order, and a version that changes when they do."""

    code: str
    max_members: int
    touched: float
    members: dict[str, RoomMember] = field(default_factory=dict)
    host_id: str | None = None
    version: int = 0


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
        max_rooms: int = MAX_ROOMS,
        ttl: float = ROOM_TTL_SECONDS,
        max_members: int = MAX_GROUP,
    ) -> None:
        """A store with a clock (so tests can move time) and caps on rooms, idle time and size."""
        self._clock = clock
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

    @staticmethod
    def members_of(room: Room) -> list[Member]:
        """The shared libraries in join order, under the display names the room gave them."""
        return [
            Member(
                e.name,
                e.member.taste,
                e.member.watched,
                e.member.want,
                e.member.languages,
                e.member.kinds,
            )
            for e in room.members.values()
        ]
