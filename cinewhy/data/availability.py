"""Where each title can be watched, packaged as one file for the artifact set.

`fetch_providers` downloads TMDB's watch-provider answer for every title into a resumable
cache. This module turns that cache into `availability.json`, which the API serves on a film's page:

    {"fetched": "2026-11-03",
     "titles": {"603": {"t": "movie/603",
                        "on": {"netflix": {"stream": "AD AE AG", "rent": "US"}, ...}}, ...}}

`t` is the title's TMDB page (the link to its full list of providers); `on` maps each of the
six platforms to the ways it is offered (stream, free, rent, buy) and the countries, as
space-separated ISO codes. Titles on none of the six platforms anywhere are left out, so a missing
entry means "none of the six", not "unknown". The data is TMDB's, powered by JustWatch, which the
page must credit, and it is a snapshot: availability changes daily, so the file carries the date it
was fetched.

    python -m cinewhy.data.availability --artifacts artifacts/v10 --out artifacts/v11
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from cinewhy.data.fetch_providers import PLATFORMS, WAY_ORDER

AVAILABILITY_FILE: Final[str] = "availability.json"
_TMDB_PATH: Final[dict[str, str]] = {"film": "movie", "series": "tv"}


@dataclass(frozen=True)
class Where:
    """One title's availability: its TMDB page and, per platform, per way, the countries."""

    tmdb: str  # "movie/603" or "tv/1396": the path under themoviedb.org
    on: dict[str, dict[str, tuple[str, ...]]]


@dataclass(frozen=True)
class Availability:
    """Availability of the catalogue's titles, as of one date."""

    fetched: str  # ISO date the snapshot was taken
    titles: dict[int, Where]


def where_from_record(record: Mapping[str, Any]) -> Where | None:
    """One cache line as a `Where`, or None when the title is on none of the six platforms.

    Platforms or ways this module does not know are ignored rather than trusted, so a stray cache
    line can never put an unlisted platform on a film's page.
    """
    kind = _TMDB_PATH.get(str(record.get("kind")))
    if not record.get("found") or kind is None or not isinstance(record.get("tmdb_id"), int):
        return None
    grouped: dict[str, dict[str, set[str]]] = {}
    for country, platforms in (record.get("where") or {}).items():
        for platform, ways in platforms.items():
            if platform not in PLATFORMS:
                continue
            for way in ways:
                if way in WAY_ORDER:
                    grouped.setdefault(platform, {}).setdefault(way, set()).add(country)
    if not grouped:
        return None
    on = {
        platform: {
            way: tuple(sorted(grouped[platform][way]))
            for way in WAY_ORDER
            if way in grouped[platform]
        }
        for platform in PLATFORMS
        if platform in grouped
    }
    return Where(f"{kind}/{record['tmdb_id']}", on)


def build_availability(records: Iterable[Mapping[str, Any]], fetched: str) -> Availability:
    """Availability from cache lines; a title seen twice (a resumed fetch) keeps its last line."""
    titles: dict[int, Where] = {}
    for record in records:
        imdb = record.get("imdb")
        if not isinstance(imdb, int):
            continue
        where = where_from_record(record)
        if where is None:
            titles.pop(imdb, None)
        else:
            titles[imdb] = where
    return Availability(fetched, titles)


def read_cache(path: Path) -> Iterable[dict[str, Any]]:
    """Lines of the provider cache; a torn last line from an interrupted run is skipped."""
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def write_availability(path: Path, availability: Availability) -> None:
    """Write `availability.json`: sorted keys, no spaces, so equal data always hashes the same."""
    document = {
        "fetched": availability.fetched,
        "titles": {
            str(imdb): {
                "t": where.tmdb,
                "on": {
                    platform: {way: " ".join(countries) for way, countries in ways.items()}
                    for platform, ways in where.on.items()
                },
            }
            for imdb, where in sorted(availability.titles.items())
        },
    }
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def load_availability(path: Path) -> Availability:
    """Read `availability.json`; the caller has verified the file's hash against the manifest."""
    document = json.loads(path.read_text(encoding="utf-8"))
    titles = {
        int(imdb): Where(
            entry["t"],
            {
                platform: {way: tuple(countries.split()) for way, countries in ways.items()}
                for platform, ways in entry["on"].items()
            },
        )
        for imdb, entry in document["titles"].items()
    }
    return Availability(str(document["fetched"]), titles)


def main() -> None:
    """Command line entry point: copy an artifact set and add its availability file."""
    from cinewhy.artifacts.manifest import MANIFEST_NAME, build, load_manifest, verify

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--artifacts", type=Path, required=True, help="the build to start from")
    parser.add_argument(
        "--providers", type=Path, default=Path("Data/raw/providers/providers.jsonl")
    )
    parser.add_argument("--fetched", default=None, help="ISO date (default: the cache's date)")
    parser.add_argument("--out", type=Path, required=True, help="a NEW folder for the new build")
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"{args.out} already exists; give a new folder so no build is overwritten")
    manifest = load_manifest(args.artifacts)
    verify(args.artifacts, manifest)
    fetched = args.fetched or date.fromtimestamp(args.providers.stat().st_mtime).isoformat()
    availability = build_availability(read_cache(args.providers), fetched)
    args.out.mkdir(parents=True)
    for name in manifest.files:
        shutil.copy2(args.artifacts / name, args.out / name)
    write_availability(args.out / AVAILABILITY_FILE, availability)
    names = sorted({*manifest.files, AVAILABILITY_FILE} - {MANIFEST_NAME})
    counts = {**manifest.row_counts, AVAILABILITY_FILE: len(availability.titles)}
    new = build(args.out, row_counts=counts, names=names)
    print(
        f"availability for {len(availability.titles)} titles as of {fetched}; "
        f"manifest {new.manifest_hash[:12]} in {args.out}"
    )


if __name__ == "__main__":
    main()
