"""The room routes: consent at the door, secrets, size, and the combined list over HTTP.

Runs on the six-film fixture (`conftest.artifact_dir`), so it checks wiring and policy. The
combining rules themselves are `test_group.py`; the store's rules are `test_rooms.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api.main as api_main


@pytest.fixture
def client(artifact_dir: Path) -> Iterator[TestClient]:
    with TestClient(api_main.create_app(artifact_dir)) as test_client:
        yield test_client
    api_main._state = None


def _library(name: str, liked: list[str], watched: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "consent": True,
        "profile": {"liked_movie_ids": liked},
        "watched_movie_ids": watched or [],
    }


def _open(client: TestClient, size: int | None = None) -> str:
    body = {} if size is None else {"max_members": size}
    return str(client.post("/rooms", json=body).json()["code"])


def _join(client: TestClient, code: str, library: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"/rooms/{code}/join", json=library)
    assert response.status_code == 200, response.text
    return dict(response.json())


def _auth(joined: dict[str, Any]) -> dict[str, str]:
    return {"X-Room-Token": joined["token"]}


# --- opening and joining --------------------------------------------------------------------


def test_a_new_room_has_a_code_and_the_default_size(client: TestClient) -> None:
    body = client.post("/rooms", json={}).json()
    assert len(body["code"]) == 6 and body["max_members"] == 5


def test_joining_without_saying_you_agree_is_refused_and_nothing_is_stored(
    client: TestClient,
) -> None:
    code = _open(client)
    library = _library("Ann", ["cw-1"])
    del library["consent"]
    assert client.post(f"/rooms/{code}/join", json=library).status_code == 400
    library["consent"] = False
    refused = client.post(f"/rooms/{code}/join", json=library)
    assert refused.status_code == 400 and refused.json()["detail"] == "consent required"
    first = _join(client, code, _library("Ann", ["cw-1"]))
    assert len(first["room"]["members"]) == 1  # the refused attempts left no trace


def test_the_first_to_join_is_the_host_and_sees_who_is_in_the_room(client: TestClient) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", ["cw-1"]))
    ben = _join(client, code, _library("Ben", ["cw-2"], ["cw-3"]))
    seen_by_ann = client.get(f"/rooms/{code}", headers=_auth(ann)).json()
    assert [m["name"] for m in seen_by_ann["members"]] == ["Ann", "Ben"]
    assert [m["is_host"] for m in seen_by_ann["members"]] == [True, False]
    assert [m["is_you"] for m in seen_by_ann["members"]] == [True, False]
    assert seen_by_ann["members"][1]["liked_movie_ids"] == [
        "cw-2"
    ]  # friends see each other's likes
    assert seen_by_ann["members"][1]["watched_count"] == 1
    assert seen_by_ann["version"] == ben["room"]["version"]


def test_a_members_secret_is_never_in_what_others_see(client: TestClient) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", []))
    ben = _join(client, code, _library("Ben", []))
    shown = client.get(f"/rooms/{code}", headers=_auth(ann)).text
    assert ben["token"] not in shown and ann["token"] not in shown


def test_a_full_room_answers_conflict(client: TestClient) -> None:
    code = _open(client, size=2)
    _join(client, code, _library("Ann", []))
    _join(client, code, _library("Ben", []))
    full = client.post(f"/rooms/{code}/join", json=_library("Cy", []))
    assert full.status_code == 409 and full.json()["detail"] == "full"


def test_a_requested_size_above_the_working_limit_is_clamped(client: TestClient) -> None:
    assert client.post("/rooms", json={"max_members": 20}).json()["max_members"] == 5


def test_a_room_code_that_does_not_exist_is_not_found(client: TestClient) -> None:
    assert client.post("/rooms/ZZZZZZ/join", json=_library("Ann", [])).status_code == 404


# --- who may look ---------------------------------------------------------------------------


def test_without_the_right_secret_a_room_cannot_be_read_or_used(client: TestClient) -> None:
    code = _open(client)
    _join(client, code, _library("Ann", []))
    for headers in ({}, {"X-Room-Token": "guess"}):
        assert client.get(f"/rooms/{code}", headers=headers).status_code == 404
        assert client.post(f"/rooms/{code}/recommend", json={}, headers=headers).status_code == 404
        assert client.post(f"/rooms/{code}/leave", headers=headers).status_code == 404


# --- the combined list ----------------------------------------------------------------------


def test_one_person_alone_cannot_ask_for_a_group_list(client: TestClient) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", ["cw-1"]))
    response = client.post(f"/rooms/{code}/recommend", json={}, headers=_auth(ann))
    assert response.status_code == 409 and response.json()["detail"] == "need_more_people"


def test_a_pair_never_gets_what_either_has_watched(client: TestClient) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", ["cw-1"], ["cw-1", "cw-2"]))
    _join(client, code, _library("Ben", ["cw-3"], ["cw-3", "cw-4"]))
    body = client.post(f"/rooms/{code}/recommend", json={"limit": 10}, headers=_auth(ann)).json()
    shown = {i["item"]["movie"]["movie_id"] for i in body["items"]}
    assert not shown & {"cw-1", "cw-2", "cw-3", "cw-4"}
    assert body["members"] == 2 and body["majority"] == 1


def test_every_member_stands_in_every_title_of_the_list(client: TestClient) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", ["cw-1"]))
    _join(client, code, _library("Ben", ["cw-2"]))
    body = client.post(f"/rooms/{code}/recommend", json={}, headers=_auth(ann)).json()
    assert body["items"]
    assert all([m["name"] for m in i["members"]] == ["Ann", "Ben"] for i in body["items"])


def test_titles_already_shown_are_left_out_of_the_next_list(client: TestClient) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", ["cw-1"]))
    _join(client, code, _library("Ben", ["cw-2"]))
    first = client.post(f"/rooms/{code}/recommend", json={"limit": 1}, headers=_auth(ann)).json()
    top = first["items"][0]["item"]["movie"]["movie_id"]
    again = client.post(
        f"/rooms/{code}/recommend",
        json={"limit": 10, "exclude_movie_ids": [top]},
        headers=_auth(ann),
    ).json()
    assert top not in {i["item"]["movie"]["movie_id"] for i in again["items"]}


# --- leaving and closing --------------------------------------------------------------------


def test_leaving_removes_you_and_your_secret_stops_working(client: TestClient) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", []))
    ben = _join(client, code, _library("Ben", ["cw-2"]))
    assert client.post(f"/rooms/{code}/leave", headers=_auth(ben)).json() == {"status": "left"}
    assert client.get(f"/rooms/{code}", headers=_auth(ben)).status_code == 404
    remaining = client.get(f"/rooms/{code}", headers=_auth(ann)).json()["members"]
    assert [m["name"] for m in remaining] == ["Ann"]


def test_only_the_host_can_close_and_closing_ends_the_room_for_everyone(
    client: TestClient,
) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", []))
    ben = _join(client, code, _library("Ben", []))
    assert client.post(f"/rooms/{code}/close", headers=_auth(ben)).status_code == 403
    assert client.post(f"/rooms/{code}/close", headers=_auth(ann)).json() == {"status": "closed"}
    for person in (ann, ben):
        assert client.get(f"/rooms/{code}", headers=_auth(person)).status_code == 404


def test_each_app_has_its_own_rooms(artifact_dir: Path) -> None:
    with TestClient(api_main.create_app(artifact_dir)) as one:
        code = _open(one)
        with TestClient(api_main.create_app(artifact_dir)) as two:
            assert two.post(f"/rooms/{code}/join", json=_library("Ann", [])).status_code == 404
    api_main._state = None
