"""The home page's shelves: one request, every row, no film twice (cinewhy/recsys/shelves.py).

The world here is 300 synthetic films across 1950 to 2024, English and Hindi, three genres. It is
big enough that the 16 picks do not use up every recent or Hindi film, so every rule can be seen
working: which shelves exist, what is left out, and what each one may contain.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.recsys import shelves as shelves_module
from cinewhy.recsys.catalogue import Catalogue, FilmStats
from cinewhy.recsys.discover import audience_popularity, audience_quality
from cinewhy.recsys.shelves import (
    MIN_SHELF,
    NEW_FROM_YEAR,
    OLD_TO_YEAR,
    PICKS_SIZE,
    Shelf,
    ShelvesResult,
    build_shelves,
)
from cinewhy.schemas import (
    Aspect,
    AspectScore,
    EvidenceSentence,
    Movie,
    MovieAspectProfile,
    TasteProfile,
)

_GENRES = ("Drama", "Comedy", "Action")


def _world(n: int = 300) -> Catalogue:
    """`n` films: year 1950 + 7i mod 75, Hindi when i is a multiple of 4, genre cycling."""
    movies, stats, meta = [], [], {}
    for i in range(n):
        year = 1950 + (i * 7) % 75
        genres = (_GENRES[i % 3],)
        movies.append(Movie(movie_id=f"cw-{i}", title=f"Film {i}", year=year, genres=genres))
        stats.append(FilmStats(100 + i, 50 * i, 3.5, 30))
        meta[f"cw-{i}"] = {
            "language": "hi" if i % 4 == 0 else "en",
            "imdb_rating": 6.0 + (i % 30) / 10,
            "imdb_votes": 1000 + 997 * i,
            "release_date": f"{year}-06-01",
        }
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
    raw = np.random.default_rng(7).random((n, n))
    sim = ((raw + raw.T) / 2).astype(np.float32)
    np.fill_diagonal(sim, 0.0)
    return Catalogue(tuple(movies), tuple(stats), profiles, evidence, sim, {}, meta)


def _build(
    world: Catalogue, profile: TasteProfile | None = None, **kwargs: object
) -> ShelvesResult:
    return build_shelves(world, profile or TasteProfile(), manifest="m", **kwargs)  # type: ignore[arg-type]


def _ids(result: ShelvesResult) -> list[str]:
    return [i.movie.movie_id for s in result.shelves for i in s.items]


def _by_id(result: ShelvesResult, shelf_id: str) -> Shelf:
    return next(s for s in result.shelves if s.id == shelf_id)


@pytest.fixture(autouse=True)
def _small_world_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test world is too small for the real 25-film minimum of a language shelf: lower it."""
    monkeypatch.setattr(shelves_module, "MIN_LANGUAGE_FILMS", 5)


def test_no_film_is_on_two_shelves() -> None:
    ids = _ids(_build(_world()))
    assert len(ids) > 20
    assert len(ids) == len(set(ids))


def test_picks_comes_first_and_holds_the_spotlight_plus_fifteen() -> None:
    first = _build(_world()).shelves[0]
    assert first.id == "picks"
    assert len(first.items) == PICKS_SIZE == 16


def test_a_cold_start_has_no_personal_shelves() -> None:
    result = _build(_world())
    shelf_ids = [s.id for s in result.shelves]
    assert result.cold_start is True
    assert "similar" not in shelf_ids and "explore" not in shelf_ids
    assert _by_id(result, "picks").title == "Tonight's picks"


def test_a_liked_film_adds_similar_and_explore_and_is_never_shown_again() -> None:
    result = _build(_world(), TasteProfile(liked_movie_ids=("cw-1",)))
    shelf_ids = [s.id for s in result.shelves]
    assert result.cold_start is False
    assert "similar" in shelf_ids and "explore" in shelf_ids
    assert "cw-1" not in _ids(result)
    assert _by_id(result, "picks").title == "Picked for you"


def test_disliked_and_excluded_films_never_appear() -> None:
    result = _build(
        _world(),
        TasteProfile(liked_movie_ids=("cw-1",), disliked_movie_ids=("cw-2",)),
        exclude=("cw-3", "cw-4"),
    )
    assert not {"cw-1", "cw-2", "cw-3", "cw-4"} & set(_ids(result))


def test_new_and_classics_respect_their_years() -> None:
    result = _build(_world())
    for item in _by_id(result, "new").items:
        assert item.movie.year is not None and item.movie.year >= NEW_FROM_YEAR
    for item in _by_id(result, "classics").items:
        assert item.movie.year is not None and item.movie.year <= OLD_TO_YEAR


def test_language_shelves_follow_the_fixed_order_and_hold_only_their_language() -> None:
    result = _build(_world())
    language_shelves = [s for s in result.shelves if s.id.startswith("lang-")]
    assert [s.id for s in language_shelves] == ["lang-en", "lang-hi"]
    for shelf in language_shelves:
        assert {i.language for i in shelf.items} == {shelf.id.removeprefix("lang-")}


