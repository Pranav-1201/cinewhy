"""The whole build with TV series in it: reviews from ebD, details from TMDB, the Japanese split."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.artifacts.manifest import load_manifest, verify
from cinewhy.data import spine
from cinewhy.recsys.catalogue import load_catalogue
from tests.test_build_end_to_end import N_FILMS, _build
from tests.test_series import _BASICS_HEADER, _EN_DASH, _RATINGS_HEADER, _gz

_REVIEW = "The acting was superb and the pacing was brilliant in {title}, episode {n} of the run."
_ANIMATION = "Animation,Fantasy"

# imdb number: (title, start year, genres, votes, TMDB language, ebD review count)
_SERIES = {
    500: ("Anime Show", 2010, _ANIMATION, 9000, "ja", 4),  # anime, with receipts
    501: ("Drama Show", 2012, "Drama", 3000, "ja", 1),  # live action, too few reviews: ratings only
    502: ("English Show", 2008, "Drama", 8000, "en", 5),  # English, with receipts
    503: ("German Show", 2011, "Drama", 7000, "de", 5),  # a language the catalogue does not carry
    504: ("Unknown Show", 2013, "Drama", 6000, "", 5),  # TMDB had nothing for it
}


def _series_files(tmp_path: Path) -> tuple[Path, Path, list[tuple[str, str, str]]]:
    basics = _BASICS_HEADER + "".join(
        f"tt{n:07d}\ttvSeries\t{t}\t{t}\t0\t{year}\t\\N\t45\t{genres}\n"
        for n, (t, year, genres, _, _, _) in _SERIES.items()
    )
    ratings = _RATINGS_HEADER + "".join(
        f"tt{n:07d}\t8.0\t{votes}\n" for n, (_, _, _, votes, _, _) in _SERIES.items()
    )
    dumps = tmp_path / "imdb"
    dumps.mkdir()
    _gz(dumps / "title.basics.tsv.gz", basics)
    _gz(dumps / "title.ratings.tsv.gz", ratings)
    cache = tmp_path / "tmdb_tv.jsonl"
    lines = [
        {
            "imdb": n,
            "found": True,
            "tmdb_id": 9000 + n,
            "original_language": language,
            "first_air_date": f"{year}-04-01",
            "overview": f"About {title}.",
            "poster_path": f"/s{n}.jpg",
            "vote_count": 50,
            "vote_average": 8.0,
            "popularity": 5.0,
        }
        for n, (title, year, _, _, language, _) in _SERIES.items()
        if language
    ]
    lines.append({"imdb": 504, "found": False})
    cache.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    ebd = [
        (f"{title} ({year}{_EN_DASH} )", f"sr{n}x{j}", _REVIEW.format(title=title, n=j))
        for n, (title, year, _, _, _, count) in _SERIES.items()
        for j in range(count)
    ]
    return dumps, cache, ebd


@pytest.fixture(autouse=True)
def _build_selects_japanese(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spine, "LANGUAGES", ("en", "hi", "ja"))


def _with_series(tmp_path: Path, **kwargs: object) -> Path:
    dumps, cache, ebd = _series_files(tmp_path)
    return _build(
        tmp_path,
        extra_ebd=ebd,
        series_dumps=dumps,
        series_tmdb=cache,
        ratings_only_min_votes=200,
        **kwargs,  # type: ignore[arg-type]
    )


def test_series_with_enough_reviews_get_full_receipts_beside_the_films(tmp_path: Path) -> None:
    out = _with_series(tmp_path)
    catalogue = load_catalogue(out, with_meta=True, with_ratings_only=True)
    kinds = {m.movie_id: m.kind for m in catalogue.movies}
    assert kinds["cw-0000500"] == kinds["cw-0000502"] == "series"
    assert sum(k == "film" for k in kinds.values()) == N_FILMS
    assert len(kinds) == N_FILMS + 2
    # Receipts: a profile and evidence, from ebD alone, as for a film.
    assert "cw-0000500" in catalogue.profiles and "cw-0000500" in catalogue.evidence
    meta = catalogue.meta["cw-0000500"]
    assert (meta["kind"], meta["language"], meta["reviews_by_source"]) == (
        "series",
        "ja",
        {"ebd": 4},
    )
    poster = catalogue.movies[catalogue.index["cw-0000500"]].poster_url
    assert poster is not None and poster.endswith("/s500.jpg")
    # Series have no MovieLens ratings, so no neighbours: like an unrated Hindi film.
    row = catalogue.index["cw-0000500"]
    assert not catalogue.similarity[row].any() and catalogue.stats[row].rating_count == 0


def test_a_series_below_the_review_floor_is_listed_with_ratings_only(tmp_path: Path) -> None:
    catalogue = load_catalogue(_with_series(tmp_path), with_ratings_only=True)
    listed = {f.movie.movie_id: f for f in catalogue.ratings_only}
    assert "ro-0000501" in listed
    drama = listed["ro-0000501"]
    assert (drama.movie.kind, drama.language, drama.imdb_votes) == ("series", "ja", 3000)
    # Not listed: it already has receipts; another language; TMDB did not know it.
    assert not {"ro-0000500", "ro-0000502", "ro-0000503", "ro-0000504"} & set(listed)


def test_japanese_is_split_into_anime_movies_and_live_action(tmp_path: Path) -> None:
    out = _with_series(tmp_path)
    blob = json.loads((out / "eval.json").read_text(encoding="utf-8"))
    report = blob["catalogue"]["ratings_only"]
    parts = report["by_language"]
    assert "ja" not in parts and {"ja-anime", "ja-movies", "ja-live-action"} <= set(parts)
    assert [parts[k]["target"] for k in ("ja-anime", "ja-movies", "ja-live-action")] == [
        2500,
        1500,
        1000,
    ]
    assert parts["ja-anime"]["full_receipts"] == 1  # Anime Show
    assert parts["ja-live-action"]["ratings_only"] == 1  # Drama Show
    assert parts["ja-movies"]["full_receipts"] == parts["ja-movies"]["ratings_only"] == 0
    assert report["series"] == 1


def test_without_series_japanese_keeps_its_single_target(tmp_path: Path) -> None:
    out = _build(tmp_path, ratings_only_min_votes=200)
    blob = json.loads((out / "eval.json").read_text(encoding="utf-8"))
    parts = blob["catalogue"]["ratings_only"]["by_language"]
    assert parts["ja"]["target"] == 5000 and "ja-anime" not in parts


def test_the_eval_report_counts_series_and_how_their_reviews_linked(tmp_path: Path) -> None:
    blob = json.loads((_with_series(tmp_path) / "eval.json").read_text(encoding="utf-8"))
    assert blob["catalogue"]["series"] == 2
    gather = blob["gather"]["series"]
    assert gather["series_with_reviews"] >= 3  # Anime, Drama and English Show have ebD reviews
    assert blob["gather"]["films_selected"] > 0  # the film report is still there


def test_the_api_serves_a_series_as_a_series(tmp_path: Path) -> None:
    out = _with_series(tmp_path)
    verify(out, load_manifest(out))
    with TestClient(api_main.create_app(out)) as client:
        page = client.get("/movie/cw-0000500").json()
        assert page["movie"]["kind"] == "series" and page["review_count"] == 4
        assert page["aspects"] and page["language"] == "ja"
        thin = client.get("/movie/ro-0000501").json()
        assert thin["ratings_only"] is True and thin["movie"]["kind"] == "series"
        assert client.get("/movie/cw-0000100").json()["movie"]["kind"] == "film"
