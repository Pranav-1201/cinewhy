"""Pilot: how much review text does TMDB hold for the films we want to add? (roadmap F0).

Throwaway measurement script, not product code. The catalogue's review sources thin out after 2020
and barely reach Hindi, Telugu, Japanese or French films (docs/DATASET.md, roadmap sections 14 and
16). TMDB's `/movie/{id}/reviews` endpoint is the one candidate that is keyed by TMDB id (no title
join) and covers recent and non-English films. This asks it, for a small fixed sample per bloc, how
many reviews exist, how long they are and how new the newest is.

PASS RULE, written before any number exists: a bloc is usable as a Tier A source (50 or more
reviews per title) if at least 30% of its sampled films report 50 or more reviews; it adds useful
text if the median film has 5 or more. Anything less is reported as it is, not argued up.

    $env:TMDB_API_TOKEN = "<your TMDB v4 read access token>"        (PowerShell)
    python experiments/tmdb_reviews_pilot.py --dry-run     # prints the sample; no network, no token
    python experiments/tmdb_reviews_pilot.py               # about 80 requests, under 10 a second

The token is read from the environment and is never printed, logged or written to the result file.
TMDB's terms (non-commercial use with attribution) apply to anything this fetches; the review text
itself is not saved, only counts, lengths and dates.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

TOKEN_VARIABLE = "TMDB_API_TOKEN"
API = "https://api.themoviedb.org/3"
MIN_IMDB_VOTES = 1000
SEED = 42
PASS_SHARE_WITH_50 = 0.30
PASS_MEDIAN = 5

# bloc name: (original_language, first_year, last_year, how many films to sample)
BLOCS: dict[str, tuple[str, int, int, int]] = {
    "english_2021_2026": ("en", 2021, 2026, 15),
    "english_up_to_2010": ("en", 1950, 2010, 5),
    "hindi": ("hi", 1950, 2026, 15),
    "telugu": ("te", 1950, 2026, 10),
    "japanese": ("ja", 1950, 2026, 10),
    "french": ("fr", 1950, 2026, 10),
}


def choose_sample(csv_path: Path) -> dict[str, list[dict[str, Any]]]:
    """A fixed random sample of well-voted films per bloc (seeded, so the same films every run)."""
    columns = ["id", "title", "original_language", "release_date", "imdb_votes"]
    films = pd.read_csv(csv_path, usecols=columns, dtype={"original_language": "string"})
    films["year"] = pd.to_numeric(films["release_date"].astype("string").str[:4], errors="coerce")
    films = films[films["imdb_votes"].fillna(0) >= MIN_IMDB_VOTES]
    sample: dict[str, list[dict[str, Any]]] = {}
    for name, (language, first, last, size) in BLOCS.items():
        pool = films[(films["original_language"] == language) & films["year"].between(first, last)]
        picked = pool.sample(n=min(size, len(pool)), random_state=SEED).sort_values("id")
        sample[name] = [
            {
                "tmdb_id": int(r.id),
                "title": str(r.title),
                "year": int(r.year),
                "votes": int(r.imdb_votes),
            }
            for r in picked.itertuples()
        ]
    return sample


def fetch_reviews(tmdb_id: int, token: str) -> dict[str, Any] | None:
    """Page 1 of a film's reviews as TMDB reports it, or None if unknown or it keeps failing."""
    request = urllib.request.Request(
        f"{API}/movie/{tmdb_id}/reviews?page=1",
        headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)  # type: ignore[no-any-return]
        except urllib.error.HTTPError as err:
            if err.code == 429:  # too many requests: wait and try again
                time.sleep(2 * (attempt + 1))
                continue
            if err.code in (401, 403):
                raise SystemExit(
                    f"TMDB refused the token (HTTP {err.code}); nothing fetched"
                ) from None
            return None
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1 + attempt)
    return None


def summarise(counts: list[int], lengths: list[int], newest: list[str]) -> dict[str, Any]:
    """The numbers that decide the pass rule, for one bloc."""
    n = len(counts)
    return {
        "films_answered": n,
        "with_any_review": sum(c >= 1 for c in counts),
        "with_5_or_more": sum(c >= 5 for c in counts),
        "with_50_or_more": sum(c >= 50 for c in counts),
        "median_reviews": statistics.median(counts) if counts else None,
        "mean_chars_per_review": round(statistics.mean(lengths)) if lengths else None,
        "newest_review_date": max(newest) if newest else None,
        "share_with_50": round(sum(c >= 50 for c in counts) / n, 3) if n else None,
        "usable_as_tier_a": bool(n) and sum(c >= 50 for c in counts) / n >= PASS_SHARE_WITH_50,
        "adds_useful_text": bool(counts) and statistics.median(counts) >= PASS_MEDIAN,
    }


def main() -> None:
    """Choose the sample, then (unless --dry-run) ask TMDB about each film and print verdicts."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", type=Path, default=Path("Data/raw/tmdb1m/TMDB_all_movies.csv"))
    parser.add_argument("--out", type=Path, default=Path("tmdb_reviews_pilot.json"))
    parser.add_argument("--dry-run", action="store_true", help="show the sample, make no requests")
    args = parser.parse_args()

    sample = choose_sample(args.csv)
    if args.dry_run:
        for name, rows in sample.items():
            print(f"{name}: {len(rows)} films")
            for r in rows:
                print(
                    f"   tmdb {r['tmdb_id']:>8}  {r['year']}  {r['votes']:>8} votes  {r['title']}"
                )
        return

    token = os.environ.get(TOKEN_VARIABLE)
    if not token:
        sys.exit(
            f"Set {TOKEN_VARIABLE} to your TMDB v4 read access token first (see the docstring)."
        )
    result: dict[str, Any] = {
        "pass_rule": {"share_with_50": PASS_SHARE_WITH_50, "median": PASS_MEDIAN}
    }
    for name, rows in sample.items():
        counts: list[int] = []
        lengths: list[int] = []
        newest: list[str] = []
        for r in rows:
            page = fetch_reviews(r["tmdb_id"], token)
            time.sleep(0.12)  # stay well under TMDB's request ceiling
            if page is None:
                continue
            counts.append(int(page.get("total_results", 0)))
            for review in page.get("results", []):
                lengths.append(len(str(review.get("content", ""))))
                if review.get("created_at"):
                    newest.append(str(review["created_at"])[:10])
        result[name] = summarise(counts, lengths, newest)
        print(name, json.dumps(result[name]))
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
