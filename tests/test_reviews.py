"""Readers for the Rotten Tomatoes and ebD review dumps (FEATURE-004).

The fixtures mimic the real layouts, quirks included: RT stores each CSV inside a folder of the
same name, prefixes quotes with `:fresh:`, and often leaves `reviewId` blank; ebD is a JSON array
that mixes TV series in with films. Every exclusion rule below protects the product's promise
that a quoted sentence is a real, safe-to-show sentence from the film it is attributed to.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import cinewhy.data.reviews as reviews_module
from cinewhy.data.linking import film_key
from cinewhy.data.reviews import (
    Capped,
    SourceReview,
    clean_ebd_text,
    clean_rt_quote,
    iter_ebd_reviews,
    iter_rt_reviews,
    read_rt_films,
    rt_runtime_minutes,
    scan_ebd_keys,
)

_EN_DASH = chr(0x2013)
_LONG = "This is a thoroughly long enough review sentence to pass the length floor."

_RT_MOVIES = (
    "movieId,movieYear,movieURL,movieTitle,critic_score,critic_sentiment,audience_score,"
    "audience_sentiment,release_date_theaters,release_date_streaming,rating,original_language,"
    "runtime\n"
    "a1,1995,https://www.rottentomatoes.com/m/heat,Heat,87.0,positive,94.0,positive,"
    '"Dec 15, 1995","Jan 1, 2000",R,English,2h 50m\n'
    "b2,2016,https://www.rottentomatoes.com/m/dangal,Dangal,88.0,positive,97.0,positive,"
    '"Dec 23, 2016","Jan 1, 2018",,Hindi,2h 41m\n'
    # RT lists some films with no year at all; they cannot be joined and must be skipped.
    "c3,,https://www.rottentomatoes.com/m/unknown,Unknown,,,,,,,,English,1h 30m\n"
)
_RT_REVIEWS_HEADER = (
    "movieId,rating,quote,reviewId,isVerified,isSuperReviewer,hasSpoilers,hasProfanity,score,"
    "creationDate,userDisplayName,userRealm,userId\n"
)


def _rt_zip(path: Path, review_rows: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("movies.csv/movies.csv", _RT_MOVIES)
        z.writestr("user_reviews.csv/user_reviews.csv", _RT_REVIEWS_HEADER + "".join(review_rows))
    return path


def _rt_row(
    movie: str,
    quote: str,
    *,
    user: str = "u1",
    spoilers: bool = False,
    profanity: bool = False,
    date: str = "2020-05-01",
) -> str:
    return f'{movie},4.0,"{quote}",,False,False,{spoilers},{profanity},4.0,{date},,RT,{user}\n'


def _ebd_zip(path: Path, records: list[dict[str, object]]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("part-01.json", json.dumps(records[:2]))
        z.writestr("part-02.json", json.dumps(records[2:]))
        z.writestr("sample.json", json.dumps(records[:1]))  # must be ignored: a duplicate sample
    return path


def _ebd(movie: str, rid: str, text: str = _LONG, spoiler: int = 0) -> dict[str, object]:
    return {
        "review_id": rid,
        "movie": movie,
        "review_detail": text,
        "spoiler_tag": spoiler,
        "rating": "8",
    }


# ---- cleaning --------------------------------------------------------------------------------


def test_rt_quote_loses_the_fresh_rotten_prefix_and_later_edit_notes() -> None:
    raw = ":fresh: pretty good, somewhat predictable, and mildly funny.\n \n [2004: it is a 7.]"
    assert clean_rt_quote(raw) == "pretty good, somewhat predictable, and mildly funny."
    assert clean_rt_quote(":rotten: " + _LONG) == _LONG


def test_short_text_is_dropped_after_cleaning() -> None:
    # 40 characters is the floor measured to separate prose from bare ratings.
    assert clean_rt_quote(":fresh: great") == ""
    assert clean_ebd_text("Too short.") == ""
    assert clean_ebd_text("  " + _LONG + "\n\n ") == _LONG


def test_rt_runtime_minutes() -> None:
    assert rt_runtime_minutes("2h 50m") == 170.0
    assert rt_runtime_minutes("14m") == 14.0
    assert rt_runtime_minutes("3h") == 180.0
    assert rt_runtime_minutes("") is None
    assert rt_runtime_minutes("unknown") is None


# ---- Rotten Tomatoes -------------------------------------------------------------------------


def test_read_rt_films(tmp_path: Path) -> None:
    films = read_rt_films(_rt_zip(tmp_path / "rt.zip", []))
    heat = next(f for f in films if f.movie_id == "a1")
    assert (heat.title, heat.year, heat.runtime) == ("Heat", 1995, 170.0)
    assert heat.url == "https://www.rottentomatoes.com/m/heat"
    assert len(films) == 2


def test_rt_reviews_keep_text_of_wanted_films_only(tmp_path: Path) -> None:
    rows = [
        _rt_row("a1", ":fresh: " + _LONG, user="u1"),
        _rt_row("zz", ":fresh: " + _LONG, user="u2"),  # film we did not select
        _rt_row("a1", ":fresh: ok", user="u3"),  # too short once cleaned
    ]
    out = list(iter_rt_reviews(_rt_zip(tmp_path / "rt.zip", rows), {"a1": 113277}))
    assert [(r.imdb_id, r.text) for r in out] == [(113277, _LONG)]


def test_rt_review_ids_name_their_source_and_survive_a_blank_review_id(tmp_path: Path) -> None:
    rows = [_rt_row("a1", _LONG, user="u1", date="2020-05-01")]
    (review,) = iter_rt_reviews(_rt_zip(tmp_path / "rt.zip", rows), {"a1": 113277})
    assert review.review_id == "rt/a1/u1-2020-05-01"


def test_rt_spoilers_and_profanity_are_excluded(tmp_path: Path) -> None:
    rows = [
        _rt_row("a1", _LONG, user="u1", spoilers=True),
        _rt_row("a1", _LONG, user="u2", profanity=True),
        _rt_row("a1", _LONG, user="u3"),
    ]
    out = list(iter_rt_reviews(_rt_zip(tmp_path / "rt.zip", rows), {"a1": 113277}))
    assert [r.review_id for r in out] == ["rt/a1/u3-2020-05-01"]


def test_rt_multiline_quotes_stay_one_review(tmp_path: Path) -> None:
    quote = _LONG + "\n \n a second paragraph of the same review."
    out = list(iter_rt_reviews(_rt_zip(tmp_path / "rt.zip", [_rt_row("a1", quote)]), {"a1": 1}))
    assert len(out) == 1
    assert "second paragraph" in out[0].text


# ---- ebD -------------------------------------------------------------------------------------


def _ebd_records() -> list[dict[str, object]]:
    return [
        _ebd("Heat (1995)", "rw1"),
        _ebd("Heat (1995)", "rw2", spoiler=1),
        _ebd(f"Journey to the Unknown (1968{_EN_DASH} )", "rw3"),
        _ebd("Heat (1995)", "rw4", text="short"),
        _ebd("Dangal (2016)", "rw5"),
    ]


def test_scan_ebd_keys_counts_films_and_skips_series(tmp_path: Path) -> None:
    counts = scan_ebd_keys(_ebd_zip(tmp_path / "ebd.zip", _ebd_records()))
    assert counts[film_key("Heat", 1995)] == 3  # every film review counts, text or not
    assert counts[film_key("Dangal", 2016)] == 1
    assert all("journey" not in key for key in counts)


def test_ebd_sample_file_is_not_double_counted(tmp_path: Path) -> None:
    counts = scan_ebd_keys(_ebd_zip(tmp_path / "ebd.zip", _ebd_records()))
    assert sum(counts.values()) == 4  # rw1, rw2, rw4, rw5; sample.json ignored


def test_ebd_reviews_exclude_spoilers_series_and_short_text(tmp_path: Path) -> None:
    wanted = {film_key("Heat", 1995): 113277, film_key("Dangal", 2016): 5074352}
    out = list(iter_ebd_reviews(_ebd_zip(tmp_path / "ebd.zip", _ebd_records()), wanted))
    assert sorted(r.review_id for r in out) == ["ebd/rw1", "ebd/rw5"]
    assert {r.review_id: r.imdb_id for r in out} == {"ebd/rw1": 113277, "ebd/rw5": 5074352}


def test_ebd_unicode_survives(tmp_path: Path) -> None:
    text = "Un film superbe, très émouvant, avec des acteurs formidables et une fin parfaite."
    zpath = _ebd_zip(tmp_path / "ebd.zip", [_ebd("Heat (1995)", "rw1", text=text)])
    (review,) = iter_ebd_reviews(zpath, {film_key("Heat", 1995): 1})
    assert review.text == text


def _many(n: int) -> list[dict[str, object]]:
    return [_ebd("Heat (1995)", f"rw{i}", text=f"{_LONG} number {i}") for i in range(n)]


def test_scan_ebd_keys_is_exact_across_chunk_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real dump is read in 64 MB chunks; a record straddling two chunks must be counted
    # exactly once, not twice and not zero times.
    zpath = _ebd_zip(tmp_path / "ebd.zip", _many(30))
    expected = scan_ebd_keys(zpath)
    assert expected[film_key("Heat", 1995)] == 30
    monkeypatch.setattr(reviews_module, "_CHUNK", 101)
    assert scan_ebd_keys(zpath) == expected


def test_iter_ebd_reviews_is_exact_across_chunk_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zpath = _ebd_zip(tmp_path / "ebd.zip", _many(30))
    wanted = {film_key("Heat", 1995): 1}
    expected = sorted(r.review_id for r in iter_ebd_reviews(zpath, wanted))
    assert len(expected) == 30
    monkeypatch.setattr(reviews_module, "_CHUNK", 101)
    assert sorted(r.review_id for r in iter_ebd_reviews(zpath, wanted)) == expected


def test_a_truncated_ebd_part_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "cut.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "part-01.json", '[{"movie": "Heat (1995)", "review_id": "rw1", "review_detail": "ab'
        )
    with pytest.raises(ValueError, match="truncated"):
        list(iter_ebd_reviews(path, {film_key("Heat", 1995): 1}))


# ---- the per-film cap ------------------------------------------------------------------------


def _review(n: int, imdb: int = 1) -> SourceReview:
    return SourceReview(imdb_id=imdb, review_id=f"rt/x/{n}", text=_LONG)


def _ids(capped: Capped) -> list[str]:
    return sorted(r.review_id for r in capped.by_film()[1])


def test_cap_bounds_each_film_independently() -> None:
    capped = Capped(cap=3)
    for n in range(10):
        capped.add(_review(n, imdb=1))
    capped.add(_review(0, imdb=2))
    got = capped.by_film()
    assert len(got[1]) == 3
    assert len(got[2]) == 1


def test_cap_choice_does_not_depend_on_arrival_order() -> None:
    forward, backward = Capped(cap=4), Capped(cap=4)
    for n in range(40):
        forward.add(_review(n))
    for n in reversed(range(40)):
        backward.add(_review(n))
    assert _ids(forward) == _ids(backward)
    assert len(_ids(forward)) == 4


def test_cap_ignores_a_repeated_review_id() -> None:
    capped = Capped(cap=5)
    capped.add(_review(1))
    capped.add(_review(1))
    assert len(capped.by_film()[1]) == 1


def test_a_repeated_review_id_does_not_use_up_a_cap_slot() -> None:
    # Duplicate rows exist in the dumps. If a repeat took a slot it would push out a distinct
    # review, so a film could keep fewer different reviews than the cap allows.
    capped = Capped(cap=3)
    for n in (0, 0, 0, 0, 1, 1, 2, 2):
        capped.add(_review(n))
    assert [r.review_id for r in capped.by_film()[1]] == ["rt/x/0", "rt/x/1", "rt/x/2"]


def test_by_film_lists_are_sorted_by_review_id() -> None:
    capped = Capped(cap=50)
    for n in (3, 1, 2):
        capped.add(_review(n))
    ids = [r.review_id for r in capped.by_film()[1]]
    assert ids == sorted(ids)


def test_cap_keeps_everything_when_under_the_limit() -> None:
    capped = Capped(cap=50)
    for n in range(5):
        capped.add(_review(n))
    assert len(capped.by_film()[1]) == 5
