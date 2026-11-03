"""Who acts in each title, from IMDb's cast files, written as one compact file for the artifact set.

IMDb's `title.principals` lists every credited person of every title, keyed by the same IMDb number
the whole project joins on, with the order they are billed in; `name.basics` gives each person's
name. This module keeps the actors and actresses (not directors, writers or "self" appearances),
the first few in billing order, for the titles in the catalogue, and writes:

    {"people": {"1588970": "Fred Astaire", ...}, "titles": {"72308": [1588970, 4096, ...], ...}}

`titles` maps an IMDb number to person numbers in billing order; `people` maps a person number to a
name. "Major" here means billed near the top, which is IMDb's order, not fame. The files are IMDb's
non-commercial datasets, like the dumps already used for series.

    python -m cinewhy.data.cast --artifacts artifacts/v8 --out artifacts/v10
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

CAST_FILE: Final[str] = "cast.json"
TOP_BILLED: Final[int] = 6  # actors and actresses kept per title
ACTING: Final[frozenset[str]] = frozenset({"actor", "actress"})


@dataclass(frozen=True)
class Cast:
    """The cast of the catalogue's titles: who is billed in what, and what each person is called."""

    titles: dict[int, tuple[int, ...]]  # IMDb number -> person numbers, billing order
    people: dict[int, str]  # person number -> name
    # Person number -> IMDb numbers they are billed in, in IMDb-number order (derived).
    by_person: dict[int, tuple[int, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Derive the person-to-titles index."""
        grouped: dict[int, list[int]] = defaultdict(list)
        for imdb in sorted(self.titles):
            for person in self.titles[imdb]:
                grouped[person].append(imdb)
        object.__setattr__(self, "by_person", {p: tuple(v) for p, v in grouped.items()})


def read_principals(
    path: Path, wanted: Collection[int], *, top: int = TOP_BILLED
) -> dict[int, tuple[int, ...]]:
    """Billed actors and actresses of the wanted titles, from IMDb's `title.principals`.

    Args:
        path: `title.principals.tsv.gz` (tconst, ordering, nconst, category, job, characters).
        wanted: IMDb numbers to keep; every other title is skipped as it streams past.
        top: Most people kept per title, first in billing order.

    Returns:
        IMDb number -> person numbers in billing order, for titles with at least one.
    """
    credits: dict[int, list[tuple[int, int]]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        next(handle, None)  # header
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4 or parts[3] not in ACTING:
                continue
            try:
                imdb, order, person = int(parts[0][2:]), int(parts[1]), int(parts[2][2:])
            except ValueError:
                continue
            if imdb in wanted:
                credits[imdb].append((order, person))
    return {imdb: tuple(p for _o, p in sorted(rows)[:top]) for imdb, rows in credits.items()}


def read_names(path: Path, needed: Collection[int]) -> dict[int, str]:
    """Names of the needed people, from IMDb's `name.basics` (columns nconst, primaryName, ...)."""
    names: dict[int, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        next(handle, None)
        for line in handle:
            nconst, _tab, rest = line.partition("\t")
            try:
                person = int(nconst[2:])
            except ValueError:
                continue
            if person in needed:
                name = rest.partition("\t")[0].strip()
                if name:
                    names[person] = name
    return names


def build_cast(
    principals: Path, name_basics: Path, wanted: Collection[int], *, top: int = TOP_BILLED
) -> Cast:
    """The cast of the wanted titles; people with no name are dropped, and titles left empty."""
    billed = read_principals(principals, wanted, top=top)
    names = read_names(name_basics, {p for people in billed.values() for p in people})
    titles = {
        imdb: kept
        for imdb, people in billed.items()
        if (kept := tuple(p for p in people if p in names))
    }
    used = {p for people in titles.values() for p in people}
    return Cast(titles, {p: names[p] for p in sorted(used)})


def write_cast(path: Path, cast: Cast) -> None:
    """Write `cast.json`. Sorted keys and no spaces, so the same cast always hashes the same."""
    document = {
        "people": {str(p): name for p, name in sorted(cast.people.items())},
        "titles": {str(i): list(people) for i, people in sorted(cast.titles.items())},
    }
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def load_cast(path: Path) -> Cast:
    """Read `cast.json`; the caller has verified the file's hash against the manifest."""
    document = json.loads(path.read_text(encoding="utf-8"))
    return Cast(
        {int(i): tuple(int(p) for p in people) for i, people in document["titles"].items()},
        {int(p): name for p, name in document["people"].items()},
    )


def imdb_numbers(movie_ids: Iterable[str]) -> set[int]:
    """IMDb numbers behind catalogue ids (`cw-0000603` and `ro-0000603` are both 603)."""
    return {int(movie_id[3:]) for movie_id in movie_ids}


def main() -> None:
    """Command line entry point: copy an artifact set and add its cast file and manifest entry."""
    from cinewhy.artifacts.manifest import MANIFEST_NAME, build, load_manifest, verify

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--artifacts", type=Path, required=True, help="the build to start from")
    parser.add_argument("--cast-dir", type=Path, default=Path("Data/raw/imdb_cast"))
    parser.add_argument("--out", type=Path, required=True, help="a NEW folder for the new build")
    parser.add_argument("--top", type=int, default=TOP_BILLED)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"{args.out} already exists; give a new folder so no build is overwritten")
    manifest = load_manifest(args.artifacts)
    verify(args.artifacts, manifest)
    catalogue = json.loads((args.artifacts / "catalogue.json").read_text(encoding="utf-8"))
    movies = catalogue["movies"] if isinstance(catalogue, dict) else catalogue
    ids = [m["movie_id"] for m in movies]
    if "ratings_only.json" in manifest.files:
        blob = json.loads((args.artifacts / "ratings_only.json").read_text(encoding="utf-8"))
        ids += [r["movie_id"] for r in (blob["films"] if isinstance(blob, dict) else blob)]
    cast = build_cast(
        args.cast_dir / "title.principals.tsv.gz",
        args.cast_dir / "name.basics.tsv.gz",
        imdb_numbers(ids),
        top=args.top,
    )
    args.out.mkdir(parents=True)
    for name in manifest.files:
        shutil.copy2(args.artifacts / name, args.out / name)
    write_cast(args.out / CAST_FILE, cast)
    names = sorted({*manifest.files, CAST_FILE} - {MANIFEST_NAME})
    counts = {**manifest.row_counts, CAST_FILE: len(cast.titles)}
    new = build(args.out, row_counts=counts, names=names)
    print(
        f"cast for {len(cast.titles)} of {len(set(ids))} titles, {len(cast.people)} people; "
        f"manifest {new.manifest_hash[:12]} in {args.out}"
    )


if __name__ == "__main__":
    main()
