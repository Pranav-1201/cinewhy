"""The pure parts of the offline build: which films qualify and whether the join is sane."""

from __future__ import annotations

import json

from cinewhy.build import (
    era_of,
    film_meta,
    movie_id_for,
    review_url,
    reviews_from,
    select_films,
    source_url_for,
    title_match_rate,
)
from cinewhy.data.spine import SpineFilm


def _film(imdb_id: int, title: str = "A", year: int = 2000) -> SpineFilm:
    return SpineFilm(
        tmdb_id=imdb_id,
        imdb_id=imdb_id,
        title=title,
        year=year,
        release_date=f"{year}-01-01",
        language="en",
        vote_count=1,
        popularity=1.0,
        runtime=100.0,
        poster_path=None,
        genres=(),
        overview="",
    )


def _reviews(n: int) -> list[tuple[str, str]]:
    return [(f"rt/x/{i}", "text") for i in range(n)]


class TestSelectFilms:
    def test_a_film_needs_enough_reviews(self) -> None:
        films = (_film(1), _film(2), _film(3))
        reviews = {1: _reviews(10), 2: _reviews(9), 3: _reviews(50)}  # 2 has too few
        assert [f.imdb_id for f in select_films(films, reviews, 10)] == [1, 3]

    def test_a_film_with_no_reviews_at_all_is_not_selected(self) -> None:
        assert select_films((_film(1),), {}, 1) == []

    def test_ratings_are_not_required_to_qualify(self) -> None:
        # The old rule demanded a MovieLens entry. Most Hindi films have too few ratings for
        # collaborative filtering, yet their reviews can still say what they are like (FEATURE-004).
        films = (_film(7),)
        assert [f.imdb_id for f in select_films(films, {7: _reviews(5)}, 5)] == [7]

    def test_input_order_is_kept_so_every_artifact_is_deterministic(self) -> None:
        films = tuple(_film(i) for i in (3, 5, 9))
        reviews = {i: _reviews(20) for i in (3, 5, 9)}
        assert [f.imdb_id for f in select_films(films, reviews, 10)] == [3, 5, 9]


class TestReviewsFrom:
    def test_keeps_only_one_sources_reviews_and_drops_films_left_empty(self) -> None:
        reviews = {1: [("rt/a/1", "x"), ("ebd/rw1", "y")], 2: [("acl/train/pos/3", "z")]}
        assert reviews_from(reviews, "rt") == {1: [("rt/a/1", "x")]}
        assert reviews_from(reviews, "acl") == {2: [("acl/train/pos/3", "z")]}

    def test_a_source_name_is_a_whole_prefix_not_a_substring(self) -> None:
        assert reviews_from({1: [("rtx/a", "x")]}, "rt") == {}


class TestSourceUrl:
    def test_rt_reviews_link_to_the_rt_page_and_others_to_imdb(self) -> None:
        link = source_url_for(113277, {113277: "https://www.rottentomatoes.com/m/heat"})
        assert link("rt/a1/u-2020") == "https://www.rottentomatoes.com/m/heat"
        assert link("ebd/rw1") == "https://www.imdb.com/title/tt0113277/reviews"
        assert link("acl/train/pos/3") == "https://www.imdb.com/title/tt0113277/reviews"

    def test_an_rt_review_with_no_known_rt_page_gets_no_link_rather_than_a_wrong_one(self) -> None:
        assert source_url_for(5, {})("rt/a1/u-2020") is None


class TestFilmMeta:
    def test_carries_the_tmdb_fields_and_counts_reviews_by_source(self) -> None:
        film = _film(113277, year=1995)
        reviews = [("acl/x", "a"), ("ebd/rw1", "b"), ("ebd/rw2", "c"), ("rt/a/u", "d")]
        meta = film_meta(film, reviews, "https://rt.test/heat", rating_count=42)
        assert meta["tmdb_id"] == 113277
        assert meta["language"] == "en"
        assert meta["reviews_by_source"] == {"acl": 1, "ebd": 2, "rt": 1}
        assert meta["rt_url"] == "https://rt.test/heat"
        assert meta["rating_count"] == 42
        assert meta["poster_path"] is None

    def test_is_json_serialisable(self) -> None:
        json.dumps(film_meta(_film(1), [("rt/a/u", "x")], None, 0))


class TestEra:
    def test_boundaries(self) -> None:
        assert era_of(1999) == "pre2000"
        assert era_of(2000) == "2000-2011"
        assert era_of(2011) == "2000-2011"
        assert era_of(2012) == "2012+"


class TestIds:
    def test_movie_id_is_zero_padded_imdb_number(self) -> None:
        assert movie_id_for(453418) == "cw-0453418"

    def test_review_url_points_at_the_imdb_title_page(self) -> None:
        assert review_url(453418) == "https://www.imdb.com/title/tt0453418/reviews"


class TestJoinCheck:
    def test_a_correct_join_names_its_own_film_far_more_often_than_a_neighbour(self) -> None:
        titles = {1: "Casablanca", 2: "Metropolis", 3: "The Third Man"}
        reviews = {
            1: [("a", "Casablanca is a classic."), ("b", "I love Casablanca.")],
            2: [("c", "Metropolis was ahead of its time."), ("d", "Metropolis!")],
            3: [("e", "The Third Man has a great zither score."), ("f", "Third Man rocks")],
        }
        result = title_match_rate(titles, reviews)
        assert result["n_reviews"] == 6
        assert result["own_title_rate"] > 0.8
        assert result["other_title_rate"] == 0.0

    def test_a_shifted_join_is_visible_as_a_collapse_in_the_own_title_rate(self) -> None:
        titles = {1: "Casablanca", 2: "Metropolis", 3: "The Third Man"}
        shifted = {
            1: [("c", "Metropolis was ahead of its time.")],
            2: [("e", "The Third Man has a great zither score.")],
            3: [("a", "Casablanca is a classic.")],
        }
        result = title_match_rate(titles, shifted)
        assert result["own_title_rate"] == 0.0

    def test_titles_too_short_to_be_distinctive_are_skipped(self) -> None:
        result = title_match_rate({1: "It", 2: "Up"}, {1: [("a", "It was fine")], 2: [("b", "Up")]})
        assert result["n_reviews"] == 0