def test_a_visitor_who_chose_hindi_sees_only_hindi_on_every_shelf() -> None:
    result = _build(_world(), languages=("hi",))
    assert {i.language for s in result.shelves for i in s.items} == {"hi"}
    assert [s.id for s in result.shelves if s.id.startswith("lang-")] == ["lang-hi"]


def test_chosen_genres_apply_everywhere_and_remove_the_genre_shelves() -> None:
    result = _build(_world(), genres=("Drama",))
    assert not [s for s in result.shelves if s.id.startswith("genre-")]
    assert all("Drama" in i.movie.genres for s in result.shelves for i in s.items)


def test_a_year_range_limits_every_shelf() -> None:
    result = _build(_world(), from_year=1990, to_year=2010)
    years = [i.movie.year for s in result.shelves for i in s.items]
    assert years and all(y is not None and 1990 <= y <= 2010 for y in years)
    assert "classics" not in [s.id for s in result.shelves]  # nothing before 1990 is allowed


def test_a_shelf_that_comes_out_short_is_left_out() -> None:
    result = _build(_world(12))
    for shelf in result.shelves:
        assert len(shelf.items) >= (1 if shelf.id == "picks" else MIN_SHELF)


def test_a_shelf_below_the_minimum_is_not_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the minimum above any shelf's size only the picks (which needs one film) remain."""
    monkeypatch.setattr(shelves_module, "MIN_SHELF", 25)
    assert [s.id for s in _build(_world()).shelves] == ["picks"]


def test_the_visitors_earliest_year_also_limits_the_new_shelf() -> None:
    """A visitor who wants 2023 onward must not see 2021 and 2022 films on the New shelf."""
    result = _build(_world(900), from_year=2023)
    new = _by_id(result, "new")
    assert new.items and all(i.movie.year is not None and i.movie.year >= 2023 for i in new.items)


def test_explore_offers_only_films_that_are_unlike_known_and_well_liked() -> None:
    """The heading says "well reviewed": a famous but poorly rated film must never qualify."""
    world = _world()
    liked = [world.index["cw-1"]]
    popularity = audience_popularity(world)
    quality = audience_quality(world)
    order = shelves_module._explore_order(world, liked, popularity, quality)
    closeness = world.similarity[:, liked].mean(axis=1).astype(np.float64)
    unit = closeness / closeness.max()
    known_cutoff = float(np.quantile(popularity, shelves_module.EXPLORE_MIN_POPULARITY))
    quality_cutoff = float(np.quantile(quality, shelves_module.EXPLORE_MIN_QUALITY))
    assert order, "the test world should leave explore candidates"
    for i in order:
        assert unit[i] < shelves_module.EXPLORE_MAX_SIMILARITY
        assert popularity[i] >= known_cutoff
        assert quality[i] >= quality_cutoff
    worst = int(np.argmin(quality))
    assert worst not in order


def test_explore_ranks_candidates_by_quality_popularity_and_distance_from_the_taste() -> None:
    world = _world()
    liked = [world.index["cw-1"]]
    popularity = audience_popularity(world)
    quality = audience_quality(world)
    order = shelves_module._explore_order(world, liked, popularity, quality)
    closeness = world.similarity[:, liked].mean(axis=1).astype(np.float64)
    unit = closeness / closeness.max()
    ranking = [float(quality[i] * popularity[i] * (1.0 - unit[i]) ** 2) for i in order]
    assert ranking == sorted(ranking, reverse=True), "best candidate first"


def test_filters_that_match_nothing_give_no_shelves() -> None:
    assert _build(_world(), languages=("fr",)).shelves == ()


def test_the_same_request_gives_the_same_shelves() -> None:
    world = _world()
    profile = TasteProfile(liked_movie_ids=("cw-1", "cw-5"))
    assert _build(world, profile) == _build(world, profile)


def test_explore_is_less_like_the_liked_film_than_similar_is() -> None:
    world = _world()
    result = _build(world, TasteProfile(liked_movie_ids=("cw-1",)))

    def closeness(shelf_id: str) -> float:
        rows = [world.index[i.movie.movie_id] for i in _by_id(result, shelf_id).items]
        return float(world.similarity[rows, world.index["cw-1"]].mean())

    assert closeness("explore") < closeness("similar")


def test_the_route_returns_shelves_and_refuses_bad_input(artifact_dir: Path) -> None:
    with TestClient(api_main.create_app(artifact_dir)) as client:
        body = client.post("/shelves", json={}).json()
        assert body["shelves"][0]["id"] == "picks" and body["cold_start"] is True
        shown = [i["movie"]["movie_id"] for s in body["shelves"] for i in s["items"]]
        assert len(shown) == len(set(shown))
        assert client.post("/shelves", json={"languages": ["xx"]}).status_code == 422
        assert client.post("/shelves", json={"exclude_movie_ids": ["a"] * 3001}).status_code == 422
        assert client.post("/shelves", json={"surprise": 1}).status_code == 422
