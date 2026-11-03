"""People: who is billed in a title, finding a person by name, and a person's titles.

Everything here reads the catalogue's `cast` (see `cinewhy.data.cast`), which is None for a build
without a cast file; every function then answers "nobody" instead of failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from cinewhy.data.cast import TOP_BILLED
from cinewhy.recsys.catalogue import Catalogue
from cinewhy.recsys.rank import fold_accents

MIN_QUERY: Final[int] = 2  # a one-letter search would match nearly everyone


@dataclass(frozen=True)
class PersonHit:
    """A person found by name, with how many catalogue titles they are billed in."""

    person_id: int
    name: str
    titles: int


def imdb_number(movie_id: str) -> int | None:
    """The IMDb number inside a catalogue id (`cw-0000603` and `ro-0000603` are both 603)."""
    _prefix, _dash, digits = movie_id.partition("-")
    return int(digits) if digits.isdigit() else None


def imdb_positions(catalogue: Catalogue) -> dict[int, int]:
    """IMDb number to catalogue position, over both tiers. Kept on the catalogue."""

    def compute() -> dict[int, int]:
        found: dict[int, int] = {}
        for position, movie in enumerate(catalogue.all_movies):
            number = imdb_number(movie.movie_id)
            if number is not None:
                found[number] = position
        return found

    return catalogue.derived("imdb_positions", compute)


def cast_of(catalogue: Catalogue, movie_id: str, limit: int = TOP_BILLED) -> list[tuple[int, str]]:
    """The billed actors and actresses of a title as (person id, name), in billing order."""
    number = imdb_number(movie_id)
    if catalogue.cast is None or number is None:
        return []
    return [(p, catalogue.cast.people[p]) for p in catalogue.cast.titles.get(number, ())[:limit]]


def person_positions(catalogue: Catalogue, person_id: int) -> list[int]:
    """Catalogue positions of the titles a person is billed in, in position order."""
    if catalogue.cast is None:
        return []
    positions = imdb_positions(catalogue)
    return sorted(
        positions[number]
        for number in catalogue.cast.by_person.get(person_id, ())
        if number in positions
    )


def search_people(catalogue: Catalogue, query: str, limit: int = 8) -> list[PersonHit]:
    """People whose name matches: exact, then name prefix, then a word prefix, then every word.

    Accents are ignored on both sides ("zoe saldana" finds Zoë Saldaña). Within a kind of match,
    the person billed in more titles comes first, then the name, so the answer is stable.
    """
    cast = catalogue.cast
    wanted = fold_accents(query).strip()
    if cast is None or len(wanted) < MIN_QUERY:
        return []
    index = catalogue.derived(
        "people_index",
        lambda: [
            (fold_accents(name), person, len(cast.by_person.get(person, ())), name)
            for person, name in cast.people.items()
        ],
    )
    words = wanted.split()
    found: list[tuple[int, int, str, int]] = []
    for folded, person, credits, name in index:
        if wanted == folded:
            kind = 0
        elif folded.startswith(wanted):
            kind = 1
        elif f" {wanted}" in f" {folded}":
            kind = 2
        elif all(word in folded for word in words):
            kind = 3
        else:
            continue
        found.append((kind, -credits, name, person))
    found.sort()
    return [PersonHit(person, name, -negative) for _kind, negative, name, person in found[:limit]]
