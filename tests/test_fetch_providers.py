"""Where to watch: which platforms are kept, how an answer becomes a cache line, what is asked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cinewhy.data import fetch_providers
from cinewhy.data.fetch_providers import (
    PLATFORM_OF,
    PLATFORMS,
    make_provider_fetcher,
    provider_path,
    record_from_providers,
    tmdb_ids,
    wanted_titles,
)
from tests.test_fetch_series import _TOKEN, _Phone, _Response


def _offer(*ids: int) -> list[dict[str, object]]:
    return [{"provider_id": i, "provider_name": f"service {i}"} for i in ids]


def test_the_six_platforms_are_exactly_the_owners_list() -> None:
    assert set(PLATFORMS) == {"netflix", "apple", "prime", "hotstar", "crunchyroll", "hbo"}


def test_every_provider_id_belongs_to_one_platform_and_the_checked_ids_are_present() -> None:
    all_ids = [i for ids in PLATFORMS.values() for i in ids]
    assert len(all_ids) == len(set(all_ids))  # no id is claimed by two platforms
    # Found by listing TMDB's providers on 2026-11-03 (D-035).
    expected = {8: "netflix", 1796: "netflix", 350: "apple", 2: "apple", 119: "prime", 9: "prime",
                2100: "prime", 613: "prime", 10: "prime", 122: "hotstar", 2336: "hotstar",
                283: "crunchyroll", 1899: "hbo"}  # fmt: skip
    assert {i: PLATFORM_OF[i] for i in expected} == expected


def test_add_on_channels_and_disney_plus_outside_hotstar_are_left_out() -> None:
    # Crunchyroll or HBO Max as an Amazon Channel, HBO Max on U-Next, plain Disney+ (337), Netflix
    # Kids (175) and YouTube (192).
    for excluded in (1968, 1825, 2284, 337, 175, 192):
        assert excluded not in PLATFORM_OF


def test_only_the_six_platforms_are_kept_and_other_services_are_dropped() -> None:
    answer = {"results": {"IN": {"flatrate": _offer(8, 237, 15), "rent": _offer(192)}}}
    record = record_from_providers(5, ("film", 603), answer)
    assert record["where"] == {"IN": {"netflix": ["stream"]}}


def test_each_way_of_watching_gets_the_viewers_word() -> None:
    answer = {
        "results": {
            "US": {
                "flatrate": _offer(8),
                "ads": _offer(613),
                "rent": _offer(2),
                "buy": _offer(2, 10),
            }
        }
    }
    where = record_from_providers(5, ("film", 1), answer)["where"]["US"]
    assert where == {"apple": ["rent", "buy"], "netflix": ["stream"], "prime": ["free", "buy"]}


def test_free_and_free_with_ads_are_one_way_and_the_ways_are_shown_in_order() -> None:
    answer = {"results": {"JP": {"buy": _offer(10), "free": _offer(9), "ads": _offer(2100)}}}
    assert record_from_providers(5, ("series", 1), answer)["where"] == {
        "JP": {"prime": ["free", "buy"]}
    }


def test_two_ids_of_one_platform_merge_into_one_entry() -> None:
    answer = {"results": {"IN": {"flatrate": _offer(8, 1796)}}}  # Netflix and Netflix with Ads
    assert record_from_providers(5, ("film", 1), answer)["where"] == {"IN": {"netflix": ["stream"]}}


def test_a_country_with_none_of_the_six_is_left_out_and_none_anywhere_gives_empty_where() -> None:
    answer = {"results": {"FR": {"flatrate": _offer(15)}, "DE": {"rent": _offer(3)}}}
    record = record_from_providers(7, ("film", 9), answer)
    assert record == {"imdb": 7, "found": True, "tmdb_id": 9, "kind": "film", "where": {}}
    assert record_from_providers(7, ("film", 9), {})["where"] == {}


def test_hotstar_in_india_is_found_under_both_of_its_names() -> None:
    for provider in (122, 2336):
        answer = {"results": {"IN": {"flatrate": _offer(provider)}}}
        assert record_from_providers(1, ("film", 1), answer)["where"] == {
            "IN": {"hotstar": ["stream"]}
        }


def test_a_film_and_a_series_use_different_paths() -> None:
    assert provider_path("film", 603) == "/3/movie/603/watch/providers"
    assert provider_path("series", 1396) == "/3/tv/1396/watch/providers"


def test_the_fetcher_asks_for_the_right_path_with_the_token_and_returns_a_record() -> None:
    answer = {"results": {"IN": {"flatrate": _offer(283)}}}
    phone = _Phone([_Response(200, answer)])
    fetch = make_provider_fetcher(
        _TOKEN, {42: ("series", 37854)}, connect=phone, sleep=lambda _s: None
    )
    assert fetch(42) == {
        "imdb": 42,
        "found": True,
        "tmdb_id": 37854,
        "kind": "series",
        "where": {"IN": {"crunchyroll": ["stream"]}},
    }
    method, path, headers = phone.connections[0].requests[0]
    assert (method, path) == ("GET", "/3/tv/37854/watch/providers")
    assert headers["Authorization"] == f"Bearer {_TOKEN}"


def test_a_title_with_no_tmdb_id_is_recorded_as_not_found_without_asking() -> None:
    phone = _Phone()
    fetch = make_provider_fetcher(_TOKEN, {}, connect=phone, sleep=lambda _s: None)
    assert fetch(99) == {"imdb": 99, "found": False}
    assert phone.calls == 0  # no connection was even opened


def test_tmdb_saying_it_does_not_know_a_title_is_recorded_as_not_found() -> None:
    phone = _Phone([_Response(404, {"status_message": "not found"})])
    fetch = make_provider_fetcher(_TOKEN, {5: ("film", 1)}, connect=phone, sleep=lambda _s: None)
    assert fetch(5) == {"imdb": 5, "found": False}


def test_a_failed_request_is_not_recorded_so_a_rerun_tries_again() -> None:
    boom: list[object] = [OSError("reset")]
    phone = _Phone(*([boom] * 5))
    fetch = make_provider_fetcher(_TOKEN, {5: ("film", 1)}, connect=phone, sleep=lambda _s: None)
    assert fetch(5) is None


def _artifact(tmp_path: Path, *, wrapped: bool) -> Path:
    movies = [
        {"movie_id": "cw-0000603", "kind": "film"},
        {"movie_id": "cw-0000500", "kind": "series"},
        {"movie_id": "cw-0000011"},  # no kind: an older artifact, so a film
    ]
    ratings_only = [
        {"movie_id": "ro-0000900", "imdb_id": 900, "kind": "film"},
        {"movie_id": "ro-0000901", "imdb_id": 901, "kind": "series"},
    ]
    (tmp_path / "catalogue.json").write_text(
        json.dumps({"movies": movies} if wrapped else movies), encoding="utf-8"
    )
    (tmp_path / "ratings_only.json").write_text(
        json.dumps({"films": ratings_only} if wrapped else ratings_only), encoding="utf-8"
    )
    return tmp_path


@pytest.mark.parametrize("wrapped", [True, False])
def test_the_wanted_titles_are_both_tiers_with_their_kind(tmp_path: Path, wrapped: bool) -> None:
    assert wanted_titles(_artifact(tmp_path, wrapped=wrapped)) == {
        603: "film",
        500: "series",
        11: "film",
        900: "film",
        901: "series",
    }


def test_an_artifact_without_a_ratings_only_file_is_still_read(tmp_path: Path) -> None:
    (tmp_path / "catalogue.json").write_text(
        json.dumps([{"movie_id": "cw-0000007"}]), encoding="utf-8"
    )
    assert wanted_titles(tmp_path) == {7: "film"}


def test_tmdb_ids_take_films_from_the_film_list_and_series_from_the_series_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"imdb_id": "tt0000603", "id": "603", "vote_count": "100"},
        {"imdb_id": "tt0000604", "id": "604", "vote_count": "5"},  # not wanted
        {
            "imdb_id": "tt0000500",
            "id": "7777",
            "vote_count": "9",
        },  # wanted as a SERIES: not a film row
        {"imdb_id": "", "id": "1", "vote_count": "1"},
        # Wanted as a series but TMDB's film list has a row for the number and the series cache has
        # none: a film row must never stand in for a series.
        {"imdb_id": "tt0000502", "id": "8888", "vote_count": "3"},
    ]
    monkeypatch.setattr(fetch_providers, "read_tmdb_rows", lambda _path: iter(rows))
    cache = tmp_path / "tv.jsonl"
    cache.write_text(
        "\n".join(
            [
                json.dumps({"imdb": 500, "found": True, "tmdb_id": 1396}),
                json.dumps({"imdb": 501, "found": False}),
                "{not json",
            ]
        ),
        encoding="utf-8",
    )
    wanted = {603: "film", 500: "series", 501: "series", 502: "series"}
    assert tmdb_ids(wanted, tmp_path / "unused.csv", cache) == {
        603: ("film", 603),
        500: ("series", 1396),
    }


def test_two_tmdb_rows_for_one_film_pick_the_most_voted_then_the_lower_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {"imdb_id": "tt0000010", "id": "30", "vote_count": "50"},
        {"imdb_id": "tt0000010", "id": "20", "vote_count": "50"},  # same votes, lower id wins
        {"imdb_id": "tt0000011", "id": "5", "vote_count": "1"},
        {"imdb_id": "tt0000011", "id": "6", "vote_count": "9"},  # more votes wins
    ]
    for order in (rows, list(reversed(rows))):  # the answer never depends on file order
        monkeypatch.setattr(fetch_providers, "read_tmdb_rows", lambda _p, o=order: iter(o))
        found = tmdb_ids({10: "film", 11: "film"}, tmp_path / "x.csv", tmp_path / "none.jsonl")
        assert found == {10: ("film", 20), 11: ("film", 6)}
