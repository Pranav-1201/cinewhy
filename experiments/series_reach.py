"""How many TV series could have full receipts, counted from the dumps on disk.

Throwaway measurement, not product code. The film joins skip ebD's series records on purpose (a
series sharing a film's title once inflated English counts 5.5%). Those records are the only review
text in the dumps that belongs to series, so this counts them: IMDb's own list of series, joined to
ebD by normalised title and start year, and how many reach 5, 20 and 50 reviews.

    python experiments/series_reach.py --root D:/NLPPROJECT --out series_reach.json

IMDb's dumps carry no language, so this counts every language together, and Animation separately
(the Japanese anime split starts from it). Run with PYTHONPATH set to the checkout.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from cinewhy.data.linking import film_key, title_key
from cinewhy.data.reviews import _CHUNK, _EBD_MOVIE_FIELD, _ebd_parts

# "Breaking Bad (2008-2013)" or "Breaking Bad (2008- )"; the dash is an en dash in the dump.
_EBD_SERIES = re.compile("^(.*) \\((\\d{4})[\u2013-](\\d{4})?\\s*\\)$")
SERIES_TYPES = {"tvSeries", "tvMiniSeries"}
VOTE_FLOORS = (50, 200, 1000)
REVIEW_FLOORS = (5, 20, 50)


def read_series(basics: Path, ratings: Path) -> list[dict[str, object]]:
    """IMDb series and miniseries with at least 50 votes."""
    votes: dict[str, int] = {}
    with gzip.open(ratings, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["numVotes"].isdigit():
                votes[row["tconst"]] = int(row["numVotes"])
    out: list[dict[str, object]] = []
    with gzip.open(basics, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["titleType"] not in SERIES_TYPES or not row["startYear"].isdigit():
                continue
            if votes.get(row["tconst"], 0) < VOTE_FLOORS[0]:
                continue
            out.append(
                {
                    "imdb": row["tconst"],
                    "title": row["primaryTitle"],
                    "original": row["originalTitle"],
                    "year": int(row["startYear"]),
                    "genres": [g for g in row["genres"].split(",") if g != "\\N"],
                    "votes": votes[row["tconst"]],
                    "type": row["titleType"],
                }
            )
    return out


def scan_ebd_series(archive: Path) -> Counter[str]:
    """Reviews per series key (`film_key(title, start year)`) in ebD, series records only."""
    counts: Counter[str] = Counter()
    with zipfile.ZipFile(archive) as z:
        for name in _ebd_parts(z):
            carry = ""
            with z.open(name) as raw:
                while chunk := raw.read(_CHUNK):
                    text = carry + chunk.decode("utf-8", errors="ignore")
                    for found in _EBD_MOVIE_FIELD.finditer(text):
                        if found.end() <= len(carry):
                            continue
                        movie = json.loads(f'"{found.group(1)}"')
                        parsed = _EBD_SERIES.match(movie)
                        if parsed:
                            counts[film_key(parsed.group(1), int(parsed.group(2)))] += 1
                    carry = text[-600:]
    return counts


def main() -> None:
    """Count series by vote level and by how many ebD reviews they reach."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--dumps", type=Path, default=Path("Data/raw/imdb_dumps"))
    parser.add_argument("--out", type=Path, default=Path("series_reach.json"))
    args = parser.parse_args()
    series = read_series(args.dumps / "title.basics.tsv.gz", args.dumps / "title.ratings.tsv.gz")
    print(f"{len(series)} IMDb series with 50+ votes", flush=True)
    ebd = scan_ebd_series(args.root / "Data" / "raw" / "imdb_ebd" / "imdb_ebd.zip")
    print(f"{len(ebd)} series keys in ebD, {sum(ebd.values())} reviews", flush=True)

    # A key two IMDb series share cannot be told apart, so neither is linked.
    shared = Counter(film_key(str(s["title"]), int(str(s["year"]))) for s in series)
    table: dict[str, Counter[str]] = defaultdict(Counter)
    for s in series:
        key = film_key(str(s["title"]), int(str(s["year"])))
        # No Latin letters in the title: the key would be the bare year, which proves nothing.
        linkable = bool(title_key(str(s["title"]))) and shared[key] == 1
        reviews = ebd.get(key, 0) if linkable else 0
        group = "animation" if "Animation" in s["genres"] else "other"  # type: ignore[operator]
        for floor in VOTE_FLOORS:
            if int(str(s["votes"])) >= floor:
                bucket = table[f"{group}/votes>={floor}"]
                bucket["series"] += 1
                for need in REVIEW_FLOORS:
                    bucket[f"reviews>={need}"] += reviews >= need
    result = {
        "imdb_series_50_votes": len(series),
        "ebd_series_keys": len(ebd),
        "ebd_series_reviews": sum(ebd.values()),
        "ambiguous_keys": sum(1 for n in shared.values() if n > 1),
        "table": {k: dict(v) for k, v in sorted(table.items())},
    }
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["table"], indent=1), flush=True)


if __name__ == "__main__":
    main()
