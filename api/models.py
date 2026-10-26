"""Response shapes that belong to the HTTP layer only.

The cross-module contract lives in `cinewhy/schemas.py` and is a two-person decision.
These models describe how the API presents things to the browser (a movie page, a
review analysis), so changing them never touches the ranker or the ABSA pipeline.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from cinewhy.schemas import Aspect, EvidenceSentence, Movie, Polarity, TasteProfile

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
    # TMDB details from `meta.json`; all optional so an artifact set built without it still serves.
    overview: str | None = None
    language: str | None = None
    release_date: str | None = None
    runtime_minutes: int | None = None
    rt_url: str | None = None
    # How many of the film's reviews each source (acl, ebd, rt) contributed.
    reviews_by_source: dict[str, int] = Field(default_factory=dict)
    # True for a film we hold only ratings for: `aspects` is empty because no reviews were read, and
    # the IMDb numbers below are what it is placed by.
    ratings_only: bool = False
    imdb_rating: float | None = None
    imdb_votes: int | None = None


class DiscoverRequest(BaseModel):
    """A discovery request from a browser, so every field is bounded."""

    model_config = ConfigDict(extra="forbid")

    profile: TasteProfile = Field(default_factory=TasteProfile)
    limit: int = Field(default=20, ge=1, le=100)
    # 0 = no preference for new films, 1 = the strongest lift the ranker allows.
    recency: float = Field(default=0.5, ge=0.0, le=1.0)
    languages: tuple[Literal["en", "hi"], ...] = Field(default=(), max_length=2)
    genres: tuple[Annotated[str, StringConstraints(max_length=40)], ...] = Field(
        default=(), max_length=10
    )
    from_year: int | None = Field(default=None, ge=1880, le=2100)
    to_year: int | None = Field(default=None, ge=1880, le=2100)
    # Watched films travel here. The browser caps each of its lists at 3,000 (web/js/profile.js
    # LIST_CAP); this must not be lower, or a long watched list would turn every shelf into a 422.
    exclude_movie_ids: tuple[str, ...] = Field(default=(), max_length=3000)


class ShelvesRequest(BaseModel):
    """A request for the whole home page's shelves at once; every field is bounded.

    The visitor's own language, genre and year choices narrow every shelf; the shelves themselves
    (picks, similar, new, classics, languages, genres) are decided by the server.
    """

    model_config = ConfigDict(extra="forbid")

    profile: TasteProfile = Field(default_factory=TasteProfile)
    recency: float = Field(default=0.5, ge=0.0, le=1.0)
    languages: tuple[Literal["en", "hi", "ja", "fr"], ...] = Field(default=(), max_length=4)
    genres: tuple[Annotated[str, StringConstraints(max_length=40)], ...] = Field(
        default=(), max_length=10
    )
    from_year: int | None = Field(default=None, ge=1880, le=2100)
    to_year: int | None = Field(default=None, ge=1880, le=2100)
    exclude_movie_ids: tuple[str, ...] = Field(default=(), max_length=3000)


class Facets(_Out):
    """Counts the UI shows next to its filters."""

    films: int
    languages: dict[str, int]
    genres: dict[str, int]
    oldest_year: int | None
    newest_year: int | None


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
