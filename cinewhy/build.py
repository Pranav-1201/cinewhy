"""Offline build: raw archives in, a verified artifact set out.

Everything expensive happens here, once, on a developer machine or in an image build. The
API only loads the result (CONSTRAINTS.md #5). Stages:

1. Choose films from the TMDB export and gather their reviews from aclImdb, Rotten Tomatoes
   and ebD (`cinewhy.data.catalogue_sources`); keep films with enough reviews to say something.
2. Score every review clause for aspect and polarity, aggregate per film, select verbatim
   evidence (`cinewhy.absa`).
3. Evaluate the recommender on held-out users of MovieLens 32M, choose the similarity
   shrinkage on validation users only, then fit the shipped similarity matrix on all users
   (`cinewhy.recsys`). Films with no ratings stay in the catalogue; their similarity is zero.
4. Write the files, an `eval.json` holding every measured number the UI displays, a `meta.json`
   with TMDB metadata, and a hash manifest the API verifies at boot (`cinewhy.artifacts`).

Run: `python -m cinewhy.build` (needs the raw dumps listed in docs/DATASET.md under Data/raw/ and
artifacts/polarity.joblib from `python -m cinewhy.absa.polarity`).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from cinewhy.absa.extract import build_profile
from cinewhy.absa.gold import evaluate_gold, evaluate_random, load_gold, load_random_gold
from cinewhy.absa.polarity import PolarityModel
from cinewhy.artifacts.manifest import build as build_manifest
from cinewhy.data import spine
from cinewhy.data.catalogue_sources import (
    SourcePaths,
    gather,
    gather_cached,
    gather_series_reviews,
)
from cinewhy.data.reviews import MAX_REVIEWS_PER_SOURCE
from cinewhy.data.series import iter_series_films, read_imdb_series, read_tmdb_tv
from cinewhy.data.sources import load_movielens_links, load_ratings
from cinewhy.data.spine import (
    SpineFilm,
    bucket_of,
    candidate_films,
    catalogue_targets,
    choose_ratings_only,
    quota,
    read_tmdb_rows,
    wide_quota,
)
from cinewhy.recsys.catalogue import (
    Catalogue,
    FilmStats,
    RatingsOnlyFilm,
    poster_url,
    write_catalogue,
)
from cinewhy.recsys.cf import bayesian_popularity, build_item_similarity
from cinewhy.recsys.evaluate import evaluate_recommenders, slider_response
from cinewhy.schemas import ArtifactManifest, Aspect, EvidenceSentence, Movie, MovieAspectProfile

ARTIFACT_FILES = (
    "catalogue.json",
    "profiles.json",
    "evidence.json",
    "item_sim.npy",
    "eval.json",
    "meta.json",
    "polarity.joblib",
)
# Which random gold samples may be quoted as clean. A and B informed the lexicon (D-015).
RANDOM_SAMPLE_ROLES = {"a": "tuned-on", "b": "tuned-on", "c": "clean"}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_PARENTHETICAL = re.compile(r"\([^)]*\)")
_MIN_TITLE_CHARS = 5


@dataclass(frozen=True)
class BuildConfig:
    """Where inputs live and how selective the catalogue is."""

    sources: SourcePaths = field(default_factory=SourcePaths)
    # Where the 25-minute gather step keeps its result between runs. None means no cache, which
    # is what tests want; the command line turns it on (see `main`).
    cache_file: Path | None = None
    ml_archive: Path = Path("Data/raw/ml32m/ml-32m.zip")
    # MovieLens names the folder inside its zip after the release.
    ml_prefix: str = "ml-32m"
    out_dir: Path = Path("artifacts")
    gold_dir: Path = Path("tests/data")
    # 5 rather than 10: measured on 2026-10-25, this grows the catalogue 77% (2,355 to 4,164
    # films) with the same relative recommender quality (DECISIONS D-015). Films with few
    # reviews simply report fewer aspects, each shown with its support.
    min_reviews: int = 5
    seed: int = 42
    # Everything below is off by default, which reproduces the shipped build. The v4 build turns
    # it on from the command line: more languages, a wider candidate list, 50 reviews for a full
    # receipt, and a ratings-only tier for the films that fall short (docs/ROADMAP, section 15).
    cap_per_source: int = MAX_REVIEWS_PER_SOURCE
    languages: tuple[str, ...] | None = None  # None: the spine's English and Hindi
    max_year: int | None = None  # None: the spine's last year
    wide: bool = False  # the wider candidate list (`spine.wide_quota`)
    # Fewest IMDb votes for a ratings-only film; None builds no ratings-only tier.
    ratings_only_min_votes: int | None = None
    # A lower floor used only to fill a language still short of its target once the films above
    # `ratings_only_min_votes` are used up. Their ratings rest on few voters; eval.json counts them.
    ratings_only_fallback_votes: int | None = None
    # TV series are built only when BOTH of these are given: IMDb's dumps (the list of series, votes
    # and genres) and the cache of TMDB's details for them (`cinewhy.data.fetch_series`). Their
    # reviews come from ebD alone. Giving them also splits the Japanese target 5 : 3 : 2.
    series_dumps: Path | None = None
    series_tmdb: Path | None = None
    series_min_votes: int = 200


def movie_id_for(imdb_id: int) -> str:
    """CineWhy's id for a film: stable, derived from the IMDb number, never reused."""
    return f"cw-{imdb_id:07d}"


