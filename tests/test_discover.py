"""Discovery ranking: audience popularity, recency, language and era filters (FEATURE-005).

The cold-start list used to rank by MovieLens Bayesian mean, so a film nobody rated there (most
Hindi films) sat at the global mean and could never surface, and the top of the page was a 1949
thriller. These tests pin the replacement: a popularity signal built from IMDb's own rating and
vote count, a recency term the visitor controls, and filters that narrow the list without ever
deleting a film from the catalogue.
"""

from __future__ import annotations

import numpy as np

from cinewhy.recsys.catalogue import Catalogue, FilmStats
from cinewhy.recsys.discover import (
    RECENCY_MAX,
    DiscoverResult,
    audience_popularity,
    discover,
    film_years,
)
from cinewhy.schemas import (
    Aspect,
    AspectScore,
    EvidenceSentence,
    Movie,
    MovieAspectProfile,
    TasteProfile,
)

# id, title, year, language, imdb_rating, imdb_votes, genres, MovieLens rating count
_ROWS = [
    ("cw-1", "Old Classic", 1949, "en", 8.1, 180_000, ("Thriller",), 60_000),
    ("cw-2", "Recent Hit", 2022, "en", 7.8, 450_000, ("Action", "Drama"), 5_000),
    ("cw-3", "Hindi Hit", 2019, "hi", 8.3, 90_000, ("Drama",), 0),
    ("cw-4", "Hindi Obscure", 2021, "hi", 6.1, 800, ("Comedy",), 0),
    ("cw-5", "Mid Nineties", 1995, "en", 7.9, 300_000, ("Crime",), 70_000),
    ("cw-6", "No Scores", 2020, "en", 0.0, 0, ("Drama",), 0),
]


def _world() -> Catalogue:
    """Six films: an old classic, a recent English hit, a Hindi hit, and fillers."""
    movies = tuple(Movie(movie_id=r[0], title=r[1], year=r[2], genres=r[6]) for r in _ROWS)
    stats = tuple(FilmStats(100 + i, r[7], 3.5, 30) for i, r in enumerate(_ROWS))
    profiles = {
        m.movie_id: MovieAspectProfile(
            movie_id=m.movie_id,
            scores=(AspectScore(aspect=Aspect.ACTING, score=0.5, support=20),),
            total_reviews=30,
        )
        for m in movies
    }
    evidence: dict[str, dict[Aspect, tuple[EvidenceSentence, ...]]] = {
        m.movie_id: {
            Aspect.ACTING: (
                EvidenceSentence(
                    text=f"The acting in {m.title} is wonderful and gripping throughout.",
                    aspect=Aspect.ACTING,
                    polarity=0.8,
                    source_review_id="rt/x/1",
                ),
            )
        }
        for m in movies
    }
    meta = {
        r[0]: {
            "language": r[3],
            "imdb_rating": r[4],
            "imdb_votes": r[5],
            "release_date": f"{r[2]}-06-01",
        }
        for r in _ROWS
    }
    similarity = np.zeros((6, 6), dtype=np.float32)
    similarity[4, 0] = similarity[0, 4] = 0.9  # Mid Nineties and Old Classic are alike
    return Catalogue(movies, stats, profiles, evidence, similarity, {}, meta)


def _titles(result: DiscoverResult) -> list[str]:
    return [item.movie.title for item in result.items]


def test_audience_popularity_does_not_depend_on_movielens() -> None:
    popularity = audience_popularity(_world())
    # The Hindi hit has zero MovieLens ratings, yet it must outrank an obscure film with far
    # fewer IMDb votes and a lower score: the signal comes from IMDb, not from MovieLens.
    assert popularity[2] > popularity[3]
    assert popularity[2] > popularity[5]  # and a film with no scores at all sits near the bottom
    assert popularity.min() >= 0.0
    assert popularity.max() <= 1.0


def test_audience_popularity_falls_back_to_movielens_without_meta() -> None:
    world = _world()
    world.meta = {}
    assert audience_popularity(world).shape == (6,)  # no crash on an artifact set without meta


def test_a_large_vote_count_beats_a_slightly_higher_score_on_few_votes() -> None:
    world = _world()
    world.meta["cw-4"]["imdb_rating"] = 7.9  # a hair above 7.8, but from 800 voters not 450,000
    popularity = audience_popularity(world)
    assert popularity[1] > popularity[3]


