"""Choose how a group's members are combined, by measuring it on MovieLens groups (D-043).

There is no data on real friends watching together, so this builds groups out of MovieLens users and
asks the question a group cares about: for each member, does the group's top list hold something
that member would have liked (a film they rated 4 or more and that we hid from their profile)?

The protocol is fixed here, before any result is read:

* 300 validation and 300 test users are held out. Item similarity and popularity are rebuilt from
  every OTHER user, so a held-out user's own ratings never inform the ranking judged on them.
* Each user's profile is 10 of their liked films (the seeds) and up to 10 they rated 1 or 2 (their
  dislikes). Everything else they rated, except the liked films we are hiding (the targets), is
  "watched". A member is hit when a target of theirs is in the group's top 20.
* Groups of 2, 3, 5, 10 and 20, drawn two ways: at random, and as friends (an anchor user and the
  users most like them). The rule for seen and disliked titles (`group.majority`) is applied as in
  production, so a strict pair loses titles a lenient group keeps.
* The strategy is chosen on VALIDATION groups only: the best average member hit rate over the sizes
  2, 3 and 5 and both kinds of group; of the strategies within one standard error of it, the
  simplest. The TEST groups are then reported once, with intervals, and are never used to choose.

What this cannot show, stated where it can be seen: the targets are films a member liked and had not
been told us about, so the seen/disliked/want rules and their penalties are not exercised (a target
is never ruled out for being seen), and MovieLens users are not friends sitting together.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from cinewhy.recsys.group import GroupConfig, Member, MemberVectors, group_scores, member_vectors

TOP_K: Final[int] = 20
SIZES: Final[tuple[int, ...]] = (2, 3, 5, 10, 20)
KINDS: Final[tuple[str, ...]] = ("random", "friends")
# The strategies compared, by the name used in the report, from simplest to least simple. The order
# is the tie-break of `choose_strategy`.
VARIANTS: Final[dict[str, GroupConfig]] = {
    "mean": GroupConfig(strategy="mean"),
    "blend50": GroupConfig(strategy="blend", blend=0.5),
    "blend25": GroupConfig(strategy="blend", blend=0.25),
    "blend75": GroupConfig(strategy="blend", blend=0.75),
    "least_misery": GroupConfig(strategy="least_misery"),
    "lower_quartile": GroupConfig(strategy="lower_quartile"),
    "geometric": GroupConfig(strategy="geometric"),
    "intersection": GroupConfig(strategy="intersection"),
}
SELECTION_SIZES: Final[tuple[int, ...]] = (2, 3, 5)
_Cell = dict[str, tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]]


@dataclass(frozen=True)
class EvalUser:
    """A held-out user as a group member: their vectors, and the films we hid to test on."""

    vectors: MemberVectors
    targets: frozenset[int]  # candidate positions of films they liked and we did not tell us about
    solo_hit: bool  # their own top list holds one of their targets


def split_profile(
    rng: np.random.Generator,
    liked: npt.NDArray[np.integer[Any]],
    low: npt.NDArray[np.integer[Any]],
    rated: npt.NDArray[np.integer[Any]],
    *,
    seeds: int = 10,
    dislikes: int = 10,
) -> tuple[list[int], list[int], set[int], set[int]]:
    """Seeds, dislikes, watched and targets for one user, from the films they rated.

    The seeds and dislikes are what the profile says; the targets are the liked films left over,
    which must NOT be in `watched` (a member has not seen what we are about to recommend them);
    everything else they rated is watched.
    """
    seed_list = rng.permutation(liked)[:seeds].tolist()
    dislike_list = rng.permutation(low)[:dislikes].tolist() if low.size else []
    targets = set(liked.tolist()) - set(seed_list)
    watched = set(rated.tolist()) - targets
    return seed_list, dislike_list, watched, targets


def top_k(scores: npt.NDArray[np.float64], k: int = TOP_K) -> npt.NDArray[np.intp]:
    """Positions of the k best finite scores (fewer if fewer are finite)."""
    finite = np.flatnonzero(np.isfinite(scores))
    if finite.size <= k:
        return finite
    best = np.argpartition(-scores[finite], k - 1)[:k]
    return finite[best]


def solo_hit(vectors: MemberVectors, targets: frozenset[int]) -> bool:
    """Whether a member's own list (minus what they know or dislike) holds one of their targets."""
    scores = np.where(vectors.seen | vectors.disliked, -np.inf, vectors.pct)
    return bool(targets & set(top_k(scores).tolist()))


