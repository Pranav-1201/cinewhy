"""The room routes: consent at the door, secrets, size, and the combined list over HTTP.

Runs on the six-film fixture (`conftest.artifact_dir`), so it checks wiring and policy. The
combining rules themselves are `test_group.py`; the store's rules are `test_rooms.py`.
"""

from __future__ import annotations

import json
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
        assert client.post(f"/rooms/{code}/results", headers=headers).status_code == 404
        assert client.post(f"/rooms/{code}/leave", headers=headers).status_code == 404


# --- quiz, swipes, deck and results ----------------------------------------------------------


def _act(client: TestClient, code: str, who: dict[str, Any], suffix: str, **body: Any) -> Any:
    return client.post(f"/rooms/{code}/{suffix}", json=body, headers=_auth(who))


def _pair(
    client: TestClient, *, watched: bool = False
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Two people in a room; with `watched`, Ann has seen cw-1 and cw-2 and Ben cw-3 and cw-4."""
    code = _open(client)
    ann = _join(client, code, _library("Ann", [], ["cw-1", "cw-2"] if watched else None))
    ben = _join(client, code, _library("Ben", [], ["cw-3", "cw-4"] if watched else None))
    return code, ann, ben


def _ids_of(cards: list[dict[str, Any]]) -> list[str]:
    return [c["movie"]["movie_id"] for c in cards]


def test_a_pair_never_gets_what_either_has_watched(client: TestClient) -> None:
    code, ann, _ = _pair(client, watched=True)
    body = _act(client, code, ann, "results").json()
    shown = {c["card"]["movie"]["movie_id"] for c in body["top"] + body["close"]}
    assert shown and not shown & {"cw-1", "cw-2", "cw-3", "cw-4"}
    assert body["members"] == 2


def test_results_show_where_each_member_stands_and_whose_top_pick_a_title_is(
    client: TestClient,
) -> None:
    code, ann, ben = _pair(client)
    assert _act(client, code, ann, "swipe", movie_id="cw-6", action="top").status_code == 200
    _act(client, code, ben, "swipe", movie_id="cw-6", action="want")
    cards = (lambda b: b["top"] + b["close"])(_act(client, code, ann, "results").json())
    card = next(c for c in cards if c["card"]["movie"]["movie_id"] == "cw-6")
    stands = {m["name"]: m for m in card["members"]}
    assert stands["Ann"]["top"] is True and stands["Ben"]["wants"] is True
    assert [m["name"] for m in card["members"]] == ["Ann", "Ben"]


def test_results_work_for_one_person_alone_and_name_only_them(client: TestClient) -> None:
    code = _open(client)
    ann = _join(client, code, _library("Ann", ["cw-1"]))
    body = _act(client, code, ann, "results").json()
    assert body["members"] == 1
    assert body["top"] and all([m["name"] for m in c["members"]] == ["Ann"] for c in body["top"])


def test_the_deck_leaves_out_what_the_member_already_answered_and_what_their_page_holds(
    client: TestClient,
) -> None:
    code, ann, _ = _pair(client)
    cards = _ids_of(_act(client, code, ann, "deck", count=10).json()["cards"])
    assert len(cards) >= 3
    _act(client, code, ann, "swipe", movie_id=cards[0], action="pass")
    again = _ids_of(
        _act(client, code, ann, "deck", count=10, held_movie_ids=[cards[1]]).json()["cards"]
    )
    assert cards[0] not in again and cards[1] not in again


def test_the_deck_never_deals_back_what_is_in_a_members_own_library(client: TestClient) -> None:
    code, ann, _ = _pair(client, watched=True)
    cards = _ids_of(_act(client, code, ann, "deck", count=10).json()["cards"])
    assert cards and not set(cards) & {"cw-1", "cw-2", "cw-3", "cw-4"}  # watched: never dealt back


def test_a_deck_card_carries_what_a_card_shows(client: TestClient) -> None:
    code, ann, _ = _pair(client)
    card = _act(client, code, ann, "deck", count=1).json()["cards"][0]
    assert {
        "movie",
        "language",
        "overview",
        "runtime_minutes",
        "imdb_rating",
        "mean_rating",
    } <= set(card)
    assert {"rating_count", "cast", "where_to_watch", "because", "ratings_only"} <= set(card)


def test_the_top_pick_asks_before_it_is_replaced(client: TestClient) -> None:
    code, ann, _ = _pair(client)
    first = _act(client, code, ann, "swipe", movie_id="cw-5", action="top")
    assert first.json() == {"swipe_count": 1, "top": "cw-5"}
    refused = _act(client, code, ann, "swipe", movie_id="cw-6", action="top")
    assert refused.status_code == 409 and refused.json()["detail"] == "top_exists"
    replaced = _act(client, code, ann, "swipe", movie_id="cw-6", action="top", replace=True)
    # Two titles were answered, so the count is 2 even though only one is the top pick now.
    assert replaced.json() == {"swipe_count": 2, "top": "cw-6"}


def test_a_swipe_on_an_unknown_title_or_with_a_bad_action_is_refused(client: TestClient) -> None:
    code, ann, _ = _pair(client)
    assert _act(client, code, ann, "swipe", movie_id="cw-nope", action="want").status_code == 404
    assert _act(client, code, ann, "swipe", movie_id="cw-5", action="love").status_code == 422


def test_the_quiz_and_swipe_counts_are_visible_as_progress_but_never_the_swipes(
    client: TestClient,
) -> None:
    code, ann, ben = _pair(client)
    _act(client, code, ann, "quiz", genres=["Drama"], languages=["en"])
    _act(client, code, ann, "swipe", movie_id="cw-5", action="want")
    seen_by_ben = client.get(f"/rooms/{code}", headers=_auth(ben)).json()
    ann_row = next(m for m in seen_by_ben["members"] if m["name"] == "Ann")
    assert (
        ann_row["quiz_done"] is True and ann_row["swipe_count"] == 1 and ann_row["has_top"] is False
    )
    assert "swipes" not in ann_row and "cw-5" not in json.dumps(
        ann_row
    )  # what she chose stays hers


def test_a_quiz_with_an_unknown_language_or_too_many_genres_is_refused(client: TestClient) -> None:
    code, ann, _ = _pair(client)
    assert _act(client, code, ann, "quiz", languages=["xx"]).status_code == 422
    assert _act(client, code, ann, "quiz", genres=["g"] * 11).status_code == 422


def test_swipes_are_limited_per_person_and_do_not_use_up_the_whole_address(
    client: TestClient,
) -> None:
    code, ann, ben = _pair(client)
    codes = [
        _act(client, code, ann, "swipe", movie_id="cw-5", action="want").status_code
        for _ in range(245)
    ]
    assert codes[:240] == [200] * 240 and set(codes[240:]) == {429}  # Ann's own limit
    assert _act(client, code, ben, "swipe", movie_id="cw-5", action="want").status_code == 200
    assert client.post("/shelves", json={}).status_code == 200  # the address is not shut out


def test_without_the_secret_nothing_in_a_room_can_be_done(client: TestClient) -> None:
    code, _, _ = _pair(client)
    for suffix, body in [
        ("deck", {}),
        ("results", None),
        ("swipe", {"movie_id": "cw-5", "action": "want"}),
        ("quiz", {}),
    ]:
        assert client.post(f"/rooms/{code}/{suffix}", json=body).status_code == 404, suffix


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
