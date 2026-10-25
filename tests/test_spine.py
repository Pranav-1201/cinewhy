"""Choosing which films enter the catalogue from the TMDB export (FEATURE-004).

The selection rules are product decisions with measured consequences, so each one is pinned:
quotas per language and era, ranking by audience votes, and the three ways a row is unusable
(wrong language or status, no IMDb number, a duplicate IMDb number).
"""

from __future__ import annotations

from collections.abc import Mapping

from cinewhy.data.spine import parse_imdb_id, quota, select_spine


def _row(
    tmdb_id: int,
    *,
    imdb: str | None = None,
    year: int = 2015,
    language: str = "en",
    votes: int = 100,
    status: str = "Released",
    title: str | None = None,
    poster: str = "/p.jpg",
    genres: str = "Drama, Crime",
) -> Mapping[str, str]:
    return {
        "id": str(tmdb_id),
        "imdb_id": imdb if imdb is not None else f"tt{tmdb_id:07d}",
        "title": title or f"Film {tmdb_id}",
        "release_date": f"{year}-06-01",
        "original_language": language,
        "vote_count": str(votes),
        "status": status,
        "runtime": "100.0",
        "popularity": "5.5",
        "poster_path": poster,
        "genres": genres,
        "overview": "A film.",
    }


def test_quota_follows_the_agreed_numbers_and_boundary() -> None:
    assert quota("en", 1999) == 75
    assert quota("hi", 1999) == 25
    assert quota("en", 2000) == 300
    assert quota("hi", 2000) == 70


def test_parse_imdb_id() -> None:
    assert parse_imdb_id("tt0094675") == 94675
    assert parse_imdb_id("tt1234567890") == 1234567890
    assert parse_imdb_id("") is None
    assert parse_imdb_id("nm0000001") is None
    assert parse_imdb_id("tt") is None


def test_keeps_the_most_voted_films_per_language_and_year() -> None:
    rows = [_row(i, votes=v) for i, v in [(1, 10), (2, 500), (3, 50)]]
    rows.append(_row(4, votes=900, language="hi"))
    result = select_spine(rows, quota_for=lambda lang, year: 2 if lang == "en" else 1)
    assert sorted(f.tmdb_id for f in result.films) == [2, 3, 4]


def test_vote_ties_break_by_tmdb_id_so_the_selection_is_deterministic() -> None:
    rows = [_row(i, votes=7) for i in (30, 10, 20)]
    result = select_spine(rows, quota_for=lambda lang, year: 2)
    assert sorted(f.tmdb_id for f in result.films) == [10, 20]


def test_unusable_rows_are_dropped_and_counted() -> None:
    rows = [
        _row(1),
        _row(2, status="Post Production"),
        _row(3, language="fr"),
        _row(4, year=1949),
        _row(5, year=2026),
        _row(6, imdb=""),
    ]
    result = select_spine(rows, quota_for=lambda lang, year: 10)
    assert [f.tmdb_id for f in result.films] == [1]
    assert result.dropped_no_imdb == 1


def test_a_film_with_no_imdb_number_does_not_use_up_a_quota_slot() -> None:
    # Ranked first by votes but unusable; the quota must go to usable films, or a year of
    # popular films could be silently emptied.
    rows = [_row(1, votes=999, imdb=""), _row(2, votes=5), _row(3, votes=4)]
    result = select_spine(rows, quota_for=lambda lang, year: 2)
    assert sorted(f.tmdb_id for f in result.films) == [2, 3]


def test_duplicate_imdb_numbers_keep_the_most_voted_row() -> None:
    rows = [_row(1, imdb="tt0000100", votes=5), _row(2, imdb="tt0000100", votes=50)]
    result = select_spine(rows, quota_for=lambda lang, year: 10)
    assert [f.tmdb_id for f in result.films] == [2]
    assert result.dropped_duplicate_imdb == 1


def test_fields_are_parsed_and_output_is_sorted_by_imdb_number() -> None:
    # TMDB id order (1, 2) is the opposite of IMDb order (200, 100): only an explicit sort by
    # IMDb number yields [100, 200], so a missing sort cannot pass by coincidence.
    rows = [
        _row(2, imdb="tt0000100", poster="", genres="Drama, Romance"),
        _row(1, imdb="tt0000200"),
    ]
    result = select_spine(rows, quota_for=lambda lang, year: 10)
    assert [f.imdb_id for f in result.films] == [100, 200]
    first = result.films[0]
    assert first.tmdb_id == 2
    assert first.poster_path is None
    assert first.genres == ("Drama", "Romance")
    assert first.year == 2015
    assert first.runtime == 100.0
