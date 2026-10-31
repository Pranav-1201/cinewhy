"""The whole offline build, once, on tiny synthetic dumps (FEATURE-004).

The real build takes about half an hour, so a mistake in how its stages hand data to each other
would otherwise show up late. This runs every stage on fifteen films and checks that the result
is a loadable, internally consistent artifact set that carries provenance.

The fixture is built to contain the cases that differ from the happy path:

* film 13 has a MovieLens link and reviews but NO ratings (most Hindi films look like this);
* film 14 has only two reviews, below the build's minimum, so it must stay out of the catalogue.
"""

from __future__ import annotations

import gc
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from cinewhy.absa.polarity import PolarityModel
from cinewhy.artifacts.manifest import load_manifest, verify
from cinewhy.build import BuildConfig, build_artifacts
from cinewhy.data.catalogue_sources import Gathered
from cinewhy.data.sources import load_ratings
from cinewhy.data.spine import quota, wide_quota
from cinewhy.recsys.catalogue import load_catalogue
from tests.dumps import movielens_zip, source_paths, tmdb_row

N_FILMS = 14  # in the catalogue
N_TMDB = 15  # selected from TMDB; the last has too few reviews
UNRATED = 13
_TITLES = [f"Film {chr(ord('A') + k)}" for k in range(N_TMDB)]


def _ratings() -> list[tuple[int, int, float]]:
    """(user, MovieLens id, stars). Films 0-12 only; MovieLens id is film index + 1."""
    rng = np.random.default_rng(1)
    return [
        (user, int(film) + 1, float(rng.choice([4.0, 4.5, 5.0, 3.0], p=[0.4, 0.3, 0.2, 0.1])))
        for user in range(1, 151)
        for film in rng.choice(UNRATED, size=12, replace=False)
    ]


def _toy_polarity(path: Path) -> None:
    texts = [
        "superb brilliant wonderful great",
        "loved it great fun",
        "stunning beautiful superb",
        "great acting wonderful story",
        "brilliant and moving",
        "a joy wonderful",
        "dull boring awful terrible",
        "tedious dull waste",
        "awful acting terrible plot",
        "boring and bad",
        "terrible dull mess",
        "not good at all boring",
    ]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    classifier = LogisticRegression(C=10.0).fit(vectorizer.fit_transform(texts), [1] * 6 + [0] * 6)
    PolarityModel(vectorizer, classifier).save(path)


def _build(
    tmp_path: Path,
    *,
    wrong_tmdb_id_for: int | None = None,
    cache_file: Path | None = None,
    ratings_only_min_votes: int | None = None,
    ratings_only_fallback_votes: int | None = None,
    extra_tmdb: list[dict[str, str]] | None = None,
) -> Path:
    tmdb = [tmdb_row(k + 1, 100 + k, _TITLES[k], 2005 + k % 8) for k in range(N_TMDB)]
    tmdb += extra_tmdb or []
    ebd = [
        (
            f"{_TITLES[k]} ({2005 + k % 8})",
            f"rw{k}x{j}",
            f"The acting was superb and the pacing was brilliant in {_TITLES[k]}, take {j}.",
        )
        for k in range(N_TMDB)
        for j in range(2 if k == N_TMDB - 1 else 6)
    ]
    rt_films = [("a0", 2005, _TITLES[0], "2h 50m"), ("a1", 2006, _TITLES[1], "2h 50m")]
    rt_reviews = [
        # Stronger praise than the ebD reviews, so RT sentences win evidence slots and the RT
        # link branch is exercised (evidence agrees with the film's mean and strongest goes first).
        (
            mid,
            f"The acting was superb brilliant wonderful great and the pacing was superb "
            f"brilliant wonderful great, said reviewer {j}.",
        )
        for mid in ("a0", "a1")
        for j in range(4)
    ]
    sources = source_paths(
        tmp_path / "dumps", tmdb=tmdb, ebd=ebd, rt_films=rt_films, rt_reviews=rt_reviews
    )
    # MovieLens normally names the same TMDB id as TMDB does; one film can be made to disagree.
    links = [(k + 1, 100 + k, 999 if k == wrong_tmdb_id_for else k + 1) for k in range(N_TMDB)]
    ml = movielens_zip(tmp_path / "ml.zip", links, _ratings())
    gold = tmp_path / "gold"
    gold.mkdir()
    out = tmp_path / "artifacts"
    out.mkdir(exist_ok=True)  # a test may already have put a file there
    _toy_polarity(out / "polarity.joblib")
    config = BuildConfig(
        sources=sources,
        cache_file=cache_file,
        ml_archive=ml,
        out_dir=out,
        gold_dir=gold,
        min_reviews=3,
        seed=7,
        ratings_only_min_votes=ratings_only_min_votes,
        ratings_only_fallback_votes=ratings_only_fallback_votes,
    )
    build_artifacts(config)
    return out


