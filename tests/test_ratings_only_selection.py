"""Choosing the ratings-only films, and the wider selection that feeds the 50-review build."""

from __future__ import annotations

from pathlib import Path

from cinewhy.data.catalogue_sources import SourcePaths, _cache_key
from cinewhy.data.spine import (
    CATALOGUE_TARGETS,
    JAPANESE_SPLIT,
    SpineFilm,
    bucket_of,
    catalogue_targets,
    choose_ratings_only,
    quota,
    select_ratings_only,
    select_spine,
    wide_quota,
)
from tests.dumps import tmdb_row


def _row(
    tmdb_id: int, lang: str, votes: int, *, rating: str = "7.0", year: int = 2010
) -> dict[str, str]:
    row = tmdb_row(tmdb_id, tmdb_id, f"Film {tmdb_id}", year, lang=lang)
    return {**row, "imdb_votes": str(votes), "imdb_rating": rating}


def _ids(films: tuple[object, ...]) -> list[int]:
    return [f.imdb_id for f in films]  # type: ignore[attr-defined]


def test_the_best_known_films_fill_a_language_up_to_its_target() -> None:
    rows = [_row(i, "fr", votes=1000 - i) for i in range(1, 9)]
    chosen = select_ratings_only(rows, taken=[], targets={"fr": 3}, min_votes=200)
    assert _ids(chosen) == [1, 2, 3]  # the three most voted, ordered by IMDb number


def test_films_that_already_have_receipts_count_towards_the_target_and_are_never_repeated() -> None:
    rows = [_row(i, "fr", votes=1000 - i) for i in range(1, 9)]
    chosen = select_ratings_only(rows, taken=[1, 2], targets={"fr": 4}, min_votes=200)
    assert _ids(chosen) == [3, 4]  # 2 taken + 2 more reaches 4; 1 and 2 are not offered again


def test_a_language_at_its_target_gets_none() -> None:
    rows = [_row(i, "ja", votes=500) for i in range(1, 5)]
    assert select_ratings_only(rows, taken=[1, 2], targets={"ja": 2}, min_votes=200) == ()


def test_too_few_votes_or_no_rating_never_qualifies() -> None:
    rows = [
        _row(1, "en", votes=199),
        _row(2, "en", votes=200),
        _row(3, "en", votes=9000, rating="0"),
        _row(4, "en", votes=9000, rating="0.0"),
    ]
    assert _ids(select_ratings_only(rows, [], {"en": 10}, min_votes=200)) == [2]


def test_a_fallback_floor_fills_a_short_language_after_the_better_voted_films() -> None:
    votes = [5000, 4000, 150, 120, 80, 30]
    rows = [_row(i + 1, "ja", votes=v) for i, v in enumerate(votes)]
    main_only = select_ratings_only(rows, [], {"ja": 5}, min_votes=200)
    assert _ids(main_only) == [1, 2]  # only two films clear the main floor
    filled = select_ratings_only(rows, [], {"ja": 5}, min_votes=200, fallback_min_votes=50)
    assert _ids(filled) == [1, 2, 3, 4, 5]  # the three best of the thin ones; 30 votes is below 50


def test_the_fallback_floor_never_displaces_a_film_above_the_main_floor() -> None:
    # Target 3: the two films above the floor are kept, and only ONE thin film is added, the
    # better voted of the two. Votes decide, not catalogue order (film 2 has the lower number).
    rows = [
        _row(1, "ja", votes=300),
        _row(2, "ja", votes=60),
        _row(3, "ja", votes=90),
        _row(4, "ja", votes=250),
    ]
    chosen = select_ratings_only(rows, [], {"ja": 3}, min_votes=200, fallback_min_votes=50)
    assert _ids(chosen) == [1, 3, 4]


def test_a_language_already_at_its_target_takes_no_fallback_films() -> None:
    rows = [_row(1, "fr", votes=900), _row(2, "fr", votes=900), _row(3, "fr", votes=80)]
    chosen = select_ratings_only(rows, [], {"fr": 2}, min_votes=200, fallback_min_votes=50)
    assert _ids(chosen) == [1, 2]


def test_a_fallback_floor_above_the_main_floor_changes_nothing() -> None:
    rows = [_row(i, "ja", votes=v) for i, v in enumerate([500, 300, 100], start=1)]
    assert select_ratings_only(rows, [], {"ja": 9}, min_votes=200, fallback_min_votes=900) == (
        select_ratings_only(rows, [], {"ja": 9}, min_votes=200)
    )