def friends_group(similarity: npt.NDArray[np.float64], anchor: int, size: int) -> list[int]:
    """An anchor and the `size - 1` users most like them (cosine of their percentiles)."""
    order = np.argsort(-similarity[anchor], kind="stable")
    return [anchor, *[int(u) for u in order if u != anchor][: size - 1]]


def draw_groups(
    rng: np.random.Generator,
    similarity: npt.NDArray[np.float64],
    size: int,
    kind: str,
    count: int,
) -> list[list[int]]:
    """`count` groups of `size` users from a pool, at random or as friends."""
    n = similarity.shape[0]
    if kind == "random":
        return [rng.choice(n, size=size, replace=False).tolist() for _ in range(count)]
    return [friends_group(similarity, int(a), size) for a in rng.choice(n, size=count)]


def evaluate_group(
    users: Sequence[EvalUser], members: Sequence[int], variants: dict[str, GroupConfig]
) -> dict[str, tuple[float, bool]]:
    """Per strategy: the share of members the group's top list hits, and whether all are hit."""
    vectors = [users[m].vectors for m in members]
    out: dict[str, tuple[float, bool]] = {}
    for name, config in variants.items():
        shown = set(top_k(group_scores(vectors, config)).tolist())
        hits = [bool(users[m].targets & shown) for m in members]
        out[name] = (sum(hits) / len(hits), all(hits))
    return out


