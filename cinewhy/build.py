"""Offline build: raw archives in, a verified artifact set out.

Everything expensive happens here, once, on a developer machine or in an image build. The
API only loads the result (CONSTRAINTS.md #5). Stages:

1. Join aclImdb reviews to MovieLens films on the exact IMDb title number
   (`cinewhy.data.sources`) and keep films with enough reviews to say something.
2. Score every review clause for aspect and polarity, aggregate per film, select verbatim
   evidence (`cinewhy.absa`).
3. Evaluate the recommender on held-out users, choose the similarity shrinkage on validation
   users only, then fit the shipped similarity matrix on all users (`cinewhy.recsys`).
4. Write the files, an `eval.json` holding every measured number the UI displays, and a
   hash manifest the API verifies at boot (`cinewhy.artifacts`).

Run: `python -m cinewhy.build` (needs Data/raw/aclImdb_v1.tar.gz, Data/raw/ml-25m.zip and
artifacts/polarity.joblib from `python -m cinewhy.absa.polarity`).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from cinewhy.absa.extract import build_profile
from cinewhy.absa.gold import evaluate_gold, load_gold
from cinewhy.absa.polarity import PolarityModel
from cinewhy.artifacts.manifest import build as build_manifest
from cinewhy.data.sources import (
    MovieLensFilm,
    iter_reviews,
    load_films,
    load_ratings,
    read_review_films,
)
from cinewhy.recsys.catalogue import Catalogue, FilmStats, write_catalogue
from cinewhy.recsys.cf import bayesian_popularity, build_item_similarity
from cinewhy.recsys.evaluate import evaluate_recommenders
from cinewhy.schemas import ArtifactManifest, Aspect, EvidenceSentence, Movie, MovieAspectProfile

ARTIFACT_FILES = (
    "catalogue.json",
    "profiles.json",
    "evidence.json",
    "item_sim.npy",
    "eval.json",
    "polarity.joblib",
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_PARENTHETICAL = re.compile(r"\([^)]*\)")
_MIN_TITLE_CHARS = 5


@dataclass(frozen=True)
class BuildConfig:
    """Where inputs live and how selective the catalogue is."""

    acl_archive: Path = Path("Data/raw/aclImdb_v1.tar.gz")
    ml_archive: Path = Path("Data/raw/ml-25m.zip")
    out_dir: Path = Path("artifacts")
    gold_dir: Path = Path("tests/data")
    min_reviews: int = 10
    seed: int = 42


def movie_id_for(imdb_id: int) -> str:
    """CineWhy's id for a film: stable, derived from the IMDb number, never reused."""
    return f"cw-{imdb_id:07d}"


def review_url(imdb_id: int) -> str:
    """Where a sceptical reader can find the film's user reviews."""
    return f"https://www.imdb.com/title/tt{imdb_id:07d}/reviews"


def select_catalogue(
    films: Mapping[int, MovieLensFilm], reviews_per_film: Mapping[int, int], min_reviews: int
) -> list[int]:
    """IMDb numbers of films that exist in both sources and have enough reviews.

    Args:
        films: MovieLens films keyed by IMDb number.
        reviews_per_film: Review count per IMDb number.
        min_reviews: Minimum reviews for a film to be recommendable.

    Returns:
        Sorted IMDb numbers, so the catalogue order (and every artifact) is deterministic.
    """
    return sorted(i for i, n in reviews_per_film.items() if n >= min_reviews and i in films)


def _normalise_title(title: str) -> str:
    return _NON_ALNUM.sub(" ", _PARENTHETICAL.sub(" ", title.lower())).strip()


def title_match_rate(
    titles: Mapping[int, str], reviews: Mapping[int, list[tuple[str, str]]]
) -> dict[str, float | int]:
    """Check the join: do reviews of a film actually mention that film's title?

    A correct join makes many reviews name their own film. A misaligned one makes almost
    none do. The control pairs every film's reviews with the NEXT film's title; the gap
    between the two rates is the evidence, not either number alone.

    Args:
        titles: Display title per IMDb number.
        reviews: `(review_id, text)` pairs per IMDb number.

    Returns:
        `{"n_reviews", "own_title_rate", "other_title_rate"}`, over films whose primary
        title is long enough to be distinctive.
    """

    def primary(imdb_id: int) -> str:
        head = _normalise_title(re.sub(r"^(the|a|an) ", "", titles[imdb_id].split(":")[0].lower()))
        return head if len(head) >= _MIN_TITLE_CHARS else ""

    ids = sorted(i for i in reviews if i in titles)
    own = other = n = 0
    for pos, imdb_id in enumerate(ids):
        mine, theirs = primary(imdb_id), primary(ids[(pos + 1) % len(ids)])
        if not mine or not theirs:
            continue
        for _, text in reviews[imdb_id]:
            haystack = f" {_normalise_title(text)} "
            n += 1
            own += f" {mine} " in haystack
            other += f" {theirs} " in haystack
    return {
        "n_reviews": n,
        "own_title_rate": own / n if n else 0.0,
        "other_title_rate": other / n if n else 0.0,
    }


