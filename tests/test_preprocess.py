"""Behaviour of `cinewhy.text.preprocess` beyond the three audit guards.

The guards in `test_methodology.py` say negation must survive. These pin *how*: which
contraction forms are expanded, which words are kept, and that the embedded stoplist is
still the list it claims to be. Expected strings were derived by hand from the rules in
the module, not copied from the function's own output.
"""

from __future__ import annotations

import pytest

from cinewhy.text import NEGATION_TOKENS, build_stoplist, normalise, strip_html
from cinewhy.text.preprocess import ENGLISH_STOPWORDS

pytestmark = pytest.mark.methodology


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Regular n't: "didn" + "t" are both stopwords, so without expansion the
        # negation would be lost even though `not` is protected.
        ("I didn't like it.", "not like"),
        ("It isn't good.", "not good"),
        # Irregular stems: "ca" + "n't" would give "ca not".
        ("I can't stand it.", "not stand"),
        ("It won't end.", "not end"),
        ("It ain't good.", "not good"),
        # Typographic apostrophe, and case.
        ("It isn’t good.", "not good"),  # noqa: RUF001 - the curly apostrophe is the point
        ("IT ISN'T GOOD", "not good"),
        # Every other negation carrier survives as a token.
        ("I cannot recommend it.", "cannot recommend"),
        ("Never again.", "never"),
        ("A film without heart.", "film without heart"),
        ("Neither good nor bad.", "neither good nor bad"),
        ("No plot, no point.", "no plot no point"),
    ],
)
def test_negation_forms_are_kept_and_contractions_expanded(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Great film.<br /><br />Loved it.", "great film loved"),
        ("Café was très bien", "café très bien"),
        ("10/10 would watch again", "10 10 would watch"),
        ("", ""),
        ("<br />", ""),
    ],
)
def test_html_unicode_digits_and_empty_input(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "This movie was not good at all.",
        "I didn't like it, and I can't say I'd watch it again.",
        "Great film.<br /><br />Loved it.",
        "No plot, no point, never again.",
    ],
)
def test_normalise_is_idempotent(raw: str) -> None:
    """Running it twice must equal running it once, or re-cleaning a stored corpus drifts."""
    once = normalise(raw)
    assert normalise(once) == once


def test_a_caller_supplied_stoplist_is_used_as_given() -> None:
    assert normalise("a b c", stoplist=frozenset({"b"})) == "a c"


def test_strip_html_keeps_inner_text_and_leaves_plain_text_alone() -> None:
    assert strip_html("<b>bold</b> text") == "bold text"
    assert strip_html("no tags here") == "no tags here"


def test_build_stoplist_subtracts_negation_from_any_base() -> None:
    base = frozenset({"not", "the", "zebra", "nor"})
    assert build_stoplist(base) == frozenset({"the", "zebra"})


def test_embedded_stoplist_is_the_recorded_nltk_list() -> None:
    """Pins provenance: 198 words copied from nltk 3.9.4, of which 3 are negation."""
    assert len(ENGLISH_STOPWORDS) == 198
    assert frozenset({"not", "no", "nor"}) == ENGLISH_STOPWORDS & NEGATION_TOKENS
    assert len(build_stoplist()) == 195
