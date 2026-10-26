"""The similarity builder must not pay for films nobody rated (FEATURE-004).

The catalogue now holds about 10,000 films, and a good share (most Hindi films) have few or no
MovieLens ratings. The matrix is n x n, so a builder that allocates several dense float64 n x n
temporaries over ALL films needs gigabytes it does not have; one that works on the rated films
only and writes the result into the n x n output needs about the size of that output.
"""

from __future__ import annotations

import gc
import tracemalloc
import weakref

import numpy as np
import pytest

import cinewhy.recsys.evaluate as evaluate_module
from cinewhy.recsys.cf import build_item_similarity


def _ratings(
    n_rated: int, n_users: int = 60, per_user: int = 8
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    users = np.repeat(np.arange(n_users, dtype=np.int32), per_user)
    items = rng.integers(0, n_rated, size=users.size).astype(np.int32)
    stars = rng.integers(1, 6, size=users.size).astype(np.float32)
    return users, items, stars


def test_unrated_films_get_zero_rows_and_leave_the_rest_unchanged() -> None:
    users, items, stars = _ratings(n_rated=5)
    compact = build_item_similarity(users, items, stars, 5, shrink=3.0)
    # The same ratings with the five rated films spread among unrated ones.
    positions = np.array([0, 2, 5, 7, 9], dtype=np.int32)
    wide = build_item_similarity(users, positions[items], stars, 12, shrink=3.0)
    assert wide.shape == (12, 12)
    np.testing.assert_allclose(wide[np.ix_(positions, positions)], compact, atol=1e-6)
    unrated = np.setdiff1d(np.arange(12), positions)
    assert not wide[unrated].any()
    assert not wide[:, unrated].any()


def test_the_evaluation_keeps_only_one_candidate_similarity_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The protocol tries three shrinkage values and keeps the best. Holding all three at once
    # triples the footprint (about 475 MB each at 10,000 films); one best-so-far plus the one
    # being scored is enough.
    alive: list[weakref.ref[np.ndarray]] = []
    most_alive = 0
    real = build_item_similarity

    def counting(*args: object, **kwargs: object) -> np.ndarray:
        nonlocal most_alive
        sim: np.ndarray = real(*args, **kwargs)  # type: ignore[arg-type]
        alive.append(weakref.ref(sim))
        gc.collect()
        most_alive = max(most_alive, sum(1 for r in alive if r() is not None))
        return sim

    monkeypatch.setattr(evaluate_module, "build_item_similarity", counting)
    rng = np.random.default_rng(3)
    n_items, n_users = 40, 400
    users = np.repeat(np.arange(n_users, dtype=np.int32), 16)
    items = np.concatenate(
        [rng.choice(n_items, size=16, replace=False) for _ in range(n_users)]
    ).astype(np.int32)
    stars = rng.choice([3.0, 4.0, 4.5, 5.0], size=users.size, p=[0.2, 0.3, 0.3, 0.2]).astype(
        np.float32
    )
    report, _ = evaluate_module.evaluate_recommenders(
        users, items, stars, n_items, np.zeros((n_items, 7), dtype=np.float32), seed=1
    )
    assert len(alive) == 3  # all three shrink values were still tried
    assert most_alive <= 2, f"{most_alive} similarity matrices alive at once"
    assert set(report.shrink_candidates_validation_hit20) == {10.0, 50.0, 200.0}


def test_a_tie_between_shrink_values_goes_to_the_larger_shrinkage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every candidate gets the same matrix, so all three score identically. The documented rule
    # (more shrinkage is the safer choice) must still pick 200, as the old `max` did.
    n_items, n_users = 40, 400
    monkeypatch.setattr(
        evaluate_module,
        "build_item_similarity",
        lambda *a, **k: np.zeros((n_items, n_items), dtype=np.float32),
    )
    rng = np.random.default_rng(3)
    users = np.repeat(np.arange(n_users, dtype=np.int32), 16)
    items = np.concatenate(
        [rng.choice(n_items, size=16, replace=False) for _ in range(n_users)]
    ).astype(np.int32)
    stars = np.full(users.size, 4.5, dtype=np.float32)
    report, chosen = evaluate_module.evaluate_recommenders(
        users, items, stars, n_items, np.zeros((n_items, 7), dtype=np.float32), seed=1
    )
    assert chosen == 200.0 == report.chosen_shrink
    assert len(set(report.shrink_candidates_validation_hit20.values())) == 1  # a real tie


def test_memory_follows_the_rated_films_not_the_catalogue_size() -> None:
    n_items = 3000  # a dense float64 matrix of this size is 72 MB; the builder made several
    users, items, stars = _ratings(n_rated=50)
    tracemalloc.start()
    try:
        sim = build_item_similarity(users, items, stars, n_items, shrink=3.0)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    output = n_items * n_items * 4  # the float32 result itself
    assert sim.shape == (n_items, n_items)
    assert peak < 2.5 * output, f"peak {peak / 1e6:.0f} MB for a {output / 1e6:.0f} MB output"
