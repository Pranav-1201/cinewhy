"""Tiny synthetic versions of the raw dumps, with the real column layouts.

Shared by the tests that exercise code reading the dumps. Not a test module: nothing here is
collected. Keeping the layouts in one place means a change in a real dump is fixed once.
"""

from __future__ import annotations

import csv
import io
import json
import tarfile
import zipfile
from pathlib import Path

from cinewhy.data.catalogue_sources import SourcePaths

TMDB_COLUMNS = [
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


def tmdb_row(
    tmdb_id: int,
    imdb: int,
    title: str,
    year: int,
    *,
    lang: str = "en",
    votes: int = 1000,
    runtime: float = 170.0,
) -> dict[str, str]:
    """One row of the TMDB export."""
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


def tmdb_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    """Write TMDB rows as the export's CSV."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TMDB_COLUMNS)
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


def rt_zip(
    path: Path,
    films: list[tuple[str, int, str, str]],
    reviews: list[tuple[str, str]] | list[tuple[str, str, float]],
) -> Path:
    """The Rotten Tomatoes zip.

    films: (movie id, year, title, runtime). reviews: (movie id, quote) or, to set the star
    rating, (movie id, quote, stars); the default is 4.0 stars.
    """
    movies = "".join(
        f"{mid},{year},https://www.rottentomatoes.com/m/{mid},{title},,,,,,,,English,{rt}\n"
        for mid, year, title, rt in films
    )
    rows = "".join(
        f'{review[0]},{review[2] if len(review) > 2 else 4.0},"{review[1]}",,False,False,'
        f"False,False,4.0,2020-01-01,,RT,user{i}\n"
        for i, review in enumerate(reviews)
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("movies.csv/movies.csv", _RT_MOVIES_HEADER + movies)
        z.writestr("user_reviews.csv/user_reviews.csv", _RT_REVIEWS_HEADER + rows)
    return path


def ebd_zip(path: Path, records: list[tuple[str, str, str]]) -> Path:
    """The ebD zip. records: (movie field, review id, text)."""
    payload = [
        {"movie": m, "review_id": rid, "review_detail": text, "spoiler_tag": 0, "rating": "8"}
        for m, rid, text in records
    ]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("part-01.json", json.dumps(payload))
    return path


def acl_tar(path: Path, reviews: list[tuple[int, str]]) -> Path:
    """The aclImdb archive. reviews: (imdb number, text), all filed under train/pos."""
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


def source_paths(
    folder: Path,
    *,
    tmdb: list[dict[str, str]],
    rt_films: list[tuple[str, int, str, str]] | None = None,
    rt_reviews: list[tuple[str, str]] | None = None,
    ebd: list[tuple[str, str, str]] | None = None,
    acl: list[tuple[int, str]] | None = None,
) -> SourcePaths:
    """All four dumps, written under `folder`."""
    folder.mkdir(exist_ok=True)
    return SourcePaths(
        tmdb_csv=tmdb_csv(folder / "tmdb.csv", tmdb),
        rt_zip=rt_zip(folder / "rt.zip", rt_films or [], rt_reviews or []),
        ebd_zip=ebd_zip(folder / "ebd.zip", ebd or []),
        acl_archive=acl_tar(folder / "acl.tar.gz", acl or [(999, "filler review for the archive")]),
    )


def movielens_zip(
    path: Path,
    links: list[tuple[int, int, int]],
    ratings: list[tuple[int, int, float]],
    release: str = "ml-32m",
) -> Path:
    """A MovieLens zip. links: (movie id, imdb number, tmdb id); ratings: (user, movie, stars)."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            f"{release}/links.csv",
            "movieId,imdbId,tmdbId\n" + "".join(f"{m},{i:07d},{t}\n" for m, i, t in links),
        )
        z.writestr(f"{release}/movies.csv", "movieId,title,genres\n")
        z.writestr(
            f"{release}/ratings.csv",
            "userId,movieId,rating,timestamp\n"
            + "".join(f"{u},{m},{r},0\n" for u, m, r in ratings),
        )
    return path