def bootstrap_interval(
    values: npt.NDArray[np.float64], rng: np.random.Generator, draws: int = 2000
) -> tuple[float, float, float]:
    """Mean and 95% interval of a per-group quantity, resampling the groups."""
    means = rng.choice(values, size=(draws, values.size)).mean(axis=1)
    return float(values.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def choose_strategy(per_strategy: dict[str, npt.NDArray[np.float64]]) -> str:
    """The strategy to ship, from each strategy's validation member-hit value per group.

    The best average, or the simplest (`VARIANTS` order) within one standard error of it.
    """
    best = max(per_strategy, key=lambda s: float(per_strategy[s].mean()))
    values = per_strategy[best]
    standard_error = float(values.std(ddof=1) / np.sqrt(values.size)) if values.size > 1 else 0.0
    floor = float(values.mean()) - standard_error
    for name in VARIANTS:  # simplest first
        if name in per_strategy and float(per_strategy[name].mean()) >= floor:
            return name
    return best


def run(
    cells: dict[tuple[int, str], list[list[int]]],
    users: Sequence[EvalUser],
    variants: dict[str, GroupConfig],
) -> dict[tuple[int, str], _Cell]:
    """Per cell and strategy: each group's member-hit share and all-hit flag."""
    out: dict[tuple[int, str], _Cell] = {}
    for cell, groups in cells.items():
        scored = [evaluate_group(users, g, variants) for g in groups]
        out[cell] = {
            name: (
                np.array([s[name][0] for s in scored]),
                np.array([float(s[name][1]) for s in scored]),
            )
            for name in variants
        }
    return out


def _build_users(  # pragma: no cover - needs the real build inputs
    artifacts: Path, ml_archive: Path, seed: int, per_pool: int, recency: float
) -> tuple[list[EvalUser], list[EvalUser]]:
    """Held-out validation and test users, ranked by a catalogue rebuilt without them."""
    from cinewhy.artifacts.manifest import load_manifest, verify
    from cinewhy.build import BuildConfig, load_rating_arrays
    from cinewhy.recsys.catalogue import FilmStats, load_catalogue
    from cinewhy.recsys.cf import bayesian_popularity, build_item_similarity
    from cinewhy.recsys.evaluate import LIKE_THRESHOLD
    from cinewhy.schemas import TasteProfile

    verify(artifacts, load_manifest(artifacts))
    catalogue = load_catalogue(artifacts)
    n = len(catalogue.movies)
    imdb_ids = [s.imdb_id for s in catalogue.stats]
    config = BuildConfig(ml_archive=ml_archive)
    _, _, users, items, stars = load_rating_arrays(config, imdb_ids)
    rng = np.random.default_rng(seed)
    order = np.argsort(users, kind="stable")
    users, items, stars = users[order], items[order], stars[order]
    starts = np.flatnonzero(np.r_[True, np.diff(users) != 0])
    bounds = np.r_[starts, users.size]
    per_user = {int(users[a]): (a, b) for a, b in pairwise(bounds)}
    eligible = [
        u for u, (a, b) in per_user.items() if int((stars[a:b] >= LIKE_THRESHOLD).sum()) >= 30
    ]
    chosen = rng.permutation(eligible)[: 2 * per_pool].tolist()
    train = ~np.isin(users, chosen)
    sim = build_item_similarity(users[train], items[train], stars[train], n, shrink=50.0)
    bayes, counts = bayesian_popularity(items[train], stars[train], n)
    stats = tuple(
        FilmStats(s.imdb_id, int(counts[p]), float(bayes[p]), s.review_count)
        for p, s in enumerate(catalogue.stats)
    )
    cat = replace(catalogue, similarity=sim, stats=stats)
    candidates = np.arange(n)
    movie_id = [m.movie_id for m in cat.movies]
    built: list[EvalUser] = []
    for u in chosen:
        a, b = per_user[u]
        it, st = items[a:b], stars[a:b]
        liked, low = it[st >= LIKE_THRESHOLD], it[st <= 2]
        seeds, dislikes, watched, targets = split_profile(rng, liked, low, it)
        member = Member(
            str(u),
            TasteProfile(
                liked_movie_ids=tuple(movie_id[p] for p in seeds),
                disliked_movie_ids=tuple(movie_id[p] for p in dislikes),
            ),
            frozenset(movie_id[p] for p in watched),
        )
        vectors, _ = member_vectors(cat, member, candidates, recency=recency)
        built.append(EvalUser(vectors, frozenset(targets), solo_hit(vectors, frozenset(targets))))
    return built[:per_pool], built[per_pool:]


def _cosine(users: Sequence[EvalUser]) -> npt.NDArray[np.float64]:
    matrix = np.vstack([u.vectors.pct for u in users])
    matrix = matrix - matrix.mean(axis=1, keepdims=True)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.asarray(matrix @ matrix.T, dtype=np.float64)


def _summarise(
    results: dict[tuple[int, str], _Cell], users: Sequence[EvalUser], rng: np.random.Generator
) -> dict[str, Any]:
    report: dict[str, Any] = {"solo_hit20": float(np.mean([u.solo_hit for u in users]))}
    for (size, kind), by_strategy in results.items():
        cell = report.setdefault(str(size), {}).setdefault(kind, {})
        for name, (member_hit, all_hit) in by_strategy.items():
            cell[name] = {
                "member_hit": bootstrap_interval(member_hit, rng),
                "all_hit": bootstrap_interval(all_hit, rng),
            }
    return report


def main() -> None:  # pragma: no cover - needs the real build inputs
    """Run the protocol and write a JSON report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--ml-archive", type=Path, default=Path("Data/raw/ml32m/ml-32m.zip"))
    parser.add_argument("--groups", type=int, default=400, help="groups per size and kind")
    parser.add_argument("--users", type=int, default=300, help="users per pool (validation, test)")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--recency", type=float, default=0.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)
    validation, test = _build_users(
        args.artifacts, args.ml_archive, args.seed, args.users, args.recency
    )
    report: dict[str, Any] = {"seed": args.seed, "groups_per_cell": args.groups}
    chosen = ""
    for pool_name, pool in (("validation", validation), ("test", test)):
        similarity = _cosine(pool)
        cells = {
            (size, kind): draw_groups(rng, similarity, size, kind, args.groups)
            for size in SIZES
            for kind in KINDS
        }
        results = run(cells, pool, VARIANTS)
        report[pool_name] = _summarise(results, pool, rng)
        if pool_name == "validation":
            selection = {
                name: np.concatenate(
                    [results[(s, k)][name][0] for s in SELECTION_SIZES for k in KINDS]
                )
                for name in VARIANTS
            }
            chosen = choose_strategy(selection)
            report["chosen"] = chosen
            report["selection_means"] = {n: float(v.mean()) for n, v in selection.items()}
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"chosen on validation: {chosen}; wrote {args.out}")


if __name__ == "__main__":
    main()
