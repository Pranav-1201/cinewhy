"""The pure parts of the offline build: which films qualify and whether the join is sane."""

from __future__ import annotations

from cinewhy.build import movie_id_for, review_url, select_catalogue, title_match_rate
from cinewhy.data.sources import MovieLensFilm


def _film(imdb_id: int, title: str) -> MovieLensFilm:
    return MovieLensFilm(movielens_id=imdb_id, imdb_id=imdb_id, title=title, year=2000, genres=())


class TestSelectCatalogue:
    def test_needs_enough_reviews_and_a_movielens_entry(self) -> None:
        films = {1: _film(1, "A"), 2: _film(2, "B"), 3: _film(3, "C")}
        reviews = {1: 10, 2: 9, 3: 50, 4: 99}  # 2 is too few, 4 has no MovieLens entry
        assert select_catalogue(films, reviews, 10) == [1, 3]

    def test_output_is_sorted_for_determinism(self) -> None:
        films = {i: _film(i, "x") for i in (9, 3, 5)}
        assert select_catalogue(films, {9: 20, 3: 20, 5: 20}, 10) == [3, 5, 9]


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
