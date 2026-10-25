"""The similarity builder must not pay for films nobody rated (FEATURE-004).

The catalogue now holds about 10,000 films, and a good share (most Hindi films) have few or no
MovieLens ratings. The matrix is n x n, so a builder that allocates several dense float64 n x n
temporaries over ALL films needs gigabytes it does not have; one that works on the rated films
only and writes the result into the n x n output needs about the size of that output.
"""

from __future__ import annotations

import tracemalloc

import numpy as np

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