def test_with_no_recency_the_order_is_exactly_audience_popularity() -> None:
    world = _world()
    result = discover(world, TasteProfile(), limit=6, recency=0.0, manifest="m")
    popularity = audience_popularity(world)
    expected = sorted(range(6), key=lambda i: (-float(popularity[i]), i))
    assert _titles(result) == [world.movies[i].title for i in expected]
    assert result.cold_start is True


def test_full_recency_puts_recent_films_ahead_of_the_classic() -> None:
    result = discover(_world(), TasteProfile(), limit=6, recency=1.0, manifest="m")
    order = _titles(result)
    assert order.index("Recent Hit") < order.index("Old Classic")
    assert order.index("Hindi Hit") < order.index("Old Classic")


def test_recency_is_bounded_so_it_cannot_override_a_much_better_film() -> None:
    assert 0.0 < RECENCY_MAX <= 0.35


def test_language_filter_keeps_only_that_language() -> None:
    result = discover(_world(), TasteProfile(), limit=6, languages=("hi",), manifest="m")
    assert set(_titles(result)) == {"Hindi Hit", "Hindi Obscure"}


def test_from_year_narrows_the_list_and_never_the_catalogue() -> None:
    world = _world()
    result = discover(world, TasteProfile(), limit=6, from_year=2000, manifest="m")
    assert "Old Classic" not in _titles(result)
    assert "Mid Nineties" not in _titles(result)
    assert len(world.movies) == 6


def test_to_year_keeps_older_films_and_is_inclusive() -> None:
    # The classics shelf: everything up to and including a year.
    result = discover(_world(), TasteProfile(), limit=6, to_year=1995, manifest="m")
    assert set(_titles(result)) == {"Old Classic", "Mid Nineties"}


def test_a_film_of_unknown_year_is_not_passed_off_as_a_classic() -> None:
    world = _world()
    movies = list(world.movies)
    movies[5] = movies[5].model_copy(update={"year": None})  # No Scores: no year, no date
    world.movies = tuple(movies)
    world.meta["cw-6"]["release_date"] = ""
    result = discover(world, TasteProfile(), limit=6, to_year=1999, manifest="m")
    assert "No Scores" not in _titles(result)


def test_from_year_and_to_year_make_a_window() -> None:
    result = discover(_world(), TasteProfile(), limit=6, from_year=2019, to_year=2020, manifest="m")
    assert set(_titles(result)) == {"Hindi Hit", "No Scores"}


def test_genre_filter_is_any_of() -> None:
    result = discover(_world(), TasteProfile(), limit=6, genres=("Comedy", "Crime"), manifest="m")
    assert set(_titles(result)) == {"Hindi Obscure", "Mid Nineties"}


def test_excluded_films_never_appear() -> None:
    result = discover(
        _world(), TasteProfile(), limit=6, exclude=("cw-2",), recency=1.0, manifest="m"
    )
    assert "Recent Hit" not in _titles(result)


def test_limit_and_determinism() -> None:
    first = discover(_world(), TasteProfile(), limit=3, recency=0.5, manifest="m")
    second = discover(_world(), TasteProfile(), limit=3, recency=0.5, manifest="m")
    assert len(first.items) == 3
    assert _titles(first) == _titles(second)


def test_a_filter_that_matches_nothing_gives_an_empty_list_not_an_error() -> None:
    result = discover(
        _world(), TasteProfile(), limit=6, languages=("hi",), from_year=2030, manifest="m"
    )
    assert result.items == ()


def test_every_item_carries_its_language_and_whether_it_is_new() -> None:
    result = discover(_world(), TasteProfile(), limit=6, manifest="m")
    by_title = {i.movie.title: i for i in result.items}
    assert by_title["Hindi Hit"].language == "hi"
    assert by_title["Recent Hit"].language == "en"
    assert by_title["Recent Hit"].is_new is True  # 2022: within 7 years of the newest film
    assert by_title["Hindi Hit"].is_new is True  # 2019
    assert by_title["Old Classic"].is_new is False


def test_cold_start_cards_still_carry_a_reason_to_show() -> None:
    result = discover(_world(), TasteProfile(), limit=6, manifest="m")
    assert all(item.is_fallback for item in result.items)
    assert all(item.reasons for item in result.items)  # "praised for acting", with a quote