def test_a_supply_shorter_than_the_target_gives_what_exists() -> None:
    rows = [_row(i, "te", votes=400) for i in range(1, 4)]
    assert len(select_ratings_only(rows, [], {"te": 2250}, min_votes=200)) == 3


def test_languages_outside_the_targets_and_unreleased_films_are_ignored() -> None:
    unreleased = {**_row(2, "fr", 900), "status": "In Production"}
    rows = [_row(1, "de", votes=900), unreleased, _row(3, "fr", votes=900, year=2040)]
    assert select_ratings_only(rows, [], {"fr": 5}, min_votes=200, max_year=2026) == ()


def test_the_result_does_not_depend_on_row_order() -> None:
    rows = [_row(i, "fr", votes=100 * (10 - i) + 200) for i in range(1, 9)]
    forward = select_ratings_only(rows, [], {"fr": 4}, min_votes=200)
    backward = select_ratings_only(list(reversed(rows)), [], {"fr": 4}, min_votes=200)
    assert forward == backward


def _title(
    imdb: int, language: str, kind: str, votes: int, genres: tuple[str, ...] = ("Drama",)
) -> SpineFilm:
    return SpineFilm(
        tmdb_id=imdb,
        imdb_id=imdb,
        title=f"Title {imdb}",
        year=2015,
        release_date="2015-01-01",
        language=language,
        vote_count=votes,
        popularity=1.0,
        runtime=0.0,
        poster_path=None,
        genres=genres,
        overview="",
        imdb_rating=7.5,
        imdb_votes=votes,
        kind=kind,
    )


_ANIMATION = ("Animation", "Fantasy")


def test_japanese_parts_follow_the_owners_5_3_2_and_anime_films_count_as_movies() -> None:
    assert JAPANESE_SPLIT == {"ja-anime": 2500, "ja-movies": 1500, "ja-live-action": 1000}
    assert sum(JAPANESE_SPLIT.values()) == CATALOGUE_TARGETS["ja"] == 5000
    assert [JAPANESE_SPLIT[k] for k in ("ja-anime", "ja-movies", "ja-live-action")] == [
        5 * 500,
        3 * 500,
        2 * 500,
    ]
    pick = {"split_japanese": True}
    assert bucket_of("ja", "series", _ANIMATION, **pick) == "ja-anime"
    assert bucket_of("ja", "film", _ANIMATION, **pick) == "ja-movies"  # an anime FILM is a movie
    assert bucket_of("ja", "film", ("Drama",), **pick) == "ja-movies"
    assert bucket_of("ja", "series", ("Drama",), **pick) == "ja-live-action"
    assert bucket_of("ja", "series", _ANIMATION, split_japanese=False) == "ja"
    assert bucket_of("fr", "series", _ANIMATION, **pick) == "fr"


def test_the_split_replaces_the_single_japanese_target_and_leaves_the_rest() -> None:
    plain, split = catalogue_targets(split_japanese=False), catalogue_targets(split_japanese=True)
    assert plain == CATALOGUE_TARGETS and "ja" in plain
    assert "ja" not in split and sum(v for k, v in split.items() if k.startswith("ja")) == 5000
    assert {k: v for k, v in split.items() if not k.startswith("ja")} == {
        k: v for k, v in plain.items() if k != "ja"
    }


def test_each_japanese_part_fills_to_its_own_target_from_its_own_kind_of_title() -> None:
    targets = {"ja-anime": 2, "ja-movies": 1, "ja-live-action": 1}
    candidates = [
        _title(1, "ja", "series", 9000, _ANIMATION),
        _title(2, "ja", "series", 8000, _ANIMATION),
        _title(3, "ja", "series", 7000, _ANIMATION),  # a third anime series: the part is full
        _title(4, "ja", "film", 6000, _ANIMATION),  # an anime film is a movie
        _title(5, "ja", "film", 5000),  # a second movie: the part is full
        _title(6, "ja", "series", 4000),  # a live-action series
        _title(7, "ja", "series", 3000),  # a second one: full
    ]
    chosen = choose_ratings_only(candidates, [], targets, min_votes=200)
    assert _ids(chosen) == [1, 2, 4, 6]


