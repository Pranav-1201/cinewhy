"""Item-item collaborative filtering and a popularity prior.

Deliberately classical. ARCHITECTURE.md §1 is explicit that collaborative filtering is a
commodity and that the product's differentiator is the aspect-evidence layer on top of it.
Item-item cosine on mean-centred ratings is a strong, well-understood baseline that fits a
2-vCPU host: it is one sparse matrix product offline and a row lookup per request.

Nothing here runs at request time except reading rows of the finished matrix
(CONSTRAINTS.md #5).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy import sparse

type Floats = npt.NDArray[np.float32]


def build_item_similarity(
    users: npt.NDArray[np.int32],
    items: npt.NDArray[np.int32],
    ratings: npt.NDArray[np.float32],
    n_items: int,
    *,
    shrink: float = 50.0,
    min_user_ratings: int = 5,
) -> Floats:
    """Cosine similarity between items over mean-centred ratings, shrunk toward zero.

    Mean-centring per user removes "this user rates everything high". Shrinkage multiplies
    each similarity by `co / (co + shrink)`, where `co` is the number of users who rated
    both films: two films seen together by three people can look identical by chance, and
    this keeps such pairs from outranking pairs backed by thousands.

    Args:
        users: User id per rating. Arbitrary integers.
        items: Item index per rating, in `[0, n_items)`.
        ratings: Star rating per rating.
        n_items: Number of items; also the matrix size.
        shrink: Shrinkage strength; larger means more conservative.
        min_user_ratings: Users with fewer ratings are dropped; their mean is noise.

    Returns:
        Dense `(n_items, n_items)` float32 matrix with a zero diagonal.
    """
    _, user_index, counts = np.unique(users, return_inverse=True, return_counts=True)
    keep = counts[user_index] >= min_user_ratings
    user_index, items, ratings = user_index[keep], items[keep], ratings[keep]
    # Re-compress after dropping users so row indices stay dense.
    _, user_index = np.unique(user_index, return_inverse=True)
    n_users = int(user_index.max()) + 1 if user_index.size else 0

    sums = np.bincount(user_index, weights=ratings, minlength=n_users)
    per_user = np.bincount(user_index, minlength=n_users)
    centred = ratings - (sums / np.maximum(per_user, 1))[user_index]

    shape = (n_users, n_items)
    r = sparse.csr_matrix((centred, (user_index, items)), shape=shape, dtype=np.float64)
    b = sparse.csr_matrix(
        (np.ones_like(centred), (user_index, items)), shape=shape, dtype=np.float64
    )
    dot = (r.T @ r).toarray()
    co = (b.T @ b).toarray()
    norms = np.sqrt(np.diag(dot))
    with np.errstate(divide="ignore", invalid="ignore"):
        cosine = dot / np.outer(norms, norms)
    cosine = np.nan_to_num(cosine, nan=0.0, posinf=0.0, neginf=0.0)
    sim = cosine * (co / (co + shrink))
    np.fill_diagonal(sim, 0.0)
    return np.asarray(sim, dtype=np.float32)


def bayesian_popularity(
    items: npt.NDArray[np.int32],
    ratings: npt.NDArray[np.float32],
    n_items: int,
    *,
    prior_weight: float = 25.0,
) -> tuple[Floats, npt.NDArray[np.int64]]:
    """Mean rating per item, pulled toward the global mean for sparsely rated films.

    A film with one five-star rating must not outrank one with ten thousand ratings
    averaging 4.4. The prior is worth `prior_weight` ratings at the global mean.

    Args:
        items: Item index per rating.
        ratings: Star rating per rating.
        n_items: Number of items.
        prior_weight: Pseudo-count of the prior.

    Returns:
        `(bayesian_mean, rating_count)`, both of length `n_items`. An item nobody rated
        gets the global mean and a count of 0.
    """
    counts = np.bincount(items, minlength=n_items).astype(np.int64)
    totals = np.bincount(items, weights=ratings, minlength=n_items)
    global_mean = float(ratings.mean()) if ratings.size else 0.0
    mean = (totals + prior_weight * global_mean) / (counts + prior_weight)
    return mean.astype(np.float32), counts
