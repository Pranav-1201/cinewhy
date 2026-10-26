"""Gathering the catalogue's films and reviews from four dumps (FEATURE-004).

Tiny synthetic versions of each dump, with the real column layouts. The scenarios are the ways a
multi-source join goes wrong silently: the same IMDb review present in two dumps, a TV series with
a film's title, two films that share a title and year, and a year that is off by one.
"""

from __future__ import annotations

import csv
import io
import json
import tarfile
import zipfile
from pathlib import Path

from cinewhy.data.catalogue_sources import Gathered, SourcePaths, gather

_EN_DASH = chr(0x2013)
_HEAT = "The pacing in Heat is superb, and the pacing never drags once in almost three hours."
_TMDB_COLUMNS = [
    "id",
    "imdb_id",
    "title",
    "release_date",
    "original_language",
    "vote_count",
    "status",
    "runtime",
    "popularity",
    "poster_path",
    "genres",
    "overview",
    "imdb_rating",
    "imdb_votes",
    "vote_average",
]


def _tmdb_row(
    tmdb_id: int,
    imdb: int,
    title: str,
    year: int,
    *,
    lang: str = "en",
    votes: int = 1000,
    runtime: float = 170.0,
) -> dict[str, str]:
    return {
        "id": str(tmdb_id),
        "imdb_id": f"tt{imdb:07d}",
        "title": title,
        "release_date": f"{year}-06-01",
        "original_language": lang,
        "vote_count": str(votes),
        "status": "Released",
        "runtime": str(runtime),
        "popularity": "9.0",
        "poster_path": "/p.jpg",
        "genres": "Crime, Drama",
        "overview": "A film.",
        "imdb_rating": "7.4",
        "imdb_votes": "10069.0",
        "vote_average": "7.1",
    }


def _tmdb_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_TMDB_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


_RT_MOVIES_HEADER = (
    "movieId,movieYear,movieURL,movieTitle,critic_score,critic_sentiment,audience_score,"
    "audience_sentiment,release_date_theaters,release_date_streaming,rating,original_language,"
    "runtime\n"
)
_RT_REVIEWS_HEADER = (
    "movieId,rating,quote,reviewId,isVerified,isSuperReviewer,hasSpoilers,hasProfanity,score,"
    "creationDate,userDisplayName,userRealm,userId\n"
)


