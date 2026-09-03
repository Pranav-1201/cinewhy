"""Text normalisation, shared by training and serving.

**This module is imported by both the offline training job and the request path.**
That is deliberate and load-bearing: a second copy of the cleaning logic is how
train/serve skew gets in, and the 2026-08-26 audit found the seed of exactly that bug
in the original notebook (FLOW.md §3, audit idea B-7). Never inline a variant of these
functions anywhere else.

Phase C owner: whoever takes the methodology repair. See CONTRIBUTING.md.
"""

from __future__ import annotations

import re
from typing import Final

# Matches an HTML tag. The source corpus is scraped review text; 29,200 of the 50,000
# IMDB rows contain a literal "<br" (measured 2026-08-26).
_HTML_TAG: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")

# Negation carriers that must survive preprocessing.
#
# NLTK's English stoplist contains "not", "no" and "nor". Removing them destroyed the
# only signal that distinguishes "not good" from "good": both reduced to 'movi good',
# produced byte-identical TF-IDF vectors, and received the same prediction. This set is
# subtracted from whatever stoplist is used. See DECISIONS.md D-003.
NEGATION_TOKENS: Final[frozenset[str]] = frozenset(
    {"not", "no", "nor", "never", "none", "cannot", "n't", "without", "neither"}
)


def strip_html(text: str) -> str:
    """Remove HTML tags, leaving their inner text.

    Args:
        text: Raw review text as scraped.

    Returns:
        The same text with tags removed.
    """
    raise NotImplementedError("Phase C")


def build_stoplist(base: frozenset[str] | None = None) -> frozenset[str]:
    """Return a stoplist with every negation carrier removed.

    This is the single place the stoplist is constructed. Callers must not filter
    tokens against a raw NLTK stoplist.

    Args:
        base: Stoplist to start from. Defaults to NLTK's English list.

    Returns:
        `base` minus `NEGATION_TOKENS`.
    """
    raise NotImplementedError("Phase C")


def normalise(text: str, *, stoplist: frozenset[str] | None = None) -> str:
    """Run the full cleaning pipeline over one document.

    The pipeline must be a pure function of its input: no module-level mutable state,
    no in-place mutation of a caller's dataframe. The original notebook mutated
    `df["review"]` through six sequential steps, which made re-running any single cell
    silently corrupt the corpus (FLOW.md §1).

    Whatever transformation is chosen, it must satisfy the guard in
    `tests/test_methodology.py::test_negation_survives_preprocessing`: two documents
    that differ only by a negation must not normalise to the same string.

    Args:
        text: Raw document.
        stoplist: Tokens to drop. Defaults to `build_stoplist()`.

    Returns:
        Normalised text, ready for a vectoriser.
    """
    raise NotImplementedError("Phase C")
