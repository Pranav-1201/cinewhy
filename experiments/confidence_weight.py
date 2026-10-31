"""Does trusting films with more reviews more improve the recommender? (roadmap 15.3).

Pranav's idea: films with few reviews should count for less, so a film with 30 reviews cannot
outrank a well-supported one on thin evidence. This tests it with the project's own held-out
protocol (`cinewhy/recsys/evaluate.py`): each film's hybrid score is multiplied by n / (n + k),
where n is the film's review count and k how many reviews it takes to be half trusted.

Rule fixed BEFORE looking: k is chosen on VALIDATION users among 10, 50 and 200 (and "no
weighting"), by the highest validation hit-at-20; a weighting is adopted only if it beats no
weighting on validation by more than one standard error. The test users are read once, afterwards,
and the result carries the paired difference from the unweighted hybrid with its 95% interval.

Honest limit: the test users can only score films that have MovieLens ratings, so this can show
whether the weighting HURTS rated films, not whether it helps films that have none.

    python experiments/confidence_weight.py --artifacts artifacts/v3 --ml-archive PATH/ml-32m.zip

About 10 minutes and 5 GB of memory on the real data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from cinewhy.artifacts.manifest import load_manifest, verify
from cinewhy.build import BuildConfig, load_rating_arrays
from cinewhy.recsys.catalogue import load_catalogue
from cinewhy.recsys.cf import bayesian_popularity, build_item_similarity
from cinewhy.recsys.evaluate import LIKE_THRESHOLD, _interval, _rank_of_target, _user_cases
from cinewhy.recsys.rank import _unit, blend_scores, infer_weights_from_rows

KS = (10.0, 50.0, 200.0)
MIN_LIKES = 8  # same as the shipped evaluation, so the baseline can be compared with eval.json
N_SEEDS = 10


def main() -> None:
    """Choose k on validation users, then score the test users once."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/v3"))
    parser.add_argument("--ml-archive", type=Path, default=Path("Data/raw/ml32m/ml-32m.zip"))
    parser.add_argument("--out", type=Path, default=Path("confidence_weight.json"))
    args = parser.parse_args()

    verify(args.artifacts, load_manifest(args.artifacts))
    catalogue = load_catalogue(args.artifacts, with_meta=True)
    shipped = json.loads((args.artifacts / "eval.json").read_text(encoding="utf-8"))["recommender"]
    shrink, fit_weight = float(shipped["chosen_shrink"]), float(shipped["chosen_fit_weight"])
    config = BuildConfig(ml_archive=args.ml_archive)
    imdb_ids = [int(m.movie_id.removeprefix("cw-")) for m in catalogue.movies]
    _, _, users, items, stars = load_rating_arrays(config, imdb_ids)
    n_items = len(catalogue.movies)
    aspect_matrix = catalogue.aspect_matrix
    reviews = np.array([s.review_count for s in catalogue.stats], dtype=np.float64)

    # The split follows evaluate_recommenders exactly, so the same users are held out.
    rng = np.random.default_rng(config.seed)
    all_users, inverse = np.unique(users, return_inverse=True)
    like_counts = np.bincount(inverse[stars >= LIKE_THRESHOLD], minlength=len(all_users))
    evaluable = rng.permutation(all_users[like_counts >= MIN_LIKES])
    n_eval = min(2000, len(evaluable) // 3)
    test_users, val_users = evaluable[:n_eval], evaluable[n_eval : n_eval + n_eval // 2]
    train_mask = ~np.isin(users, np.concatenate([test_users, val_users]))
    mean_rating, _ = bayesian_popularity(items[train_mask], stars[train_mask], n_items)
    popularity = _unit(mean_rating.astype(np.float64))
    sim = build_item_similarity(
        users[train_mask], items[train_mask], stars[train_mask], n_items, shrink=shrink
    )
    val_cases = [c for c in _user_cases(users, items, stars, val_users, N_SEEDS, rng) if c[1]]
    test_cases = [c for c in _user_cases(users, items, stars, test_users, N_SEEDS, rng) if c[1]]
    print(f"validation cases {len(val_cases)}, test cases {len(test_cases)}", flush=True)

    def confidence(k: float | None) -> npt.NDArray[np.float64]:
        return np.ones(n_items) if k is None else reviews / (reviews + k)

    def hits(cases: list[tuple[int, list[int]]], k: float | None) -> npt.NDArray[np.float64]:
        weight = confidence(k)
        out = []
        for target, seeds in cases:
            weights = infer_weights_from_rows(aspect_matrix, seeds)
            score = blend_scores(
                sim,
                aspect_matrix,
                popularity,
                liked=seeds,
                disliked=[],
                weights=weights,
                fit_weight=fit_weight,
            )
            out.append(_rank_of_target(score * weight, target, seeds) <= 20)
        return np.array(out, dtype=np.float64)

    candidates: list[float | None] = [None, *KS]
    validation = {k: hits(val_cases, k) for k in candidates}
    base = validation[None]
    standard_error = float(np.sqrt(base.mean() * (1 - base.mean()) / len(base)))
    best = max(KS, key=lambda k: validation[k].mean())
    chosen: float | None = best if validation[best].mean() > base.mean() + standard_error else None
    print(
        {str(k): round(float(v.mean()), 4) for k, v in validation.items()},
        "chosen",
        chosen,
        flush=True,
    )

    test_base = hits(test_cases, None)
    result: dict[str, Any] = {
        "validation_hit20": {str(k): float(v.mean()) for k, v in validation.items()},
        "validation_standard_error": standard_error,
        "chosen_k": chosen,
        "test_hit20_unweighted": float(test_base.mean()),
        "test_by_k": {},
    }
    for k in KS:  # all reported, but only the validation-chosen one counts as the result
        test_k = hits(test_cases, k)
        diff = _interval(test_k - test_base, rng)
        interval = _interval(test_k, rng)
        result["test_by_k"][str(k)] = {
            "hit20": {"mean": interval.mean, "lo": interval.lo, "hi": interval.hi},
            "vs_unweighted": {"mean": diff.mean, "lo": diff.lo, "hi": diff.hi},
        }
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=1), flush=True)


if __name__ == "__main__":
    main()