def _rt_zip(
    path: Path, films: list[tuple[str, int, str, str]], reviews: list[tuple[str, str]]
) -> Path:
    """films: (movie id, year, title, runtime text); reviews: (movie id, quote)."""
    movies = "".join(
        f"{mid},{year},https://www.rottentomatoes.com/m/{mid},{title},,,,,,,,English,{rt}\n"
        for mid, year, title, rt in films
    )
    rows = "".join(
        f'{mid},4.0,"{quote}",,False,False,False,False,4.0,2020-01-01,,RT,user{i}\n'
        for i, (mid, quote) in enumerate(reviews)
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("movies.csv/movies.csv", _RT_MOVIES_HEADER + movies)
        z.writestr("user_reviews.csv/user_reviews.csv", _RT_REVIEWS_HEADER + rows)
    return path


def _ebd_zip(path: Path, records: list[tuple[str, str, str]]) -> Path:
    """records: (movie field, review id, text)."""
    payload = [
        {"movie": m, "review_id": rid, "review_detail": text, "spoiler_tag": 0, "rating": "8"}
        for m, rid, text in records
    ]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("part-01.json", json.dumps(payload))
    return path


def _acl_tar(path: Path, reviews: list[tuple[int, str]]) -> Path:
    """reviews: (imdb number, text); all filed under train/pos."""
    urls = "".join(f"http://www.imdb.com/title/tt{imdb:07d}/usercomments\n" for imdb, _ in reviews)
    with tarfile.open(path, "w:gz") as tar:
        members = {"aclImdb/train/urls_pos.txt": urls}
        members.update(
            {f"aclImdb/train/pos/{n}_9.txt": text for n, (_, text) in enumerate(reviews)}
        )
        for name, content in members.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _paths(
    folder: Path,
    *,
    tmdb: list[dict[str, str]],
    rt_films: list[tuple[str, int, str, str]] | None = None,
    rt_reviews: list[tuple[str, str]] | None = None,
    ebd: list[tuple[str, str, str]] | None = None,
    acl: list[tuple[int, str]] | None = None,
) -> SourcePaths:
    folder.mkdir(exist_ok=True)
    return SourcePaths(
        tmdb_csv=_tmdb_csv(folder / "tmdb.csv", tmdb),
        rt_zip=_rt_zip(folder / "rt.zip", rt_films or [], rt_reviews or []),
        ebd_zip=_ebd_zip(folder / "ebd.zip", ebd or []),
        acl_archive=_acl_tar(
            folder / "acl.tar.gz", acl or [(999, "filler review for the archive")]
        ),
    )


def _ids(result: Gathered, imdb: int) -> list[str]:
    return [rid for rid, _ in result.reviews.get(imdb, [])]


def _sources(result: Gathered, imdb: int) -> list[str]:
    return sorted(rid.split("/")[0] for rid in _ids(result, imdb))


def test_a_film_collects_reviews_from_every_source_with_prefixed_ids(tmp_path: Path) -> None:
    paths = _paths(
        tmp_path,
        tmdb=[_tmdb_row(949, 113277, "Heat", 1995)],
        rt_films=[("a1", 1995, "Heat", "2h 50m")],
        rt_reviews=[("a1", "Heat is a masterpiece of tension and character, beautifully made.")],
        ebd=[("Heat (1995)", "rw1", "A towering crime epic with two great leads and a heist.")],
        acl=[(113277, "An older review of Heat that mentions the shootout on the street.")],
    )
    result = gather(paths)
    assert _sources(result, 113277) == ["acl", "ebd", "rt"]
    assert result.rt_url[113277] == "https://www.rottentomatoes.com/m/a1"


def test_the_same_review_in_two_dumps_is_kept_once_with_the_older_source(tmp_path: Path) -> None:
    # aclImdb and ebD are both scrapes of IMDb, so one review can sit in both.
    shared = "A towering crime epic with two great leads and a famous bank robbery scene."
    paths = _paths(
        tmp_path,
        tmdb=[_tmdb_row(949, 113277, "Heat", 1995)],
        ebd=[("Heat (1995)", "rw1", shared.upper())],  # case differs: still the same review
        acl=[(113277, shared)],
    )
    result = gather(paths)
    assert _sources(result, 113277) == ["acl"]
    assert result.report["duplicates_dropped"] == 1


def test_a_tv_series_with_the_films_title_gives_it_no_reviews(tmp_path: Path) -> None:
    paths = _paths(
        tmp_path,
        tmdb=[_tmdb_row(949, 113277, "Heat", 1995)],
        ebd=[(f"Heat (1995{_EN_DASH} )", "rw9", _HEAT)],
    )
    result = gather(paths)
    assert _ids(result, 113277) == []
    # A film with no reviews is absent, not listed with an empty list: callers test membership.
    assert 113277 not in result.reviews
    assert result.report["films_with_reviews"] == 0


def test_ebd_gets_exact_years_only(tmp_path: Path) -> None:
    paths = _paths(
        tmp_path,
        tmdb=[_tmdb_row(949, 113277, "Heat", 1995)],
        ebd=[("Heat (1996)", "rw1", _HEAT)],  # off by one year, and ebD has no runtime to confirm
    )
    assert _ids(gather(paths), 113277) == []


def test_rt_accepts_an_adjacent_year_only_when_the_runtime_agrees(tmp_path: Path) -> None:
    quote = "Heat is a masterpiece of tension and character, beautifully made."
    agree = _paths(
        tmp_path / "agree",
        tmdb=[_tmdb_row(949, 113277, "Heat", 1995)],
        rt_films=[("a1", 1996, "Heat", "2h 51m")],
        rt_reviews=[("a1", quote)],
    )
    assert _sources(gather(agree), 113277) == ["rt"]
    differ = _paths(
        tmp_path / "differ",
        tmdb=[_tmdb_row(949, 113277, "Heat", 1995)],
        rt_films=[("a1", 1996, "Heat", "1h 20m")],
        rt_reviews=[("a1", quote)],
    )
    assert _ids(gather(differ), 113277) == []


def test_an_exact_year_claim_beats_an_adjacent_year_claim_on_one_rt_film(tmp_path: Path) -> None:
    quote = "Heat is a masterpiece of tension and character, beautifully made."
    paths = _paths(
        tmp_path,
        # 1995 reaches the RT film only through the adjacent year; 1996 matches it exactly.
        tmdb=[_tmdb_row(1, 100, "Heat", 1995), _tmdb_row(2, 200, "Heat", 1996)],
        rt_films=[("a1", 1996, "Heat", "2h 50m")],
        rt_reviews=[("a1", quote)],
    )
    result = gather(paths)
    assert _sources(result, 200) == ["rt"]
    assert _ids(result, 100) == []


def test_two_adjacent_year_claims_on_one_rt_film_leave_it_with_neither(tmp_path: Path) -> None:
    quote = "Heat is a masterpiece of tension and character, beautifully made."
    paths = _paths(
        tmp_path,
        # 1995 and 1997 are each one year from the RT film (1996) and equally plausible.
        tmdb=[_tmdb_row(1, 100, "Heat", 1995), _tmdb_row(2, 200, "Heat", 1997)],
        rt_films=[("a1", 1996, "Heat", "2h 50m")],
        rt_reviews=[("a1", quote)],
    )
    result = gather(paths)
    assert _ids(result, 100) == [] and _ids(result, 200) == []
    assert result.report["rt_contested_films"] == 1
    # The contested film's reviews must not even be read in under a made-up owner.
    assert result.report["reviews_per_source_after_cap"]["rt"] == 0
    assert -1 not in result.rt_url


def test_two_films_sharing_a_title_and_year_get_no_title_joined_reviews(tmp_path: Path) -> None:
    # Which of the two a review of "Don (2006)" belongs to cannot be known; guessing would put
    # reviews on the wrong film.
    paths = _paths(
        tmp_path,
        tmdb=[_tmdb_row(1, 100, "Don", 2006, lang="hi"), _tmdb_row(2, 200, "Don", 2006, lang="hi")],
        ebd=[("Don (2006)", "rw1", _HEAT)],
        acl=[(100, "An aclImdb review of the first Don, matched by id and not by title.")],
    )
    result = gather(paths)
    assert _ids(result, 200) == []
    assert _sources(result, 100) == ["acl"]  # the id join is still exact
    assert result.report["candidate_title_collisions"] == 2


def test_the_report_counts_outcomes_per_source_and_language(tmp_path: Path) -> None:
    paths = _paths(
        tmp_path,
        tmdb=[_tmdb_row(949, 113277, "Heat", 1995), _tmdb_row(5, 500, "Missing", 2001, lang="hi")],
        rt_films=[("a1", 1995, "Heat", "2h 50m")],
        rt_reviews=[("a1", "Heat is a masterpiece of tension and character, beautifully made.")],
        ebd=[("Heat (1995)", "rw1", _HEAT)],
    )
    report = gather(paths).report
    assert report["films_selected"] == 2
    assert report["rt_link"] == {"en/exact": 1, "hi/none": 1}
    assert report["ebd_link"] == {"en/exact": 1, "hi/none": 1}
    json.dumps(report)  # the report goes into eval.json, so it must be JSON-serialisable


def test_reviews_are_sorted_by_id_so_the_build_is_reproducible(tmp_path: Path) -> None:
    paths = _paths(
        tmp_path,
        tmdb=[_tmdb_row(949, 113277, "Heat", 1995)],
        ebd=[("Heat (1995)", f"rw{n}", f"{_HEAT} Take number {n}.") for n in (3, 1, 2)],
    )
    ids = _ids(gather(paths), 113277)
    assert ids == sorted(ids)
    assert len(ids) == 3
