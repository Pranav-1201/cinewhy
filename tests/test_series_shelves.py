"""Series on the page: the kind filter, the Series and Anime shelves, and the kind counts."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import api.main as api_main
from api.models import DiscoverRequest, Facets, ShelvesRequest
from cinewhy.recsys import shelves as shelves_module
from cinewhy.recsys.catalogue import Catalogue, RatingsOnlyFilm
from cinewhy.recsys.discover import catalogue_facets, discover
from cinewhy.recsys.shelves import ShelvesResult, build_shelves
from cinewhy.schemas import TasteProfile
from tests.test_ratings_only import _extra
from tests.test_shelves import _world


@pytest.fixture(autouse=True)
def _small_world_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shelves_module, "MIN_LANGUAGE_FILMS", 5)


def _series_world(every: int = 5) -> Catalogue:
    """The 300-film test world with every `every`-th title a TV series (cw-0, cw-5, ...)."""
    world = _world()
    movies = tuple(
        m.model_copy(update={"kind": "series"}) if i % every == 0 else m
        for i, m in enumerate(world.movies)
    )
    return replace(world, movies=movies)


def _anime(n: int, kind: str, language: str = "ja", genre: str = "Animation") -> RatingsOnlyFilm:
    base = _extra(n, language=language, genre=genre, year=2005, votes=60_000 - 100 * n)
    return replace(base, movie=base.movie.model_copy(update={"kind": kind}))


def _ids(result: ShelvesResult, shelf_id: str) -> list[str]:
    return [i.movie.movie_id for s in result.shelves if s.id == shelf_id for i in s.items]


def _kinds(result: ShelvesResult, shelf_id: str) -> set[str]:
    return {i.movie.kind for s in result.shelves if s.id == shelf_id for i in s.items}


def test_the_series_flag_marks_both_tiers() -> None:
    world = replace(_series_world(), ratings_only=(_anime(1, "series"), _anime(2, "film")))
    flagged = {
        m.movie_id for m, flag in zip(world.all_movies, world.is_series, strict=True) if flag
    }
    assert {"cw-0", "cw-5", "ro-1"} <= flagged and "ro-2" not in flagged and "cw-1" not in flagged
    assert int(world.is_series.sum()) == 60 + 1  # every 5th of 300, plus one ratings-only series


def test_a_series_only_request_returns_series_and_a_film_only_request_returns_films() -> None:
    world = _series_world()
    both = discover(world, TasteProfile(), limit=50, manifest="m")
    assert {i.movie.kind for i in both.items} == {"film", "series"}
    only_series = discover(world, TasteProfile(), limit=50, kinds=("series",), manifest="m")
    assert only_series.items and {i.movie.kind for i in only_series.items} == {"series"}
    only_films = discover(world, TasteProfile(), limit=50, kinds=("film",), manifest="m")
    assert only_films.items and {i.movie.kind for i in only_films.items} == {"film"}


def test_asking_for_both_kinds_is_the_same_as_asking_for_neither() -> None:
    world = _series_world()
    neither = discover(world, TasteProfile(), limit=40, manifest="m")
    assert discover(world, TasteProfile(), limit=40, kinds=("film", "series"), manifest="m") == (
        neither
    )


def test_every_shelf_respects_the_kind_choice() -> None:
    world = _series_world()
    films = build_shelves(world, TasteProfile(), kinds=("film",), manifest="m")
    assert all(i.movie.kind == "film" for s in films.shelves for i in s.items)
    series = build_shelves(world, TasteProfile(), kinds=("series",), manifest="m")
    assert series.shelves and all(i.movie.kind == "series" for s in series.shelves for i in s.items)


def test_a_series_shelf_holds_only_series_and_is_named_for_the_visitor() -> None:
    world = _series_world()
    cold = build_shelves(world, TasteProfile(), manifest="m")
    shelf = next(s for s in cold.shelves if s.id == "series")
    assert shelf.title == "Top series" and _kinds(cold, "series") == {"series"}
    warm = build_shelves(world, TasteProfile(liked_movie_ids=("cw-1",)), manifest="m")
    assert next(s for s in warm.shelves if s.id == "series").title == "Series for you"


def test_the_series_shelf_sits_after_old_school_and_before_the_languages() -> None:
    ids = [s.id for s in build_shelves(_series_world(), TasteProfile(), manifest="m").shelves]
    assert ids.index("classics") < ids.index("series") < ids.index("lang-en")


def test_no_series_means_no_series_shelf_and_a_films_only_choice_hides_it() -> None:
    plain = build_shelves(_world(), TasteProfile(), manifest="m")
    assert "series" not in [s.id for s in plain.shelves]
    asked_for_films = build_shelves(_series_world(), TasteProfile(), kinds=("film",), manifest="m")
    assert "series" not in [s.id for s in asked_for_films.shelves]


def test_no_title_is_on_the_series_shelf_and_another() -> None:
    result = build_shelves(_series_world(), TasteProfile(), manifest="m")
    ids = [i.movie.movie_id for s in result.shelves for i in s.items]
    assert len(ids) == len(set(ids))


def test_the_anime_shelf_holds_japanese_animation_films_and_series_together() -> None:
    # 120 titles: the Series shelf and the Japanese language shelf each take their best 20 first
    # (no title is on two shelves), and the anime shelf gets what is left.
    extras = [_anime(i, "series" if i % 2 else "film") for i in range(1, 121)]
    # Decoys that would be on the shelf if a rule failed. A French animation film leads on votes, so
    # the language rule is what keeps it out. Japanese dramas rank just behind the best twenty
    # Japanese titles (which the language shelf takes) and ahead of the other anime, so they
    # would head the shelf if the genre rule failed.
    extras.append(replace(_anime(800, "film", language="fr"), imdb_votes=999_999))
    extras += [
        replace(_anime(900 + i, "film", genre="Drama"), imdb_votes=57_500) for i in range(30)
    ]
    world = replace(_world(), ratings_only=tuple(extras))
    result = build_shelves(world, TasteProfile(), manifest="m")
    anime = [i for s in result.shelves if s.id == "anime" for i in s.items]
    assert {"film", "series"} <= {i.movie.kind for i in anime}
    assert all(i.language == "ja" and "Animation" in i.movie.genres for i in anime)
    ids = [s.id for s in result.shelves]
    assert ids.index("anime") > ids.index("lang-ja")  # after the language rows


def test_the_anime_shelf_goes_when_the_visitors_choices_rule_it_out() -> None:
    extras = [_anime(i, "series") for i in range(1, 121)]
    world = replace(_world(), ratings_only=tuple(extras))
    assert "anime" in [s.id for s in build_shelves(world, TasteProfile(), manifest="m").shelves]
    english = build_shelves(world, TasteProfile(), languages=("en",), manifest="m")
    assert "anime" not in [s.id for s in english.shelves]
    drama = build_shelves(world, TasteProfile(), genres=("Drama",), manifest="m")
    assert "anime" not in [s.id for s in drama.shelves]


def test_the_facets_count_films_and_series_separately() -> None:
    world = replace(_series_world(), ratings_only=(_anime(1, "series"), _anime(2, "film")))
    facets = catalogue_facets(world)
    assert facets["kinds"] == {"film": 241, "series": 61}
    assert facets["films"] == 302  # every title, the older name for the total
    assert Facets.model_validate(facets).kinds == {"film": 241, "series": 61}


def test_the_api_passes_the_kind_choice_to_every_list(monkeypatch: pytest.MonkeyPatch) -> None:
    state = api_main._State(SimpleNamespace(manifest_hash="m"), _series_world(), {}, None)  # type: ignore[arg-type]
    monkeypatch.setattr(api_main, "_state", state)
    shelves = api_main.shelves(ShelvesRequest(kinds=("series",)))
    assert shelves.shelves and all(
        i.movie.kind == "series" for s in shelves.shelves for i in s.items
    )
    found = api_main.discover_films(DiscoverRequest(kinds=("series",), limit=30))
    assert found.items and all(i.movie.kind == "series" for i in found.items)
    films = api_main.discover_films(DiscoverRequest(kinds=("film",), limit=30))
    assert films.items and all(i.movie.kind == "film" for i in films.items)
    assert api_main.facets().kinds == {"film": 240, "series": 60}


def test_requests_accept_films_and_series_and_nothing_else() -> None:
    for model in (DiscoverRequest, ShelvesRequest):
        assert model(kinds=("series",)).kinds == ("series",)
        assert model(kinds=("film", "series")).kinds == ("film", "series")
        assert model().kinds == ()
        with pytest.raises(ValidationError):
            model(kinds=("movie",))  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            model(kinds=("film", "series", "film"))
