"""Would matching on a film's ORIGINAL title link more foreign films to the review dumps?

Throwaway measurement, not product code. Rotten Tomatoes and IMDb (ebD) reviews are joined to films
by normalised title plus release year, using TMDB's `title`. For a Japanese or French film TMDB's
`title` is usually an English one, while the dumps may carry the original or the international
title, so a second key built from `original_title` could link films the first one misses. This
counts, per language, how many of the same wide candidate list link by title, by original title,
and by either. It counts LINKS only (an upper bound: the real pipeline also checks runtimes and
refuses ambiguous titles), so the answer is whether the lever is worth building, not a final
number.

    python experiments/title_join_lift.py --root D:/NLPPROJECT --out title_join_lift.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cinewhy.data.linking import film_key
from cinewhy.data.reviews import read_rt_films, scan_ebd_keys
from cinewhy.data.spine import parse_imdb_id, read_tmdb_rows

LANGUAGES = ("en", "hi", "te", "ja", "fr")
QUOTA = {"en": 1000}
OTHER_QUOTA = 300


def stem_key(title: str, year: int) -> str | None:
    """`film_key`, or None when the title has no Latin letters or digits to match on.

    `film_key` keeps only ASCII letters and digits, so a Japanese or Hindi title becomes the bare
    year and would "link" to every film of that year. A first run counted those as links.
    """
    key = film_key(title, year)
    return key if len(key) > len(str(year)) else None


def candidates(csv_path: Path) -> list[dict[str, Any]]:
    """The wide candidate list: top films by TMDB votes per language and year, one per IMDb id."""
    best: dict[int, dict[str, Any]] = {}
    for row in read_tmdb_rows(csv_path):
        year = row["release_date"][:4]
        imdb = parse_imdb_id(row["imdb_id"])
        if (
            row["original_language"] not in LANGUAGES
            or row["status"] != "Released"
            or not year.isdigit()
            or not 1950 <= int(year) <= 2026
            or imdb is None
        ):
            continue
        votes = int(float(row["vote_count"] or 0))
        held = best.get(imdb)
        if held is None or votes > held["votes"]:
            best[imdb] = {
                "imdb": imdb,
                "language": row["original_language"],
                "year": int(year),
                "title": row["title"],
                "original": row["original_title"],
                "votes": votes,
            }
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for film in best.values():
        groups[(film["language"], film["year"])].append(film)
    kept: list[dict[str, Any]] = []
    for (language, _year), films in groups.items():
        films.sort(key=lambda f: -f["votes"])
        kept.extend(films[: QUOTA.get(language, OTHER_QUOTA)])
    return kept


def main() -> None:
    """Count links by title, by original title and by either, per language, for RT and for ebD."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, default=Path("title_join_lift.json"))
    args = parser.parse_args()
    raw = args.root / "Data" / "raw"

    films = candidates(raw / "tmdb1m" / "TMDB_all_movies.csv")
    print(f"{len(films)} candidate films", flush=True)
    rt_keys = {
        stem_key(f.title, f.year) for f in read_rt_films(raw / "rt_mother" / "rt_mother.zip")
    } - {None}
    print(f"{len(rt_keys)} Rotten Tomatoes film keys", flush=True)
    ebd_keys = {k for k in scan_ebd_keys(raw / "imdb_ebd" / "imdb_ebd.zip") if not k.isdigit()}
    print(f"{len(ebd_keys)} ebD film keys", flush=True)

    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for f in films:
        by_title = stem_key(f["title"], f["year"])
        by_original = stem_key(f["original"], f["year"])
        tally = counts[f["language"]]
        for source, keys in (("rt", rt_keys), ("ebd", ebd_keys)):
            a = by_title is not None and by_title in keys
            b = by_original is not None and by_original in keys
            tally[f"{source}_title"] += a
            tally[f"{source}_original_only"] += b and not a
            tally[f"{source}_either"] += a or b
        tally["films"] += 1
        tally["different_original_title"] += (
            f["original"].strip().lower() != f["title"].strip().lower()
        )
    result = {lang: dict(c) for lang, c in counts.items()}
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=1), flush=True)


if __name__ == "__main__":
    main()
