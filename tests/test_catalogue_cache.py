"""The values a request would rebuild on every call are kept on the catalogue, and never go stale.

On the 106k-title v8 catalogue, rebuilding every film, every year and the filter counts cost about
half of a `/shelves` answer (D-032). The cache is keyed on the identity of the `movies` and
`ratings_only` tuples, because tests (and only tests) replace them on a built world.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from cinewhy.recsys.catalogue import Catalogue
from cinewhy.recsys.discover import (
    _language_at,
    catalogue_facets,
    expand_languages,
    film_years,
    genre_masks,
    language_codes,
    languages_of,
    score_films,
    select_items,
)
from cinewhy.schemas import Movie, TasteProfile
from tests.test_ratings_only import _extra
from tests.test_shelves import _world


def test_the_derived_values_are_computed_once_per_catalogue() -> None:
    world = _world()
    assert world.all_movies is world.all_movies
    assert film_years(world) is film_years(world)
    assert catalogue_facets(world) is catalogue_facets(world)


def test_a_value_is_computed_once_and_a_different_name_is_a_different_value() -> None:
    world = _world()
    calls: list[int] = []

    def compute() -> int:
        calls.append(1)
        return len(calls)

    assert [world.derived("probe", compute) for _ in range(3)] == [1, 1, 1]
    assert len(calls) == 1
    world.derived("other", compute)
    assert len(calls) == 2


def test_replacing_the_core_films_gives_fresh_values_not_stale_ones() -> None:
    world = _world()
    before_years = film_years(world).tolist()
    before_movies = world.all_movies
    first = world.movies[0]
    world.movies = (
        Movie(movie_id=first.movie_id, title=first.title, year=1901, genres=first.genres),
        *world.movies[1:],
    )
    assert world.all_movies is not before_movies and world.all_movies[0].year == 1901
    assert film_years(world)[0] == 1901 and film_years(world).tolist() != before_years
    assert catalogue_facets(world)["oldest_year"] == 1901


def test_replacing_the_ratings_only_films_gives_fresh_values_not_stale_ones() -> None:
    world = _world()
    n = len(world.all_movies)
    facets_before = catalogue_facets(world)
    world.ratings_only = (_extra(1, language="ja", year=1899),)
    assert len(world.all_movies) == n + 1
    assert len(film_years(world)) == n + 1
    after = catalogue_facets(world)
    assert after is not facets_before
    assert after["films"] == facets_before["films"] + 1  # type: ignore[operator]
    assert after["oldest_year"] == 1899


def test_a_kept_value_equals_one_computed_from_scratch() -> None:
    world = replace(_world(), ratings_only=(_extra(1), _extra(2, language="fr", year=1980)))
    kept = (world.all_movies, film_years(world), catalogue_facets(world))
    # `replace` builds a new catalogue, so it starts with nothing kept.
    fresh_world = replace(world)
    assert fresh_world.all_movies == kept[0]
    assert np.array_equal(film_years(fresh_world), kept[1])
    assert catalogue_facets(fresh_world) == kept[2]


def _mixed_world() -> Catalogue:
    extras = (
        _extra(1, language="ja", genre="Animation", year=2019),
        _extra(2, language="fr", genre="Drama", year=1985),
        _extra(3, language="hi", genre="Comedy", year=2023),
    )
    return replace(_world(), ratings_only=extras)


def test_the_language_list_and_codes_match_a_plain_lookup_for_every_film() -> None:
    world = _mixed_world()
    plain = [_language_at(world, p) for p in range(len(world.all_movies))]
    assert languages_of(world) == plain and languages_of(world) is languages_of(world)
    assert language_codes(world).tolist() == [lang or "" for lang in plain]


def test_a_genre_mask_marks_exactly_the_films_that_carry_the_genre() -> None:
    world = _mixed_world()
    masks = genre_masks(world)
    assert genre_masks(world) is masks
    every_genre = {g for m in world.all_movies for g in m.genres}
    assert set(masks) == every_genre
    for genre in every_genre:
        assert masks[genre].tolist() == [genre in m.genres for m in world.all_movies]


def test_a_film_with_no_known_language_matches_no_language_filter() -> None:
    nameless = replace(_extra(7, genre="Drama"), language=None)
    world = replace(_world(), ratings_only=(nameless,))
    assert languages_of(world)[-1] is None and language_codes(world)[-1] == ""
    scored = score_films(world, TasteProfile(), recency=0.0)
    for code in ("en", "hi", "ja", "fr"):
        shown = select_items(world, scored, limit=len(world.all_movies), languages=(code,))
        assert "ro-7" not in [item.movie.movie_id for item in shown]
    everything = select_items(world, scored, limit=len(world.all_movies))
    assert "ro-7" in [item.movie.movie_id for item in everything]  # no filter: still listed


def test_the_masks_follow_replaced_films_like_everything_else_kept() -> None:
    world = _mixed_world()
    assert "Horror" not in genre_masks(world)
    world.ratings_only = (_extra(9, language="fr", genre="Horror"),)
    assert genre_masks(world)["Horror"].sum() == 1
    assert language_codes(world)[-1] == "fr" and len(language_codes(world)) == len(world.all_movies)


def test_filters_by_language_and_genre_keep_the_films_a_plain_loop_would() -> None:
    world = _mixed_world()
    scored = score_films(world, TasteProfile(), recency=0.0)
    everyone = len(world.all_movies)
    for languages, genres in (
        (("ja",), ()),
        (("fr", "hi"), ()),
        ((), ("Animation",)),
        ((), ("Comedy", "Drama")),
        (("hi",), ("Comedy",)),
        (("hi",), ("Animation",)),  # nothing is both: empty, not everything
        ((), ("No Such Genre",)),
    ):
        wanted_languages = expand_languages(languages) if languages else None
        expected = [
            m.movie_id
            for p, m in enumerate(world.all_movies)
            if (wanted_languages is None or _language_at(world, p) in wanted_languages)
            and (not genres or set(genres) & set(m.genres))
        ]
        got = [
            item.movie.movie_id
            for item in select_items(
                world, scored, limit=everyone, languages=languages, genres=genres
            )
        ]
        assert sorted(got) == sorted(expected), (languages, genres)


def test_two_catalogues_never_share_kept_values() -> None:
    small, larger = _world(), replace(_world(), ratings_only=(_extra(1),))
    assert len(larger.all_movies) == len(small.all_movies) + 1
    assert len(film_years(larger)) == len(film_years(small)) + 1
