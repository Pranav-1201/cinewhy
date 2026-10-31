"""Ranking: blend collaborative filtering with aspect fit, and attach the evidence.

The ranker answers two questions. WHAT to recommend comes from two signals: what people
with similar ratings liked (`cf`), and how well a film's aspect scores match what this viewer
cares about (`fit`). WHY comes only from `Catalogue.evidence`, which is quoted review text
chosen offline, never generated here. A personalised result that cannot be explained with at
least one real sentence is not returned (`schemas.Recommendation` enforces this too).

Deterministic by construction: ties break on catalogue position, so the same profile always
yields the same list (the contract test `test_recommendations_are_deterministic`).
"""

from __future__ import annotations

import unicodedata
from typing import Final

import numpy as np
import numpy.typing as npt

from cinewhy.recsys.catalogue import Catalogue, aspect_order
from cinewhy.schemas import (
    Aspect,
    EvidenceSentence,
    Movie,
    MovieAspectProfile,
    Reason,
    Recommendation,
    RecommendRequest,
    RecommendResponse,
)

# A shrunk aspect score below this is not worth presenting as a reason.
MIN_REASON_SCORE: Final[float] = 0.1
MAX_REASONS: Final[int] = 3
MAX_EVIDENCE: Final[int] = 3
# Inferred taste keeps only aspects at least this fraction as strong as the strongest, so a
# viewer who loved three films for their pacing is not told they also "care about" soundtrack.
INFER_FLOOR: Final[float] = 0.25
# Down-weight for disliked films' neighbours: a dislike is weaker evidence than a like,
# because people dislike films for reasons that say little about the neighbours.
DISLIKE_FACTOR: Final[float] = 0.5

# Signal weights when only ONE personal signal is present; weights always sum to one.
_BLEND: Final[dict[str, tuple[float, float, float]]] = {
    # name:        (cf,   fit,  popularity)
    "cf": (0.85, 0.0, 0.15),
    "fit": (0.0, 0.80, 0.20),
}
# Aspect-fit share when the viewer moved the aspect sliders themselves: they asked for
# aspect-driven results, so honour it. NOT validated offline (there is no ground truth for
# stated preferences); the evaluated case is the inferred one below.
EXPLICIT_FIT_WEIGHT: Final[float] = 0.45
# Aspect-fit share when the weights were only inferred from liked films, used if the
# artifact carries no tuned value. The build tunes this on validation users.
DEFAULT_INFERRED_FIT_WEIGHT: Final[float] = 0.2


