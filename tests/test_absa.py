"""Behaviour of `split_sentences` and `detect_aspects`.

The contract tests only say these functions exist and honour their types. These pin what
they actually do. Expected values were derived by hand from the rules in the module.

They say nothing about how *accurate* aspect detection is: no aspect-labelled sentences
exist in this repository, so no precision or recall has been measured (see the comment
above the lexicon in `cinewhy/absa/extract.py`).
"""

from __future__ import annotations

import pytest

from cinewhy.absa import detect_aspects, split_sentences
from cinewhy.schemas import Aspect
from cinewhy.text import strip_html

pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (
            "The pacing dragged. The ending saved it.",
            ["The pacing dragged.", "The ending saved it."],
        ),
        ("Is it good? Yes! Absolutely.", ["Is it good?", "Yes!", "Absolutely."]),
        # HTML breaks are boundaries: deleting the tags would fuse these two sentences.
        ("Loved it!<br /><br />Would watch again.", ["Loved it!", "Would watch again."]),
        # Abbreviations and initials are not sentence ends.
        (
            "Dr. Smith was superb. The rest was fine.",
            ["Dr. Smith was superb.", "The rest was fine."],
        ),
        ("Directed by J. K. Smith. Great film.", ["Directed by J. K. Smith.", "Great film."]),
        ("Try e.g. this one. Then leave.", ["Try e.g. this one.", "Then leave."]),
        # An ellipsis followed by a capital ends a sentence; followed by lowercase it does not.
        ("It was slow... The end came.", ["It was slow...", "The end came."]),
        ("Wait... what happened here?", ["Wait... what happened here?"]),
        ("I gave it 10/10. Great.", ["I gave it 10/10.", "Great."]),
        ("No terminal punctuation", ["No terminal punctuation"]),
    ],
)
def test_split_sentences(document: str, expected: list[str]) -> None:
    assert split_sentences(document) == expected


@pytest.mark.parametrize("document", ["", "   ", "<br />", "<br /><br />"])
def test_nothing_to_split_gives_an_empty_list(document: str) -> None:
    assert split_sentences(document) == []


def test_sentences_are_verbatim_slices_of_the_document() -> None:
    """The UI quotes these; a sentence that is not in the source would be a fabrication."""
    document = "Slow start.<br />Great middle! Did the ending work?  Mostly."
    visible = strip_html(document, replacement=" ")
    sentences = split_sentences(document)
    assert len(sentences) == 4
    assert all(s in visible for s in sentences)
    assert visible.index(sentences[0]) < visible.index(sentences[-1])


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("The soundtrack was extraordinary.", {Aspect.SOUNDTRACK}),
        ("Great acting but the ending was weak.", {Aspect.ACTING, Aspect.ENDING}),
        ("The pacing dragged badly.", {Aspect.PACING}),
        ("The runtime is too long.", {Aspect.PACING}),
        ("The cinematography is stunning.", {Aspect.VISUALS}),
        ("The plot twists were brilliant.", {Aspect.PLOT}),
        ("I could watch it again and again.", {Aspect.REWATCHABILITY}),
        ("Worth a second viewing.", {Aspect.REWATCHABILITY}),
        ("Watched it twice.", {Aspect.REWATCHABILITY}),
        ("SOUNDTRACK ROCKS", {Aspect.SOUNDTRACK}),
    ],
)
def test_detect_aspects_finds_the_named_aspects(sentence: str, expected: set[Aspect]) -> None:
    assert detect_aspects(sentence) == frozenset(expected)


@pytest.mark.parametrize(
    "sentence",
    [
        "I watched this on a Tuesday.",
        "I watched it.",
        # Whole words only: none of these contains a lexicon word as a word.
        "The scoreboard broke.",
        "He typecast the broadcast.",
        "They were plotting.",
        "",
    ],
)
def test_most_sentences_belong_to_no_aspect(sentence: str) -> None:
    assert detect_aspects(sentence) == frozenset()


def test_detect_aspects_returns_a_frozenset() -> None:
    assert isinstance(detect_aspects("The acting was good."), frozenset)
