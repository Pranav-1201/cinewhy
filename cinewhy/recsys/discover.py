"""Discovery ranking: what to show first, with a say over era, language and genre (FEATURE-005).

`rank.recommend` answers "what suits this taste". Discovery adds the question a first-time
visitor actually has: "what is worth watching, and is it recent enough to be mine?". Three
changes from the cold-start list it replaces:

* Popularity comes from IMDb's own rating and vote count, not from MovieLens. A film nobody rated
  on MovieLens (most Hindi films) used to sit at the global mean and could never surface.
* A recency term, scaled by the visitor, lifts newer films. It is bounded (`RECENCY_MAX`) so it can
  reorder films of similar standing but never lift a poor new film over a clearly better old one.
* Filters (from-year, language, genre) narrow the LIST. They never touch the catalogue: older
  films are demoted or hidden from a view, not deleted, and search still finds them.

Nothing here trains or fits anything (CONSTRAINTS.md #5): it reads the catalogue and its `meta`.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict

from cinewhy.recsys import rank
from cinewhy.recsys.catalogue import Catalogue
from cinewhy.schemas import Aspect, Movie, Reason, TasteProfile

# The most the recency term can add to a score that otherwise runs from 0 to 1. At 0.30 a film
# from 2022 can overtake a film from 1995 that is somewhat better liked, but not a far better one.
RECENCY_MAX: Final[float] = 0.30
# Films this old or older get no recency lift; the lift grows linearly to the newest film.
RECENCY_FROM_YEAR: Final[int] = 1980
# A film counts as "new" if it is within this many years of the newest film in the catalogue.
NEW_WINDOW_YEARS: Final[int] = 7
# IMDb votes worth of pull toward the average rating: a 9.5 from 800 voters is not a 9.5.
VOTE_PRIOR: Final[float] = 5000.0
# Share of popularity from how well liked a film is; the rest is how many people have voted.
QUALITY_SHARE: Final[float] = 0.5


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DiscoverItem(_Frozen):
    """One film in a discovery list, with what a card needs beyond the film itself."""

    movie: Movie
    language: str | None
    is_new: bool
    score: float
    reasons: tuple[Reason, ...]
    # True when nothing about the visitor was used: the film is shown for being well known.
    is_fallback: bool


class DiscoverResult(_Frozen):
    """A discovery list and which build produced it."""

    items: tuple[DiscoverItem, ...]
    cold_start: bool
    manifest: str


def _unit(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    span = float(values.max() - values.min())
    return (values - values.min()) / span if span > 0 else np.zeros_like(values)


def recency_lift(years: npt.NDArray[np.int64], recency: float) -> npt.NDArray[np.float64]:
    """Score added to each film for being recent, at a recency setting from 0 to 1.

    Zero up to `RECENCY_FROM_YEAR`, then linear to `RECENCY_MAX * recency` for the newest film.
    The evaluation and the live ranking both call this, so what is measured is what ships.
    """
    newest = int(years.max()) if len(years) else 0
    span = max(1, newest - RECENCY_FROM_YEAR)
    return np.asarray(
        RECENCY_MAX * recency * np.clip((years - RECENCY_FROM_YEAR) / span, 0.0, 1.0),
        dtype=np.float64,
    )


def film_years(catalogue: Catalogue) -> npt.NDArray[np.int64]:
    """Release year per film: its own year, else the year in its TMDB release date, else 0.

    Args:
        catalogue: The loaded catalogue.

    Returns:
        One year per film, in catalogue order; 0 means unknown.
    """

    def year_of(movie: Movie) -> int:
        if movie.year:
            return movie.year
        date = str(catalogue.meta.get(movie.movie_id, {}).get("release_date") or "")
        return int(date[:4]) if date[:4].isdigit() else 0

    return np.array([year_of(m) for m in catalogue.movies], dtype=np.int64)


def catalogue_facets(catalogue: Catalogue) -> dict[str, object]:
    """Counts the UI shows next to its filters: films per language, per genre, and the year range.

    Args:
        catalogue: The loaded catalogue.

    Returns:
        `films`, `languages` (original language to count; only films with a known language),
        `genres`, and `oldest_year` / `newest_year` (None when no film has a year).
    """
    languages: dict[str, int] = {}
    genres: dict[str, int] = {}
    for movie in catalogue.movies:
        if language := catalogue.meta.get(movie.movie_id, {}).get("language"):
            languages[language] = languages.get(language, 0) + 1
        for genre in movie.genres:
            genres[genre] = genres.get(genre, 0) + 1
    known = [int(y) for y in film_years(catalogue) if y > 0]
    return {
        "films": len(catalogue.movies),
        "languages": dict(sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))),
        "genres": dict(sorted(genres.items(), key=lambda kv: (-kv[1], kv[0]))),
        "oldest_year": min(known) if known else None,
        "newest_year": max(known) if known else None,
    }


def audience_popularity(catalogue: Catalogue) -> npt.NDArray[np.float64]:
    """How well known and well liked each film is, 0 to 1, from IMDb numbers when available.

    Quality is IMDb's rating pulled toward the average by `VOTE_PRIOR` votes, so a score from
    few voters counts for little. Known-ness is the log of the vote count, so a hundred
    thousand votes outweighs a thousand without a blockbuster drowning everything else.
    Without `meta.json` it falls back to the MovieLens-based signal the old list used.

    Args:
        catalogue: The loaded catalogue.

    Returns:
        One value per film, in catalogue order.
    """
    parts = _quality_and_known(catalogue)
    if parts is None:
        return rank.popularity_unit(catalogue)
    quality, known = parts
    return QUALITY_SHARE * quality + (1.0 - QUALITY_SHARE) * known


def audience_quality(catalogue: Catalogue) -> npt.NDArray[np.float64]:
    """How well liked each film is, 0 to 1: IMDb's rating pulled toward the average by votes.

    Unlike `audience_popularity` this ignores how many people voted beyond the pull toward the
    average, so a famous but poorly rated film scores low. Used where a heading claims "well
    reviewed".
    Without `meta.json` it falls back to the MovieLens-based signal.
    """
    parts = _quality_and_known(catalogue)
    return rank.popularity_unit(catalogue) if parts is None else parts[0]


def _quality_and_known(
    catalogue: Catalogue,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]] | None:
    """(quality, known-ness), each 0 to 1 per film, or None when no film has IMDb numbers."""
    ratings = np.array(
        [
            float(catalogue.meta.get(m.movie_id, {}).get("imdb_rating") or 0.0)
            for m in catalogue.movies
        ]
    )
    votes = np.array(
        [
            float(catalogue.meta.get(m.movie_id, {}).get("imdb_votes") or 0.0)
            for m in catalogue.movies
        ]
    )
    scored = (ratings > 0) & (votes > 0)
    if not scored.any():
        return None
    mean = float(ratings[scored].mean())
    shrunk = np.where(scored, (ratings * votes + mean * VOTE_PRIOR) / (votes + VOTE_PRIOR), mean)
    known = np.log10(1.0 + votes) / math.log10(1.0 + float(votes.max()))
    return _unit(shrunk), known


Mode = Literal["blend", "similar"]


@dataclass(frozen=True)
class Scored:
    """Every film's score for one visitor, worked out once and then filtered for many shelves.

    Scoring is the costly part (a pass over the similarity matrix); picking a shelf's films from
    the result is cheap, so a page of twenty shelves costs a few scorings, not twenty.
    """

    score: npt.NDArray[np.float64]
    weights: dict[Aspect, float]
    cold: bool
    years: npt.NDArray[np.int64]
    language_of: list[str | None]
    order: list[int]  # film positions, best score first; ties break on catalogue position


def score_films(
    catalogue: Catalogue, profile: TasteProfile, *, recency: float = 0.5, mode: Mode = "blend"
) -> Scored:
    """Score every film for this visitor.

    `mode="blend"` is what `discover` has always done: collaborative filtering and aspect fit,
    or popularity alone for a cold start. `mode="similar"` uses only what viewers who liked the
    same films went on to like (no aspect fit), and is a cold start when nothing is liked.

    Args:
        catalogue: The loaded catalogue.
        profile: What the visitor said they like; may be empty.
        recency: 0 for no preference for new films, 1 for the strongest lift (`RECENCY_MAX`).
        mode: Which signals to use, as above.

    Returns:
        Scores, the aspect weights the reasons should use, and whether this is a cold start.
    """
    n = len(catalogue.movies)
    years = film_years(catalogue)
    language_of = [catalogue.meta.get(m.movie_id, {}).get("language") for m in catalogue.movies]
    popularity = audience_popularity(catalogue)
    lift = recency_lift(years, recency)
    liked = [catalogue.index[i] for i in profile.liked_movie_ids if i in catalogue.index]
    disliked = [catalogue.index[i] for i in profile.disliked_movie_ids if i in catalogue.index]

    weights: dict[Aspect, float] = {}
    if mode == "similar":
        cold = not liked
    else:
        weights = {a: w for a, w in profile.aspect_weights.items() if w > 0}
        explicit = bool(weights)
        if not weights:
            weights = rank.infer_weights(catalogue, profile.liked_movie_ids)
        cold = not liked and not weights

    if cold:
        score = popularity + lift
    elif mode == "similar":
        score = (
            rank.blend_scores(
                catalogue.similarity,
                catalogue.aspect_matrix,
                popularity,
                liked=liked,
                disliked=disliked,
                weights={},
            )
            + lift
        )
    else:
        fit_weight = (
            rank.EXPLICIT_FIT_WEIGHT
            if explicit
            else catalogue.settings.get("inferred_fit_weight", rank.DEFAULT_INFERRED_FIT_WEIGHT)
        )
        score = (
            rank.blend_scores(
                catalogue.similarity,
                catalogue.aspect_matrix,
                popularity,
                liked=liked,
                disliked=disliked,
                weights=weights,
                fit_weight=fit_weight,
            )
            + lift
        )
    order = sorted(range(n), key=lambda j: (-float(score[j]), j))
    return Scored(score, weights, cold, years, language_of, order)


def select_items(
    catalogue: Catalogue,
    scored: Scored,
    *,
    limit: int,
    languages: Sequence[str] = (),
    genres: Sequence[str] = (),
    from_year: int | None = None,
    to_year: int | None = None,
    exclude: Collection[str] = (),
    order: Sequence[int] | None = None,
) -> tuple[DiscoverItem, ...]:
    """The best films for one shelf: `scored`, filtered by language, genre and years.

    Args:
        catalogue: The loaded catalogue.
        scored: From `score_films`.
        limit: Most films to return.
        languages: Keep only films whose original language is one of these (empty keeps all).
        genres: Keep only films with at least one of these genres (empty keeps all).
        from_year: Keep only films released in or after this year.
        to_year: Keep only films released in or before this year (films with no known year are
            left out).
        exclude: Film ids never to return (including ones already shown on another shelf).
        order: Film positions in the order to consider them; default is best score first.

    Returns:
        Up to `limit` films, in order; fewer (even none) when the filters leave few.
    """
    n = len(catalogue.movies)
    years = scored.years
    newest = int(years.max()) if n else 0
    allowed = np.ones(n, dtype=bool)
    if from_year is not None:
        allowed &= years >= from_year
    if to_year is not None:
        # A film of unknown year (0) is not "older than" anything: keep it out of a shelf of
        # classics rather than let a missing date pass for a very old film.
        allowed &= (years > 0) & (years <= to_year)
    if languages:
        allowed &= np.array([lang in languages for lang in scored.language_of], dtype=bool)
    if genres:
        wanted = set(genres)
        allowed &= np.array([bool(wanted & set(m.genres)) for m in catalogue.movies], dtype=bool)

    skip = set(exclude)
    items: list[DiscoverItem] = []
    for i in order if order is not None else scored.order:
        movie = catalogue.movies[i]
        if not allowed[i] or movie.movie_id in skip:
            continue
        reasons = rank.reasons_for(
            catalogue, movie.movie_id, scored.weights, highlight=not scored.weights
        )
        if not scored.cold and not reasons:  # nothing real to say about this film for this visitor
            continue
        items.append(
            DiscoverItem(
                movie=movie,
                language=scored.language_of[i],
                is_new=bool(newest and years[i] >= newest - NEW_WINDOW_YEARS),
                score=float(scored.score[i]),
                reasons=reasons,
                is_fallback=scored.cold,
            )
        )
        if len(items) == limit:
            break
    return tuple(items)


def discover(
    catalogue: Catalogue,
    profile: TasteProfile,
    *,
    limit: int = 20,
    recency: float = 0.5,
    languages: Sequence[str] = (),
    genres: Sequence[str] = (),
    from_year: int | None = None,
    to_year: int | None = None,
    exclude: Sequence[str] = (),
    manifest: str,
) -> DiscoverResult:
    """Rank films for a visitor, with optional era, language and genre filters.

    A profile with no liked films and no aspect weights is a cold start: films are ordered by
    audience popularity plus the recency lift. Otherwise the existing blend of collaborative
    filtering and aspect fit decides (`rank.blend_scores`), with the same popularity signal
    and the same recency lift added. Ties break on catalogue position, so the same request
    always returns the same list.

    Args:
        catalogue: The loaded catalogue.
        profile: What the visitor said they like; may be empty.
        limit: Most films to return.
        recency: 0 for no preference for new films, 1 for the strongest lift (`RECENCY_MAX`).
        languages: Keep only films whose original language is one of these (empty keeps all).
        genres: Keep only films with at least one of these genres (empty keeps all).
        from_year: Keep only films released in or after this year.
        to_year: Keep only films released in or before this year (films with no known year are
            left out).
        exclude: Film ids never to return.
        manifest: Hash of the artifact set, echoed so a result can be traced to its build.

    Returns:
        The ranked list, possibly empty when the filters match nothing.
    """
    scored = score_films(catalogue, profile, recency=recency)
    items = select_items(
        catalogue,
        scored,
        limit=limit,
        languages=languages,
        genres=genres,
        from_year=from_year,
        to_year=to_year,
        exclude=set(exclude) | set(profile.liked_movie_ids) | set(profile.disliked_movie_ids),
    )
    return DiscoverResult(items=items, cold_start=scored.cold, manifest=manifest)