def review_url(imdb_id: int) -> str:
    """Where a sceptical reader can find the film's user reviews."""
    return f"https://www.imdb.com/title/tt{imdb_id:07d}/reviews"


def select_films(
    films: Sequence[SpineFilm],
    reviews: Mapping[int, Sequence[tuple[str, str]]],
    min_reviews: int,
) -> list[SpineFilm]:
    """Films with enough reviews to say something about.

    Ratings are NOT required: most Hindi films have too few MovieLens ratings for collaborative
    filtering, but their reviews still describe them (FEATURE-004). Such a film is ranked on
    aspects and popularity and has a zero similarity row.

    Args:
        films: Candidate films, in the deterministic order `gather` returns (by IMDb number).
        reviews: Merged reviews per IMDb number; a film with none is simply absent.
        min_reviews: Minimum reviews for a film to be recommendable.

    Returns:
        The qualifying films in the order given, so every artifact is deterministic.
    """
    return [f for f in films if len(reviews.get(f.imdb_id, ())) >= min_reviews]


def ratings_only_id(imdb_id: int) -> str:
    """CineWhy's id for a film listed with ratings only: distinct from `movie_id_for` on purpose."""
    return f"ro-{imdb_id:07d}"


def build_targets(config: BuildConfig, *, with_series: bool) -> dict[str, int]:
    """The wanted size of each bucket: with series in the build, Japanese is split 5 : 3 : 2."""
    return catalogue_targets(split_japanese=with_series)


def series_candidates(config: BuildConfig) -> list[SpineFilm]:
    """TV series TMDB knows, in the build's languages, as build records (none when not asked for).

    Series need both IMDb's dumps (which titles are series, and their votes and genres) and the
    downloaded TMDB details (their language, poster and description).
    """
    if config.series_dumps is None or config.series_tmdb is None:
        return []
    languages = set(config.languages) if config.languages else set(spine.LANGUAGES)
    listed = read_imdb_series(
        config.series_dumps / "title.basics.tsv.gz",
        config.series_dumps / "title.ratings.tsv.gz",
        min_votes=config.series_min_votes,
    )
    last_year = config.max_year if config.max_year is not None else spine.MAX_YEAR
    return [
        f
        for f in iter_series_films(listed, read_tmdb_tv(config.series_tmdb))
        if f.language in languages and f.year <= last_year
    ]


