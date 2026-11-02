"""Download where each title can be watched, for six streaming platforms, into a resumable cache.

TMDB's watch-provider data (supplied by JustWatch, which the page must credit) answers one
question per title: in which countries is it on which service, to stream, free with ads, rent or
buy. One request returns every country, so the whole catalogue is one request per title. Like the
series download it is polite (a fixed rate), resumable (a rerun asks only for titles not yet
cached) and safe to interrupt.

    $env:TMDB_API_TOKEN = "<TMDB v4 read access token>"          (PowerShell)
    python -m cinewhy.data.fetch_providers --artifacts artifacts/v8

The token is read from the environment and never printed, logged or written. Only six platforms
are kept (the owner's list: Netflix, Apple TV, Amazon Prime Video, Disney+ Hotstar, Crunchyroll,
HBO Max); every other service in the answer is dropped. Output is JSON lines, keyed by IMDb number:

    {"imdb": 903747, "found": true, "tmdb_id": 1396, "kind": "series",
     "where": {"IN": {"netflix": ["stream"]}, "US": {"netflix": ["stream"], "apple": ["buy"]}}}

`found` is false when TMDB does not know the title. A title with no availability on the six
platforms has `"where": {}`. Availability changes constantly, so the cache is a snapshot, and the
page must say when it was taken.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from cinewhy.data.fetch_series import (
    DEFAULT_WORKERS,
    TOKEN_VARIABLE,
    already_fetched,
    fetch_all,
    make_json_fetcher,
)
from cinewhy.data.spine import parse_imdb_id, read_tmdb_rows

# TMDB provider ids per platform, found by listing TMDB's providers on 2026-11-03. Names changed
# over time (HBO Max became Max and back; Disney+ Hotstar became JioHotstar in India), and each
# service has several ids (a free-with-ads plan, an older id, a store for renting). Amazon
# "Channel" add-ons (Crunchyroll or HBO Max sold through Prime) and Disney+ outside the Hotstar
# countries are NOT included: the owner asked for these six platforms. The ids are the same for
# films and series.
PLATFORMS: Final[dict[str, tuple[int, ...]]] = {
    "netflix": (8, 1796),  # Netflix; Netflix Standard with Ads
    "apple": (350, 2),  # Apple TV (subscription); Apple TV Store (rent or buy)
    # Prime Video; an older id; with Ads; Free with Ads; Amazon Video (rent or buy)
    "prime": (119, 9, 2100, 613, 10),
    "hotstar": (122, 2336),  # Disney+ Hotstar; JioHotstar
    "crunchyroll": (283,),
    "hbo": (1899,),  # HBO Max
}
PLATFORM_OF: Final[dict[int, str]] = {pid: name for name, ids in PLATFORMS.items() for pid in ids}
# How TMDB names the ways to watch, and what the page calls them. Free-with-ads and free are one
# thing to a viewer. The order is the order they are shown in.
WAYS: Final[dict[str, str]] = {
    "flatrate": "stream",
    "ads": "free",
    "free": "free",
    "rent": "rent",
    "buy": "buy",
}
WAY_ORDER: Final[tuple[str, ...]] = ("stream", "free", "rent", "buy")
DEFAULT_RATE: Final[float] = 25.0  # requests a second; TMDB allows about 50


def record_from_providers(
    imdb_id: int, tmdb: tuple[str, int], answer: Mapping[str, Any]
) -> dict[str, Any]:
    """The cache line for one watch-provider answer: only the six platforms, per country.

    Args:
        imdb_id: The title's IMDb number (the cache key).
        tmdb: ("film" or "series", the title's TMDB id).
        answer: TMDB's JSON: `{"results": {"IN": {"flatrate": [{"provider_id": 8, ...}], ...}}}`.
    """
    kind, tmdb_id = tmdb
    where: dict[str, dict[str, list[str]]] = {}
    for country, offers in (answer.get("results") or {}).items():
        platforms: dict[str, set[str]] = {}
        for way_key, way in WAYS.items():
            for provider in offers.get(way_key) or []:
                platform = PLATFORM_OF.get(provider.get("provider_id"))
                if platform is not None:
                    platforms.setdefault(platform, set()).add(way)
        if platforms:
            where[country] = {
                platform: [w for w in WAY_ORDER if w in ways]
                for platform, ways in sorted(platforms.items())
            }
    return {"imdb": imdb_id, "found": True, "tmdb_id": tmdb_id, "kind": kind, "where": where}


def provider_path(kind: str, tmdb_id: int) -> str:
    """The TMDB request path for a title's watch providers."""
    return f"/3/{'tv' if kind == 'series' else 'movie'}/{tmdb_id}/watch/providers"


def wanted_titles(artifacts: Path) -> dict[int, str]:
    """IMDb number to "film" or "series" for every title in an artifact set, both tiers."""
    wanted: dict[int, str] = {}
    catalogue = json.loads((artifacts / "catalogue.json").read_text(encoding="utf-8"))
    for movie in catalogue["movies"] if isinstance(catalogue, dict) else catalogue:
        if movie["movie_id"].startswith("cw-"):
            wanted[int(movie["movie_id"][3:])] = movie.get("kind", "film")
    ratings_only = artifacts / "ratings_only.json"
    if ratings_only.is_file():
        blob = json.loads(ratings_only.read_text(encoding="utf-8"))
        for film in blob["films"] if isinstance(blob, dict) else blob:
            wanted[int(film["imdb_id"])] = film.get("kind", "film")
    return wanted


def tmdb_ids(
    wanted: Mapping[int, str], tmdb_csv: Path, series_cache: Path
) -> dict[int, tuple[str, int]]:
    """TMDB's id for each wanted title: films from TMDB's film list, series from the series cache.

    A film's IMDb number can appear on more than one TMDB row; the most voted row wins, ties
    broken by the lower TMDB id, so the answer never depends on file order.
    """
    found: dict[int, tuple[str, int]] = {}
    best_votes: dict[int, tuple[int, int]] = {}
    for row in read_tmdb_rows(tmdb_csv):
        imdb = parse_imdb_id(row["imdb_id"])
        if imdb is None or wanted.get(imdb) != "film":
            continue
        rank = (int(float(row["vote_count"] or 0)), -int(row["id"]))
        if imdb not in best_votes or rank > best_votes[imdb]:
            best_votes[imdb] = rank
            found[imdb] = ("film", int(row["id"]))
    if series_cache.is_file():
        with series_cache.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                imdb = record.get("imdb")
                if record.get("found") and wanted.get(imdb) == "series":
                    found[int(imdb)] = ("series", int(record["tmdb_id"]))
    return found


def make_provider_fetcher(token: str, ids: Mapping[int, tuple[str, int]], **kwargs: Any) -> Any:
    """A fetcher that asks TMDB where one title can be watched (`kwargs` go to the connection)."""
    return make_json_fetcher(
        token,
        lambda imdb: provider_path(*ids[imdb]) if imdb in ids else None,
        lambda imdb, answer: record_from_providers(imdb, ids[imdb], answer),
        **kwargs,
    )


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--artifacts", type=Path, required=True, help="the build whose titles to cover"
    )
    parser.add_argument(
        "--tmdb-csv", type=Path, default=Path("Data/raw/tmdb1m/TMDB_all_movies.csv")
    )
    parser.add_argument("--series-cache", type=Path, default=Path("Data/raw/series/tmdb_tv.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("Data/raw/providers/providers.jsonl"))
    parser.add_argument("--rate", type=float, default=DEFAULT_RATE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--limit", type=int, default=None, help="only the first N titles (a trial)")
    parser.add_argument("--dry-run", action="store_true", help="count what would be fetched")
    args = parser.parse_args()
    wanted = wanted_titles(args.artifacts)
    ids = tmdb_ids(wanted, args.tmdb_csv, args.series_cache)
    todo = sorted(set(wanted) - already_fetched(args.out))
    if args.limit is not None:
        todo = todo[: args.limit]
    unknown = sum(1 for imdb in todo if imdb not in ids)
    print(
        f"{len(wanted)} titles, {len(ids)} with a TMDB id, {len(todo)} to fetch "
        f"({unknown} of them have no TMDB id and will be recorded as not found)",
        flush=True,
    )
    if args.dry_run or not todo:
        return
    token = os.environ.get(TOKEN_VARIABLE)
    if not token:
        raise SystemExit(f"set {TOKEN_VARIABLE} to your TMDB read access token")
    started = time.monotonic()
    written = fetch_all(
        todo,
        args.out,
        make_provider_fetcher(token, ids),
        rate=args.rate,
        workers=args.workers,
        on_progress=lambda m: print(m, flush=True),
    )
    print(f"wrote {written} answers in {time.monotonic() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
