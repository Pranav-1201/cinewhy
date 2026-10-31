"""How many liked films does the recommender need? Hit-at-20 by number of seed films (D-025).

The first-visit "Rate films" dialog asks a new visitor about films one at a time. How many answers
are worth asking for? This replays the project's held-out protocol (`cinewhy/recsys/evaluate.py`)
but varies how many of a user's liked films the ranker is given: 0 (popularity only, the cold
start), 1, 2, 3, 5, 10 and 20. The hidden target and the users are the same at every count, so the
numbers on the curve are paired and the difference between two counts carries its own 95% interval.

Same rules as the shipped evaluation: users are split BY USER, the similarity and the popularity
prior are fitted on training users only, the settings (shrink 200, aspect-fit share 0.45) are the
ones `eval.json` already chose on validation users, and the test users are read once, here.

Limit, stated up front: to give every count the same users, only users with at least 21 liked films
(a hidden target plus 20 seeds) qualify. They are heavier raters than a typical newcomer, so read
the curve for its SHAPE (where more answers stop helping), not as the hit rate a new visitor will
see.

    python experiments/seed_curve.py --artifacts artifacts/v3 --ml-archive PATH-TO/ml-32m.zip

About 10 minutes and 5 GB of memory on the real data.
"""

from __future__ import annotations

import argparse
import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from cinewhy.artifacts.manifest import load_manifest, verify
from cinewhy.build import BuildConfig, load_rating_arrays
from cinewhy.recsys.catalogue import load_catalogue
from cinewhy.recsys.cf import bayesian_popularity, build_item_similarity
from cinewhy.recsys.evaluate import LIKE_THRESHOLD, _interval, _rank_of_target, _user_cases
from cinewhy.recsys.rank import _unit, blend_scores, infer_weights_from_rows

SEED_COUNTS = (0, 1, 2, 3, 5, 10, 20)
MAX_SEEDS = max(SEED_COUNTS)
MIN_LIKES = MAX_SEEDS + 1  # one hidden target plus the most seeds we will give


def _summary(hits: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    interval = _interval(hits, rng)
    return {"mean": interval.mean, "lo": interval.lo, "hi": interval.hi}


def main() -> None:
    """Run the experiment against built artifacts and write the curve as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/v3"))
    parser.add_argument("--ml-archive", type=Path, default=Path("Data/raw/ml32m/ml-32m.zip"))
    parser.add_argument("--out", type=Path, default=Path("seed_curve.json"))
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

    rng = np.random.default_rng(config.seed)
    all_users, inverse = np.unique(users, return_inverse=True)
    like_counts = np.bincount(inverse[stars >= LIKE_THRESHOLD], minlength=len(all_users))
    evaluable = rng.permutation(all_users[like_counts >= MIN_LIKES])
    n_eval = min(2000, len(evaluable) // 3)
    test_users, val_users = evaluable[:n_eval], evaluable[n_eval : n_eval + n_eval // 2]
    train_mask = ~np.isin(users, np.concatenate([test_users, val_users]))
    print(
        f"users with {MIN_LIKES}+ liked films: {len(evaluable)}; test {len(test_users)}", flush=True
    )

    mean_rating, _ = bayesian_popularity(items[train_mask], stars[train_mask], n_items)
    popularity = _unit(mean_rating.astype(np.float64))
    sim = build_item_similarity(
        users[train_mask], items[train_mask], stars[train_mask], n_items, shrink=shrink
    )
    cases = [
        c
        for c in _user_cases(users, items, stars, test_users, MAX_SEEDS, rng)
        if len(c[1]) == MAX_SEEDS
    ]
    print(f"test cases: {len(cases)}", flush=True)

    hits: dict[str, dict[int, np.ndarray]] = {"popularity": {}, "cf": {}, "hybrid": {}}
    for k in SEED_COUNTS:
        row: dict[str, list[bool]] = {"popularity": [], "cf": [], "hybrid": []}
        for target, seeds in cases:
            chosen = seeds[:k]
            row["popularity"].append(_rank_of_target(popularity, target, chosen) <= 20)
            if not chosen:  # nothing known: the ranker can only fall back to popularity
                row["cf"].append(row["popularity"][-1])
                row["hybrid"].append(row["popularity"][-1])
                continue
            cf = blend_scores(sim, aspect_matrix, popularity, liked=chosen, disliked=[], weights={})
            row["cf"].append(_rank_of_target(cf, target, chosen) <= 20)
            weights = infer_weights_from_rows(aspect_matrix, chosen)
            if weights:
                score = blend_scores(
                    sim,
                    aspect_matrix,
                    popularity,
                    liked=chosen,
                    disliked=[],
                    weights=weights,
                    fit_weight=fit_weight,
                )
                row["hybrid"].append(_rank_of_target(score, target, chosen) <= 20)
            else:
                row["hybrid"].append(row["cf"][-1])
        for name in hits:
            hits[name][k] = np.array(row[name], dtype=np.float64)
        print(f"k={k}: hybrid hit@20 {hits['hybrid'][k].mean():.3f}", flush=True)

    result: dict[str, Any] = {
        "protocol": "held-out users, one hidden liked film, hit@20; "
        "same users and targets at every count",
        "min_likes": MIN_LIKES,
        "n_test_users": len(cases),
        "shrink": shrink,
        "fit_weight": fit_weight,
        "hit_at_20": {
            name: {str(k): _summary(h, rng) for k, h in by_k.items()} for name, by_k in hits.items()
        },
        "hybrid_gain_from_extra_seeds": {
            f"{a}_to_{b}": _summary(hits["hybrid"][b] - hits["hybrid"][a], rng)
            for a, b in pairwise(SEED_COUNTS)
        },
    }
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["hit_at_20"]["hybrid"], indent=1), flush=True)
    print(json.dumps(result["hybrid_gain_from_extra_seeds"], indent=1), flush=True)


if __name__ == "__main__":
    main()
