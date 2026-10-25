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

import os
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from cinewhy.schemas import Aspect, AspectScore, EvidenceSentence, MovieAspectProfile
from cinewhy.text import strip_html

if TYPE_CHECKING:  # imported lazily at call time: sklearn is not needed to split sentences
    pass


class PolarityScorer(Protocol):
    """Anything that turns clauses into polarities in [-1, 1].

    `PolarityModel` is the production implementation; tests pass a tiny stand-in so the
    aggregation logic is checkable without a trained model.
    """

    def score_many(self, texts: Sequence[str]) -> list[float]:
        """Score each text from -1 (negative) to +1 (positive)."""
        ...


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
        # "cast" as a passive verb ("Fonda was cast in the original") is not about acting.
        # Every pattern below the first group earned its place by uniquely recovering at least
        # one real mention, and adding no false flag, on the dev samples (DECISIONS D-015).
        Aspect.ACTING: (
            "acting", "actors?", "actress(?:es)?", "performances?", "performers?", "portrayal",
            "portrayed",
            r"(?<!was\s)(?<!were\s)(?<!been\s)(?<!be\s)(?<!is\s)(?<!get\s)cast(?:ing)?",
            r"support\s+from", r"pulled\s+(?:it|that|this)?\s*off",
            r"play(?:s|ed|ing)?\s+(?:the\s+)?(?:role|roll|part)",
            r"(?:girl|boy|man|woman|actor|actress|guy|lady|kid|child)\s+playing",
            r"(?:convincing|believable|hilarious|enjoyable|sincere|dependable|wonderful|great"
            r"|superb|terrific|excellent|awful|terrible|wooden)\s+as\b",
            r"(?:screen\s+)?presence", r"(?:can|can't|cannot|couldn't|could)\s+act",
            r"(?:well|brilliantly|beautifully|superbly|perfectly)\s+(?:played|cast|acted)",
        ),
        Aspect.PLOT: (
            "plots?", "story(?:lines?)?", "script", "screenplay", "twists?", r"narrativ(?:e|ly)",
            "dialogues?", "writing",
            "premise", "subplots?", r"events\s+in\s+(?:this|the)\s+(?:film|movie)",
            r"what\s+(?:this|the)\s+(?:movie|film)\s+was\s+about",
            r"(?:best|great|good|bad|worst|memorable)\s+lines",
        ),
        # Bare "drag" and "slowly" were the main false positives (drag queens, "slowly loses
        # it"), and "change of pace" is an idiom. Each is now tied to the film or its tempo.
        Aspect.PACING: (
            "pacing", r"(?<!of\s)pace", "paced", "draggy", "slow", "rushed", "tempo", "runtime",
            r"too\s+long", r"drag(?:s|ged|ging)?\s+(?:on|out|down|badly|a\s+lot|a\s+bit)",
            r"(?:it|film|movie|story|plot|part|half|hour|middle|act|second|third)\s+drag(?:s|ged|ging)?",
            r"(?:moves|runs|unfolds|progresses|builds)\s+(?:very\s+|so\s+|too\s+)?slowly",
            r"dull\s+stretch(?:es)?", "tedious", "momentum", r"kept\s+waiting",
        ),
        # "effects of tradition" is not special effects; require a visual qualifier.
        Aspect.VISUALS: (
            "visuals?", "cinematograph(?:y|er)", "cgi", "scenery", "camerawork", "animation",
            "costumes?", "photography", r"(?:special|visual|digital|computer|practical)\s+effects?",
            r"effects\s+(?:are|were|was|look|looked|work|worked)", r"set\s+design",
            r"picture\s+quality", r"blue\s?screen", r"fashions?", r"production\s+values?",
            "artwork", r"well[-\s]shot", r"(?:production\s+)?sets\b", r"low[-\s]budget",
            r"visually\s+\w+", r"underwater\s+scenes",
        ),
        # `(?<!-)` keeps "never-ending" out; "in conclusion" is a discourse marker.
        Aspect.ENDING: (
            r"(?<!-)endings?", "finale", "climax", r"(?<!in\s)conclusion",
            r"(?:final|last)\s+(?:scene|act|minutes|twist|sequence)",
        ),
        # Bare "score" also means a rating ("a score of 4"), so it needs a music context.
        Aspect.SOUNDTRACK: (
            "soundtracks?", "music", "songs?", "composer", r"sound\s+design", "hymn",
            r"(?:music|musical|original|film|movie)\s+score",
            r"(?:the|its)\s+score(?!\s*(?:of|board))",
        ),
        # Standalone "again and again" described anything repeated ("killed again and again").
        Aspect.REWATCHABILITY: (
            "rewatch(?:ed|ing|able)?",
            r"(?:watch|see|seen|view)(?:ed|ing)?\s+(?:it\s+|this\s+|that\s+|the\s+(?:movie|film)\s+)?(?:again|twice)",
            r"(?:watch|see|seen)(?:ed|ing)?\s+(?:it\s+)?(?:a\s+(?:few|couple)\s+(?:of\s+)?times|multiple\s+times)",
            r"second\s+viewing", r"multiple\s+viewings", r"second\s+(?:and\s+third\s+)?time",
            r"(?:watch|see)(?:ing)?\s+(?:it\s+|this\s+|that\s+)?(?:a\s+)?(?:second|third)",
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


# A contrast marker separates two opinions that often concern different aspects: "The acting
# was great but the plot dragged." Splitting there lets each aspect take its own polarity
# instead of both inheriting one blended score. "while" is deliberately absent: it is
# mostly temporal ("while watching"), not contrastive.
_CONTRAST: Final[re.Pattern[str]] = re.compile(
    r"\s*(?:;|,?\s+\b(?:but|however|although|though|yet|whereas)\b,?)\s+", re.IGNORECASE
)
_MIN_CLAUSE_WORDS: Final[int] = 3


def split_clauses(sentence: str) -> list[str]:
    """Split a sentence at contrast markers into clauses that can be scored separately.

    Every returned clause is a verbatim substring of the input, so it can be quoted as
    evidence without paraphrase (CONSTRAINTS.md #9). A split is only made when both sides
    keep at least three words; "Good, but." stays whole.

    Args:
        sentence: One sentence.

    Returns:
        One or more clauses in source order. Never empty for non-empty input.
    """
    text = sentence.strip()
    # Work in character spans of the ORIGINAL text. Merging a too-short piece back into its
    # neighbour by re-joining strings would drop the separator that was removed between
    # them, and the result would no longer be a quotable substring.
    spans: list[tuple[int, int]] = []
    start = 0
    for marker in _CONTRAST.finditer(text):
        spans.append((start, marker.start()))
        start = marker.end()
    spans.append((start, len(text)))

    merged: list[tuple[int, int]] = []
    for span in spans:
        if merged and (
            len(text[span[0] : span[1]].split()) < _MIN_CLAUSE_WORDS
            or len(text[merged[-1][0] : merged[-1][1]].split()) < _MIN_CLAUSE_WORDS
        ):
            merged[-1] = (merged[-1][0], span[1])
        else:
            merged.append(span)
    return [c for s, e in merged if (c := text[s:e].strip())] or [text]


_default_model: PolarityScorer | None = None


def default_polarity_model() -> PolarityScorer:
    """Load the production polarity model once.

    The path comes from `CINEWHY_POLARITY_MODEL`, falling back to
    `artifacts/polarity.joblib`. The file is a joblib pickle, so it must only ever come
    from the artifact directory whose hashes `cinewhy.artifacts.verify` has just checked;
    the API enforces that order at boot.

    Raises:
        FileNotFoundError: If no model has been built. Run
            `python -m cinewhy.absa.polarity` first.
    """
    global _default_model
    if _default_model is None:
        from cinewhy.absa.polarity import PolarityModel

        path = Path(os.environ.get("CINEWHY_POLARITY_MODEL", "artifacts/polarity.joblib"))
        if not path.is_file():
            raise FileNotFoundError(
                f"no polarity model at {path}; run `python -m cinewhy.absa.polarity`"
            )
        _default_model = PolarityModel.load(path)
    return _default_model


def score_polarity(sentence: str, *, model: PolarityScorer | None = None) -> float:
    """Score one sentence from -1 (negative) to +1 (positive).

    Trained and evaluated under the methodology rules in `cinewhy.absa.polarity`.

    Args:
        sentence: One sentence or clause.
        model: Scorer to use. Defaults to the production model.

    Returns:
        Polarity in [-1.0, 1.0]; 0.0 when the text has too little content to judge.
    """
    return (model or default_polarity_model()).score_many([sentence])[0]


# Negators that flip a rewatch statement: "I'd not watch it again", "isn't anything I'd watch".
_NEGATOR: Final[re.Pattern[str]] = re.compile(
    r"\b(?:not|never|no|neither|nor|hardly)\b|n't\b", re.I
)
_REWATCH_STRENGTH: Final[float] = 0.8
# Below this absolute polarity a clause is treated as not judging the aspect at all.
MIN_OPINION: Final[float] = 0.2


def aspect_polarity(aspect: Aspect, clause: str, model_score: float) -> float:
    """Polarity of a clause with respect to one aspect.

    For most aspects this is the polarity model's score. Rewatchability is the exception:
    "I would watch it again" carries no review-level sentiment vocabulary (normalisation
    even drops "again" as a stopword and leaves the model nothing to score), yet it is a
    clear statement. It is read by rule: positive unless the clause negates it.

    Args:
        aspect: The aspect the clause was flagged for.
        clause: The clause text.
        model_score: The polarity model's score for the clause.

    Returns:
        Polarity in [-1.0, 1.0].
    """
    if aspect is Aspect.REWATCHABILITY:
        return -_REWATCH_STRENGTH if _rewatch_is_negated(clause) else _REWATCH_STRENGTH
    return apply_cues(clause, model_score)


# Words that settle the polarity of a short clause where a model trained on whole reviews is
# unreliable: it learned that "entertainment" means praise, so "too long for a night's
# entertainment" scored +0.86, and it reads "aren't terrible" as strongly negative.
_NEG_CUES: Final[re.Pattern[str]] = re.compile(
    r"\b(?:too\s+(?:long|slow|rushed|short|loud)|dragg(?:s|ed|ing|y)|tedious|plodding|glacial"
    r"|lack(?:s|ed|ing)?|inconclusive|puzzling|confusing|abrupt|let\s?down|dated|dodgy|cheesy"
    r"|cheap|poor(?:ly)?|weak|mediocre|wooden|bland|forgettable|uninspired|predictable"
    r"|ridiculous|silly|non-?existent|awful|terrible|horrible|boring|dull|lame|annoying"
    r"|irritating|bad(?:ly)?|worst|out\s+of\s+place|overdone|overrated)\b",
    re.IGNORECASE,
)
_POS_CUES: Final[re.Pattern[str]] = re.compile(
    r"\b(?:perfect(?:ly)?|brilliant|excellent|superb|stunning|beautiful(?:ly)?|memorable"
    r"|wonderful(?:ly)?|amazing|fantastic|gripping|tight|crisp|moving|touching|impressive"
    r"|great|best|gorgeous|masterful|terrific|top-?notch)\b",
    re.IGNORECASE,
)
_CUE_STRENGTH: Final[float] = 0.4
_NEGATION_WINDOW: Final[int] = 3


def apply_cues(clause: str, model_score: float) -> float:
    """Correct the model's score when explicit cue words say the opposite.

    Each cue word votes for its own polarity, flipped when a negator sits within three
    words before it ("not terrible" is mildly positive; "not great" is mildly negative).
    The model's score is kept when there are no cues, when positive and negative cues
    cancel (a mixed clause), or when the cues agree with the model. When the cues disagree
    with the model, the cues win and the score becomes a mild +-0.4: we trust the
    direction, not the magnitude.

    Args:
        clause: The clause text.
        model_score: The polarity model's score for it.

    Returns:
        The corrected polarity in [-1.0, 1.0].
    """
    net = 0
    for pattern, sign in ((_NEG_CUES, -1), (_POS_CUES, 1)):
        for found in pattern.finditer(clause):
            lead = _CLAUSE_BREAK.split(clause[: found.start()])[-1]
            negated = bool(_NEGATOR.search(" ".join(lead.split()[-_NEGATION_WINDOW:])))
            net += -sign if negated else sign
    if net == 0 or (net > 0) == (model_score > 0):
        return model_score
    return _CUE_STRENGTH if net > 0 else -_CUE_STRENGTH


_CLAUSE_BREAK: Final[re.Pattern[str]] = re.compile(r"[,.;:!?()—-]")


def _rewatch_is_negated(clause: str) -> bool:
    """True when a negator directly governs the first "watch it again" phrase.

    A negator elsewhere in the clause does not count: "never tire of watching it again",
    "if you haven't seen it, rent it, then watch it again" and "can't find it. A movie you
    can watch again" are all positive. So only the words just before the phrase are
    examined (at most six, and not across punctuation).
    """
    found = _ASPECT_PATTERNS[Aspect.REWATCHABILITY].search(clause)
    if found is None:
        return bool(_NEGATOR.search(clause))
    lead = _CLAUSE_BREAK.split(clause[: found.start()])[-1]
    return bool(_NEGATOR.search(" ".join(lead.split()[-6:])))


@dataclass(frozen=True)
class _Mention:
    """One clause that talks about one aspect, with its polarity."""

    review_id: str
    aspect: Aspect
    clause: str
    polarity: float


# Evidence is quoted to a reader, so it must read as a complete thought: too short is
# fragment noise ("Great acting."), too long is a paragraph nobody will read.
_EVIDENCE_MIN_CHARS: Final[int] = 30
_EVIDENCE_MAX_CHARS: Final[int] = 300
# A clause this close to neutral says nothing for or against, so it cannot justify a score.
_EVIDENCE_MIN_ABS_POLARITY: Final[float] = 0.3


def build_profile(
    movie_id: str,
    reviews: Iterable[tuple[str, str]],
    *,
    min_support: int = 3,
    model: PolarityScorer | None = None,
    evidence_per_aspect: int = 3,
    source_url: str | Callable[[str], str | None] | None = None,
) -> tuple[MovieAspectProfile, Sequence[EvidenceSentence]]:
    """Aggregate per-clause judgements into one film's aspect profile.

    Aspects with fewer than `min_support` supporting clauses are dropped rather than
    reported with a wide error bar the UI has no room to show. A missing aspect renders
    as "not enough reviews mention this", which is honest; a score computed from one
    sentence rendered identically to one computed from four hundred is not.

    The aspect score is the plain mean polarity of its clauses; `support` travels with it.
    Evidence for an aspect is chosen from clauses that AGREE with the sign of its score,
    strongest first, at most one per review so a single opinionated reviewer cannot
    fill the panel.

    Args:
        movie_id: CineWhy internal id.
        reviews: Pairs of (review_id, review_text).
        min_support: Minimum supporting clauses for an aspect to be reported.
        model: Polarity scorer. Defaults to the production model.
        evidence_per_aspect: Maximum evidence sentences kept per aspect.
        source_url: Where a sceptical reader can find the reviews, attached to each
            evidence sentence. A function maps a review id to its own link, for films whose
            reviews come from several dumps; a string is used for every sentence.

    Returns:
        The profile, and the evidence sentences selected to justify it.
    """
    scorer = model or default_polarity_model()
    review_list = list(reviews)
    found: list[tuple[str, str, frozenset[Aspect]]] = []
    for review_id, text in review_list:
        for sentence in split_sentences(text):
            for clause in split_clauses(sentence):
                if aspects := detect_aspects(clause):
                    found.append((review_id, clause, aspects))

    base_scores = scorer.score_many([clause for _, clause, _ in found]) if found else []
    mentions: dict[Aspect, list[_Mention]] = defaultdict(list)
    for (review_id, clause, aspects), base in zip(found, base_scores, strict=True):
        for aspect in aspects:
            polarity = aspect_polarity(aspect, clause, base)
            # A near-neutral clause ("The story is about a goldfish.") mentions the aspect
            # without judging it. Counting it would dilute the mean toward zero and inflate
            # support, so only opinionated clauses are mentions.
            if abs(polarity) >= MIN_OPINION:
                mentions[aspect].append(_Mention(review_id, aspect, clause, polarity))

    scores: list[AspectScore] = []
    evidence: list[EvidenceSentence] = []
    for aspect in Aspect:  # enum order keeps the output deterministic
        items = mentions.get(aspect, [])
        if len(items) < min_support:
            continue
        mean = sum(m.polarity for m in items) / len(items)
        scores.append(
            AspectScore(aspect=aspect, score=max(-1.0, min(1.0, mean)), support=len(items))
        )
        evidence.extend(_pick_evidence(items, mean, evidence_per_aspect, source_url))

    profile = MovieAspectProfile(
        movie_id=movie_id, scores=tuple(scores), total_reviews=len(review_list)
    )
    return profile, evidence


def _pick_evidence(
    items: Sequence[_Mention],
    mean: float,
    limit: int,
    source_url: str | Callable[[str], str | None] | None,
) -> list[EvidenceSentence]:
    """Choose quotable clauses that agree with the aspect's overall direction."""
    sign = 1.0 if mean >= 0 else -1.0
    candidates = [
        m
        for m in items
        if m.polarity * sign >= _EVIDENCE_MIN_ABS_POLARITY
        and _EVIDENCE_MIN_CHARS <= len(m.clause) <= _EVIDENCE_MAX_CHARS
    ]
    # Strongest first; review id then text break ties so the choice is reproducible.
    candidates.sort(key=lambda m: (-abs(m.polarity), m.review_id, m.clause))
    chosen: list[EvidenceSentence] = []
    seen_reviews: set[str] = set()
    for m in candidates:
        if m.review_id in seen_reviews:
            continue
        seen_reviews.add(m.review_id)
        chosen.append(
            EvidenceSentence(
                text=m.clause,
                aspect=m.aspect,
                polarity=max(-1.0, min(1.0, m.polarity)),
                source_review_id=m.review_id,
                source_url=source_url(m.review_id) if callable(source_url) else source_url,
            )
        )
        if len(chosen) == limit:
            break
    return chosen
