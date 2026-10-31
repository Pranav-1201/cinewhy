"""The TMDB series downloader: what it asks, how it retries, and that it can be resumed."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
from typing import Any

import pytest

from cinewhy.data.fetch_series import (
    already_fetched,
    fetch_all,
    make_fetcher,
    record_from_find,
)

_TOKEN = "secret-token-value"
_FOUND = {
    "tv_results": [
        {
            "id": 1396,
            "name": "Breaking Bad",
            "original_language": "en",
            "first_air_date": "2008-01-20",
            "overview": "A teacher.",
            "poster_path": "/bb.jpg",
            "vote_count": 100,
            "vote_average": 8.9,
            "popularity": 55.5,
            "origin_country": ["US"],
        }
    ]
}


class _Response:
    def __init__(
        self, status: int, body: object = None, headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body or {}).encode()
        self._headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str) -> str | None:
        return self._headers.get(name)


class _Connection:
    """Answers from a script: a response to return, or an exception to raise."""

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.requests.append((method, path, headers))

    def getresponse(self) -> _Response:
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        assert isinstance(step, _Response)
        return step

    def close(self) -> None:
        self.closed = True


class _Phone:
    """A connect() that hands out scripted connections and counts how often it was called."""

    def __init__(self, *scripts: list[object]) -> None:
        self.connections = [_Connection(s) for s in scripts]
        self.calls = 0

    def __call__(self) -> http.client.HTTPSConnection:
        connection = self.connections[self.calls]
        self.calls += 1
        return connection  # type: ignore[return-value]


def _fetcher(phone: _Phone, slept: list[float] | None = None) -> Any:
    log = slept if slept is not None else []
    return make_fetcher(_TOKEN, connect=phone, sleep=log.append)


def test_a_find_answer_keeps_the_first_tv_result_and_what_the_build_needs() -> None:
    record = record_from_find(903747, _FOUND)
    assert record["found"] is True and record["imdb"] == 903747 and record["tmdb_id"] == 1396
    assert record["original_language"] == "en" and record["first_air_date"] == "2008-01-20"
    assert record["poster_path"] == "/bb.jpg" and record["origin_country"] == ["US"]
    assert "name" not in record  # the build takes titles from IMDb, not TMDB


def test_an_answer_with_no_tv_result_is_recorded_as_not_found() -> None:
    assert record_from_find(5, {"tv_results": [], "movie_results": [{"id": 1}]}) == {
        "imdb": 5,
        "found": False,
    }
    assert record_from_find(5, {}) == {"imdb": 5, "found": False}


def test_it_asks_for_the_imdb_number_with_the_token_in_a_header_only() -> None:
    phone = _Phone([_Response(200, _FOUND)])
    record = _fetcher(phone)(903747)
    method, path, headers = phone.connections[0].requests[0]
    assert (method, path) == ("GET", "/3/find/tt0903747?external_source=imdb_id")
    assert headers["Authorization"] == f"Bearer {_TOKEN}"
    assert _TOKEN not in json.dumps(record) and _TOKEN not in path


def test_one_connection_is_reused_for_every_request() -> None:
    phone = _Phone([_Response(200, _FOUND)] * 3)
    fetch = _fetcher(phone)
    assert [fetch(i)["found"] for i in (1, 2, 3)] == [True, True, True]
    assert phone.calls == 1 and len(phone.connections[0].requests) == 3


def test_too_many_requests_waits_as_long_as_tmdb_asks_then_retries() -> None:
    slept: list[float] = []
    phone = _Phone([_Response(429, headers={"Retry-After": "7"}), _Response(200, _FOUND)])
    assert _fetcher(phone, slept)(1)["found"] is True
    assert slept == [7.0] and phone.calls == 1  # the connection was fine, so it was kept


def test_an_unknown_id_is_not_found_and_a_refused_token_stops_everything() -> None:
    assert _fetcher(_Phone([_Response(404)]))(1) == {"imdb": 1, "found": False}
    with pytest.raises(SystemExit) as stopped:
        _fetcher(_Phone([_Response(401)]))(1)
    assert _TOKEN not in str(stopped.value)


def test_a_server_error_or_a_dropped_connection_reconnects_and_tries_again() -> None:
    slept: list[float] = []
    phone = _Phone(
        [_Response(503)],  # the server hiccups: drop the connection and start a new one
        [TimeoutError("timed out")],  # the new one times out as well
        [_Response(200, _FOUND)],
    )
    assert _fetcher(phone, slept)(1)["found"] is True
    assert phone.calls == 3 and phone.connections[0].closed and phone.connections[1].closed
    assert slept == [1, 2]  # a little longer each time


def test_a_garbled_body_is_retried_and_a_dead_server_gives_up_with_none() -> None:
    # A garbled body drops the connection, so the retry arrives on a new one.
    phone = _Phone([_Response(200, b"<html>")], [_Response(200, _FOUND)])
    assert _fetcher(phone)(1)["found"] is True and phone.calls == 2
    scripts: list[list[object]] = [[OSError("down")] for _ in range(5)]
    dead = _Phone(*scripts)
    assert _fetcher(dead)(1) is None


def _fake(fetch_log: list[int], *, fail: set[int] | None = None) -> Any:
    def fetch(imdb_id: int) -> dict[str, Any] | None:
        fetch_log.append(imdb_id)
        if fail and imdb_id in fail:
            return None
        return {"imdb": imdb_id, "found": imdb_id % 2 == 1}

    return fetch


def _run(cache: Path, ids: list[int], fetch: Any, **kwargs: Any) -> int:
    return fetch_all(ids, cache, fetch, on_progress=lambda _m: None, **kwargs)


def test_every_answer_is_written_and_a_rerun_asks_only_for_what_is_missing(tmp_path: Path) -> None:
    cache = tmp_path / "deep" / "tmdb_tv.jsonl"
    asked: list[int] = []
    assert _run(cache, [3, 1, 2], _fake(asked), rate=1000) == 3
    assert sorted(asked) == [1, 2, 3] and already_fetched(cache) == {1, 2, 3}
    again: list[int] = []
    assert _run(cache, [1, 2, 3, 4], _fake(again), rate=1000) == 1
    assert again == [4]


def test_a_failed_request_is_not_recorded_so_the_next_run_retries_it(tmp_path: Path) -> None:
    cache = tmp_path / "tmdb_tv.jsonl"
    assert _run(cache, [1, 2, 3], _fake([], fail={2}), rate=1000) == 2
    assert already_fetched(cache) == {1, 3}
    retry: list[int] = []
    _run(cache, [1, 2, 3], _fake(retry), rate=1000)
    assert retry == [2]


def test_a_half_written_last_line_does_not_stop_a_resume(tmp_path: Path) -> None:
    cache = tmp_path / "tmdb_tv.jsonl"
    cache.write_text('{"imdb": 1, "found": true}\n{"imdb": 2, "fou', encoding="utf-8")
    assert already_fetched(cache) == {1}


def test_requests_start_no_faster_than_the_rate(tmp_path: Path) -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    _run(
        tmp_path / "c.jsonl",
        [1, 2, 3, 4, 5],
        _fake([]),
        rate=10,
        workers=1,
        clock=lambda: now[0],
        sleep=sleep,
    )
    # Five requests at 10 a second: the first starts at once, the rest 0.1 s apart.
    assert sum(slept) == pytest.approx(0.4)
