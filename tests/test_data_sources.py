"""The aclImdb x MovieLens join, exercised on tiny synthetic archives.

The join is the product's foundation: if line N of a URL file were paired with the wrong
review file, every aspect score would be attached to the wrong film and nothing downstream
would notice. These tests build archives where each review's text names its own film, so a
mis-pairing is visible as a text/film disagreement.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from cinewhy.data.sources import (
    iter_reviews,
    load_films,
    load_movielens_links,
    load_ratings,
    parse_title,
)

_URL = "http://www.imdb.com/title/tt{:07d}/usercomments\n"


def _add(tar: tarfile.TarFile, name: str, content: str) -> None:
    data = content.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _make_acl(path: Path) -> None:
    """Three films; each review's text says which tt number it should map to."""
    with tarfile.open(path, "w:gz") as tar:
        # train/pos: file 0 -> tt100, file 1 -> tt200 (order matters: line N <-> file N)
        _add(tar, "aclImdb/train/urls_pos.txt", _URL.format(100) + _URL.format(200))
        _add(tar, "aclImdb/train/pos/0_9.txt", "about 100 pos")
        _add(tar, "aclImdb/train/pos/1_8.txt", "about 200 pos")
        _add(tar, "aclImdb/train/urls_neg.txt", _URL.format(100))
        _add(tar, "aclImdb/train/neg/0_2.txt", "about 100 neg")
        _add(tar, "aclImdb/train/urls_unsup.txt", _URL.format(300))
        _add(tar, "aclImdb/train/unsup/0_0.txt", "about 300 unsup")
        _add(tar, "aclImdb/train/pos/9_7.txt", "orphan: no url line 9")


def _make_ml(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ml-25m/links.csv", "movieId,imdbId,tmdbId\n1,0000100,5\n2,0000200,6\n3,,7\n")
        z.writestr(
            "ml-25m/movies.csv",
            'movieId,title,genres\n1,"Matrix, The (1999)",Action|Sci-Fi\n'
            "2,Heat (1995),(no genres listed)\n3,Unlinked (2000),Drama\n",
        )
        z.writestr(
            "ml-25m/ratings.csv",
            "userId,movieId,rating,timestamp\n10,1,4.5,0\n10,2,3.0,0\n11,3,5.0,0\n11,1,2.0,0\n",
        )


class TestParseTitle:
    def test_moves_trailing_article_and_extracts_year(self) -> None:
        assert parse_title("Matrix, The (1999)") == ("The Matrix", 1999)

    def test_title_without_year(self) -> None:
        assert parse_title("Some Film") == ("Some Film", None)

    def test_year_only_stripped_from_the_end(self) -> None:
        assert parse_title("2001: A Space Odyssey (1968)") == ("2001: A Space Odyssey", 1968)


class TestReviewJoin:
    def test_every_review_is_paired_with_the_film_its_text_names(self, tmp_path: Path) -> None:
        archive = tmp_path / "acl.tar.gz"
        _make_acl(archive)
        reviews = list(iter_reviews(archive))
        assert reviews, "the join produced no reviews at all"
        for review in reviews:
            assert f"about {review.imdb_id}" in review.text

    def test_a_review_without_a_url_line_is_dropped_not_guessed(self, tmp_path: Path) -> None:
        archive = tmp_path / "acl.tar.gz"
        _make_acl(archive)
        assert all("orphan" not in r.text for r in iter_reviews(archive))

    def test_labels_and_stars_come_from_the_archive_path(self, tmp_path: Path) -> None:
        archive = tmp_path / "acl.tar.gz"
        _make_acl(archive)
        by_id = {r.review_id: r for r in iter_reviews(archive)}
        assert by_id["train/pos/0"].label == 1 and by_id["train/pos/0"].stars == 9
        assert by_id["train/neg/0"].label == 0
        assert by_id["train/unsup/0"].label is None

    def test_keep_films_filters_without_losing_the_rest(self, tmp_path: Path) -> None:
        archive = tmp_path / "acl.tar.gz"
        _make_acl(archive)
        kept = list(iter_reviews(archive, frozenset({100})))
        assert {r.imdb_id for r in kept} == {100}
        assert len(kept) == 2  # one pos and one neg review of tt100


class TestMovieLens:
    def test_films_are_keyed_by_imdb_number_and_unlinked_are_omitted(self, tmp_path: Path) -> None:
        archive = tmp_path / "ml.zip"
        _make_ml(archive)
        films = load_films(archive)
        assert set(films) == {100, 200}
        assert films[100].title == "The Matrix" and films[100].year == 1999
        assert films[100].genres == ("Action", "Sci-Fi")
        assert films[200].genres == ()

    def test_ratings_are_filtered_to_requested_films(self, tmp_path: Path) -> None:
        archive = tmp_path / "ml.zip"
        _make_ml(archive)
        users, movies, stars = load_ratings(archive, frozenset({1}))
        assert sorted(zip(users.tolist(), movies.tolist(), stars.tolist(), strict=True)) == [
            (10, 1, 4.5),
            (11, 1, 2.0),
        ]


def _make_ml_release(path: Path, release: str) -> None:
    """The same tiny MovieLens, filed under another release's folder name."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{release}/links.csv", "movieId,imdbId,tmdbId\n1,0000100,5\n2,0000200,\n3,,7\n")
        z.writestr(f"{release}/movies.csv", "movieId,title,genres\n1,Heat (1995),Action\n")
        z.writestr(
            f"{release}/ratings.csv", "userId,movieId,rating,timestamp\n10,1,4.5,0\n11,1,2.0,0\n"
        )


class TestMovieLensReleases:
    def test_links_give_the_movielens_and_tmdb_id_for_each_imdb_number(
        self, tmp_path: Path
    ) -> None:
        archive = tmp_path / "ml.zip"
        _make_ml(archive)
        assert load_movielens_links(archive) == {100: (1, 5), 200: (2, 6)}

    def test_a_missing_tmdb_id_is_none_and_a_missing_imdb_id_is_omitted(
        self, tmp_path: Path
    ) -> None:
        archive = tmp_path / "ml32.zip"
        _make_ml_release(archive, "ml-32m")
        assert load_movielens_links(archive, "ml-32m") == {100: (1, 5), 200: (2, None)}

    def test_ratings_read_from_the_named_release(self, tmp_path: Path) -> None:
        archive = tmp_path / "ml32.zip"
        _make_ml_release(archive, "ml-32m")
        users, movies, _ = load_ratings(archive, frozenset({1}), "ml-32m")
        assert sorted(users.tolist()) == [10, 11]
        assert set(movies.tolist()) == {1}
