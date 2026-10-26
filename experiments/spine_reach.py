"""How many films reach 50 reviews if the film list is widened? (roadmap F1).

Throwaway measurement, not product code and not a build. The shipped catalogue takes the 300 most
voted English films a year (70 Hindi), then keeps those with 5 or more reviews; Pranav's floor for
full receipts is 50 reviews, with a ratings-only tier below it. Before spending hours on a new
build, this widens the list (and adds Telugu, Japanese and French, which the build does not yet
select), runs the SAME joins against the SAME dumps, and counts the films per language and era that
reach 5, 20 and 50 merged reviews.

Per-source cap here is 60, not 150: a film needs only 50 to pass, and the lower cap keeps memory
near 3 GB instead of 5+. Counts of 50 or more are therefore exact; counts above 60 per source are
not needed and not reported.

    python experiments/spine_reach.py --root D:/NLPPROJECT --out spine_reach.json

About 30 to 40 minutes and 3 to 6 GB of memory on the real data; nothing is written but the JSON.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cinewhy.data import spine
from cinewhy.data.catalogue_sources import SourcePaths, gather

CAP = 60
FLOORS = (5, 20, 50)
LANGUAGES = ("en", "hi", "te", "ja", "fr")
# Wider than the shipped quotas: (language, year) to how many films to take by TMDB votes.
EN_RECENT, EN_OLD, OTHER = 1000, 250, 300


def wide_quota(language: str, year: int) -> int:
    """Films per (language, year): many more English than the build keeps, plus new languages."""
    if language == "en":
        return EN_RECENT if year >= 2000 else EN_OLD
    return OTHER


def era(year: int) -> str:
    """Release-year bucket for the table."""
    if year < 2000:
        return "before 2000"
    if year < 2012:
        return "2000-2011"
    return "2012-2020" if year < 2021 else "2021 on"


def main() -> None:
    """Gather with the wide quota, then count films reaching each review floor."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, default=Path("spine_reach.json"))
    args = parser.parse_args()

    spine.LANGUAGES = LANGUAGES  # type: ignore[misc]  # the build selects only en and hi today
    spine.MAX_YEAR = 2026  # type: ignore[misc]
    raw = args.root / "Data" / "raw"
    paths = SourcePaths(
        tmdb_csv=raw / "tmdb1m" / "TMDB_all_movies.csv",
        rt_zip=raw / "rt_mother" / "rt_mother.zip",
        ebd_zip=raw / "imdb_ebd" / "imdb_ebd.zip",
        acl_archive=raw / "aclImdb_v1.tar.gz",
    )
    gathered = gather(
        paths, cap=CAP, quota_for=wide_quota, on_progress=lambda m: print(m, flush=True)
    )

    table: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for film in gathered.films:
        bucket = table[film.language][era(film.year)]
        n = len(gathered.reviews.get(film.imdb_id, ()))
        bucket["films_selected"] += 1
        for floor in FLOORS:
            if n >= floor:
                bucket[f"reviews_{floor}_plus"] += 1
    keys = ("films_selected", *(f"reviews_{f}_plus" for f in FLOORS))
    result: dict[str, Any] = {
        "cap_per_source": CAP,
        "quotas": {"en_2000_on": EN_RECENT, "en_before_2000": EN_OLD, "other_languages": OTHER},
        "by_language_and_era": {
            lang: {e: dict(c) for e, c in eras.items()} for lang, eras in table.items()
        },
        "totals_by_language": {
            lang: {k: sum(c[k] for c in eras.values()) for k in keys}
            for lang, eras in table.items()
        },
        "join_report": gathered.report,
    }
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result["totals_by_language"], indent=1), flush=True)


if __name__ == "__main__":
    main()
