"""Response shapes that belong to the HTTP layer only.

The cross-module contract lives in `cinewhy/schemas.py` and is a two-person decision.
These models describe how the API presents things to the browser (a movie page, a
review analysis), so changing them never touches the ranker or the ABSA pipeline.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from cinewhy.schemas import Aspect, EvidenceSentence, Movie, Polarity

# What the UI shows next to each slider and bar. One definition, served at /aspects, so the
# frontend never carries its own copy that could drift from the enum.
ASPECT_INFO: dict[Aspect, tuple[str, str]] = {
    Aspect.ACTING: ("Acting", "Performances and casting."),
    Aspect.PLOT: ("Plot", "Story, script and dialogue."),
    Aspect.PACING: ("Pacing", "How the film moves: too slow, too rushed, or just right."),
    Aspect.VISUALS: ("Visuals", "Cinematography, effects, costumes and scenery."),
    Aspect.ENDING: ("Ending", "How the story lands."),
    Aspect.SOUNDTRACK: ("Soundtrack", "Music and songs."),
    Aspect.REWATCHABILITY: ("Rewatchability", "Whether reviewers would watch it again."),
}


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AspectInfo(_Out):
    """Display metadata for one aspect."""

    aspect: Aspect
    label: str
    description: str


class AspectDetail(_Out):
    """One aspect of one film: the score, how well supported it is, and the quotes."""

    aspect: Aspect
    score: Polarity
    support: int
    evidence: tuple[EvidenceSentence, ...]


class MovieDetail(_Out):
    """Everything the movie page shows."""

    movie: Movie
    imdb_url: str
    rating_count: int
    mean_rating: float
    review_count: int
    aspects: tuple[AspectDetail, ...]


class AnalyzeRequest(BaseModel):
    """A review the viewer pasted in."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=5000)


class AspectMention(_Out):
    """One aspect found in one clause, with its polarity for that aspect."""

    aspect: Aspect
    polarity: Polarity


class ClauseAnalysis(_Out):
    """One clause: the verbatim text, its overall polarity, and the aspects it talks about."""

    text: str
    polarity: Polarity
    mentions: tuple[AspectMention, ...]


class SentenceAnalysis(_Out):
    """One sentence split into clauses."""

    text: str
    clauses: tuple[ClauseAnalysis, ...]


class AspectSummary(_Out):
    """Mean polarity of the opinionated mentions of one aspect in the pasted review."""

    aspect: Aspect
    polarity: Polarity
    mentions: int


class AnalyzeResponse(_Out):
    """Result of analysing a pasted review."""

    overall: Polarity
    sentences: tuple[SentenceAnalysis, ...]
    summary: tuple[AspectSummary, ...]


class ErrorResponse(_Out):
    """Body of every 5xx. Carries an opaque id only; the detail stays in the server log."""

    error_id: str