def ratings_only_films(
    config: BuildConfig, taken: Sequence[int], series: Sequence[SpineFilm] = ()
) -> tuple[RatingsOnlyFilm, ...]:
    """The ratings-only tier: well-voted films and series to bring each bucket up to its target.

    Empty when the config asks for no such tier. A title that already has full receipts is never
    listed twice (`taken`), and a bucket the dumps cannot fill simply has fewer than its target;
    the build reports that gap in eval.json instead of padding the list.

    Args:
        config: The build settings (`ratings_only_min_votes` switches the tier on).
        taken: IMDb numbers of the films and series that have full receipts.
        series: Every series that may be listed (empty when the build has none).

    Returns:
        The titles, ordered by IMDb number so the artifact is deterministic.
    """
    if config.ratings_only_min_votes is None:
        return ()
    targets = build_targets(config, with_series=bool(series))
    films = choose_ratings_only(
        [
            *candidate_films(read_tmdb_rows(config.sources.tmdb_csv), targets, config.max_year),
            *series,
        ],
        taken,
        targets,
        min_votes=config.ratings_only_min_votes,
        fallback_min_votes=config.ratings_only_fallback_votes,
    )
    return tuple(
        RatingsOnlyFilm(
            movie=Movie(
                movie_id=ratings_only_id(f.imdb_id),
                title=f.title,
                year=f.year,
                genres=f.genres,
                poster_url=poster_url(f.poster_path),
                kind="series" if f.kind == "series" else "film",
            ),
            imdb_id=f.imdb_id,
            language=f.language,
            imdb_rating=f.imdb_rating,
            imdb_votes=f.imdb_votes,
            overview=f.overview or None,
            release_date=f.release_date or None,
            runtime=int(f.runtime) if f.runtime > 0 else None,
        )
        for f in films
    )


def ratings_only_report(
    config: BuildConfig,
    full_receipt_films: Iterable[SpineFilm],
    ratings_only: Sequence[RatingsOnlyFilm],
    *,
    with_series: bool = False,
) -> dict[str, Any] | None:
    """What the ratings-only tier holds, and how far each bucket is from its target.

    A bucket is a language, or with series in the build one of the three Japanese parts (anime
    series, movies, live-action series). None when the build has no such tier. `short_by` is what
    the owner's target asks for beyond what the dumps could supply; it is reported, never hidden
    by padding the list.
    """
    if config.ratings_only_min_votes is None:
        return None
    split = with_series

    def bucket(language: str, kind: str, genres: Iterable[str]) -> str:
        return bucket_of(language, kind, tuple(genres), split_japanese=split)

    full = Counter(bucket(f.language, f.kind, f.genres) for f in full_receipt_films)
    only = Counter(bucket(f.language or "", f.movie.kind, f.movie.genres) for f in ratings_only)
    # Titles listed on fewer votes than the main floor: the fallback tier, counted on its own so the
    # page's honesty about thin ratings can be checked against how many there are.
    thin = Counter(
        bucket(f.language or "", f.movie.kind, f.movie.genres)
        for f in ratings_only
        if f.imdb_votes < config.ratings_only_min_votes
    )
    return {
        "min_imdb_votes": config.ratings_only_min_votes,
        "fallback_min_imdb_votes": config.ratings_only_fallback_votes,
        "films": len(ratings_only),
        "series": sum(f.movie.kind == "series" for f in ratings_only),
        "by_language": {
            name: {
                "target": target,
                "full_receipts": full.get(name, 0),
                "ratings_only": only.get(name, 0),
                "of_which_below_the_main_floor": thin.get(name, 0),
                "short_by": max(0, target - full.get(name, 0) - only.get(name, 0)),
            }
            for name, target in build_targets(config, with_series=split).items()
        },
    }


def reviews_from(
    reviews: Mapping[int, Sequence[tuple[str, str]]], source: str
) -> dict[int, list[tuple[str, str]]]:
    """One source's reviews, by the `<source>/` prefix every review id carries.

    Films left with no review from that source are dropped from the result.
    """
    prefix = f"{source}/"
    kept = {i: [r for r in rs if r[0].startswith(prefix)] for i, rs in reviews.items()}
    return {i: rs for i, rs in kept.items() if rs}


