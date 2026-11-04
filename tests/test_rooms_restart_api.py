"""A server restart does not end a room: two app instances, one shared rooms file (D-047).

"Restart" here is the real thing at the app level: the first app shuts down (which writes the file
once more) and a second one starts and reads it. People keep their secrets, their answers and their
top pick; rooms that were closed or left are not brought back; a damaged file starts empty.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.recsys.rooms import RoomSaver


@contextmanager
def _server(artifact_dir: Path, rooms_file: Path | None) -> Iterator[TestClient]:
    with TestClient(api_main.create_app(artifact_dir, rooms_file=rooms_file)) as client:
        yield client
    api_main._state = None


def _join(client: TestClient, code: str, name: str) -> dict[str, Any]:
    body = {"name": name, "consent": True, "profile": {"liked_movie_ids": []}}
    response = client.post(f"/rooms/{code}/join", json=body)
    assert response.status_code == 200, response.text
    return dict(response.json())


def _auth(joined: dict[str, Any]) -> dict[str, str]:
    return {"X-Room-Token": joined["token"]}


def _room_with_two(client: TestClient) -> tuple[str, dict[str, Any], dict[str, Any]]:
    code = client.post("/rooms", json={}).json()["code"]
    return code, _join(client, code, "Ann"), _join(client, code, "Ben")


def _swipe(client: TestClient, code: str, who: dict[str, Any], movie: str, action: str) -> Any:
    body = {"movie_id": movie, "action": action}
    return client.post(f"/rooms/{code}/swipe", json=body, headers=_auth(who))


def test_a_room_and_everything_in_it_survives_a_restart(artifact_dir: Path, tmp_path: Path) -> None:
    saved = tmp_path / "rooms.json"
    with _server(artifact_dir, saved) as before:
        code, ann, ben = _room_with_two(before)
        before.post(f"/rooms/{code}/quiz", json={"genres": ["Drama"]}, headers=_auth(ann))
        _swipe(before, code, ann, "cw-5", "top")
        _swipe(before, code, ben, "cw-6", "want")

    with _server(artifact_dir, saved) as after:  # the server was restarted
        seen_by_ann = after.get(f"/rooms/{code}", headers=_auth(ann))
        assert seen_by_ann.status_code == 200  # her secret still works: she was not logged out
        members = {m["name"]: m for m in seen_by_ann.json()["members"]}
        assert set(members) == {"Ann", "Ben"} and members["Ann"]["is_host"] is True
        assert members["Ann"]["quiz_done"] and members["Ann"]["has_top"]
        assert members["Ann"]["swipe_count"] == 1
        assert members["Ben"]["swipe_count"] == 1 and not members["Ben"]["quiz_done"]
        assert after.get(f"/rooms/{code}", headers=_auth(ben)).status_code == 200

        # Ann's top pick is still her top pick: naming another still has to be confirmed.
        again = _swipe(after, code, ann, "cw-6", "top")
        assert again.status_code == 409 and again.json()["detail"] == "top_exists"
        results = after.post(f"/rooms/{code}/results", headers=_auth(ann)).json()
        cards = results["top"] + results["close"]
        mine = next(c for c in cards if c["card"]["movie"]["movie_id"] == "cw-5")
        assert next(m for m in mine["members"] if m["name"] == "Ann")["top"] is True


def test_a_closed_room_is_not_brought_back(artifact_dir: Path, tmp_path: Path) -> None:
    saved = tmp_path / "rooms.json"
    with _server(artifact_dir, saved) as before:
        code, ann, _ = _room_with_two(before)
        assert before.post(f"/rooms/{code}/close", headers=_auth(ann)).status_code == 200
    assert json.loads(saved.read_text(encoding="utf-8"))["rooms"] == []  # nothing of it is on disk
    with _server(artifact_dir, saved) as after:
        assert after.get(f"/rooms/{code}", headers=_auth(ann)).status_code == 404


def test_a_member_who_left_before_the_restart_stays_gone(
    artifact_dir: Path, tmp_path: Path
) -> None:
    saved = tmp_path / "rooms.json"
    with _server(artifact_dir, saved) as before:
        code, ann, ben = _room_with_two(before)
        before.post(f"/rooms/{code}/leave", headers=_auth(ben))
    text = saved.read_text(encoding="utf-8")
    assert ben["token"] not in text and ann["token"] in text  # Ben's secret and data left the file
    with _server(artifact_dir, saved) as after:
        assert after.get(f"/rooms/{code}", headers=_auth(ben)).status_code == 404
        assert after.get(f"/rooms/{code}", headers=_auth(ann)).status_code == 200


def test_the_file_is_written_while_the_server_runs_not_only_at_the_end(
    artifact_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = tmp_path / "rooms.json"

    def quick(*args: Any, **kwargs: Any) -> RoomSaver:
        return RoomSaver(*args, interval=0.02, **kwargs)

    monkeypatch.setattr("api.main.RoomSaver", quick)
    with _server(artifact_dir, saved) as live:
        code, _, _ = _room_with_two(live)
        for _ in range(250):  # up to five seconds for the background writer
            if saved.exists() and code in saved.read_text(encoding="utf-8"):
                break
            time.sleep(0.02)
        assert code in saved.read_text(encoding="utf-8")  # a crash now would still keep the room


def test_without_a_rooms_file_nothing_is_written(artifact_dir: Path, tmp_path: Path) -> None:
    before = sorted(p.name for p in tmp_path.iterdir())  # the artifacts live here too
    with _server(artifact_dir, None) as client:
        _room_with_two(client)
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # no rooms file appeared


def test_a_damaged_rooms_file_starts_the_server_with_no_rooms_instead_of_failing(
    artifact_dir: Path, tmp_path: Path
) -> None:
    saved = tmp_path / "rooms.json"
    saved.write_text('{"format": 1, "rooms": [{"code": "ABCDEF"', encoding="utf-8")  # cut off
    with _server(artifact_dir, saved) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/rooms/ABCDEF", headers={"X-Room-Token": "x"}).status_code == 404
        _room_with_two(client)  # and rooms work as normal
    assert json.loads(saved.read_text(encoding="utf-8"))["rooms"]  # then the file is good again


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        (None, Path("Data") / "rooms.json"),
        ("somewhere/else.json", Path("somewhere/else.json")),
        ("off", None),
        ("OFF", None),
        ("none", None),
        ("", None),
        ("   ", None),
    ],
)
def test_where_the_rooms_are_kept_can_be_chosen_or_switched_off(
    monkeypatch: pytest.MonkeyPatch, setting: str | None, expected: Path | None
) -> None:
    if setting is None:
        monkeypatch.delenv("CINEWHY_ROOMS_FILE", raising=False)
    else:
        monkeypatch.setenv("CINEWHY_ROOMS_FILE", setting)
    assert api_main.default_rooms_file() == expected