def test_a_taste_profile_personalises_and_keeps_the_liked_film_out() -> None:
    profile = TasteProfile(liked_movie_ids=("cw-5",))
    result = discover(_world(), profile, limit=5, recency=0.0, manifest="m")
    assert result.cold_start is False
    assert "Mid Nineties" not in _titles(result)
    assert _titles(result)[0] == "Old Classic"  # the one film similar to what they liked
    assert not result.items[0].is_fallback
    assert result.items[0].reasons


def test_moving_only_the_aspect_sliders_is_a_personalised_request() -> None:
    profile = TasteProfile(aspect_weights={Aspect.ACTING: 0.8})
    result = discover(_world(), profile, limit=3, manifest="m")
    assert result.cold_start is False  # a stated preference is something to personalise on
    assert not result.items[0].is_fallback
    assert result.items[0].reasons[0].user_weight == 0.8  # "because you care about acting"


def test_the_new_window_includes_exactly_the_last_seven_years() -> None:
    world = _world()
    movies = list(world.movies)
    # Newest film is 2022; put one film at the edge (2015) and one just outside it (2014).
    movies[3] = movies[3].model_copy(update={"year": 2015})
    movies[4] = movies[4].model_copy(update={"year": 2014})
    world.movies = tuple(movies)
    by_title = {
        i.movie.title: i for i in discover(world, TasteProfile(), limit=6, manifest="m").items
    }
    assert by_title["Hindi Obscure"].is_new is True
    assert by_title["Mid Nineties"].is_new is False


def test_from_year_includes_the_year_itself() -> None:
    result = discover(_world(), TasteProfile(), limit=6, from_year=2019, manifest="m")
    assert "Hindi Hit" in _titles(result)  # released in 2019 exactly
    assert "Mid Nineties" not in _titles(result)


def test_an_exact_tie_goes_to_the_earlier_catalogue_position() -> None:
    world = _world()
    world.meta["cw-6"] = dict(world.meta["cw-4"])  # same scores and votes as cw-4
    result = discover(world, TasteProfile(), limit=6, recency=0.0, manifest="m")
    order = _titles(result)
    assert order.index("Hindi Obscure") < order.index("No Scores")


def test_among_equally_voted_films_the_better_liked_one_is_more_popular() -> None:
    world = _world()
    world.meta["cw-1"].update({"imdb_votes": 100_000, "imdb_rating": 8.4})
    world.meta["cw-5"].update({"imdb_votes": 100_000, "imdb_rating": 6.0})
    popularity = audience_popularity(world)
    assert popularity[0] > popularity[4]


def test_a_personalised_card_needs_a_real_reason_but_a_cold_one_does_not() -> None:
    world = _world()
    del world.evidence["cw-1"]  # nothing quotable about the old classic
    personal = discover(world, TasteProfile(liked_movie_ids=("cw-5",)), limit=6, manifest="m")
    assert "Old Classic" not in _titles(personal)  # an unexplained pick is not shown
    cold = discover(world, TasteProfile(), limit=6, manifest="m")
    old = next(i for i in cold.items if i.movie.title == "Old Classic")
    assert old.reasons == () and old.is_fallback  # shown for being well known, labelled as such


def test_a_film_with_no_year_takes_it_from_its_release_date() -> None:
    world = _world()
    movies = list(world.movies)
    movies[3] = movies[3].model_copy(update={"year": None})  # Hindi Obscure, released 2021
    world.movies = tuple(movies)
    assert film_years(world).tolist() == [1949, 2022, 2019, 2021, 1995, 2020]
    kept = discover(world, TasteProfile(), limit=6, from_year=2021, manifest="m")
    assert "Hindi Obscure" in _titles(kept)


def test_a_film_with_neither_year_nor_date_has_year_zero() -> None:
    world = _world()
    movies = list(world.movies)
    movies[5] = movies[5].model_copy(update={"year": None})
    world.movies = tuple(movies)
    world.meta["cw-6"]["release_date"] = ""
    assert film_years(world)[5] == 0


def test_filters_apply_to_personalised_lists_too() -> None:
    profile = TasteProfile(liked_movie_ids=("cw-5",))
    result = discover(_world(), profile, limit=5, from_year=2000, manifest="m")
    assert "Old Classic" not in _titles(result)