def source_url_for(imdb_id: int, rt_url: Mapping[int, str]) -> Callable[[str], str | None]:
    """Where a reader can check a quoted sentence: its own source's page for that film.

    RT reviews link to the film's Rotten Tomatoes page; aclImdb and ebD reviews are IMDb's, so
    they link to the IMDb reviews page. An RT review of a film with no known RT page gets no
    link at all rather than a wrong one.
    """
    imdb_page = review_url(imdb_id)

    def link(review_id: str) -> str | None:
        return rt_url.get(imdb_id) if review_id.startswith("rt/") else imdb_page

    return link


def film_meta(
    film: SpineFilm, reviews: Sequence[tuple[str, str]], rt_url: str | None, rating_count: int
) -> dict[str, Any]:
    """TMDB fields for one film, plus how many reviews each source contributed."""
    by_source = Counter(review_id.split("/", 1)[0] for review_id, _ in reviews)
    return {
        "tmdb_id": film.tmdb_id,
        "imdb_id": film.imdb_id,
        "kind": film.kind,
        "language": film.language,
        "release_date": film.release_date,
        "popularity": film.popularity,
        "vote_count": film.vote_count,
        "imdb_rating": film.imdb_rating,
        "imdb_votes": film.imdb_votes,
        "vote_average": film.vote_average,
        "runtime": film.runtime,
        "poster_path": film.poster_path,
        "overview": film.overview,
        "rt_url": rt_url,
        "reviews_by_source": dict(sorted(by_source.items())),
        "rating_count": rating_count,
    }


def era_of(year: int) -> str:
    """The release era used for coverage reporting: before 2000, 2000-2011, or 2012 onward."""
    if year < 2000:
        return "pre2000"
    return "2000-2011" if year < 2012 else "2012+"


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


def load_rating_arrays(
    config: BuildConfig, imdb_ids: Sequence[int]
) -> tuple[
    dict[int, tuple[int, int | None]],
    dict[int, int],
    npt.NDArray[np.int32],
    npt.NDArray[np.int32],
    npt.NDArray[np.float32],
]:
    """MovieLens ratings of the catalogue films, with each film as its catalogue position.

    Args:
        config: Where the MovieLens archive lives.
        imdb_ids: Catalogue films in catalogue order; a film's position is its row everywhere.

    Returns:
        `(links, movielens_of, users, items, stars)`: the raw IMDb-to-MovieLens links, the links
        restricted to catalogue films, and one user id, catalogue position and star rating per
        rating. Shared by the build and the recency check so both see the same ratings.
    """
    links = load_movielens_links(config.ml_archive, config.ml_prefix)
    movielens_of = {i: links[i][0] for i in imdb_ids if i in links}
    users, movielens_ids, stars = load_ratings(
        config.ml_archive, frozenset(movielens_of.values()), config.ml_prefix
    )
    position_of = {imdb_id: p for p, imdb_id in enumerate(imdb_ids)}
    lookup = np.full(
        max(int(movielens_ids.max()), max(movielens_of.values())) + 1, -1, dtype=np.int32
    )
    for imdb_id, movielens_id in movielens_of.items():
        lookup[movielens_id] = position_of[imdb_id]
    return links, movielens_of, users, lookup[movielens_ids], stars


