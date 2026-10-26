"""The home page's shelves, built in one pass (docs/ROADMAP-2026-10-27.md, sections 8 and 15).

One request returns every row of films the page shows, in order, with no film on two rows. Before
this the page made one request per row, so twenty rows would have meant twenty requests against a
limit of 120 a minute, and the same film could appear on several rows. The shelves, in order:

* picks: the best films for this visitor; the first is the page's spotlight, the rest fill a row;
* similar: what viewers who liked the same films went on to like (needs at least one liked film);
* explore: well-reviewed films unlike the visitor's usual taste, so a new taste can find them;
* new (2021 onward) and classics (before 1990), each ranked for this visitor;
* one row per language the catalogue has enough films in, in a fixed order (English, Hindi,
  Japanese, French);
* one row per popular genre.

A shelf with fewer than `MIN_SHELF` films is left out rather than shown nearly empty. Every shelf
is filtered by the visitor's own language, genre and year choices. Nothing here trains or fits
anything (CONSTRAINTS.md #5).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Final

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict

from cinewhy.recsys.catalogue import Catalogue
from cinewhy.recsys.discover import (
    DiscoverItem,
    Scored,
    audience_popularity,
    audience_quality,
    catalogue_facets,
    score_films,
    select_items,
)
from cinewhy.schemas import TasteProfile

PICKS_SIZE: Final[int] = 16  # the spotlight film plus 15 for the row beneath it
SHELF_SIZE: Final[int] = 20
MIN_SHELF: Final[int] = 4
NEW_FROM_YEAR: Final[int] = 2021  # "New" means released in 2021 or later
OLD_TO_YEAR: Final[int] = 1989  # "Old school" means released before 1990
LANGUAGE_ORDER: Final[tuple[str, ...]] = ("en", "hi", "ja", "fr")
LANGUAGE_NAMES: Final[dict[str, str]] = {
    "en": "English",
    "hi": "Hindi",
    "ja": "Japanese",
    "fr": "French",
}
MIN_LANGUAGE_FILMS: Final[int] = 25  # fewer films than this and a language gets no shelf of its own
GENRE_SHELVES: Final[int] = 8
# Explore keeps films that are unlike the visitor's likes (similarity below this share of the
# maximum), well known (the better-known half) AND well liked (the top quarter by shrunk IMDb
# rating).
# Without the quality bar the shelf filled with famous but poorly rated films, under a heading that
# says "well reviewed".
EXPLORE_MAX_SIMILARITY: Final[float] = 0.5
EXPLORE_MIN_POPULARITY: Final[float] = 0.5
EXPLORE_MIN_QUALITY: Final[float] = 0.75  # quantile: films at or above it count as well liked


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Shelf(_Frozen):
    """One row of films with its heading."""

    id: str
    title: str
    subtitle: str
    items: tuple[DiscoverItem, ...]


class ShelvesResult(_Frozen):
    """Every shelf for one visitor, and which build produced them."""

    shelves: tuple[Shelf, ...]
    cold_start: bool
    manifest: str


def _later(*years: int | None) -> int | None:
    known = [y for y in years if y is not None]
    return max(known) if known else None


def _earlier(*years: int | None) -> int | None:
    known = [y for y in years if y is not None]
    return min(known) if known else None


def _explore_order(
    catalogue: Catalogue,
    liked: Sequence[int],
    popularity: npt.NDArray[np.float64],
    quality: npt.NDArray[np.float64],
) -> list[int]:
    """Film positions for the explore shelf: well liked, well known, unlike what was liked.

    A film's closeness to the visitor's taste is its mean item similarity to the liked films,
    scaled to 0..1. Films at or above `EXPLORE_MAX_SIMILARITY` of that, in the less-known half, or
    below the quality bar are not candidates; the rest are ranked by quality times popularity
    times the square of their distance from the taste.
    """
    closeness = catalogue.similarity[:, list(liked)].mean(axis=1).astype(np.float64)
    top = float(closeness.max())
    unit = closeness / top if top > 0 else np.zeros_like(closeness)
    known_cutoff = float(np.quantile(popularity, EXPLORE_MIN_POPULARITY))
    quality_cutoff = float(np.quantile(quality, EXPLORE_MIN_QUALITY))
    ranking = quality * popularity * (1.0 - unit) ** 2
    candidates = [
        i
        for i in range(len(catalogue.movies))
        if unit[i] < EXPLORE_MAX_SIMILARITY
        and popularity[i] >= known_cutoff
        and quality[i] >= quality_cutoff
    ]
    return sorted(candidates, key=lambda i: (-float(ranking[i]), i))


def build_shelves(
    catalogue: Catalogue,
    profile: TasteProfile,
    *,
    recency: float = 0.5,
    languages: Sequence[str] = (),
    genres: Sequence[str] = (),
    from_year: int | None = None,
    to_year: int | None = None,
    exclude: Collection[str] = (),
    manifest: str,
) -> ShelvesResult:
    """Build every shelf for one visitor.

    Deterministic: the same request gives the same shelves in the same order, so a reload does not
    reshuffle the page.

    Args:
        catalogue: The loaded catalogue.
        profile: What the visitor said they like; may be empty (a cold start).
        recency: 0 for no preference for new films, 1 for the strongest lift.
        languages: The visitor's language choice (empty means all); limits every shelf.
        genres: The visitor's genre choice (empty means all); limits every shelf.
        from_year: Earliest release year the visitor allows.
        to_year: Latest release year the visitor allows.
        exclude: Film ids never to show (the films the visitor has watched).
        manifest: Hash of the artifact set, echoed so a result can be traced to its build.

    Returns:
        The shelves, with each film on at most one of them; shelves that came out too short are
        left out, so the result may be empty when the visitor's filters match almost nothing.
    """
    blend = score_films(catalogue, profile, recency=recency)
    seen: set[str] = set(exclude) | set(profile.liked_movie_ids) | set(profile.disliked_movie_ids)
    shelves: list[Shelf] = []

    def add(
        shelf_id: str,
        title: str,
        subtitle: str,
        *,
        limit: int = SHELF_SIZE,
        scored: Scored = blend,
        shelf_languages: Sequence[str] = languages,
        shelf_genres: Sequence[str] = genres,
        lo: int | None = from_year,
        hi: int | None = to_year,
        order: Sequence[int] | None = None,
        minimum: int = MIN_SHELF,
    ) -> None:
        items = select_items(
            catalogue,
            scored,
            limit=limit,
            languages=shelf_languages,
            genres=shelf_genres,
            from_year=lo,
            to_year=hi,
            exclude=seen,
            order=order,
        )
        if len(items) < minimum:
            return
        seen.update(item.movie.movie_id for item in items)
        shelves.append(Shelf(id=shelf_id, title=title, subtitle=subtitle, items=items))

    cold = blend.cold
    add(
        "picks",
        "Tonight's picks" if cold else "Picked for you",
        "Well known and well liked, newest first"
        if cold
        else "Ranked by your taste, with the sentences behind each pick",
        limit=PICKS_SIZE,
        minimum=1,
    )

    liked = [catalogue.index[i] for i in profile.liked_movie_ids if i in catalogue.index]
    if liked:
        similar = score_films(catalogue, profile, recency=recency, mode="similar")
        add(
            "similar",
            "Viewers like you also watch",
            "Films that people who liked the same things went on to like",
            scored=similar,
        )
        add(
            "explore",
            "Something different",
            "Popular and well rated, but unlike what you usually pick",
            scored=similar,
            order=_explore_order(
                catalogue, liked, audience_popularity(catalogue), audience_quality(catalogue)
            ),
        )

    add(
        "new",
        "New and now" if cold else "New and matching your taste",
        f"Released in {NEW_FROM_YEAR} or later",
        lo=_later(from_year, NEW_FROM_YEAR),
    )
    add(
        "classics",
        "Old school favourites" if cold else "Old school, picked for you",
        f"Released before {OLD_TO_YEAR + 1}",
        hi=_earlier(to_year, OLD_TO_YEAR),
        scored=score_films(catalogue, profile, recency=0.0),
    )

    facets = catalogue_facets(catalogue)
    language_counts = facets["languages"]
    assert isinstance(language_counts, dict)
    for code in LANGUAGE_ORDER:
        enough = language_counts.get(code, 0) >= MIN_LANGUAGE_FILMS
        if enough and (not languages or code in languages):
            name = LANGUAGE_NAMES[code]
            add(
                f"lang-{code}",
                f"Best of {name}",
                f"{name} films, ranked for you",
                shelf_languages=[code],
            )

    if not genres:
        genre_counts = facets["genres"]
        assert isinstance(genre_counts, dict)
        for genre in list(genre_counts)[:GENRE_SHELVES]:
            add(
                f"genre-{genre}",
                f"Best of {genre}",
                f"{genre} films, ranked for you",
                shelf_genres=[genre],
            )

    return ShelvesResult(shelves=tuple(shelves), cold_start=cold, manifest=manifest)
