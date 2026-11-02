"""Why are some ebD films with 50+ reviews missing from the catalogue, and what would reach them?

Throwaway measurement, not product code and not a build (DECISIONS D-033). Read-only: it prints
counts and writes nothing.

It starts from the ebD films that have 50 or more reviews and sorts each into one of:

* already in the artifact's catalogue;
* no TMDB film with that title and year, or several (ambiguous), or in another language;
* reachable (one TMDB film, in the five languages) but missing, and for those, whether the film was
  outside `wide_quota`, or was selected and then lost.

"Selected then lost" is mostly the spoiler and profanity filter: `scan_ebd_keys` counts every
review whatever its length or spoiler flag, while the gather excludes flagged reviews because
sentences from them are shown to users. Last, for the films outside the quota, how deep each sits in
its (language, year) ranking by TMDB votes, so a quota can be chosen from the numbers.

    python experiments/floor50_reach.py --root D:/NLPPROJECT --artifacts artifacts/v8

About 5 minutes and 3 GB; exact-year title matches only (the build's English plus-or-minus-one-year
rule is not applied), so "no TMDB film" is slightly overstated for English.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from cinewhy.data.linking import film_key, parse_ebd_movie
from cinewhy.data.reviews import clean_ebd_text, iter_ebd_records, scan_ebd_keys
from cinewhy.data.spine import parse_imdb_id, read_tmdb_rows, select_spine, wide_quota

FIVE = ("en", "hi", "te", "ja", "fr")
FLOOR = 50
QUOTAS = (400, 600, 1000, 1500, 2000, 3000)


def _catalogue_imdb_ids(artifacts: Path) -> set[int]:
    """IMDb numbers of the films with full receipts in an artifact set (series are left out)."""
    blob = json.loads((artifacts / "catalogue.json").read_text(encoding="utf-8"))
    movies = blob if isinstance(blob, list) else blob["movies"]
    return {
        int(m["movie_id"][3:])
        for m in movies
        if m["movie_id"].startswith("cw-") and m.get("kind", "film") == "film"
    }


def main() -> None:
    """Classify the missing ebD films, then size the quota that would reach them."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="folder holding Data/raw")
    parser.add_argument("--artifacts", type=Path, required=True, help="artifact set to compare")
    args = parser.parse_args()
    raw = args.root / "Data" / "raw"
    tmdb = raw / "tmdb1m" / "TMDB_all_movies.csv"

    have = _catalogue_imdb_ids(args.artifacts)
    wanted = {
        k: n for k, n in scan_ebd_keys(raw / "imdb_ebd" / "imdb_ebd.zip").items() if n >= FLOOR
    }
    print(f"films with receipts: {len(have)} | ebD film keys with {FLOOR}+ reviews: {len(wanted)}")

    selection = select_spine(read_tmdb_rows(tmdb), wide_quota, languages=FIVE, max_year=2026)
    selected = {f.imdb_id: f for f in selection.films}
    shared_key = Counter(film_key(f.title, f.year) for f in selection.films)

    # Every TMDB film each wanted key could mean, and every film's rank in its (language, year).
    by_key: dict[str, set[int]] = {}
    language_of: dict[int, str] = {}
    pools: dict[tuple[str, int], list[tuple[int, int, int]]] = {}
    for row in read_tmdb_rows(tmdb):
        year = row["release_date"][:4]
        imdb = parse_imdb_id(row["imdb_id"])
        if row["status"] != "Released" or not year.isdigit() or imdb is None:
            continue
        for title in {row["title"], row.get("original_title", "")}:
            key = film_key(title, int(year)) if title else ""
            if key in wanted:
                by_key.setdefault(key, set()).add(imdb)
                language_of[imdb] = row["original_language"]
        if row["original_language"] in FIVE:
            votes = -int(float(row["vote_count"] or 0))
            pools.setdefault((row["original_language"], int(year)), []).append(
                (votes, int(row["id"]), imdb)
            )

    verdict: Counter[str] = Counter()
    outside: set[int] = set()
    lost: dict[str, int] = {}  # key -> IMDb number of the films selected but not in the catalogue
    for key in wanted:
        ids = by_key.get(key, set())
        if not ids:
            verdict["no TMDB film with that title and year"] += 1
        elif len(ids) > 1:
            verdict["ambiguous: several TMDB films share the key"] += 1
        else:
            imdb = next(iter(ids))
            if imdb in have:
                verdict["already in the catalogue"] += 1
            elif language_of[imdb] not in FIVE:
                verdict["another language"] += 1
            elif imdb not in selected:
                verdict["reachable, outside wide_quota"] += 1
                outside.add(imdb)
            elif shared_key[film_key(selected[imdb].title, selected[imdb].year)] > 1:
                verdict["reachable, selected, dropped as ambiguous"] += 1
            else:
                verdict["reachable, selected, then lost"] += 1
                lost[key] = imdb
    for why, n in verdict.most_common():
        print(f"{n:>7}  {why}")

    # Why were they lost? Count their reviews the way the gather does (no spoiler flag, text left
    # after cleaning): if most fall under the floor, the raw count was what overstated them.
    usable: Counter[str] = Counter()
    for record in iter_ebd_records(raw / "imdb_ebd" / "imdb_ebd.zip"):
        movie = parse_ebd_movie(str(record.get("movie") or ""))
        if movie is None or record.get("spoiler_tag") or film_key(*movie) not in lost:
            continue
        if clean_ebd_text(str(record.get("review_detail") or "")):
            usable[film_key(*movie)] += 1
    short = sum(usable[key] < FLOOR for key in lost)
    print(f"\nof the {len(lost)} lost films, {short} have fewer than {FLOOR} usable reviews")

    ranks: list[int] = []
    for items in pools.values():
        items.sort()
        ranks.extend(position for position, (_, _, imdb) in enumerate(items, 1) if imdb in outside)
    print(f"\nrank in (language, year) of the {len(ranks)} films outside the quota:")
    for quota in QUOTAS:
        print(f"  a quota of {quota:>5} would take {sum(r <= quota for r in ranks):>5}")


if __name__ == "__main__":
    main()
