"""Text normalisation, shared by training and serving.

**This module is imported by both the offline training job and the request path.**
That is deliberate and load-bearing: a second copy of the cleaning logic is how
train/serve skew gets in, and the 2026-08-26 audit found the seed of exactly that bug
in the original notebook (FLOW.md §3, audit idea B-7). Never inline a variant of these
functions anywhere else.

Standard library only. The request path must not need nltk or a downloaded corpus, so
the stoplist is embedded below and stemming is not performed (DECISIONS.md D-010).

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

# NLTK's English stoplist, copied verbatim (198 words, nltk 3.9.4, 2026-09-29) instead of
# imported, so serving needs neither nltk nor its downloadable corpus. It still contains
# "not", "no" and "nor" and the negative contractions; `build_stoplist` is the only
# sanctioned way to consume it.
ENGLISH_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a", "about", "above", "after", "again", "against", "ain", "all", "am", "an", "and",
        "any", "are", "aren", "aren't", "as", "at", "be", "because", "been", "before", "being",
        "below", "between", "both", "but", "by", "can", "couldn", "couldn't", "d", "did",
        "didn", "didn't", "do", "does", "doesn", "doesn't", "doing", "don", "don't", "down",
        "during", "each", "few", "for", "from", "further", "had", "hadn", "hadn't", "has",
        "hasn", "hasn't", "have", "haven", "haven't", "having", "he", "he'd", "he'll", "he's",
        "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "i'd", "i'll",
        "i'm", "i've", "if", "in", "into", "is", "isn", "isn't", "it", "it'd", "it'll", "it's",
        "its", "itself", "just", "ll", "m", "ma", "me", "mightn", "mightn't", "more", "most",
        "mustn", "mustn't", "my", "myself", "needn", "needn't", "no", "nor", "not", "now", "o",
        "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out",
        "over", "own", "re", "s", "same", "shan", "shan't", "she", "she'd", "she'll", "she's",
        "should", "should've", "shouldn", "shouldn't", "so", "some", "such", "t", "than",
        "that", "that'll", "the", "their", "theirs", "them", "themselves", "then", "there",
        "these", "they", "they'd", "they'll", "they're", "they've", "this", "those", "through",
        "to", "too", "under", "until", "up", "ve", "very", "was", "wasn", "wasn't", "we",
        "we'd", "we'll", "we're", "we've", "were", "weren", "weren't", "what", "when", "where",
        "which", "while", "who", "whom", "why", "will", "with", "won", "won't", "wouldn",
        "wouldn't", "y", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
        "yourself", "yourselves",
    }
)  # fmt: skip

# Splitting on punctuation turns "didn't" into "didn" + "t", both of which are stopwords,
# so the negation vanishes even with `not` protected. Contractions are therefore expanded
# to a real "not" *before* punctuation is removed. The four stems below are irregular
# ("ca" + "n't" is not "can not"); everything else is `<verb>n't` and is handled by the
# general rule.
_IRREGULAR_NEGATIVE_STEMS: Final[dict[str, str]] = {
    "won": "will",
    "can": "can",
    "shan": "shall",
    "ain": "is",
}
_IRREGULAR_NEGATIVE: Final[re.Pattern[str]] = re.compile(r"\b(won|can|shan|ain)'t\b")
_REGULAR_NEGATIVE: Final[re.Pattern[str]] = re.compile(r"n't\b")

# Anything that is not a letter or digit. Unicode-aware on purpose: the notebook kept
# accented letters via str.isalnum, and dropping them would silently change the corpus.
_NON_ALNUM: Final[re.Pattern[str]] = re.compile(r"[\W_]+")


def strip_html(text: str) -> str:
    """Remove HTML tags, leaving their inner text.

    Args:
        text: Raw review text as scraped.

    Returns:
        The same text with tags removed.
    """
    return _HTML_TAG.sub("", text)


def build_stoplist(base: frozenset[str] | None = None) -> frozenset[str]:
    """Return a stoplist with every negation carrier removed.

    This is the single place the stoplist is constructed. Callers must not filter
    tokens against a raw NLTK stoplist.

    Args:
        base: Stoplist to start from. Defaults to NLTK's English list.

    Returns:
        `base` minus `NEGATION_TOKENS`.
    """
    return (ENGLISH_STOPWORDS if base is None else base) - NEGATION_TOKENS


_DEFAULT_STOPLIST: Final[frozenset[str]] = build_stoplist()


def normalise(text: str, *, stoplist: frozenset[str] | None = None) -> str:
    """Run the full cleaning pipeline over one document.

    The pipeline must be a pure function of its input: no module-level mutable state,
    no in-place mutation of a caller's dataframe. The original notebook mutated
    `df["review"]` through six sequential steps, which made re-running any single cell
    silently corrupt the corpus (FLOW.md §1).

    Whatever transformation is chosen, it must satisfy the guard in
    `tests/test_methodology.py::test_negation_survives_preprocessing`: two documents
    that differ only by a negation must not normalise to the same string.

    Steps: strip HTML, lowercase, expand negative contractions to `not`, replace every
    non-alphanumeric run with a space, drop stopwords. No stemming (DECISIONS.md D-010).

    Args:
        text: Raw document.
        stoplist: Tokens to drop. Defaults to `build_stoplist()`. A caller-supplied
            list is used as given, so build it with `build_stoplist` to keep negation.

    Returns:
        Normalised text, ready for a vectoriser.
    """
    words = _REGULAR_NEGATIVE.sub(
        " not",
        _IRREGULAR_NEGATIVE.sub(
            lambda m: f"{_IRREGULAR_NEGATIVE_STEMS[m.group(1)]} not",
            strip_html(text).lower().replace("’", "'"),  # noqa: RUF001 - typographic apostrophe
        ),
    )
    drop = _DEFAULT_STOPLIST if stoplist is None else stoplist
    return " ".join(t for t in _NON_ALNUM.sub(" ", words).split() if t not in drop)
