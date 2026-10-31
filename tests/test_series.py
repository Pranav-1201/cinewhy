"""TV series: IMDb's list, TMDB's details, and ebD's series reviews (cinewhy/data/series.py)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from cinewhy.data.linking import film_key, parse_ebd_movie, parse_ebd_series
from cinewhy.data.reviews import iter_ebd_reviews, scan_ebd_keys
from cinewhy.data.series import (
    ImdbSeries,
    imdb_number,
    iter_series_films,
    read_imdb_series,
    read_tmdb_tv,
    series_genres,
    to_spine_film,
)
from tests.dumps import ebd_zip

_EN_DASH = chr(0x2013)
_BASICS_HEADER = (
    "tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear\t"
    "runtimeMinutes\tgenres\n"
)
_RATINGS_HEADER = "tconst\taverageRating\tnumVotes\n"


def _gz(path: Path, text: str) -> Path:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def _dumps(tmp_path: Path) -> tuple[Path, Path]:
    basics = (
        _BASICS_HEADER
        + "tt0000003\ttvSeries\tThird\tThird\t0\t2005\t\\N\t45\tDrama,Sci-Fi\n"
        + "tt0000001\ttvMiniSeries\tFirst\tPremier\t0\t1999\t2000\t60\tComedy\n"
        + "tt0000002\tmovie\tA Film\tA Film\t0\t2001\t\\N\t100\tDrama\n"
        + "tt0000004\ttvSeries\tNo Start\tNo Start\t0\t\\N\t\\N\t30\tDrama\n"
        + "tt0000005\ttvSeries\tToo Few\tToo Few\t0\t2010\t\\N\t30\tDrama\n"
        + "tt0000006\ttvEpisode\tAn Episode\tAn Episode\t0\t2010\t\\N\t30\tDrama\n"
        + "tt0000007\ttvSeries\tTalk Show\tTalk Show\t0\t2012\t\\N\t30\tTalk-Show,Reality-TV\n"
    )
    ratings = (
        _RATINGS_HEADER
        + "tt0000001\t7.5\t900\n"
        + "tt0000002\t8.0\t5000\n"
        + "tt0000003\t8.8\t12000\n"
        + "tt0000004\t6.0\t800\n"
        + "tt0000005\t6.0\t120\n"
        + "tt0000006\t9.0\t9000\n"
        + "tt0000007\t5.0\t1000\n"
    )
    return _gz(tmp_path / "basics.tsv.gz", basics), _gz(tmp_path / "ratings.tsv.gz", ratings)


def test_genres_use_the_films_names_and_drop_ones_nobody_filters_by() -> None:
    assert series_genres("Drama,Sci-Fi,Musical") == ("Drama", "Science Fiction", "Music")
    assert series_genres("Talk-Show,Reality-TV,News,Sport,Biography") == ()
    assert series_genres("\\N") == ()
    assert series_genres("") == ()


def test_an_imdb_number_is_read_from_a_title_id() -> None:
    assert imdb_number("tt0903747") == 903747
    assert imdb_number("nm0000001") is None
    assert imdb_number("tt") is None


def test_only_series_with_a_start_year_and_enough_votes_are_listed(tmp_path: Path) -> None:
    basics, ratings = _dumps(tmp_path)
    found = read_imdb_series(basics, ratings, min_votes=200)
    # Series and miniseries only; no film, no episode; a year; and 200 or more votes.
    assert [s.imdb_id for s in found] == [1, 3, 7]
    first = found[0]
    assert (first.title, first.original_title, first.start_year, first.miniseries) == (
        "First",
        "Premier",
        1999,
        True,
    )
    assert (first.votes, first.rating, first.genres) == (900, 7.5, ("Comedy",))
    assert found[1].genres == ("Drama", "Science Fiction") and found[1].miniseries is False


def test_the_vote_floor_is_inclusive_and_lowering_it_adds_series(tmp_path: Path) -> None:
    basics, ratings = _dumps(tmp_path)
    assert [s.imdb_id for s in read_imdb_series(basics, ratings, min_votes=900)] == [1, 3, 7]
    assert [s.imdb_id for s in read_imdb_series(basics, ratings, min_votes=901)] == [3, 7]
    assert 5 in [s.imdb_id for s in read_imdb_series(basics, ratings, min_votes=100)]


def test_the_cache_keeps_found_series_and_survives_a_torn_last_line(tmp_path: Path) -> None:
    cache = tmp_path / "tmdb_tv.jsonl"
    cache.write_text(
        json.dumps({"imdb": 1, "found": True, "tmdb_id": 11, "original_language": "ja"})
        + "\n"
        + json.dumps({"imdb": 2, "found": False})
        + "\n"
        + '{"imdb": 3, "found": tr',  # an interrupted download
        encoding="utf-8",
    )
    assert set(read_tmdb_tv(cache)) == {1}
    assert read_tmdb_tv(tmp_path / "missing.jsonl") == {}


def _series(**changes: object) -> ImdbSeries:
    base = ImdbSeries(7, "Title", "Orig", 2015, ("Drama",), 5000, 8.1, False)
    return ImdbSeries(**{**base.__dict__, **changes})


def test_a_series_becomes_a_build_record_with_imdbs_numbers_and_tmdbs_looks() -> None:
    tmdb = {
        "tmdb_id": 99,
        "original_language": "ja",
        "first_air_date": "2015-04-05",
        "overview": "A story.",
        "poster_path": "/p.jpg",
        "vote_count": 321,
        "vote_average": 7.9,
        "popularity": 12.5,
    }
    film = to_spine_film(_series(), tmdb)
    assert film.kind == "series" and film.imdb_id == 7 and film.tmdb_id == 99
    assert (film.title, film.original_title, film.year) == ("Title", "Orig", 2015)
    assert (film.language, film.release_date, film.poster_path) == ("ja", "2015-04-05", "/p.jpg")
    assert (film.imdb_rating, film.imdb_votes, film.genres) == (8.1, 5000, ("Drama",))
    assert film.runtime == 0.0 and film.overview == "A story."


def test_missing_tmdb_details_fall_back_without_inventing_any() -> None:
    film = to_spine_film(_series(), {"tmdb_id": 5, "first_air_date": "", "poster_path": None})
    assert film.release_date == "2015-01-01"  # the year IMDb gave, as a date
    assert film.poster_path is None and film.language == "" and film.overview == ""


def test_only_series_tmdb_knows_are_built_and_in_imdb_number_order() -> None:
    series = [_series(imdb_id=3), _series(imdb_id=9), _series(imdb_id=5)]
    known = {5: {"tmdb_id": 50}, 3: {"tmdb_id": 30}}
    assert [f.imdb_id for f in iter_series_films(series, known)] == [3, 5]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"Breaking Bad (2008{_EN_DASH}2013)", ("Breaking Bad", 2008)),
        (f"Dark (2017{_EN_DASH} )", ("Dark", 2017)),
        ("Dark (2017- )", ("Dark", 2017)),
        ("Heat (1995)", None),  # a film
        ("A Video Release (2009 Video)", None),
        ("No year at all", None),
    ],
)
def test_an_ebd_series_field_gives_its_title_and_start_year(
    raw: str, expected: tuple[str, int] | None
) -> None:
    assert parse_ebd_series(raw) == expected


def test_a_field_is_a_film_or_a_series_never_both() -> None:
    for raw in ("Heat (1995)", f"Dark (2017{_EN_DASH} )", f"Show (2008{_EN_DASH}2013)"):
        assert (parse_ebd_movie(raw) is None) != (parse_ebd_series(raw) is None)


_REVIEW = "The acting in this was superb, and the story held me from the first to the last episode."


def _ebd(tmp_path: Path) -> Path:
    return ebd_zip(
        tmp_path / "ebd.zip",
        [
            (f"Dark (2017{_EN_DASH} )", "s1", _REVIEW),
            (f"Dark (2017{_EN_DASH} )", "s2", _REVIEW + " Again."),
            (f"Other Show (2010{_EN_DASH}2012)", "s3", _REVIEW),
            ("Heat (1995)", "f1", _REVIEW),
        ],
    )


def test_the_key_scan_counts_films_by_default_and_series_when_asked(tmp_path: Path) -> None:
    archive = _ebd(tmp_path)
    assert scan_ebd_keys(archive) == {film_key("Heat", 1995): 1}
    series = scan_ebd_keys(archive, parse_ebd_series)
    assert series == {film_key("Dark", 2017): 2, film_key("Other Show", 2010): 1}


def test_series_reviews_are_read_under_their_start_year_and_films_are_not_mixed_in(
    tmp_path: Path,
) -> None:
    archive = _ebd(tmp_path)
    wanted = {film_key("Dark", 2017): 7, film_key("Heat", 1995): 8}
    got = list(iter_ebd_reviews(archive, wanted, parse_ebd_series))
    assert sorted((r.imdb_id, r.review_id) for r in got) == [(7, "ebd/s1"), (7, "ebd/s2")]
    films = list(iter_ebd_reviews(archive, wanted))  # the default is still films only
    assert [(r.imdb_id, r.review_id) for r in films] == [(8, "ebd/f1")]