def build_artifacts(config: BuildConfig) -> ArtifactManifest:
    """Run the whole offline build and return the manifest that was written.

    Args:
        config: Input and output locations and the catalogue threshold.

    Returns:
        The verified-at-boot manifest.
    """
    out = config.out_dir
    out.mkdir(parents=True, exist_ok=True)

    _log("gathering films and reviews from TMDB, aclImdb, Rotten Tomatoes and ebD")
    quota_for = wide_quota if config.wide else quota
    if config.cache_file is None:
        gathered = gather(
            config.sources,
            cap=config.cap_per_source,
            quota_for=quota_for,
            languages=config.languages,
            max_year=config.max_year,
            on_progress=_log,
        )
    else:
        gathered = gather_cached(
            config.sources,
            config.cache_file,
            cap=config.cap_per_source,
            quota_for=quota_for,
            languages=config.languages,
            max_year=config.max_year,
            on_progress=_log,
        )
    chosen = select_films(gathered.films, gathered.reviews, config.min_reviews)
    # TV series: their reviews come from ebD alone, joined by title and start year.
    series = series_candidates(config)
    series_reviews: dict[int, list[tuple[str, str]]] = {}
    series_report: dict[str, Any] | None = None
    if series:
        _log(f"reading ebD for the reviews of {len(series)} series")
        series_reviews, series_report = gather_series_reviews(
            config.sources.ebd_zip, series, cap=config.cap_per_source, on_progress=_log
        )
        # IMDb is the authority on type: a TMDB film row carrying a number IMDb files as a series
        # is dropped, and the series (with its own reviews) stands in its place.
        series_numbers = {s.imdb_id for s in series}
        films_chosen = [f for f in chosen if f.imdb_id not in series_numbers]
        series_report["films_dropped_for_being_series"] = len(chosen) - len(films_chosen)
        chosen = sorted(
            [*films_chosen, *select_films(series, series_reviews, config.min_reviews)],
            key=lambda f: f.imdb_id,
        )
    imdb_ids = [f.imdb_id for f in chosen]
    ratings_only = ratings_only_films(config, imdb_ids, series)
    _log(f"ratings-only tier: {len(ratings_only)} titles")
    films = {f.imdb_id: f for f in chosen}
    all_reviews = {**gathered.reviews, **series_reviews}
    reviews = {i: all_reviews[i] for i in imdb_ids}
    _log(
        f"catalogue: {len(chosen)} titles, {sum(f.kind == 'series' for f in chosen)} of them "
        f"series (of {len(gathered.films)} films selected, {len(gathered.reviews)} with any review)"
    )

    # Does a film's reviews name that film more often than a neighbour's? Checked per source,
    # because RT and ebD join by title and year, so a wrong film is a real possibility there.
    titles = {i: films[i].title for i in imdb_ids}
    join_check = {
        source: title_match_rate(titles, reviews_from(reviews, source))
        for source in ("acl", "ebd", "rt")
    }
    _log(f"join check: {join_check}")

    model = PolarityModel.load(out / "polarity.joblib")
    movies: list[Movie] = []
    profiles: dict[str, MovieAspectProfile] = {}
    evidence: dict[str, dict[Aspect, tuple[EvidenceSentence, ...]]] = {}
    for n, imdb_id in enumerate(imdb_ids, start=1):
        film = films[imdb_id]
        movie_id = movie_id_for(imdb_id)
        movies.append(
            Movie(
                movie_id=movie_id,
                title=film.title,
                year=film.year,
                genres=film.genres,
                kind="series" if film.kind == "series" else "film",
            )
        )
        profile, sentences = build_profile(
            movie_id,
            reviews[imdb_id],
            model=model,
            source_url=source_url_for(imdb_id, gathered.rt_url),
        )
        profiles[movie_id] = profile
        by_aspect: dict[Aspect, list[EvidenceSentence]] = defaultdict(list)
        for sentence in sentences:
            by_aspect[sentence.aspect].append(sentence)
        if by_aspect:
            evidence[movie_id] = {a: tuple(v) for a, v in by_aspect.items()}
        if n % 250 == 0:
            _log(f"profiled {n}/{len(imdb_ids)} films")

    # The review text (about 2 GB on the real dumps) was only needed to build the profiles above.
    # Keep the few numbers later stages want and release the text before the ratings and the
    # evaluation, which are the memory-hungry part: three n x n matrices and their temporaries.
    review_counts = {i: len(reviews[i]) for i in imdb_ids}
    n_reviews = sum(review_counts.values())
    meta = {
        movie_id_for(i): film_meta(films[i], reviews[i], gathered.rt_url.get(i), rating_count=0)
        for i in imdb_ids
    }
    gather_report = {**gathered.report, "series": series_report}
    del reviews, gathered

    _log("loading ratings for catalogue films")
    links, movielens_of, users, items, stars = load_rating_arrays(config, imdb_ids)
    # A second, independent id: where both MovieLens and TMDB name a TMDB id for the film, they
    # should agree. A disagreement means the IMDb-number join paired two different films.
    tmdb_disagreements = sum(
        1 for i in imdb_ids if i in links and links[i][1] not in (None, films[i].tmdb_id)
    )
    _log(
        f"MovieLens: {len(movielens_of)} of {len(imdb_ids)} catalogue films linked "
        f"({tmdb_disagreements} disagree on the TMDB id)"
    )
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
        FilmStats(i, int(counts[p]), float(bayes[p]), review_counts[i])
        for p, i in enumerate(imdb_ids)
    )
    catalogue = Catalogue(
        tuple(movies),
        stats,
        profiles,
        evidence,
        similarity,
        {"inferred_fit_weight": rec_report.chosen_fit_weight},
        ratings_only=ratings_only,
    )
    write_catalogue(out, catalogue)
    # TMDB fields the API merges later (posters, language, overview). Kept out of catalogue.json
    # so the shared `Movie` contract in schemas.py does not change with this feature.
    for p, i in enumerate(imdb_ids):
        meta[movie_id_for(i)]["rating_count"] = int(counts[p])
    (out / "meta.json").write_text(
        json.dumps(meta, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )

    gold: dict[str, Any] = {}
    for name in ("dev", "heldout"):
        path = config.gold_dir / f"aspect_gold_{name}.jsonl"
        if path.is_file():
            gold[name] = asdict(evaluate_gold(load_gold(path), model))
    # Uniform random samples of clauses: the only ones that can measure recall. A and B were
    # used to tune the lexicon, so only C (and the polarity of B+C, which the lexicon tuning
    # did not touch) are reported as clean. See DECISIONS D-015.
    random_rows = {
        name: load_random_gold(config.gold_dir / f"aspect_gold_random_{name}.jsonl")
        for name in RANDOM_SAMPLE_ROLES
        if (config.gold_dir / f"aspect_gold_random_{name}.jsonl").is_file()
    }
    random_gold: dict[str, Any] = {
        name: {**asdict(evaluate_random(rows, model)), "role": RANDOM_SAMPLE_ROLES[name]}
        for name, rows in random_rows.items()
    }
    clean_pool = [r for n in ("b", "c") for r in random_rows.get(n, [])]
    if clean_pool:
        random_gold["clean_pooled_b_c"] = asdict(evaluate_random(clean_pool, model))
    slider = slider_response(catalogue)
    polarity_path = out / "polarity_report.json"
    # Written by `python -m cinewhy.absa.domain_check`: how the model does on RT and ebD text,
    # which it was not trained on. A separate command because the scan takes about 15 minutes.
    domain_path = out / "polarity_domain.json"
    eval_blob = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {
            "films": "TMDB export (Kaggle alanvourch/tmdb-movies-daily-updates): top films per "
            "language and year by vote count",
            "reviews": "aclImdb v1 (Maas et al. 2011); Rotten Tomatoes user reviews (Kaggle "
            "bwandowando, to mid-2024); IMDb reviews (Kaggle ebiswas, to about 2020)",
            "ratings": "MovieLens 32M (GroupLens), to 12 Oct 2023",
            "join": "aclImdb and MovieLens by exact IMDb number; RT and ebD by title and year "
            "with a runtime check (docs/FEATURE-004.md)",
        },
        "gather": gather_report,
        "movielens": {
            "catalogue_films_linked": len(movielens_of),
            "tmdb_id_disagreements": tmdb_disagreements,
        },
        "catalogue": {
            "films": n_films,
            "films_by_language_and_era": dict(
                sorted(Counter(f"{f.language}/{era_of(f.year)}" for f in films.values()).items())
            ),
            "films_with_ratings": int((counts > 0).sum()),
            "similarity_megabytes": round(similarity.nbytes / 1e6),
            "reviews": n_reviews,
            "evidence_sentences": sum(len(s) for by in evidence.values() for s in by.values()),
            "min_reviews_per_film": config.min_reviews,
            "series": sum(f.kind == "series" for f in films.values()),
            "ratings_only": ratings_only_report(
                config, films.values(), ratings_only, with_series=bool(series)
            ),
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
        "polarity_domain": json.loads(domain_path.read_text(encoding="utf-8"))
        if domain_path.is_file()
        else None,
        "gold": gold,
        "random_gold": random_gold,
        "slider_check": slider,
        "gold_note": "Labels written by the assistant, not an independent human. See gold.py.",
        "recommender": asdict(rec_report),
    }
    (out / "eval.json").write_text(
        json.dumps(eval_blob, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )

    row_counts = {"films": n_films, "ratings": len(stars), "reviews": n_reviews}
    # Name the artifacts explicitly: the directory may also hold logs, and hashing a file that
    # is still being written would make the manifest fail to verify at the next boot.
    names = (*ARTIFACT_FILES, "ratings_only.json") if ratings_only else ARTIFACT_FILES
    manifest = build_manifest(out, row_counts=row_counts, names=names)
    _log(f"manifest {manifest.manifest_hash[:12]} over {len(manifest.files)} files")
    return manifest


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    defaults = BuildConfig()
    parser.add_argument("--tmdb", type=Path, default=defaults.sources.tmdb_csv)
    parser.add_argument("--rt", type=Path, default=defaults.sources.rt_zip)
    parser.add_argument("--ebd", type=Path, default=defaults.sources.ebd_zip)
    parser.add_argument("--acl", type=Path, default=defaults.sources.acl_archive)
    parser.add_argument("--ml", type=Path, default=defaults.ml_archive)
    parser.add_argument("--out", type=Path, default=defaults.out_dir)
    parser.add_argument("--min-reviews", type=int, default=defaults.min_reviews)
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("Data/raw/_cache/gathered.jsonl"),
        help="where the gather step keeps its result (gitignored); reused while the dumps and "
        "the gather logic are unchanged",
    )
    parser.add_argument("--no-cache", action="store_true", help="always re-read the dumps")
    parser.add_argument(
        "--cap",
        type=int,
        default=defaults.cap_per_source,
        help="most reviews kept per film per source; lower it to save memory on a wide build",
    )
    parser.add_argument(
        "--languages",
        default=None,
        help="comma-separated original languages to select, e.g. en,hi,te,ja,fr (default: en,hi)",
    )
    parser.add_argument("--max-year", type=int, default=None, help="latest release year")
    parser.add_argument(
        "--wide", action="store_true", help="the wider candidate list (spine.wide_quota)"
    )
    parser.add_argument(
        "--ratings-only-min-votes",
        type=int,
        default=None,
        help="also list films with this many IMDb votes and no full receipt (default: none)",
    )
    parser.add_argument(
        "--ratings-only-fallback-votes",
        type=int,
        default=None,
        help="a lower vote floor used only to fill a language still short of its target",
    )
    parser.add_argument(
        "--series-dumps",
        type=Path,
        default=None,
        help="folder with IMDb's title.basics and title.ratings dumps (adds series with the next)",
    )
    parser.add_argument(
        "--series-tmdb",
        type=Path,
        default=None,
        help="the TMDB series cache written by `python -m cinewhy.data.fetch_series`",
    )
    parser.add_argument("--series-min-votes", type=int, default=200, help="fewest IMDb votes")
    args = parser.parse_args()
    build_artifacts(
        BuildConfig(
            sources=SourcePaths(
                tmdb_csv=args.tmdb, rt_zip=args.rt, ebd_zip=args.ebd, acl_archive=args.acl
            ),
            cache_file=None if args.no_cache else args.cache,
            ml_archive=args.ml,
            out_dir=args.out,
            min_reviews=args.min_reviews,
            cap_per_source=args.cap,
            languages=tuple(args.languages.split(",")) if args.languages else None,
            max_year=args.max_year,
            wide=args.wide,
            ratings_only_min_votes=args.ratings_only_min_votes,
            ratings_only_fallback_votes=args.ratings_only_fallback_votes,
            series_dumps=args.series_dumps,
            series_tmdb=args.series_tmdb,
            series_min_votes=args.series_min_votes,
        )
    )


if __name__ == "__main__":
    main()
