"""The whole offline build, once, on tiny synthetic dumps (FEATURE-004).

The real build takes about half an hour, so a mistake in how its stages hand data to each other
would otherwise show up late. This runs every stage on fifteen films and checks that the result
is a loadable, internally consistent artifact set that carries provenance.

The fixture is built to contain the cases that differ from the happy path:

* film 13 has a MovieLens link and reviews but NO ratings (most Hindi films look like this);
* film 14 has only two reviews, below the build's minimum, so it must stay out of the catalogue.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from cinewhy.absa.polarity import PolarityModel
from cinewhy.build import BuildConfig, build_artifacts
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
    tmp_path: Path, *, wrong_tmdb_id_for: int | None = None, cache_file: Path | None = None
) -> Path:
    tmdb = [tmdb_row(k + 1, 100 + k, _TITLES[k], 2005 + k % 8) for k in range(N_TMDB)]
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
    out.mkdir()
    _toy_polarity(out / "polarity.joblib")
    config = BuildConfig(
        sources=sources,
        cache_file=cache_file,
        ml_archive=ml,
        out_dir=out,
        gold_dir=gold,
        min_reviews=3,
        seed=7,
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