def test_the_build_produces_a_loadable_consistent_artifact_set(tmp_path: Path) -> None:
    out = _build(tmp_path)
    catalogue = load_catalogue(out)
    assert len(catalogue.movies) == N_FILMS
    assert catalogue.similarity.shape == (N_FILMS, N_FILMS)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "meta.json" in manifest["files"]


def test_a_film_below_the_review_minimum_stays_out_and_an_unrated_film_stays_in(
    tmp_path: Path,
) -> None:
    out = _build(tmp_path)
    catalogue = load_catalogue(out)
    ids = {m.movie_id for m in catalogue.movies}
    assert "cw-0000114" not in ids  # two reviews, minimum is three
    assert "cw-0000113" in ids  # no ratings at all, but plenty of reviews
    # Nobody rated it, so it has no neighbours: its similarity row and column are zero.
    position = catalogue.index["cw-0000113"]
    assert not catalogue.similarity[position].any()
    assert not catalogue.similarity[:, position].any()


def test_rating_counts_land_on_the_right_films(tmp_path: Path) -> None:
    meta = json.loads((_build(tmp_path) / "meta.json").read_text(encoding="utf-8"))
    expected = Counter(movielens_id - 1 for _, movielens_id, _ in _ratings())
    for film in range(UNRATED):
        assert meta[f"cw-{100 + film:07d}"]["rating_count"] == expected[film]
    assert meta["cw-0000113"]["rating_count"] == 0


def test_the_build_writes_a_gather_cache_when_asked_and_not_otherwise(tmp_path: Path) -> None:
    uncached = tmp_path / "uncached"
    uncached.mkdir()
    _build(uncached)
    assert not list(uncached.rglob("*.jsonl"))
    cached = tmp_path / "cached"
    cached.mkdir()
    cache_file = cached / "gathered.jsonl"
    _build(cached, cache_file=cache_file)
    assert cache_file.is_file()
    # A second build served from the cache must produce the same catalogue.
    again = tmp_path / "again"
    again.mkdir()
    out = _build(again, cache_file=cache_file)
    first = json.loads((cached / "artifacts" / "meta.json").read_text(encoding="utf-8"))
    assert json.loads((out / "meta.json").read_text(encoding="utf-8")) == first


