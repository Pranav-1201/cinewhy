"""Download TMDB's details for TV series, once, into a resumable local cache.

IMDb's dumps list the series but not their language, poster or description. TMDB's `/find` answers
all three from an IMDb number, one request per series. About 30,000 series are wanted, so this is
polite (a fixed request rate well under TMDB's limit), resumable (a rerun asks only for series not
yet in the cache) and safe to interrupt (a half-written last line is ignored on read).

    $env:TMDB_API_TOKEN = "<TMDB v4 read access token>"          (PowerShell)
    python -m cinewhy.data.fetch_series --min-votes 200

The token is read from the environment and is never printed, logged or written. TMDB's terms
(non-commercial use, with attribution) apply to what is downloaded. Output is JSON lines:
`{"imdb": 903747, "found": true, "tmdb_id": 1396, "original_language": "en", ...}`, or
`{"imdb": N, "found": false}` when TMDB does not know the series.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Final

from cinewhy.data.series import read_imdb_series

TOKEN_VARIABLE: Final[str] = "TMDB_API_TOKEN"
HOST: Final[str] = "api.themoviedb.org"
DEFAULT_RATE: Final[float] = 20.0  # requests a second; TMDB allows about 50
DEFAULT_WORKERS: Final[int] = 6
_KEPT: Final[tuple[str, ...]] = (
    "original_language",
    "first_air_date",
    "overview",
    "poster_path",
    "vote_count",
    "vote_average",
    "popularity",
)

Fetcher = Callable[[int], "dict[str, Any] | None"]


def record_from_find(imdb_id: int, answer: dict[str, Any]) -> dict[str, Any]:
    """The cache line for one `/find` answer: the first TV result, or "not found"."""
    results = answer.get("tv_results") or []
    if not results:
        return {"imdb": imdb_id, "found": False}
    first = results[0]
    record: dict[str, Any] = {"imdb": imdb_id, "found": True, "tmdb_id": int(first["id"])}
    record.update({key: first.get(key) for key in _KEPT})
    record["origin_country"] = list(first.get("origin_country") or [])
    return record


def _new_connection() -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(HOST, timeout=30)


def make_fetcher(
    token: str,
    *,
    connect: Callable[[], http.client.HTTPSConnection] = _new_connection,
    sleep: Callable[[float], None] = time.sleep,
) -> Fetcher:
    """A function that asks TMDB about one IMDb number; None means "failed, try again later".

    Each worker thread keeps ONE connection open and reuses it. Opening a new one per request
    costs a TLS handshake (measured here: 0.7 to 8 seconds each, against 0.24 s on a reused
    connection), which would turn a 25-minute download into most of a day.
    """
    local = threading.local()

    def drop() -> None:
        conn = getattr(local, "conn", None)
        if conn is not None:
            conn.close()
        local.conn = None

    def fetch(imdb_id: int) -> dict[str, Any] | None:
        path = f"/3/find/tt{imdb_id:07d}?external_source=imdb_id"
        headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
        for attempt in range(5):
            try:
                if getattr(local, "conn", None) is None:
                    local.conn = connect()
                local.conn.request("GET", path, headers=headers)
                response = local.conn.getresponse()
                body = response.read()
            except (OSError, http.client.HTTPException):  # includes timeouts
                drop()
                sleep(1 + attempt)
                continue
            if response.status == 200:
                try:
                    return record_from_find(imdb_id, json.loads(body))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    drop()
                    sleep(1 + attempt)
                    continue
            if response.status in (401, 403):
                raise SystemExit(f"TMDB refused the token (HTTP {response.status})")
            if response.status == 429:  # too many requests: wait as long as TMDB asks
                sleep(float(response.getheader("Retry-After") or 2 * (attempt + 1)))
                continue
            if response.status < 500:
                return {"imdb": imdb_id, "found": False}
            drop()
            sleep(1 + attempt)
        return None

    return fetch


def already_fetched(cache: Path) -> set[int]:
    """IMDb numbers with a complete line in the cache (found or not)."""
    done: set[int] = set()
    if cache.is_file():
        with cache.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    done.add(int(json.loads(line)["imdb"]))
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    continue
    return done


def fetch_all(
    imdb_ids: Iterable[int],
    cache: Path,
    fetch: Fetcher,
    *,
    rate: float = DEFAULT_RATE,
    workers: int = DEFAULT_WORKERS,
    on_progress: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fetch every id not yet in the cache, appending each answer as it arrives.

    Args:
        imdb_ids: The series wanted.
        cache: JSON-lines file to append to (created if missing).
        fetch: Asks TMDB about one id; None means failure, which is not recorded so a rerun retries.
        rate: Most requests started per second, across all workers.
        workers: Concurrent requests.
        on_progress: Called with a status line every thousand series.
        clock: Monotonic time source (injectable for tests).
        sleep: Delay function (injectable for tests).

    Returns:
        How many answers were written in this run.
    """
    wanted = sorted(set(imdb_ids) - already_fetched(cache))
    cache.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    gate = threading.Lock()
    next_start = [clock()]
    written = [0]
    interval = 1.0 / rate

    def one(imdb_id: int) -> None:
        with gate:  # one request starts per interval, whichever worker is free
            wait = next_start[0] - clock()
            if wait > 0:
                sleep(wait)
            next_start[0] = max(next_start[0], clock()) + interval
        record = fetch(imdb_id)
        if record is None:
            return
        with lock:
            with cache.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written[0] += 1
            if written[0] % 1000 == 0:
                on_progress(f"{written[0]} of {len(wanted)} fetched")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, wanted))
    return written[0]


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--dumps", type=Path, default=Path("Data/raw/imdb_dumps"))
    parser.add_argument("--out", type=Path, default=Path("Data/raw/series/tmdb_tv.jsonl"))
    parser.add_argument("--min-votes", type=int, default=200)
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--dry-run", action="store_true", help="count what would be fetched")
    args = parser.parse_args()
    series = read_imdb_series(
        args.dumps / "title.basics.tsv.gz",
        args.dumps / "title.ratings.tsv.gz",
        min_votes=args.min_votes,
    )
    todo = len({s.imdb_id for s in series} - already_fetched(args.out))
    print(f"{len(series)} series with {args.min_votes}+ votes, {todo} not yet fetched", flush=True)
    if args.dry_run or not todo:
        return
    token = os.environ.get(TOKEN_VARIABLE)
    if not token:
        raise SystemExit(f"set {TOKEN_VARIABLE} to your TMDB read access token")
    started = time.monotonic()
    written = fetch_all(
        (s.imdb_id for s in series),
        args.out,
        make_fetcher(token),
        rate=args.rate,
        workers=args.workers,
        on_progress=lambda m: print(m, flush=True),
    )
    print(f"wrote {written} answers in {time.monotonic() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