def _unit(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Min-max scale to [0, 1]; a constant vector maps to zeros."""
    span = float(values.max() - values.min())
    return (values - values.min()) / span if span > 0 else np.zeros_like(values)


def infer_weights_from_rows(
    aspect_matrix: npt.NDArray[np.float32], rows: list[int]
) -> dict[Aspect, float]:
    """Infer what a viewer values from the aspect scores of films they liked.

    Averages the positive part of each liked film's aspect scores and scales so the
    strongest aspect is 1.0. A viewer who never states a preference still gets an
    explainable ranking, and the UI shows the inferred weights so they can be corrected.

    Args:
        aspect_matrix: `(films, aspects)` shrunk aspect scores.
        rows: Row indices of the liked films.

    Returns:
        Aspect weights in (0, 1], empty when nothing can be inferred.
    """
    if not rows:
        return {}
    mean_positive = np.clip(aspect_matrix[rows], 0.0, None).mean(axis=0)
    top = float(mean_positive.max())
    if top <= 0.0:
        return {}
    return {
        aspect: round(float(v) / top, 3)
        for aspect, v in zip(aspect_order(), mean_positive, strict=True)
        if float(v) / top >= INFER_FLOOR
    }


def infer_weights(catalogue: Catalogue, liked_ids: tuple[str, ...]) -> dict[Aspect, float]:
    """`infer_weights_from_rows` for catalogue film ids; unknown ids are ignored."""
    rows = [catalogue.index[i] for i in liked_ids if i in catalogue.index]
    return infer_weights_from_rows(catalogue.aspect_matrix, rows)


def blend_scores(
    similarity: npt.NDArray[np.float32],
    aspect_matrix: npt.NDArray[np.float32],
    popularity: npt.NDArray[np.float64],
    *,
    liked: list[int],
    disliked: list[int],
    weights: dict[Aspect, float],
    fit_weight: float = EXPLICIT_FIT_WEIGHT,
) -> npt.NDArray[np.float64]:
    """Score every film for one viewer: collaborative filtering, aspect fit and popularity.

    This is the one place the blend is defined. `recommend` serves it and
    `cinewhy.recsys.evaluate` measures it, so the offline numbers describe the shipped code.

    Args:
        similarity: Item-item similarity.
        aspect_matrix: `(films, aspects)` shrunk aspect scores.
        popularity: Popularity per film, scaled to [0, 1].
        liked: Row indices of liked films (may be empty).
        disliked: Row indices of disliked films (may be empty).
        weights: Aspect weights (may be empty). At least one of `liked` or `weights` must
            be non-empty.
        fit_weight: Share given to aspect fit when BOTH collaborative filtering and aspect
            fit are present; collaborative filtering gets `0.9 - fit_weight` and popularity
            a fixed 0.1. Offline evaluation showed aspect fit costs hit-rate, so the weight
            is large only when the viewer set the aspects themselves.

    Returns:
        One score per film, higher is better. Not yet filtered for exclusions.
    """
    signals: dict[str, npt.NDArray[np.float64]] = {}
    if liked:
        cf = similarity[:, liked].mean(axis=1).astype(np.float64)
        if disliked:
            cf -= DISLIKE_FACTOR * similarity[:, disliked].mean(axis=1)
        signals["cf"] = _unit(cf)
    if weights:
        vector = np.array([weights.get(a, 0.0) for a in aspect_order()], dtype=np.float64)
        fit = aspect_matrix.astype(np.float64) @ vector / vector.sum()
        signals["fit"] = (fit + 1.0) / 2.0
    if not signals:
        raise ValueError("need liked films or aspect weights to personalise")
    if len(signals) == 2:
        cf_w, fit_w, pop_w = 0.9 - fit_weight, fit_weight, 0.1
    else:
        cf_w, fit_w, pop_w = _BLEND[next(iter(signals))]
    score = pop_w * popularity
    if "cf" in signals:
        score = score + cf_w * signals["cf"]
    if "fit" in signals:
        score = score + fit_w * signals["fit"]
    return score


def popularity_unit(catalogue: Catalogue) -> npt.NDArray[np.float64]:
    """Bayesian mean rating per film, scaled to [0, 1]."""
    return _unit(np.array([s.bayes_mean for s in catalogue.stats], dtype=np.float64))


def _raw_score(profile: MovieAspectProfile, aspect: Aspect) -> float:
    return next(s.score for s in profile.scores if s.aspect is aspect)


def _reasons(
    catalogue: Catalogue, movie_id: str, weights: dict[Aspect, float], *, highlight: bool = False
) -> tuple[Reason, ...]:
    """Reasons a film suits these weights, strongest first, each with real evidence.

    With `highlight=True` no viewer preference exists (for example the only film they liked
    has no positively scored aspect to infer from), so the film's own best-supported praise
    is shown instead, with `user_weight=0.0` so the UI can say "praised for" rather than
    "because you care about".
    """
    if highlight:
        weights = dict.fromkeys(aspect_order(), 1.0)
    ranked: list[tuple[float, Aspect]] = []
    for aspect, weight in weights.items():
        shrunk = catalogue.shrunk(movie_id, aspect)
        if (
            weight > 0
            and shrunk >= MIN_REASON_SCORE
            and catalogue.evidence.get(movie_id, {}).get(aspect)
        ):
            ranked.append((weight * shrunk, aspect))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].value))
    profile = catalogue.profiles[movie_id]
    return tuple(
        Reason(
            aspect=aspect,
            movie_score=_raw_score(profile, aspect),
            user_weight=0.0 if highlight else min(1.0, max(0.0, weights[aspect])),
            evidence=catalogue.evidence[movie_id][aspect][:MAX_EVIDENCE],
        )
        for _, aspect in ranked[:MAX_REASONS]
    )


# Public name for the reasons builder, so `cinewhy.recsys.discover` does not import a private one.
reasons_for = _reasons


def popular(catalogue: Catalogue, excluded: set[str], limit: int) -> tuple[Recommendation, ...]:
    """Most-liked films by Bayesian mean rating, labelled as the fallback they are."""
    order = sorted(range(len(catalogue.movies)), key=lambda i: (-catalogue.stats[i].bayes_mean, i))
    picked = [i for i in order if catalogue.movies[i].movie_id not in excluded][:limit]
    return tuple(
        Recommendation(
            movie=catalogue.movies[i],
            score=catalogue.stats[i].bayes_mean,
            reasons=(),
            is_fallback=True,
        )
        for i in picked
    )


def recommend(catalogue: Catalogue, request: RecommendRequest, manifest: str) -> RecommendResponse:
    """Rank films for a taste profile and attach the evidence for each.

    Args:
        catalogue: The loaded catalogue.
        request: Taste profile, limit and exclusions.
        manifest: Hash of the artifact set, echoed so a result can be traced to its build.

    Returns:
        Ranked recommendations. A cold-start profile gets the popularity fallback with
        `cold_start=True`; it is not an error and carries no invented rationale.
    """
    profile = request.profile
    excluded = (
        set(profile.liked_movie_ids)
        | set(profile.disliked_movie_ids)
        | set(request.exclude_movie_ids)
    )
    if profile.is_cold_start:
        return RecommendResponse(
            items=popular(catalogue, excluded, request.limit), cold_start=True, manifest=manifest
        )

    liked = [catalogue.index[i] for i in profile.liked_movie_ids if i in catalogue.index]
    disliked = [catalogue.index[i] for i in profile.disliked_movie_ids if i in catalogue.index]
    weights = {a: w for a, w in profile.aspect_weights.items() if w > 0}
    explicit = bool(weights)
    if not weights:
        weights = infer_weights(catalogue, profile.liked_movie_ids)
    fit_weight = (
        EXPLICIT_FIT_WEIGHT
        if explicit
        else catalogue.settings.get("inferred_fit_weight", DEFAULT_INFERRED_FIT_WEIGHT)
    )

    if not liked and not weights:  # only unknown ids were supplied: nothing to personalise on
        return RecommendResponse(
            items=popular(catalogue, excluded, request.limit), cold_start=True, manifest=manifest
        )
    score = blend_scores(
        catalogue.similarity,
        catalogue.aspect_matrix,
        popularity_unit(catalogue),
        liked=liked,
        disliked=disliked,
        weights=weights,
        fit_weight=fit_weight,
    )

    items: list[Recommendation] = []
    for i in sorted(range(len(catalogue.movies)), key=lambda j: (-float(score[j]), j)):
        movie = catalogue.movies[i]
        if movie.movie_id in excluded:
            continue
        reasons = _reasons(catalogue, movie.movie_id, weights, highlight=not weights)
        if not reasons:  # nothing real to say about this film for this viewer
            continue
        items.append(Recommendation(movie=movie, score=float(score[i]), reasons=reasons))
        if len(items) == request.limit:
            break
    if not items:
        items_fallback = popular(catalogue, excluded, request.limit)
        return RecommendResponse(items=items_fallback, cold_start=False, manifest=manifest)
    return RecommendResponse(items=tuple(items), cold_start=False, manifest=manifest)


def fold_accents(text: str) -> str:
    """Lowercase, with accents removed: so "amelie" finds the film titled with an accent on its e.

    Keeps spaces and punctuation (search matches word starts), unlike the join key in
    `cinewhy.data.linking`, which drops them. Letters that do not decompose (an o with a stroke)
    are left as they are.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def search(catalogue: Catalogue, query: str, limit: int = 20) -> list[Movie]:
    """Find films by title: prefix matches first, then word-start, then substring.

    Accents are ignored on both sides. Within a tier, better-known films (more ratings) come first.

    Args:
        catalogue: The catalogue.
        query: User-supplied text. Matched literally; never interpreted as a pattern.
        limit: Maximum results.

    Returns:
        Matching films, best first. Empty for a blank query.
    """
    needle = fold_accents(query.strip())
    if not needle:
        return []
    hits: list[tuple[int, int, int, int]] = []
    everything = catalogue.all_movies
    for i, movie in enumerate(everything):
        title = fold_accents(movie.title)
        if title.startswith(needle):
            tier = 0
        elif f" {needle}" in f" {title}":
            tier = 1
        elif needle in title:
            tier = 2
        else:
            continue
        # Films with reviews first within a tier; a ratings-only film follows, best known first
        # (its vote count is IMDb's, not MovieLens', so the two are never compared with each other).
        if i < len(catalogue.movies):
            hits.append((tier, 0, -catalogue.stats[i].rating_count, i))
        else:
            hits.append((tier, 1, -catalogue.ratings_only_at(i).imdb_votes, i))
    hits.sort()
    return [everything[i] for _, _, _, i in hits[:limit]]


def movie_detail(
    catalogue: Catalogue, movie_id: str
) -> tuple[Movie, MovieAspectProfile, dict[Aspect, tuple[EvidenceSentence, ...]]]:
    """Return one film, its aspect profile and its evidence by aspect.

    Raises:
        KeyError: If there is no such film. The HTTP layer maps this to a 404.
    """
    movie = catalogue.movies[catalogue.index[movie_id]]
    return movie, catalogue.profiles[movie_id], catalogue.evidence.get(movie_id, {})
