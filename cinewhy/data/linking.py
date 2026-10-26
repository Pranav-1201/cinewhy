"""Title-and-year joins between TMDB films and sources that carry no film id.

Rotten Tomatoes and ebD (IMDb) identify a film only by title and year, so every match here is a
claim that can be wrong: a remake shares a title, a TV series shares a title and a year, two TMDB
films can collide on one key. The rules below are the measured defence (FEATURE-004): an exact
year first, an adjacent year for English only, a runtime cross-check wherever both sides have
one, and refusal, never a guess, when a key is ambiguous.

Pure functions only. Nothing here reads a file; the readers in `cinewhy.data.reviews` do.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

# Agreement between two runtime listings of the SAME film is loose (director's cuts, rounding,
# theatrical vs home video: Arizona Dream 142 vs 119). 15 minutes keeps those and rejects the
# 40-minute gaps that mean a different film. Measured on 5,629 English matches (D-016).
RUNTIME_TOLERANCE_MINUTES: Final[float] = 15.0

_NON_ALNUM: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]")
# A film is "Title (YYYY)" and nothing after the year. Series ("(1968- )", "(2009-2013)") and
# "(2009 Video)" fail this on purpose: the loose form matched series and inflated English text
# counts by about 5.5%.
_EBD_FILM: Final[re.Pattern[str]] = re.compile(r"^(.*) \((\d{4})\)$")

MatchStatus = Literal["exact", "adjacent", "none", "ambiguous", "runtime_rejected"]


@dataclass(frozen=True)
class Candidate:
    """A TMDB film we want reviews for."""

    imdb_id: int
    title: str
    year: int
    language: str
    runtime: float


@dataclass(frozen=True)
class MatchResult[T]:
    """Outcome of one join attempt; `item` is set only for `exact` and `adjacent`."""

    status: MatchStatus
    item: T | None = None


def title_key(title: str) -> str:
    """Lowercase letters and digits only, so punctuation and spacing never break a join."""
    return _NON_ALNUM.sub("", title.lower())


def film_key(title: str, year: int) -> str:
    """The join key for a film: normalised title followed by its four-digit year."""
    return f"{title_key(title)}{year}"


def parse_ebd_movie(raw: str) -> tuple[str, int] | None:
    """Split an ebD `movie` field into title and year, or None if it is not a plain film.

    Args:
        raw: e.g. `"Kill Bill: Vol. 2 (2004)"`; a series carries an open year range after
            the title instead of a single year.

    Returns:
        `("Kill Bill: Vol. 2", 2004)` for a film; None for a series, a video release, or a
        string with no year.
    """
    found = _EBD_FILM.match(raw)
    return (found.group(1), int(found.group(2))) if found else None


def runtimes_agree(a: float | None, b: float | None, tolerance: float) -> bool:
    """True when two runtimes (minutes) are within `tolerance`, or either is unknown.

    Unknown (None or not positive) carries no evidence, so it can neither confirm nor reject.
    """
    if a is None or b is None or a <= 0 or b <= 0:
        return True
    return abs(a - b) <= tolerance


def _known(runtime: float | None) -> bool:
    return runtime is not None and runtime > 0


def match_film[T](
    candidate: Candidate,
    index: Mapping[str, Sequence[T]],
    runtime_of: Callable[[T], float | None],
    *,
    tolerance: float = RUNTIME_TOLERANCE_MINUTES,
) -> MatchResult[T]:
    """Find the one source record for a TMDB film, or say why there is none.

    Order: the exact year; then, for English only, the year before and after. Hindi adjacent
    years agreed with runtime only 57.9% of the time (n=19) against 79.5% for exact years, so
    they are not trusted. An adjacent-year hit is accepted only when both runtimes are known and
    agree. The first usable year decides: a hit that is ambiguous or fails the runtime check ends
    the search rather than falling through to a looser year.

    Args:
        candidate: The film to look up.
        index: Source records grouped by `film_key`.
        runtime_of: Runtime in minutes of a source record, None when it has none.
        tolerance: Largest accepted runtime gap in minutes.

    Returns:
        The match, with `status` recording which rule decided.
    """
    if not title_key(candidate.title):
        # No Latin letters or digits survive (kana, Devanagari): the key would be the bare year and
        # match whichever source record of that year is also stemless. No evidence, so no link.
        return MatchResult("none")
    offsets = (0, -1, 1) if candidate.language == "en" else (0,)
    for offset in offsets:
        hits = index.get(film_key(candidate.title, candidate.year + offset))
        if not hits:
            continue
        if len(hits) > 1:
            return MatchResult("ambiguous")
        source_runtime = runtime_of(hits[0])
        if offset != 0 and not (_known(candidate.runtime) and _known(source_runtime)):
            # Nothing to confirm a different-year hit against (ebD has no runtime): a title that
            # merely recurs a year apart, like a remake, would be accepted blind.
            continue
        if not runtimes_agree(candidate.runtime, source_runtime, tolerance):
            return MatchResult("runtime_rejected")
        return MatchResult("exact" if offset == 0 else "adjacent", hits[0])
    return MatchResult("none")


def ambiguous_candidate_keys(candidates: Iterable[Candidate]) -> set[str]:
    """Keys shared by more than one candidate: a source record could belong to either.

    The caller drops these candidates from title-based joins; guessing which film a review
    belongs to would put reviews on the wrong film, silently.
    """
    counts = Counter(film_key(c.title, c.year) for c in candidates)
    return {key for key, n in counts.items() if n > 1}