def test_full_receipts_count_toward_their_japanese_part() -> None:
    targets = {"ja-anime": 2, "ja-movies": 1, "ja-live-action": 1}
    candidates = [
        _title(1, "ja", "series", 9000, _ANIMATION),  # already has full receipts
        _title(2, "ja", "series", 8000, _ANIMATION),
        _title(3, "ja", "series", 7000, _ANIMATION),
    ]
    assert _ids(choose_ratings_only(candidates, [1], targets, min_votes=200)) == [2]


def test_series_and_films_compete_on_votes_alone_within_a_language() -> None:
    candidates = [
        _title(1, "hi", "film", 500),
        _title(2, "hi", "series", 90_000),
        _title(3, "hi", "film", 40_000),
        _title(4, "hi", "series", 300),
    ]
    chosen = choose_ratings_only(candidates, [], {"hi": 2}, min_votes=200)
    assert _ids(chosen) == [2, 3]  # the famous series first, then the best-voted film


def test_a_series_with_no_known_language_is_never_listed() -> None:
    candidates = [_title(1, "", "series", 9000), _title(2, "fr", "series", 9000)]
    assert _ids(choose_ratings_only(candidates, [], {"fr": 5}, min_votes=200)) == [2]


def test_the_fallback_floor_reaches_a_thin_japanese_series_only_for_a_short_part() -> None:
    targets = {"ja-anime": 2, "ja-movies": 1, "ja-live-action": 1}
    candidates = [
        _title(1, "ja", "series", 5000, _ANIMATION),
        _title(2, "ja", "series", 120, _ANIMATION),  # thin: only if the part is still short
        _title(3, "ja", "series", 90, _ANIMATION),
    ]
    assert _ids(choose_ratings_only(candidates, [], targets, min_votes=200)) == [1]
    filled = choose_ratings_only(candidates, [], targets, min_votes=200, fallback_min_votes=50)
    assert _ids(filled) == [1, 2]


def test_the_targets_are_the_owners_ratio() -> None:
    # English 10,000; Hindi and Telugu 7,500 split 70/30; Japanese 5,000; French 2,500.
    assert CATALOGUE_TARGETS["hi"] + CATALOGUE_TARGETS["te"] == 7_500
    assert CATALOGUE_TARGETS["hi"] * 3 == CATALOGUE_TARGETS["te"] * 7
    assert [CATALOGUE_TARGETS[k] for k in ("en", "ja", "fr")] == [10_000, 5_000, 2_500]


def test_select_spine_takes_the_languages_it_is_given() -> None:
    rows = [_row(1, "fr", 900), _row(2, "ja", 900), _row(3, "en", 900)]
    assert _ids(select_spine(rows, quota).films) == [3]  # the default is English and Hindi only
    wide = select_spine(rows, quota, languages=("en", "fr", "ja"))
    assert _ids(wide.films) == [1, 2, 3]


def test_select_spine_honours_a_later_last_year() -> None:
    rows = [_row(1, "en", 900, year=2026)]
    assert select_spine(rows).films == ()  # the shipped selection stops at 2025
    assert _ids(select_spine(rows, max_year=2026).films) == [1]


def test_the_wide_quota_is_wider_and_never_narrower_than_the_shipped_one() -> None:
    for language in ("en", "hi", "te", "ja", "fr"):
        for year in (1960, 1999, 2000, 2024):
            assert wide_quota(language, year) >= quota(language, year)
    assert wide_quota("en", 2010) == 1000 and wide_quota("ja", 2010) == 300


def test_a_gather_cache_is_not_reused_for_another_selection(tmp_path: Path) -> None:
    for name in ("tmdb.csv", "rt.zip", "ebd.zip", "acl.tar.gz"):
        (tmp_path / name).write_bytes(b"x")
    paths = SourcePaths(
        tmdb_csv=tmp_path / "tmdb.csv",
        rt_zip=tmp_path / "rt.zip",
        ebd_zip=tmp_path / "ebd.zip",
        acl_archive=tmp_path / "acl.tar.gz",
    )
    base = _cache_key(paths, 150)
    assert base == _cache_key(paths, 150, quota)
    assert base != _cache_key(paths, 150, wide_quota)
    assert base != _cache_key(paths, 150, quota, ("en", "hi", "fr"))
    assert base != _cache_key(paths, 150, quota, None, 2026)
    # The same languages in another order are the same selection.
    assert _cache_key(paths, 150, quota, ("fr", "en")) == _cache_key(
        paths, 150, quota, ("en", "fr")
    )
