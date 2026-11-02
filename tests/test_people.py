"""People: the cast of a title, finding a person by name, and the top titles of a person."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.data.cast import Cast, write_cast
from cinewhy.recsys.catalogue import Catalogue, load_catalogue
from cinewhy.recsys.discover import discover, score_films, select_items
from cinewhy.recsys.people import (
    PersonHit,
    cast_of,
    imdb_number,
    person_positions,
    search_people,
)
from cinewhy.schemas import TasteProfile
from tests.smoke_artifacts import write_smoke_artifacts
from tests.test_ratings_only import _extra
from tests.test_shelves import _world

_PEOPLE = {
    1: "Zoë Saldaña",
    2: "Zoe Smith",
    3: "Anna Zoe",
    4: "Zoey Deschanel",
    5: "Tom Hanks",
}
# IMDb number (the digits of the test ids "cw-N") to the people billed in it, first billed first.
_TITLES = {1: (1, 5), 2: (1, 2), 3: (1,), 4: (1, 3), 6: (4,), 7: (4,), 10: (5,), 11: (5, 1)}


def _world_with_cast() -> Catalogue:
    return replace(_world(40), cast=Cast(dict(_TITLES), dict(_PEOPLE)))


def _names(hits: Sequence[PersonHit]) -> list[str]:
    return [h.name for h in hits]


def test_the_imdb_number_is_the_digits_after_the_prefix() -> None:
    assert imdb_number("cw-0000603") == 603 and imdb_number("ro-7") == 7
    assert imdb_number("nonsense") is None and imdb_number("cw-") is None


def test_the_cast_of_a_title_is_in_billing_order_with_names_and_respects_the_limit() -> None:
    world = _world_with_cast()
    assert cast_of(world, "cw-1") == [(1, "Zoë Saldaña"), (5, "Tom Hanks")]
    assert cast_of(world, "cw-11", limit=1) == [(5, "Tom Hanks")]


def test_a_title_with_no_cast_an_unknown_id_or_a_build_without_cast_gives_nobody() -> None:
    world = _world_with_cast()
    assert cast_of(world, "cw-30") == [] and cast_of(world, "nonsense") == []
    assert cast_of(_world(40), "cw-1") == []  # no cast file in this build


def test_a_ratings_only_title_gets_its_cast_by_the_same_imdb_number() -> None:
    world = replace(
        _world(40), ratings_only=(_extra(77),), cast=Cast({77: (4,)}, {4: "Zoey Deschanel"})
    )
    assert cast_of(world, "ro-77") == [(4, "Zoey Deschanel")]


def test_kinds_of_match_are_ordered_exact_prefix_word_start_then_every_word() -> None:
    world = _world_with_cast()
    assert _names(search_people(world, "zoe")) == [
        "Zoë Saldaña",  # name starts with it; billed in 5 titles
        "Zoey Deschanel",  # name starts with it; 2 titles
        "Zoe Smith",  # name starts with it; 1 title
        "Anna Zoe",  # only a word start
    ]
    assert _names(search_people(world, "tom hanks")) == ["Tom Hanks"]  # exact
    assert _names(search_people(world, "hanks tom")) == ["Tom Hanks"]  # every word, any order


def test_search_ignores_accents_and_case_in_the_query_and_the_name() -> None:
    world = _world_with_cast()
    assert _names(search_people(world, "ZOE SALDANA")) == ["Zoë Saldaña"]
    assert _names(search_people(world, "saldaña")) == ["Zoë Saldaña"]


def test_a_person_is_reported_with_how_many_titles_they_are_billed_in() -> None:
    (hit,) = search_people(_world_with_cast(), "saldana")
    assert (hit.person_id, hit.titles) == (1, 5)


def test_a_one_letter_query_a_missing_cast_and_no_match_give_nobody() -> None:
    world = _world_with_cast()
    assert search_people(world, "z") == [] and search_people(world, "  ") == []
    assert search_people(world, "nobody by this name") == []
    assert search_people(_world(40), "zoe") == []


def _small_cast() -> Cast:
    # Title 99 is not in the six-film smoke catalogue: a cast file may name titles it lacks.
    return Cast({1: (1, 2), 2: (2,), 99: (1,)}, {1: "Ann Actor", 2: "Ben Actor"})


def test_the_loader_reads_the_cast_only_when_asked(tmp_path: Path) -> None:
    out = write_smoke_artifacts(tmp_path / "v", cast=_small_cast())
    assert load_catalogue(out, with_cast=True).cast == _small_cast()
    assert load_catalogue(out).cast is None


def test_boot_loads_a_cast_the_verified_manifest_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = write_smoke_artifacts(tmp_path / "v", cast=_small_cast())
    monkeypatch.setattr(api_main, "_state", None)
    api_main.load_artifacts(out)
    assert api_main._loaded().catalogue.cast == _small_cast()
    assert [p.name for p in api_main.movie_detail("cw-1").cast] == ["Ann Actor", "Ben Actor"]


def test_boot_ignores_a_cast_file_the_manifest_does_not_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = write_smoke_artifacts(tmp_path / "v")  # a build with no cast in its manifest
    write_cast(out / "cast.json", _small_cast())  # a stray file nobody verified
    monkeypatch.setattr(api_main, "_state", None)
    api_main.load_artifacts(out)
    assert api_main._loaded().catalogue.cast is None  # unverified data is never read


def test_a_cast_that_names_a_title_the_catalogue_lacks_is_skipped() -> None:
    world = replace(_world(40), cast=Cast({999: (1,), 1: (1,)}, {1: "A"}))
    assert person_positions(world, 1) == [1]


def test_the_limit_caps_the_answer() -> None:
    assert len(search_people(_world_with_cast(), "zoe", limit=2)) == 2


def test_a_persons_positions_are_the_catalogue_positions_of_their_titles() -> None:
    world = _world_with_cast()
    assert person_positions(world, 1) == [1, 2, 3, 4, 11]
    assert person_positions(world, 999) == [] and person_positions(_world(40), 1) == []


def _result_ids(
    world: Catalogue, profile: TasteProfile | None = None, **kwargs: object
) -> list[str]:
    result = discover(world, profile or TasteProfile(), limit=100, manifest="m", **kwargs)  # type: ignore[arg-type]
    return [item.movie.movie_id for item in result.items]


def test_a_persons_list_holds_only_their_titles_in_the_same_order_as_the_full_ranking() -> None:
    world = _world_with_cast()
    person = _result_ids(world, person_id=1)
    assert set(person) == {"cw-1", "cw-2", "cw-3", "cw-4", "cw-11"}
    everyone = _result_ids(world)
    assert person == [movie_id for movie_id in everyone if movie_id in set(person)]


def test_a_persons_list_obeys_the_visitors_filters_and_never_repeats_a_liked_title() -> None:
    world = _world_with_cast()
    assert _result_ids(world, person_id=1, kinds=("series",)) == []  # the test world has films only
    liked = TasteProfile(liked_movie_ids=("cw-2",))
    shown = _result_ids(world, liked, person_id=1)
    assert "cw-2" not in shown and set(shown) <= {"cw-1", "cw-3", "cw-4", "cw-11"}


def test_an_unknown_person_or_a_build_without_cast_gives_an_empty_list_not_everything() -> None:
    assert _result_ids(_world_with_cast(), person_id=999) == []
    assert _result_ids(_world(40), person_id=1) == []


def test_select_items_with_an_empty_only_returns_nothing_and_none_means_everything() -> None:
    world = _world(40)
    scored = score_films(world, TasteProfile(), recency=0.0)
    assert select_items(world, scored, limit=5, only=[]) == ()
    assert len(select_items(world, scored, limit=5, only=None)) == 5
    assert {i.movie.movie_id for i in select_items(world, scored, limit=5, only=[3, 7])} == {
        "cw-3",
        "cw-7",
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    manifest = SimpleNamespace(manifest_hash="m")
    state = api_main._State(manifest, _world_with_cast(), {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr(api_main, "_state", state)
    return TestClient(api_main.create_app())  # no `with`: the artifacts are already in place


def test_the_people_route_finds_people_and_clamps_its_input(client: TestClient) -> None:
    body = client.get("/people", params={"q": "zoe"}).json()
    assert body[0]["name"] == "Zoë Saldaña"
    assert set(body[0]) == {"id", "name", "titles"}
    assert len(client.get("/people", params={"q": "zoe", "limit": 1}).json()) == 1
    assert len(client.get("/people", params={"q": "zoe", "limit": 9999}).json()) <= 20
    assert client.get("/people", params={"q": "z"}).json() == []
    assert client.get("/people").json() == []
    assert client.get("/people", params={"q": "zoe" + "x" * 500}).json() == []  # capped, no error


def test_a_film_page_lists_its_cast(client: TestClient) -> None:
    page = client.get("/movie/cw-1").json()
    assert page["cast"] == [{"id": 1, "name": "Zoë Saldaña"}, {"id": 5, "name": "Tom Hanks"}]
    assert client.get("/movie/cw-30").json()["cast"] == []


def test_discover_accepts_a_person_and_rejects_a_bad_one(client: TestClient) -> None:
    ok = client.post("/discover", json={"person_id": 5, "limit": 10})
    assert ok.status_code == 200
    assert {i["movie"]["movie_id"] for i in ok.json()["items"]} == {"cw-1", "cw-10", "cw-11"}
    assert client.post("/discover", json={"person_id": 0}).status_code == 422
    assert client.post("/discover", json={"person_id": "tom"}).status_code == 422


def test_facets_say_whether_people_can_be_searched(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get("/facets").json()["cast"] is True
    manifest = SimpleNamespace(manifest_hash="m")
    bare = api_main._State(manifest, _world(40), {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr(api_main, "_state", bare)
    assert client.get("/facets").json()["cast"] is False
