"""Aspect-based sentiment extraction — the component the product is built on.

Given review text for a film, decide which aspects each sentence talks about and how
positively. The output is `MovieAspectProfile` plus the `EvidenceSentence` objects the
UI quotes verbatim.

The IMDB 50k corpus trains the polarity half of this. It cannot supply the other half:
it has no movie identifiers (DECISIONS.md D-002), so aspect scores can only be attached
to films once Phase D lands an item-keyed corpus.

Phase C/D boundary. Owner: see CONTRIBUTING.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Final

from cinewhy.schemas import Aspect, EvidenceSentence, MovieAspectProfile
from cinewhy.text import strip_html

# A boundary is sentence-ending punctuation, whitespace, then something that can start a
# sentence. Requiring a capital or digit next keeps "e.g. this" and "wait... what" whole.
_SENTENCE_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]*[A-Z0-9])")

# Pieces that end in one of these are glued to the next piece: a period after them is not
# a sentence end. "etc." is deliberately absent because it usually is one.
_ABBREVIATIONS: Final[frozenset[str]] = frozenset(
    {"mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "vs.", "jr.", "sr.", "e.g.", "i.e."}
)
_INITIAL: Final[re.Pattern[str]] = re.compile(r"[A-Z]\.")

# Whole-word lexicon per aspect, written as regex fragments. This is a baseline: it is
# precise where it fires and blind everywhere else, and NO precision or recall has been
# measured because the repository holds no aspect-labelled sentences. Known false
# positives: "score" also means a rating, "cast" can be a verb. Replace with a trained
# detector only after a hand-labelled sample exists to compare against (Phase C).
_ASPECT_PATTERNS: Final[dict[Aspect, re.Pattern[str]]] = {
    aspect: re.compile(r"\b(?:" + "|".join(fragments) + r")\b", re.IGNORECASE)
    for aspect, fragments in {
        Aspect.ACTING: (
            "acting", "actors?", "actress(?:es)?", "cast(?:ing)?", "performances?",
            "performers?", "portrayal", "portrayed",
        ),
        Aspect.PLOT: (
            "plots?", "story(?:lines?)?", "script", "screenplay", "twists?", "narrative",
            "dialogues?", "writing",
        ),
        Aspect.PACING: (
            "pacing", "pace", "paced", "drag(?:s|ged|ging)?", "slow(?:ly)?", "rushed",
            "tempo", "runtime", r"too\s+long",
        ),
        Aspect.VISUALS: (
            "visuals?", "cinematograph(?:y|er)", "cgi", "scenery", "camerawork", "animation",
            "costumes?", "photography", r"(?:special\s+)?effects", r"set\s+design",
        ),
        Aspect.ENDING: ("endings?", "finale", "climax", "conclusion"),
        Aspect.SOUNDTRACK: (
            "soundtracks?", "score", "music", "songs?", "composer", r"sound\s+design",
        ),
        Aspect.REWATCHABILITY: (
            "rewatch(?:ed|ing|able)?",
            r"watch(?:ed|ing)?\s+(?:it\s+|this\s+|that\s+)?(?:again|twice)",
            r"second\s+viewing", r"multiple\s+(?:viewings|times)", r"again\s+and\s+again",
        ),
    }.items()
}  # fmt: skip


def split_sentences(document: str) -> list[str]:
    """Split a review into candidate sentences.

    Aspect scoring is per sentence, not per review: one review routinely praises the
    acting and criticises the pacing, and collapsing it to a single document-level
    polarity throws away exactly the signal this product sells.

    Args:
        document: One full review.

    Returns:
        Sentences in source order. Never empty for non-empty input.
    """
    # Tags become spaces, not nothing: "It ends.<br /><br />The next" would otherwise
    # lose the whitespace that marks the boundary and fuse into one sentence.
    text = strip_html(document, replacement=" ").strip()
    sentences: list[str] = []
    for piece in _SENTENCE_BOUNDARY.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)
    return sentences


def _ends_with_abbreviation(sentence: str) -> bool:
    """True when the last token is an abbreviation or an initial, not a sentence end."""
    last = sentence.rsplit(None, 1)[-1]
    return last.lower() in _ABBREVIATIONS or _INITIAL.fullmatch(last) is not None


def detect_aspects(sentence: str) -> frozenset[Aspect]:
    """Return the aspects a sentence is talking about.

    May return an empty set — most sentences in a review are plot summary or
    throat-clearing and belong to no aspect. Returning nothing is the correct answer
    far more often than not, and forcing an assignment is how the evidence panel fills
    with irrelevant quotes.

    Args:
        sentence: One sentence.

    Returns:
        Zero or more aspects.
    """
    return frozenset(
        aspect for aspect, pattern in _ASPECT_PATTERNS.items() if pattern.search(sentence)
    )


def score_polarity(sentence: str) -> float:
    """Score one sentence from -1 (negative) to +1 (positive).

    Must be trained and evaluated under the methodology rules: fit on train only,
    select on cross-validation, report with spread (CONSTRAINTS.md #1-#3).

    Args:
        sentence: One sentence.

    Returns:
        Polarity in [-1.0, 1.0].
    """
    raise NotImplementedError("Phase C")


def build_profile(
    movie_id: str,
    reviews: Iterable[tuple[str, str]],
    *,
    min_support: int = 3,
) -> tuple[MovieAspectProfile, Sequence[EvidenceSentence]]:
    """Aggregate per-sentence judgements into one film's aspect profile.

    Aspects with fewer than `min_support` supporting sentences are dropped rather than
    reported with a wide error bar the UI has no room to show. A missing aspect renders
    as "not enough reviews mention this", which is honest; a score computed from one
    sentence rendered identically to one computed from four hundred is not.

    Args:
        movie_id: CineWhy internal id.
        reviews: Pairs of (review_id, review_text).
        min_support: Minimum supporting sentences for an aspect to be reported.

    Returns:
        The profile, and the evidence sentences selected to justify it.
    """
    raise NotImplementedError("Phase D")
