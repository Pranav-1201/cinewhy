"""Does age or sex tell us what a first-time visitor will like? Measured on MovieLens-1M.

Throwaway measurement script, not product code. Protocol fixed before looking at results:
users are split 50/50 (seed 42) BEFORE any fitting; the genre prior is fitted on train users only;
its strength and which demographic variant to use are chosen on a validation slice of the train
users; test users are scored once. Target = one random liked film (rating >= 4) per test user, the
ranker sees only the demographics (cold start), hit@20 over all ML-1M films.
"""

from __future__ import annotations

import io
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cinewhy.recsys.cf import bayesian_popularity
from cinewhy.recsys.evaluate import LIKE_THRESHOLD, _interval

Key = Callable[[int], tuple[object, ...]]
rng = np.random.default_rng(42)
z = zipfile.ZipFile(Path("Data/raw/ml1m/ml-1m.zip"))


def read(name: str) -> list[list[str]]:
    """Rows of one `::`-separated ML-1M file."""
    return [ln.split("::") for ln in io.TextIOWrapper(z.open(f"ml-1m/{name}"), encoding="latin-1")]


users = {int(r[0]): (r[1], int(r[2])) for r in read("users.dat")}
movies = {int(r[0]): r[2].strip().split("|") for r in read("movies.dat")}
mids = sorted(movies)
col = {m: i for i, m in enumerate(mids)}
genres = sorted({g for gs in movies.values() for g in gs})
gcol = {g: i for i, g in enumerate(genres)}
film_genre = np.zeros((len(mids), len(genres)))
for m, gs in movies.items():
    for g in gs:
        film_genre[col[m], gcol[g]] = 1.0
film_genre /= film_genre.sum(axis=1, keepdims=True)  # mean over a film's genres

rows = read("ratings.dat")
u = np.array([int(r[0]) for r in rows], dtype=np.int32)
it = np.array([col[int(r[1])] for r in rows], dtype=np.int32)
st = np.array([float(r[2]) for r in rows], dtype=np.float32)
print(f"{len(u)} ratings, {len(users)} users, {len(mids)} films, {len(genres)} genres")

uids = rng.permutation(np.array(sorted(users)))
test_u, train_u = set(uids[: len(uids) // 2].tolist()), uids[len(uids) // 2 :]
val_u = set(train_u[: len(train_u) // 3].tolist())
fit_u = set(train_u[len(train_u) // 3 :].tolist())
print(f"fit {len(fit_u)}  val {len(val_u)}  test {len(test_u)}")

bucket = {
    "full": lambda uid: (users[uid][0], users[uid][1]),
    "age": lambda uid: (users[uid][1],),
    "sex": lambda uid: (users[uid][0],),
}


def fit_prior(fit_users: set[int], key: Key) -> dict[tuple[object, ...], np.ndarray]:
    """Per group: log lift of 'liked' rate per genre over the global rate, shrunk by 50 ratings."""
    mask = np.isin(u, list(fit_users))
    uu, ii, ss = u[mask], it[mask], st[mask]
    liked = ss >= LIKE_THRESHOLD
    rated_by_genre = film_genre[ii].sum(axis=0)
    liked_by_genre = film_genre[ii[liked]].sum(axis=0)
    glob = (liked_by_genre + 1) / (rated_by_genre + 2)
    groups: dict = {}
    for uid in np.unique(uu):
        groups.setdefault(key(int(uid)), []).append(int(uid))
    prior = {}
    for grp, members in groups.items():
        m = np.isin(uu, members)
        r_g = film_genre[ii[m]].sum(axis=0)
        l_g = film_genre[ii[m & liked]].sum(axis=0)
        rate = (l_g + 50 * glob) / (r_g + 50)
        prior[grp] = np.log(rate / glob)
    return prior


def popularity(fit_users: set[int]) -> np.ndarray:
    """Shrunk mean rating per film from the given users, scaled to 0..1."""
    mask = np.isin(u, list(fit_users))
    mean, _ = bayesian_popularity(it[mask], st[mask], len(mids))
    span = float(mean.max() - mean.min())
    return (mean - mean.min()) / span


def cases(eval_users: set[int]) -> list[tuple[int, int]]:
    """(user id, hidden liked film column), one per user, fixed by the seed."""
    out = []
    mask = (st >= LIKE_THRESHOLD) & np.isin(u, list(eval_users))
    order = np.argsort(u[mask], kind="stable")
    su, si = u[mask][order], it[mask][order]
    bounds = np.flatnonzero(np.diff(su)) + 1
    for uid_block, items_block in zip(np.split(su, bounds), np.split(si, bounds), strict=True):
        out.append((int(uid_block[0]), int(rng.choice(items_block))))
    return out


def hits(
    pop: np.ndarray,
    prior: dict[tuple[object, ...], np.ndarray],
    key: Key,
    lam: float,
    case_list: list[tuple[int, int]],
) -> np.ndarray:
    """1.0 where the hidden liked film lands in the top 20 for that user's demographic group."""
    result = []
    for uid, target in case_list:
        score = pop.copy()
        grp = key(uid)
        if lam and grp in prior:
            score = score + lam * (film_genre @ prior[grp])
        rank = int((score >= score[target]).sum())  # ties count against the target
        result.append(rank <= 20)
    return np.array(result, dtype=np.float64)


LAMBDAS = (0.0, 0.05, 0.1, 0.2, 0.4, 0.8)
pop_fit = popularity(fit_u)
val_cases = cases(val_u)
base_val = hits(pop_fit, {}, bucket["full"], 0.0, val_cases).mean()
best = ("none", 0.0, base_val)
table = []
for name, key in bucket.items():
    prior = fit_prior(fit_u, key)
    for lam in LAMBDAS[1:]:
        h = hits(pop_fit, prior, key, lam, val_cases).mean()
        table.append((name, lam, h))
        if h > best[2]:
            best = (name, lam, h)
print(f"validation popularity-only hit@20 = {base_val:.4f}  (n={len(val_cases)})")
for name, lam, h in table:
    print(f"  val {name:5s} lambda={lam:<5} hit@20={h:.4f}")
print("chosen on validation:", best)

train_all = fit_u | val_u
pop_all = popularity(train_all)
test_cases = cases(test_u)
base = hits(pop_all, {}, bucket["full"], 0.0, test_cases)
print(f"\nTEST n={len(test_cases)} popularity-only hit@20 = {base.mean():.4f}")
rng2 = np.random.default_rng(7)
iv = _interval(base, rng2)
print(f"  baseline interval [{iv.lo:.4f}, {iv.hi:.4f}]")
name, lam = best[0], best[1]
if name == "none":
    print("validation found no variant better than popularity: prior is OFF")
else:
    prior = fit_prior(train_all, bucket[name])
    chosen = hits(pop_all, prior, bucket[name], lam, test_cases)
    d = _interval(chosen - base, rng2)
    print(f"  chosen ({name}, lambda={lam}) hit@20 = {chosen.mean():.4f}")
    print(f"  paired difference = {d.mean * 100:+.2f} pts  [{d.lo * 100:+.2f}, {d.hi * 100:+.2f}]")
    for other, key in bucket.items():  # context only; NOT used for selection
        p = fit_prior(train_all, key)
        h = hits(pop_all, p, key, lam, test_cases)
        dd = _interval(h - base, rng2)
        low, high = dd.lo * 100, dd.hi * 100
        print(
            f"  context {other:5s} lambda={lam}: {dd.mean * 100:+.2f} pts [{low:+.2f}, {high:+.2f}]"
        )
