"""Recency checks for eval.json: what the "how new" setting does to a first page, and what it costs.

FEATURE-005 promised two numbers before the recency lift could be called finished:

1. *Cold-start mix.* With nothing known about a visitor, how many of the first 20 films are from
   2000 on (the audience the feature is for), and how many from 2012 on, at each setting.
2. *Cost.* The lift reorders films, so it can push a film someone liked out of their top 20. The
   cost is the drop in held-out hit rate at 20 against the same hybrid without the lift, reported
   with its paired interval. It is measured with the exact `recency_lift` the live ranking uses.

The cost needs the held-out protocol (about 8 minutes and 5 GB of memory on the real data), so it
is a command, not part of every build:

    python -m cinewhy.recsys.recency_check --artifacts artifacts/v3

which adds a `recency` block to that directory's `eval.json` and re-seals its manifest. Caveat
written into the result: the evaluated hybrid ranks with MovieLens-based popularity, while the
live list uses IMDb audience scores, so the cost is for the lift on top of the evaluated hybrid.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from cinewhy.recsys.catalogue import Catalogue
from cinewhy.recsys.discover import discover, film_years, recency_lift
from cinewhy.recsys.evaluate import evaluate_recommenders
from cinewhy.schemas import TasteProfile

# Settings the UI can produce: age-band defaults run from 0.25 to 0.8, the slider from 0 to 1.
SETTINGS: dict[str, float] = {"r25": 0.25, "r50": 0.5, "r80": 0.8, "r100": 1.0}


def cold_start_mix(
    catalogue: Catalogue,
    recencies: Sequence[float] = (0.0, 0.25, 0.5, 0.8, 1.0),
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """How the first page for an unknown visitor splits by era, at each recency setting.

    Args:
        catalogue: The loaded catalogue, with `meta` so films have release years.
        recencies: Recency settings to try, 0 to 1.
        limit: Length of the first page.

    Returns:
        `catalogue_share_from_2000` (the share of all films from 2000 on, for scale) and one row
        per setting with counts of the first `limit` films from 2000 on, from 2012 on, in Hindi,
        and the median release year.
    """
    years = film_years(catalogue)
    known = years > 0
    rows = []
    for recency in recencies:
        page = discover(
            catalogue, TasteProfile(), limit=limit, recency=recency, manifest="recency-check"
        )
        shown = [int(years[catalogue.index[i.movie.movie_id]]) for i in page.items]
        rows.append(
            {
                "recency": recency,
                "films": len(shown),
                "from_2000": sum(y >= 2000 for y in shown),
                "from_2012": sum(y >= 2012 for y in shown),
                "hindi": sum(i.language == "hi" for i in page.items),
                "median_year": int(np.median(shown)) if shown else None,
            }
        )
    return {
        "page_size": limit,
        "catalogue_share_from_2000": float((years[known] >= 2000).mean()) if known.any() else None,
        "by_recency": rows,
    }


def lifts_for(catalogue: Catalogue) -> dict[str, npt.NDArray[np.float64]]:
    """The lift vector the live ranking would add at each setting in `SETTINGS`."""
    years = film_years(catalogue)
    return {name: recency_lift(years, value) for name, value in SETTINGS.items()}


def cost_of_recency(
    catalogue: Catalogue,
    users: npt.NDArray[np.int32],
    items: npt.NDArray[np.int32],
    stars: npt.NDArray[np.float32],
    *,
    seed: int,
    on_progress: Callable[[str], None] = lambda _m: None,
) -> dict[str, Any]:
    """Held-out hit rate with and without each recency lift, and the paired difference.

    Args:
        catalogue: The loaded catalogue (for years and the aspect matrix).
        users: User id per rating.
        items: Catalogue position per rating.
        stars: Star rating per rating.
        seed: The build's seed, so the user split matches the one in `eval.json`.
        on_progress: Status line sink.

    Returns:
        `hybrid` (hit rate at 10 and 20 without any lift) and, per setting, `hit_rate` and
        `vs_hybrid` (paired difference per cutoff, with its 95% interval). Negative is a cost.
    """
    report, _ = evaluate_recommenders(
        users,
        items,
        stars,
        len(catalogue.movies),
        catalogue.aspect_matrix,
        seed=seed,
        recency_lifts=lifts_for(catalogue),
        on_progress=on_progress,
    )
    plain = asdict(report)
    methods = {m["name"]: m["hit_rate"] for m in plain["methods"]}
    out: dict[str, Any] = {
        "n_test_users": report.n_test_users,
        "hybrid": methods["hybrid"],
        "settings": {},
    }
    for name, value in SETTINGS.items():
        out["settings"][name] = {
            "recency": value,
            "hit_rate": methods[f"hybrid_{name}"],
            "vs_hybrid": {
                d["k"]: d["diff"]
                for d in plain["differences"]
                if d["a"] == f"hybrid_{name}" and d["b"] == "hybrid"
            },
        }
    return out


def merge_into_eval(root: Path, block: dict[str, Any]) -> None:
    """Add `block` as `recency` in `root/eval.json` and re-seal the manifest over the same files."""
    # Imported here: build pulls in the whole pipeline, which the cold-start check does not need.
    from cinewhy.artifacts.manifest import build as build_manifest
    from cinewhy.artifacts.manifest import load_manifest
    from cinewhy.build import ARTIFACT_FILES

    old = load_manifest(root)
    path = root / "eval.json"
    blob = json.loads(path.read_text(encoding="utf-8"))
    blob["recency"] = block
    path.write_text(json.dumps(blob, indent=2, sort_keys=True, default=str), encoding="utf-8")
    build_manifest(root, row_counts=dict(old.row_counts), names=ARTIFACT_FILES)


def main() -> None:
    """Command line: run the checks against a built artifact directory and record them."""
    from cinewhy.artifacts.manifest import load_manifest, verify
    from cinewhy.build import BuildConfig, load_rating_arrays
    from cinewhy.recsys.catalogue import load_catalogue

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts") / "v2")
    parser.add_argument("--skip-cost", action="store_true", help="only the cold-start mix")
    args = parser.parse_args()
    root: Path = args.artifacts

    verify(root, load_manifest(root))
    catalogue = load_catalogue(root, with_meta=True)
    block: dict[str, Any] = {
        "cold_start": cold_start_mix(catalogue),
        "note": "Cost is the held-out hit-rate change from adding the live recency lift to the "
        "evaluated hybrid (which ranks with MovieLens-based popularity, not the IMDb scores the "
        "live list uses). Mean and 95% bootstrap interval over the same test users as "
        "`recommender`.",
    }
    if not args.skip_cost:
        config = BuildConfig()
        imdb_ids = [int(m.movie_id.removeprefix("cw-")) for m in catalogue.movies]
        _, _, users, items, stars = load_rating_arrays(config, imdb_ids)
        block["cost"] = cost_of_recency(
            catalogue, users, items, stars, seed=config.seed, on_progress=print
        )
        eval_blob = json.loads((root / "eval.json").read_text(encoding="utf-8"))
        shipped = {m["name"]: m["hit_rate"] for m in eval_blob["recommender"]["methods"]}
        block["cost"]["reproduces_recommender_block"] = bool(
            abs(shipped["hybrid"]["20"]["mean"] - block["cost"]["hybrid"][20]["mean"]) < 1e-9
        )
    merge_into_eval(root, block)
    print(json.dumps(block["cold_start"], indent=1))
    if "cost" in block:
        print(json.dumps(block["cost"], indent=1, default=str)[:3000])


if __name__ == "__main__":
    main()
