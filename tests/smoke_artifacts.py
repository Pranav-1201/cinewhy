"""Write a tiny, hash-verified artifact set for boot checks.

Usage: `python -m tests.smoke_artifacts --out DIR`.

The CI "docker" job boots the real image against this set. The real build is several hours of
work and 365 MB of data that CI cannot have, but a container only needs SOME verified artifacts to
prove the image starts, verifies a manifest, and answers requests. It is the same six-film set the
unit tests use (`tests/conftest.py`), so what CI boots is already covered by the suite.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from cinewhy.artifacts.manifest import build as build_manifest
from cinewhy.recsys.catalogue import RatingsOnlyFilm, write_catalogue
from cinewhy.schemas import Movie
from tests.conftest import _toy_polarity_model, make_catalogue


def _ratings_only_films(count: int) -> tuple[RatingsOnlyFilm, ...]:
    """`count` Japanese animation films with IMDb numbers but no reviews, years 1996 to 2015.

    Enough of them (the page needs 25 films in a language for its shelf) and old enough that the
    "new" shelf (2021 on) does not take them all first.
    """
    return tuple(
        RatingsOnlyFilm(
            movie=Movie(
                movie_id=f"ro-{n}",
                title=f"Anime film {n}",
                year=1996 + n % 20,
                genres=("Animation", "Drama") if n % 2 else ("Animation",),
            ),
            imdb_id=8_000_000 + n,
            language="ja",
            imdb_rating=6.0 + (n % 30) / 10,
            imdb_votes=5_000 + 700 * n,
            overview=f"A made-up film number {n}, for tests.",
            release_date=f"{1996 + n % 20}-04-01",
            runtime=90 + n % 40,
        )
        for n in range(count)
    )


def write_smoke_artifacts(out: Path, *, ratings_only: int = 0) -> Path:
    """Write the six-film artifact set into `out` (created if missing) and return it.

    `ratings_only` adds that many films we hold only ratings for (none by default, so the set the
    other tests pin is unchanged).
    """
    out.mkdir(parents=True, exist_ok=True)
    write_catalogue(out, replace(make_catalogue(), ratings_only=_ratings_only_films(ratings_only)))
    # Years and languages like the real build's meta.json, so the page's year bar, language shelves
    # and filters have something to work with. Written before the manifest, which hashes every file.
    years = (1975, 1988, 1995, 2004, 2012, 2023)
    meta = {
        f"cw-{n}": {
            "language": "hi" if n % 3 == 0 else "en",
            "release_date": f"{year}-06-01",
            "imdb_rating": 6.5 + n / 4,
            "imdb_votes": 20_000 * n,
        }
        for n, year in enumerate(years, start=1)
    }
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    _toy_polarity_model().save(out / "polarity.joblib")
    (out / "eval.json").write_text(json.dumps({"catalogue": {"films": 6}}), encoding="utf-8")
    build_manifest(out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ratings-only", type=int, default=0, help="also write this many films")
    args = parser.parse_args()
    written = write_smoke_artifacts(args.out, ratings_only=args.ratings_only)
    print(f"wrote smoke artifacts to {written}")


if __name__ == "__main__":
    main()
