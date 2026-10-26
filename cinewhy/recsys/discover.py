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
from collections.abc import Sequence
from typing import Final

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict

from cinewhy.recsys import rank
from cinewhy.recsys.catalogue import Catalogue
from cinewhy.schemas import Movie, Reason, TasteProfile

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
        return rank.popularity_unit(catalogue)
    mean = float(ratings[scored].mean())
    shrunk = np.where(scored, (ratings * votes + mean * VOTE_PRIOR) / (votes + VOTE_PRIOR), mean)
    known = np.log10(1.0 + votes) / math.log10(1.0 + float(votes.max()))
    return QUALITY_SHARE * _unit(shrunk) + (1.0 - QUALITY_SHARE) * known


def discover(
    catalogue: Catalogue,
    profile: TasteProfile,
    *,
    limit: int = 20,
    recency: float = 0.5,
    languages: Sequence[str] = (),
    genres: Sequence[str] = (),
    from_year: int | None = None,
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
        exclude: Film ids never to return.
        manifest: Hash of the artifact set, echoed so a result can be traced to its build.

    Returns:
        The ranked list, possibly empty when the filters match nothing.
    """
    n = len(catalogue.movies)
    years = film_years(catalogue)
    newest = int(years.max()) if n else 0
    language_of = [catalogue.meta.get(m.movie_id, {}).get("language") for m in catalogue.movies]

    allowed = np.ones(n, dtype=bool)
    if from_year is not None:
        allowed &= years >= from_year
    if languages:
        allowed &= np.array([lang in languages for lang in language_of], dtype=bool)
    if genres:
        wanted = set(genres)
        allowed &= np.array([bool(wanted & set(m.genres)) for m in catalogue.movies], dtype=bool)

    skip = set(exclude) | set(profile.liked_movie_ids) | set(profile.disliked_movie_ids)
    popularity = audience_popularity(catalogue)
    span = max(1, newest - RECENCY_FROM_YEAR)
    lift = RECENCY_MAX * recency * np.clip((years - RECENCY_FROM_YEAR) / span, 0.0, 1.0)

    liked = [catalogue.index[i] for i in profile.liked_movie_ids if i in catalogue.index]
    disliked = [catalogue.index[i] for i in profile.disliked_movie_ids if i in catalogue.index]
    weights = {a: w for a, w in profile.aspect_weights.items() if w > 0}
    explicit = bool(weights)
    if not weights:
        weights = rank.infer_weights(catalogue, profile.liked_movie_ids)
    cold = not liked and not weights

    if cold:
        score = popularity + lift
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

    items: list[DiscoverItem] = []
    for i in sorted(range(n), key=lambda j: (-float(score[j]), j)):
        movie = catalogue.movies[i]
        if not allowed[i] or movie.movie_id in skip:
            continue
        reasons = rank.reasons_for(catalogue, movie.movie_id, weights, highlight=not weights)
        if not cold and not reasons:  # nothing real to say about this film for this visitor
            continue
        items.append(
            DiscoverItem(
                movie=movie,
                language=language_of[i],
                is_new=bool(newest and years[i] >= newest - NEW_WINDOW_YEARS),
                score=float(score[i]),
                reasons=reasons,
                is_fallback=cold,
            )
        )
        if len(items) == limit:
            break
    return DiscoverResult(items=tuple(items), cold_start=cold, manifest=manifest)
