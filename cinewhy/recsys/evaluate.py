"""Offline evaluation of the recommender, with spread, against a popularity baseline.

The protocol follows the project's methodology rules (CONSTRAINTS.md #1-#3):

* Users are split into train / validation / test **by user**. The similarity matrix and the
  popularity prior are fitted on train users' ratings only, so no test user's rating can
  influence the model that is scored on them.
* The one tunable (similarity shrinkage) is chosen on validation users. Test users are read
  once, afterwards.
* Every figure carries a bootstrap 95% interval, and every comparison is a *paired*
  difference with its own interval, because "A beat B by 0.01" means nothing without the
  spread (this project's previous headline conclusion was noise).

Task: for each test user, hide one film they rated >= 4 and give the ranker up to ten of their
other liked films as the taste profile. The metric is hit-rate@k, the fraction of users whose
hidden film appears in the top k. Ties count against the method (pessimistic), so a method
cannot score by returning identical scores for everything.

What this does NOT measure: whether the aspect-based explanations are *true* (that is the
gold-set evaluation in `cinewhy.absa.gold`), or whether users like the results.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from cinewhy.recsys.catalogue import Catalogue
from cinewhy.recsys.cf import bayesian_popularity, build_item_similarity
from cinewhy.recsys.rank import _unit, blend_scores, infer_weights_from_rows, recommend
from cinewhy.schemas import Aspect, Recommendation, RecommendRequest, TasteProfile

LIKE_THRESHOLD = 4.0
_KS = (10, 20)
_BOOTSTRAPS = 2000
# Aspect-fit shares tried for the hybrid when the taste is inferred from liked films.
FIT_WEIGHTS = (0.0, 0.1, 0.2, 0.3, 0.45)


@dataclass(frozen=True)
class Interval:
    """A mean with its bootstrap 95% interval."""

    mean: float
    lo: float
    hi: float


@dataclass(frozen=True)
class MethodResult:
    """Hit-rate of one method at each cut-off."""

    name: str
    hit_rate: dict[int, Interval]


@dataclass(frozen=True)
class PairedDifference:
    """`a - b` in hit-rate@k, paired over the same test users."""

    a: str
    b: str
    k: int
    diff: Interval

    @property
    def significant(self) -> bool:
        """True when the 95% interval excludes zero."""
        return self.diff.lo > 0.0 or self.diff.hi < 0.0


@dataclass(frozen=True)
class RecEvalReport:
    """Everything a reader needs to judge the recommender."""

    n_train_users: int
    n_validation_users: int
    n_test_users: int
    shrink_candidates_validation_hit20: dict[float, float]
    chosen_shrink: float
    # Validation hit@20 of the hybrid at each aspect-fit share, and the pure-CF reference it
    # was compared with. The share chosen is the largest within one standard error of CF.
    fit_weight_candidates_validation_hit20: dict[float, float]
    validation_cf_hit20: float
    chosen_fit_weight: float
    methods: tuple[MethodResult, ...]
    differences: tuple[PairedDifference, ...]
    seeds_per_user: int


def _interval(values: npt.NDArray[np.float64], rng: np.random.Generator) -> Interval:
    """Bootstrap 95% interval for the mean of per-user indicators."""
    n = len(values)
    picks = rng.integers(0, n, size=(_BOOTSTRAPS, n))
    means = values[picks].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return Interval(float(values.mean()), float(lo), float(hi))


def _paired(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], rng: np.random.Generator
) -> Interval:
    return _interval(a - b, rng)


def _rank_of_target(score: npt.NDArray[np.float64], target: int, seeds: list[int]) -> int:
    """1-based rank of `target`, with the seed films removed and ties counted against it."""
    keep = np.ones(len(score), dtype=bool)
    keep[seeds] = False
    keep[target] = False
    return int((score[keep] >= score[target]).sum()) + 1


def _user_cases(
    users: npt.NDArray[np.int32],
    items: npt.NDArray[np.int32],
    ratings: npt.NDArray[np.float32],
    chosen_users: npt.NDArray[np.int32],
    n_seeds: int,
    rng: np.random.Generator,
) -> list[tuple[int, list[int]]]:
    """Per user: (hidden target film, up to n_seeds other liked films)."""
    mask = np.isin(users, chosen_users) & (ratings >= LIKE_THRESHOLD)
    order = np.argsort(users[mask], kind="stable")
    sorted_users, sorted_items = users[mask][order], items[mask][order]
    bounds = np.flatnonzero(np.diff(sorted_users)) + 1
    cases: list[tuple[int, list[int]]] = []
    for liked in np.split(sorted_items, bounds):
        pool = rng.permutation(liked)
        cases.append((int(pool[0]), [int(i) for i in pool[1 : 1 + n_seeds]]))
    return cases


def slider_response(catalogue: Catalogue, *, limit: int = 20) -> dict[str, dict[str, float]]:
    """Check that each aspect slider steers the results the way it is labelled.

    This does NOT show that stated preferences predict what a viewer will enjoy: there is no
    ground truth for that, and offline numbers cannot supply one. It shows only the
    directional property a user would notice first: pushing the Pacing slider to the maximum
    should return films whose pacing scores are higher than the default list's.

    Args:
        catalogue: The catalogue under test.
        limit: How many films to compare.

    Returns:
        Per aspect: the mean support-shrunk score of that aspect over the top `limit` films
        with that slider at 1.0 (`steered`), over the default cold-start list (`default`),
        and their difference (`lift`).
    """
    cold = recommend(catalogue, RecommendRequest(profile=TasteProfile(), limit=limit), "check")
    result: dict[str, dict[str, float]] = {}
    for aspect in Aspect:
        steered = recommend(
            catalogue,
            RecommendRequest(profile=TasteProfile(aspect_weights={aspect: 1.0}), limit=limit),
            "check",
        )

        def mean(items: tuple[Recommendation, ...], a: Aspect = aspect) -> float:
            return float(np.mean([catalogue.shrunk(i.movie.movie_id, a) for i in items]))

        steered_mean, default_mean = mean(steered.items), mean(cold.items)
        result[aspect.value] = {
            "steered": steered_mean,
            "default": default_mean,
            "lift": steered_mean - default_mean,
        }
    return result


def evaluate_recommenders(
    users: npt.NDArray[np.int32],
    items: npt.NDArray[np.int32],
    ratings: npt.NDArray[np.float32],
    n_items: int,
    aspect_matrix: npt.NDArray[np.float32],
    *,
    seed: int = 42,
    shrinks: tuple[float, ...] = (10.0, 50.0, 200.0),
    min_likes: int = 8,
    n_seeds: int = 10,
    max_eval_users: int = 2000,
    on_progress: Callable[[str], None] = lambda _msg: None,
) -> tuple[RecEvalReport, float]:
    """Run the full protocol.

    Args:
        users: User id per rating.
        items: Catalogue item index per rating.
        ratings: Star rating per rating.
        n_items: Number of catalogue items.
        aspect_matrix: `(n_items, n_aspects)` shrunk aspect scores, for the aspect methods.
        seed: Seed for the user split, target choice and bootstrap.
        shrinks: Candidate shrinkage values, chosen between on validation users.
        min_likes: A user needs this many liked films to be evaluable (1 target + seeds).
        n_seeds: Maximum liked films given to the ranker as the taste profile.
        max_eval_users: Cap on validation and on test users, for runtime.
        on_progress: Called with a status line at each stage.

    Returns:
        `(report, chosen_shrink)`. The shrink is returned separately so the build can fit
        the shipped similarity matrix on all users with the value selected here.
    """
    rng = np.random.default_rng(seed)
    all_users, inverse = np.unique(users, return_inverse=True)
    like_counts = np.bincount(inverse[ratings >= LIKE_THRESHOLD], minlength=len(all_users))
    evaluable = rng.permutation(all_users[like_counts >= min_likes])
    n_eval = min(max_eval_users, len(evaluable) // 3)
    test_users, val_users = evaluable[:n_eval], evaluable[n_eval : n_eval + n_eval // 2]
    held_out = np.concatenate([test_users, val_users])
    train_mask = ~np.isin(users, held_out)
    on_progress(
        f"split: train {int(train_mask.sum())} ratings, "
        f"{len(val_users)} val, {len(test_users)} test users"
    )

    mean_rating, _ = bayesian_popularity(items[train_mask], ratings[train_mask], n_items)
    popularity = _unit(mean_rating.astype(np.float64))

    sims = {}
    for shrink in shrinks:
        sims[shrink] = build_item_similarity(
            users[train_mask], items[train_mask], ratings[train_mask], n_items, shrink=shrink
        )
        on_progress(f"built similarity (shrink={shrink:g})")

    def hit20(sim: npt.NDArray[np.float32], cases: list[tuple[int, list[int]]]) -> float:
        hits = [
            _rank_of_target(
                blend_scores(sim, aspect_matrix, popularity, liked=seeds, disliked=[], weights={}),
                target,
                seeds,
            )
            <= 20
            for target, seeds in cases
            if seeds
        ]
        return float(np.mean(hits))

    val_cases = _user_cases(users, items, ratings, val_users, n_seeds, rng)
    val_scores = {s: hit20(sims[s], val_cases) for s in shrinks}
    # max() keeps the first of equals; iterate largest-first so ties go to more shrinkage.
    chosen = max(sorted(shrinks, reverse=True), key=lambda s: val_scores[s])
    on_progress(f"validation hit@20 by shrink: {val_scores}; chosen {chosen:g}")

    # Choose the aspect-fit share on VALIDATION users, by a rule fixed before looking: the
    # largest share whose hit@20 is within one standard error of pure collaborative
    # filtering. Aspect fit buys explainability, and this bounds what it may cost.
    val_sim = sims[chosen]
    cf_val = hit20(val_sim, val_cases)
    standard_error = float(np.sqrt(cf_val * (1.0 - cf_val) / max(1, len(val_cases))))

    def hybrid_val_hit20(fit_weight: float) -> float:
        hits = []
        for target, seeds in val_cases:
            weights = infer_weights_from_rows(aspect_matrix, seeds)
            if not seeds or not weights:
                continue
            score = blend_scores(
                val_sim,
                aspect_matrix,
                popularity,
                liked=seeds,
                disliked=[],
                weights=weights,
                fit_weight=fit_weight,
            )
            hits.append(_rank_of_target(score, target, seeds) <= 20)
        return float(np.mean(hits)) if hits else cf_val

    fit_val = {w: hybrid_val_hit20(w) for w in FIT_WEIGHTS}
    eligible = [w for w in FIT_WEIGHTS if fit_val[w] >= cf_val - standard_error]
    chosen_fit = max(eligible) if eligible else 0.0
    on_progress(
        f"validation hit@20: cf {cf_val:.3f} (se {standard_error:.3f}); "
        f"hybrid by fit weight {fit_val}; chosen {chosen_fit:g}"
    )

    test_cases = [c for c in _user_cases(users, items, ratings, test_users, n_seeds, rng) if c[1]]
    sim = sims[chosen]
    names = ("popularity", "cf", "aspect", "hybrid")
    ranks: dict[str, list[int]] = {n: [] for n in names}
    for target, seeds in test_cases:
        weights = infer_weights_from_rows(aspect_matrix, seeds)
        scored = {
            "popularity": popularity,
            "cf": blend_scores(
                sim, aspect_matrix, popularity, liked=seeds, disliked=[], weights={}
            ),
        }
        if weights:
            scored["aspect"] = blend_scores(
                sim, aspect_matrix, popularity, liked=[], disliked=[], weights=weights
            )
            scored["hybrid"] = blend_scores(
                sim,
                aspect_matrix,
                popularity,
                liked=seeds,
                disliked=[],
                weights=weights,
                fit_weight=chosen_fit,
            )
        else:  # no aspect signal could be inferred: those methods reduce to their fallbacks
            scored["aspect"] = popularity
            scored["hybrid"] = scored["cf"]
        for name in names:
            ranks[name].append(_rank_of_target(scored[name], target, seeds))

    hits = {
        name: {k: (np.array(r) <= k).astype(np.float64) for k in _KS} for name, r in ranks.items()
    }
    methods = tuple(
        MethodResult(name, {k: _interval(hits[name][k], rng) for k in _KS}) for name in names
    )
    pairs = (
        ("cf", "popularity"),
        ("hybrid", "cf"),
        ("aspect", "popularity"),
        ("hybrid", "popularity"),
    )
    differences = tuple(
        PairedDifference(a, b, k, _paired(hits[a][k], hits[b][k], rng))
        for a, b in pairs
        for k in _KS
    )
    report = RecEvalReport(
        n_train_users=int(len(all_users) - len(held_out)),
        n_validation_users=len(val_users),
        n_test_users=len(test_cases),
        shrink_candidates_validation_hit20=val_scores,
        chosen_shrink=chosen,
        fit_weight_candidates_validation_hit20=fit_val,
        validation_cf_hit20=cf_val,
        chosen_fit_weight=chosen_fit,
        methods=methods,
        differences=differences,
        seeds_per_user=n_seeds,
    )
    return report, chosen