def _log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def build_artifacts(config: BuildConfig) -> ArtifactManifest:
    """Run the whole offline build and return the manifest that was written.

    Args:
        config: Input and output locations and the catalogue threshold.

    Returns:
        The verified-at-boot manifest.
    """
    out = config.out_dir
    out.mkdir(parents=True, exist_ok=True)

    _log("reading MovieLens films and the review->film table")
    films = load_films(config.ml_archive)
    review_films = read_review_films(config.acl_archive)
    per_film = Counter(review_films.values())
    imdb_ids = select_catalogue(films, per_film, config.min_reviews)
    _log(f"catalogue: {len(imdb_ids)} films (of {len(per_film)} reviewed, {len(films)} linked)")

    reviews: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for review in iter_reviews(config.acl_archive, frozenset(imdb_ids)):
        reviews[review.imdb_id].append((review.review_id, review.text))
    for pairs in reviews.values():
        pairs.sort()
    join_check = title_match_rate({i: films[i].title for i in imdb_ids}, reviews)
    _log(f"join check: {join_check}")

    model = PolarityModel.load(out / "polarity.joblib")
    movies: list[Movie] = []
    profiles: dict[str, MovieAspectProfile] = {}
    evidence: dict[str, dict[Aspect, tuple[EvidenceSentence, ...]]] = {}
    for n, imdb_id in enumerate(imdb_ids, start=1):
        film = films[imdb_id]
        movie_id = movie_id_for(imdb_id)
        movies.append(
            Movie(movie_id=movie_id, title=film.title, year=film.year, genres=film.genres)
        )
        profile, sentences = build_profile(
            movie_id, reviews[imdb_id], model=model, source_url=review_url(imdb_id)
        )
        profiles[movie_id] = profile
        by_aspect: dict[Aspect, list[EvidenceSentence]] = defaultdict(list)
        for sentence in sentences:
            by_aspect[sentence.aspect].append(sentence)
        if by_aspect:
            evidence[movie_id] = {a: tuple(v) for a, v in by_aspect.items()}
        if n % 250 == 0:
            _log(f"profiled {n}/{len(imdb_ids)} films")

    _log("loading ratings for catalogue films")
    users, movielens_ids, stars = load_ratings(
        config.ml_archive, frozenset(films[i].movielens_id for i in imdb_ids)
    )
    lookup = np.full(int(movielens_ids.max()) + 1, -1, dtype=np.int32)
    for position, imdb_id in enumerate(imdb_ids):
        lookup[films[imdb_id].movielens_id] = position
    items = lookup[movielens_ids]
    _log(f"{len(stars)} ratings from {len(np.unique(users))} users")

    n_films = len(movies)
    placeholder = Catalogue(
        tuple(movies),
        tuple(FilmStats(i, 0, 0.0, 0) for i in imdb_ids),
        profiles,
        evidence,
        np.zeros((n_films, n_films), dtype=np.float32),
    )
    _log("evaluating the recommender on held-out users")
    rec_report, shrink = evaluate_recommenders(
        users, items, stars, n_films, placeholder.aspect_matrix, seed=config.seed, on_progress=_log
    )

    _log(f"fitting the shipped similarity on all users (shrink={shrink:g})")
    similarity = build_item_similarity(users, items, stars, n_films, shrink=shrink)
    bayes, counts = bayesian_popularity(items, stars, n_films)
    stats = tuple(
        FilmStats(i, int(counts[p]), float(bayes[p]), len(reviews[i]))
        for p, i in enumerate(imdb_ids)
    )
    catalogue = Catalogue(
        tuple(movies),
        stats,
        profiles,
        evidence,
        similarity,
        {"inferred_fit_weight": rec_report.chosen_fit_weight},
    )
    write_catalogue(out, catalogue)

    gold: dict[str, Any] = {}
    for name in ("dev", "heldout"):
        path = config.gold_dir / f"aspect_gold_{name}.jsonl"
        if path.is_file():
            gold[name] = asdict(evaluate_gold(load_gold(path), model))
    polarity_path = out / "polarity_report.json"
    n_reviews = sum(len(v) for v in reviews.values())
    eval_blob = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {
            "reviews": "Maas et al. 2011, aclImdb v1 (IMDb reviews with title ids)",
            "ratings": "MovieLens 25M (GroupLens)",
            "join": "exact IMDb title number, MovieLens links.csv",
        },
        "catalogue": {
            "films": n_films,
            "reviews": n_reviews,
            "evidence_sentences": sum(len(s) for by in evidence.values() for s in by.values()),
            "min_reviews_per_film": config.min_reviews,
            "ratings": len(stars),
            "films_with_aspect": {
                a.value: sum(any(s.aspect is a for s in p.scores) for p in profiles.values())
                for a in Aspect
            },
        },
        "join_check": join_check,
        "polarity": json.loads(polarity_path.read_text(encoding="utf-8"))
        if polarity_path.is_file()
        else None,
        "gold": gold,
        "gold_note": "Labels written by the assistant, not an independent human. See gold.py.",
        "recommender": asdict(rec_report),
    }
    (out / "eval.json").write_text(
        json.dumps(eval_blob, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )

    row_counts = {"films": n_films, "ratings": len(stars), "reviews": n_reviews}
    # Name the artifacts explicitly: the directory may also hold logs, and hashing a file that
    # is still being written would make the manifest fail to verify at the next boot.
    manifest = build_manifest(out, row_counts=row_counts, names=ARTIFACT_FILES)
    _log(f"manifest {manifest.manifest_hash[:12]} over {len(manifest.files)} files")
    return manifest


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    defaults = BuildConfig()
    parser.add_argument("--acl", type=Path, default=defaults.acl_archive)
    parser.add_argument("--ml", type=Path, default=defaults.ml_archive)
    parser.add_argument("--out", type=Path, default=defaults.out_dir)
    parser.add_argument("--min-reviews", type=int, default=defaults.min_reviews)
    args = parser.parse_args()
    build_artifacts(
        BuildConfig(
            acl_archive=args.acl, ml_archive=args.ml, out_dir=args.out, min_reviews=args.min_reviews
        )
    )


if __name__ == "__main__":
    main()
