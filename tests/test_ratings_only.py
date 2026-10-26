"""Films we hold ratings for but have not read reviews of (cinewhy/recsys/catalogue.py, "Tier B").

They sit beside the full-receipt films, not inside the similarity matrix, so these tests pin what
that costs and what it must never do: appear where a heading promises quotes, get a reason that
was not computed, or reach a row of the matrix that does not exist.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import api.main as api_main
from cinewhy.recsys import shelves as shelves_module
from cinewhy.recsys.catalogue import (
    Catalogue,
    RatingsOnlyFilm,
    load_catalogue,
    write_catalogue,
)
from cinewhy.recsys.discover import (
    DiscoverItem,
    catalogue_facets,
    genre_affinity,
    ratings_only_popularity,
)
from cinewhy.recsys.rank import search
from cinewhy.recsys.shelves import ShelvesResult, build_shelves
from cinewhy.schemas import Movie, TasteProfile
from tests.test_shelves import _world


def _extra(
    n: int,
    *,
    language: str = "ja",
    genre: str = "Drama",
    year: int = 2022,
    rating: float = 8.0,
    votes: int = 50_000,
    title: str | None = None,
) -> RatingsOnlyFilm:
    return RatingsOnlyFilm(
        movie=Movie(movie_id=f"ro-{n}", title=title or f"Extra {n}", year=year, genres=(genre,)),
        imdb_id=9_000_000 + n,
        language=language,
        imdb_rating=rating,
        imdb_votes=votes,
        overview=f"About extra {n}.",
        release_date=f"{year}-05-01",
        runtime=95,
    )


def _with_extras(*extras: RatingsOnlyFilm) -> Catalogue:
    return replace(_world(), ratings_only=tuple(extras))


def _japanese(count: int = 8, **kwargs: object) -> list[RatingsOnlyFilm]:
    """Japanese films, best known first.

    2005 by default: the "new" shelf is 2021 on, and it would otherwise take every one of them
    before the language shelf is built (no film is on two shelves).
    """
    options: dict[str, object] = {"year": 2005, **kwargs}
    return [
        _extra(i, **{"votes": 80_000 - 1000 * i, **options})  # type: ignore[arg-type]
        for i in range(count)
    ]


@pytest.fixture(autouse=True)
def _small_world_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shelves_module, "MIN_LANGUAGE_FILMS", 5)


def _shelf_ids(result: ShelvesResult) -> list[str]:
    return [s.id for s in result.shelves]


def _items(result: ShelvesResult, shelf_id: str) -> list[DiscoverItem]:
    return [i for s in result.shelves if s.id == shelf_id for i in s.items]


def _everything(result: ShelvesResult) -> list[str]:
    return [i.movie.movie_id for s in result.shelves for i in s.items]


def test_positions_put_the_ratings_only_films_after_the_full_receipt_ones() -> None:
    world = _with_extras(_extra(1), _extra(2))
    assert [m.movie_id for m in world.all_movies][-2:] == ["ro-1", "ro-2"]
    assert world.all_index["ro-2"] == len(world.movies) + 1
    assert world.is_ratings_only(len(world.movies)) and not world.is_ratings_only(0)
    # `index` stays the matrix's index: a ratings-only id there would read a missing row.
    assert "ro-1" not in world.index


def test_one_id_in_both_tiers_is_refused() -> None:
    clash = _extra(1)
    clash = replace(clash, movie=clash.movie.model_copy(update={"movie_id": "cw-3"}))
    with pytest.raises(ValueError, match="both tiers"):
        _with_extras(clash)


def test_a_catalogue_round_trips_its_ratings_only_films(tmp_path: Path) -> None:
    world = _with_extras(*_japanese(3))
    write_catalogue(tmp_path, world)
    assert (tmp_path / "ratings_only.json").is_file()
    again = load_catalogue(tmp_path, with_ratings_only=True)
    assert again.ratings_only == world.ratings_only
    # The file is read only when the verified manifest lists it, so a stray copy changes nothing.
    assert load_catalogue(tmp_path).ratings_only == ()


def test_no_ratings_only_films_writes_no_file(tmp_path: Path) -> None:
    write_catalogue(tmp_path, _world())
    assert not (tmp_path / "ratings_only.json").exists()


def test_facets_count_both_tiers() -> None:
    plain = catalogue_facets(_world())
    mixed = catalogue_facets(_with_extras(*_japanese(6)))
    assert mixed["films"] == plain["films"] + 6  # type: ignore[operator]
    assert mixed["languages"]["ja"] == 6  # type: ignore[index]


def test_a_language_shelf_appears_and_holds_only_ratings_only_films() -> None:
    result = build_shelves(_with_extras(*_japanese()), TasteProfile(), manifest="m")
    shelf = _items(result, "lang-ja")
    assert len(shelf) == 8
    assert all(i.ratings_only and i.reasons == () and i.because is None for i in shelf)


def test_picks_similar_and_explore_never_hold_one() -> None:
    # Eight Japanese films at the top of popularity, so a rule that let them in would show them.
    world = _with_extras(*_japanese(8, rating=9.5, votes=900_000))
    result = build_shelves(world, TasteProfile(liked_movie_ids=("cw-1",)), manifest="m")
    for shelf_id in ("picks", "similar", "explore"):
        assert shelf_id in _shelf_ids(result)
        assert not any(i.ratings_only for i in _items(result, shelf_id))


def test_a_cold_start_pick_is_never_a_ratings_only_film_however_popular() -> None:
    # Cold, every film is ranked on popularity alone, so films at 9.5 from 900,000 voters WOULD lead
    # the picks if the spotlight and its row did not refuse them.
    world = _with_extras(*_japanese(8, rating=9.5, votes=900_000))
    result = build_shelves(world, TasteProfile(), manifest="m")
    assert result.cold_start is True
    picks = _items(result, "picks")
    assert len(picks) == 16 and not any(i.ratings_only for i in picks)


def test_a_warm_shelf_lists_ratings_only_films_of_the_liked_genre_first() -> None:
    # Equal fame, comedies listed first so catalogue order cannot be what puts the dramas on top.
    comedy = [_extra(100 + i, genre="Comedy", year=2005, votes=30_000) for i in range(5)]
    drama = [_extra(i, genre="Drama", year=2005, votes=30_000) for i in range(5)]
    world = _with_extras(*comedy, *drama)
    result = build_shelves(world, TasteProfile(liked_movie_ids=("cw-0",)), manifest="m")  # a Drama
    japanese = _items(result, "lang-ja")
    # A warm profile still shows them (they carry no reasons, and say so instead of being dropped).
    assert len(japanese) == 10 and all(i.ratings_only for i in japanese)
    assert [i.movie.genres[0] for i in japanese] == ["Drama"] * 5 + ["Comedy"] * 5


def test_a_ratings_only_film_is_on_one_shelf_only() -> None:
    ids = _everything(build_shelves(_with_extras(*_japanese()), TasteProfile(), manifest="m"))
    assert len(ids) == len(set(ids))


def test_the_new_shelf_can_carry_a_ratings_only_film_with_its_flag() -> None:
    result = build_shelves(_with_extras(*_japanese(8, year=2023)), TasteProfile(), manifest="m")
    assert any(i.ratings_only for i in _items(result, "new"))


def test_liking_a_genre_lifts_ratings_only_films_of_that_genre() -> None:
    drama = [_extra(i, genre="Drama", votes=20_000) for i in range(6)]
    comedy = [_extra(100 + i, genre="Comedy", votes=20_000) for i in range(6)]
    world = _with_extras(*drama, *comedy)
    liked = world.index["cw-0"]  # cw-0 is a Drama in the shared world
    assert world.movies[liked].genres == ("Drama",)
    affinity = genre_affinity(world, [liked], [])
    assert affinity[:6].min() > affinity[6:].max()
    assert affinity[:6].max() == pytest.approx(1.0)


def test_disliking_a_genre_pushes_those_films_down() -> None:
    world = _with_extras(_extra(1, genre="Drama"), _extra(2, genre="Comedy"))
    comedy_film = world.index["cw-1"]
    assert world.movies[comedy_film].genres == ("Comedy",)
    affinity = genre_affinity(world, [world.index["cw-0"]], [comedy_film])
    assert affinity[1] < 0 < affinity[0]


def test_no_taste_means_no_genre_signal() -> None:
    world = _with_extras(_extra(1), _extra(2))
    assert not genre_affinity(world, [], []).any()


def test_a_liked_ratings_only_film_makes_the_visit_personal_without_breaking_scoring() -> None:
    world = _with_extras(*_japanese())
    # Liking only a film with no similarity row must not reach the matrix (a crash), nor be cold.
    result = build_shelves(world, TasteProfile(liked_movie_ids=("ro-1",)), manifest="m")
    assert result.cold_start is False
    assert "similar" not in _shelf_ids(result)  # nothing for collaborative filtering to use
    assert "ro-1" not in _everything(result)  # a film the visitor liked is not offered again


def test_popularity_is_on_the_same_scale_as_the_full_receipt_films() -> None:
    world = _with_extras(
        _extra(1, rating=9.9, votes=10_000_000),  # beyond anything in the full-receipt tier
        _extra(2, rating=1.0, votes=1),
    )
    popularity = ratings_only_popularity(world)
    assert popularity.min() >= 0.0 and popularity.max() <= 1.0
    assert popularity[0] > popularity[1]


def test_search_lists_full_receipt_films_before_ratings_only_ones() -> None:
    world = _with_extras(_extra(1, title="Film 7 Reborn", votes=9_000_000))
    hits = [m.movie_id for m in search(world, "film 7", limit=50)]
    assert hits.index("ro-1") > hits.index("cw-7")


def test_the_movie_page_of_a_ratings_only_film_has_facts_but_no_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _with_extras(_extra(1))
    monkeypatch.setattr(api_main, "_state", api_main._State(None, world, {}, None))  # type: ignore[arg-type]
    page = api_main.movie_detail("ro-1")
    assert page.ratings_only is True
    assert page.aspects == () and page.review_count == 0
    assert (page.imdb_rating, page.imdb_votes) == (8.0, 50_000)
    assert page.imdb_url.endswith("tt9000001/")
    assert page.language == "ja" and page.runtime_minutes == 95
    with pytest.raises(KeyError):
        api_main.movie_detail("ro-404")