def test_the_review_text_is_released_before_ratings_are_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On the real dumps the review text is about 2 GB, and the stages after profiling (ratings,
    # three-way similarity evaluation) are the memory-hungry ones. The text is only needed to
    # build the profiles, so it must be gone by the time ratings are read.
    seen: dict[str, bool] = {}

    def spy(*args: Any, **kwargs: Any) -> Any:
        gc.collect()
        seen["text_still_held"] = any(isinstance(o, Gathered) for o in gc.get_objects())
        return load_ratings(*args, **kwargs)

    monkeypatch.setattr("cinewhy.build.load_ratings", spy)
    _build(tmp_path)
    assert seen["text_still_held"] is False


def _extra_row(tmdb_id: int, imdb: int, lang: str, votes: int) -> dict[str, str]:
    return {**tmdb_row(tmdb_id, imdb, f"Extra {imdb}", 2012, lang=lang), "imdb_votes": str(votes)}


def test_without_the_option_there_is_no_ratings_only_tier(tmp_path: Path) -> None:
    out = _build(tmp_path, extra_tmdb=[_extra_row(90, 900, "fr", 5000)])
    assert not (out / "ratings_only.json").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "ratings_only.json" not in manifest["files"]
    assert (
        json.loads((out / "eval.json").read_text(encoding="utf-8"))["catalogue"]["ratings_only"]
        is None
    )


def test_the_ratings_only_tier_lists_well_voted_films_that_have_no_receipt(
    tmp_path: Path,
) -> None:
    extras = [
        _extra_row(90, 900, "fr", 5000),  # French, well voted: listed
        _extra_row(91, 901, "fr", 150),  # too few votes: not listed
        _extra_row(92, 902, "de", 9000),  # a language the catalogue does not carry: not listed
    ]
    out = _build(tmp_path, ratings_only_min_votes=200, extra_tmdb=extras)
    verify(out, load_manifest(out))  # the new file is hashed into the manifest the API checks
    catalogue = load_catalogue(out, with_ratings_only=True)
    listed = {f.movie.movie_id: f for f in catalogue.ratings_only}
    # Film 14 (index 14, IMDb 114) has two reviews: below the build's minimum of three, but it is
    # a well-voted English film, so it is listed rather than lost.
    assert set(listed) == {"ro-0000900", "ro-0000114"}
    assert listed["ro-0000900"].language == "fr" and listed["ro-0000900"].imdb_votes == 5000
    # Nothing is in both tiers, and the full-receipt tier is the same as without the option.
    assert not {m.movie_id for m in catalogue.movies} & set(listed)
    assert len(catalogue.movies) == N_FILMS
    report = json.loads((out / "eval.json").read_text(encoding="utf-8"))["catalogue"][
        "ratings_only"
    ]
    assert report["min_imdb_votes"] == 200 and report["films"] == 2
    french = report["by_language"]["fr"]
    assert french == {
        "target": 2500,
        "full_receipts": 0,
        "ratings_only": 1,
        "of_which_below_the_main_floor": 0,
        "short_by": 2499,
    }
    # English: 14 full receipts plus 1 ratings-only film, against the 10,000 target.
    assert report["by_language"]["en"]["short_by"] == 10_000 - N_FILMS - 1


def test_a_fallback_floor_lists_thin_films_and_the_report_counts_them(tmp_path: Path) -> None:
    extras = [
        _extra_row(90, 900, "fr", 5000),  # above the main floor
        _extra_row(91, 901, "fr", 150),  # below it, above the fallback floor: listed, and counted
        _extra_row(92, 902, "fr", 60),  # below the fallback floor: not listed
    ]
    out = _build(
        tmp_path,
        ratings_only_min_votes=200,
        ratings_only_fallback_votes=100,
        extra_tmdb=extras,
    )
    catalogue = load_catalogue(out, with_ratings_only=True)
    assert {f.movie.movie_id for f in catalogue.ratings_only} >= {"ro-0000900", "ro-0000901"}
    assert "ro-0000902" not in {f.movie.movie_id for f in catalogue.ratings_only}
    report = json.loads((out / "eval.json").read_text(encoding="utf-8"))["catalogue"][
        "ratings_only"
    ]
    assert report["fallback_min_imdb_votes"] == 100
    french = report["by_language"]["fr"]
    assert french["ratings_only"] == 2 and french["of_which_below_the_main_floor"] == 1
    # English has a film of 10,069 votes among the fixture's own rows, none below the floor.
    assert report["by_language"]["en"]["of_which_below_the_main_floor"] == 0


@pytest.mark.parametrize("wide", [False, True])
def test_the_build_passes_its_selection_settings_to_gather(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wide: bool
) -> None:
    seen: dict[str, Any] = {}

    class Stop(Exception):  # noqa: N818  # a sentinel: the point is only to read the arguments
        pass

    def spy(*_args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr("cinewhy.build.gather", spy)
    config = BuildConfig(
        sources=source_paths(tmp_path / "dumps", tmdb=[]),
        out_dir=tmp_path,
        wide=wide,
        languages=("en", "fr"),
        max_year=2026,
        cap_per_source=77,
    )
    with pytest.raises(Stop):
        build_artifacts(config)
    assert seen["quota_for"] is (wide_quota if wide else quota)
    assert (seen["languages"], seen["max_year"], seen["cap"]) == (("en", "fr"), 2026, 77)


def test_a_catalogue_with_a_ratings_only_tier_still_serves(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    import api.main as api_main

    out = _build(tmp_path, ratings_only_min_votes=200, extra_tmdb=[_extra_row(90, 900, "fr", 5000)])
    with TestClient(api_main.create_app(out)) as client:
        page = client.get("/movie/ro-0000900").json()
        assert page["ratings_only"] is True and page["aspects"] == []
        assert client.get("/facets").json()["languages"]["fr"] == 1


def test_a_domain_check_next_to_the_model_is_carried_into_eval_json(tmp_path: Path) -> None:
    out_dir = tmp_path / "artifacts"
    out_dir.mkdir()
    marker = {"by_source": {"rt": {"n": 6000, "accuracy": 0.8}}}
    (out_dir / "polarity_domain.json").write_text(json.dumps(marker), encoding="utf-8")
    out = _build(tmp_path)
    blob = json.loads((out / "eval.json").read_text(encoding="utf-8"))
    assert blob["polarity_domain"] == marker


def test_without_a_domain_check_eval_json_says_none_was_run(tmp_path: Path) -> None:
    blob = json.loads((_build(tmp_path) / "eval.json").read_text(encoding="utf-8"))
    assert blob["polarity_domain"] is None


def test_a_disagreement_between_movielens_and_tmdb_ids_is_counted(tmp_path: Path) -> None:
    blob = json.loads((_build(tmp_path, wrong_tmdb_id_for=3) / "eval.json").read_text("utf-8"))
    assert blob["movielens"]["tmdb_id_disagreements"] == 1


def test_the_catalogue_stores_how_many_reviews_each_film_has(tmp_path: Path) -> None:
    catalogue = load_catalogue(_build(tmp_path))
    stats = {m.movie_id: s for m, s in zip(catalogue.movies, catalogue.stats, strict=True)}
    assert stats["cw-0000100"].review_count == 10  # 6 ebD + 4 RT
    assert stats["cw-0000105"].review_count == 6


def test_meta_json_carries_tmdb_fields_and_review_provenance(tmp_path: Path) -> None:
    meta = json.loads((_build(tmp_path) / "meta.json").read_text(encoding="utf-8"))
    assert len(meta) == N_FILMS
    first = meta["cw-0000100"]
    assert first["tmdb_id"] == 1
    assert first["language"] == "en"
    assert first["poster_path"] == "/p.jpg"
    assert first["reviews_by_source"] == {"ebd": 6, "rt": 4}
    assert first["rt_url"] == "https://www.rottentomatoes.com/m/a0"
    assert meta["cw-0000105"]["reviews_by_source"] == {"ebd": 6}  # no RT reviews for this film


def test_eval_json_reports_where_the_data_came_from_and_how_the_joins_went(tmp_path: Path) -> None:
    blob = json.loads((_build(tmp_path) / "eval.json").read_text(encoding="utf-8"))
    assert blob["catalogue"]["films"] == N_FILMS
    assert blob["catalogue"]["films_with_ratings"] == N_FILMS - 1
    assert blob["gather"]["films_selected"] == N_TMDB
    assert blob["gather"]["rt_link"]["en/exact"] == 2
    assert blob["movielens"] == {"catalogue_films_linked": N_FILMS, "tmdb_id_disagreements": 0}
    assert set(blob["join_check"]) == {"acl", "ebd", "rt"}
    assert sum(blob["catalogue"]["films_by_language_and_era"].values()) == N_FILMS


def test_every_evidence_sentence_names_its_source_and_a_page_to_check_it(tmp_path: Path) -> None:
    out = _build(tmp_path)
    evidence = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    sentences = [s for film in evidence.values() for s in film]
    assert sentences, "the fixtures were built to produce evidence"
    assert {s["source_review_id"].split("/")[0] for s in sentences} == {"ebd", "rt"}
    for s in sentences:
        source = s["source_review_id"].split("/")[0]
        assert source in {"ebd", "rt"}
        assert s["source_url"] is not None
        if source == "rt":
            assert s["source_url"].startswith("https://www.rottentomatoes.com/m/")
        else:
            assert s["source_url"].startswith("https://www.imdb.com/title/tt")
