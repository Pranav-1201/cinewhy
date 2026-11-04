"""Response shapes that belong to the HTTP layer only.

The cross-module contract lives in `cinewhy/schemas.py` and is a two-person decision.
These models describe how the API presents things to the browser (a movie page, a
review analysis), so changing them never touches the ranker or the ABSA pipeline.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from cinewhy.recsys.group import MemberFit
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


class PersonRef(_Out):
    """A person billed in a title: enough for the page to show a name and search for the person."""

    id: int
    name: str


class PersonHit(_Out):
    """A person found by name, with how many catalogue titles they are billed in."""

    id: int
    name: str
    titles: int


class WatchOption(_Out):
    """One platform and, for each way of watching it, the countries where that way is offered."""

    # Names from `fetch_providers.PLATFORMS` and ways from `WAY_ORDER`; the loader admits no others.
    platform: str
    ways: dict[str, tuple[str, ...]]


class WhereToWatch(_Out):
    """Where a title can be watched: a dated snapshot, never a live answer."""

    fetched: str  # ISO date of the snapshot; the page says "as of" this
    # The title's watch page on TMDB, powered by JustWatch (the page credits it); None when the
    # title is on none of the six platforms, so there is nothing to link.
    tmdb_url: str | None = None
    platforms: tuple[WatchOption, ...]


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
    # The billed actors and actresses, first billed first; empty for a build with no cast file.
    cast: tuple[PersonRef, ...] = ()
    # Where it can be watched among the six platforms we cover; None for a build with no
    # availability file, and present-but-empty `platforms` when it is on none of them.
    where_to_watch: WhereToWatch | None = None


class DiscoverRequest(BaseModel):
    """A discovery request from a browser, so every field is bounded."""

    model_config = ConfigDict(extra="forbid")

    profile: TasteProfile = Field(default_factory=TasteProfile)
    limit: int = Field(default=20, ge=1, le=100)
    # 0 = no preference for new films, 1 = the strongest lift the ranker allows.
    recency: float = Field(default=0.5, ge=0.0, le=1.0)
    languages: tuple[Literal["en", "hi", "ja", "fr"], ...] = Field(default=(), max_length=4)
    genres: tuple[Annotated[str, StringConstraints(max_length=40)], ...] = Field(
        default=(), max_length=10
    )
    # Films, series or both (empty is both).
    kinds: tuple[Literal["film", "series"], ...] = Field(default=(), max_length=2)
    from_year: int | None = Field(default=None, ge=1880, le=2100)
    to_year: int | None = Field(default=None, ge=1880, le=2100)
    # Only the titles this person (an id from `/people`) is billed in, ranked like any other list.
    person_id: int | None = Field(default=None, ge=1, le=2_000_000_000)
    # Keep out the titles we hold only ratings for (the top pick promises the sentences behind it).
    receipts_only: bool = False
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
    # Films, series or both (empty is both).
    kinds: tuple[Literal["film", "series"], ...] = Field(default=(), max_length=2)
    from_year: int | None = Field(default=None, ge=1880, le=2100)
    to_year: int | None = Field(default=None, ge=1880, le=2100)
    exclude_movie_ids: tuple[str, ...] = Field(default=(), max_length=3000)
    # "Show more" on one row: only that shelf, this many titles. Leave both out for the whole page.
    only: Annotated[str, StringConstraints(max_length=60)] | None = None
    limit: int = Field(default=20, ge=1, le=40)


_ID_LIST = Field(default=(), max_length=3000)


class RoomCreateRequest(BaseModel):
    """Open a room. The size is a request: the server clamps it to what it allows."""

    model_config = ConfigDict(extra="forbid")

    max_members: int | None = Field(default=None, ge=2, le=20)


class RoomJoinRequest(BaseModel):
    """A person joining: their library, and their agreement to share it.

    `consent` has to be true. It is checked in the route, not only here, so a client that leaves
    it out gets a refusal that names the reason.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(max_length=60)] = ""
    consent: bool = False
    profile: TasteProfile = Field(default_factory=TasteProfile)
    watched_movie_ids: tuple[str, ...] = _ID_LIST
    want_movie_ids: tuple[str, ...] = _ID_LIST
    languages: tuple[Literal["en", "hi", "ja", "fr"], ...] = Field(default=(), max_length=4)
    kinds: tuple[Literal["film", "series"], ...] = Field(default=(), max_length=2)


class QuizRequest(BaseModel):
    """A member's mood for tonight. Empty lists mean no preference; unknown genres match nothing."""

    model_config = ConfigDict(extra="forbid")

    kinds: tuple[Literal["film", "series"], ...] = Field(default=(), max_length=2)
    languages: tuple[Literal["en", "hi", "ja", "fr"], ...] = Field(default=(), max_length=4)
    genres: tuple[Annotated[str, StringConstraints(max_length=40)], ...] = Field(
        default=(), max_length=10
    )


class SwipeRequest(BaseModel):
    """One swipe. `replace` confirms swapping the member's existing top pick for this title."""

    model_config = ConfigDict(extra="forbid")

    movie_id: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    action: Literal["want", "pass", "seen", "top"]
    replace: bool = False


class SwipeAck(_Out):
    """What the server now holds for the member: how many answers, and their top pick."""

    swipe_count: int
    top: str | None


class DeckRequest(BaseModel):
    """The next cards for this member; `held_movie_ids` are the ones their page already has."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=20, ge=1, le=40)
    held_movie_ids: tuple[str, ...] = Field(default=(), max_length=600)


class DeckCard(_Out):
    """Everything a swipe card shows, in one piece so a card never waits on a second request."""

    movie: Movie
    language: str | None = None
    overview: str | None = None
    runtime_minutes: int | None = None
    imdb_rating: float | None = None
    imdb_votes: int | None = None
    rating_count: int = 0
    mean_rating: float = 0.0
    ratings_only: bool = False
    cast: tuple[PersonRef, ...] = ()
    where_to_watch: WhereToWatch | None = None
    because: str | None = None


class Deck(_Out):
    """A batch of cards, and whether the pool has run dry for this member."""

    cards: tuple[DeckCard, ...]
    exhausted: bool


class ResultCard(_Out):
    """A title on the results screen with where each member stands on it."""

    card: DeckCard
    members: tuple[MemberFit, ...]
    score: float


class RoomResults(_Out):
    """The group's best titles now, then the next-closest. `activity` dates the list."""

    activity: int
    members: int
    top: tuple[ResultCard, ...]
    close: tuple[ResultCard, ...]
    notes: tuple[str, ...] = ()


class RoomMemberView(_Out):
    """Who is in a room. Friends see each other's likes, so the liked ids are shown (capped)."""

    member_id: str
    name: str
    is_host: bool
    is_you: bool
    liked_movie_ids: tuple[str, ...]
    watched_count: int
    want_count: int
    # Progress only, never the swipes themselves (those are shown on the results screen).
    quiz_done: bool = False
    swipe_count: int = 0
    has_top: bool = False


class RoomView(_Out):
    """A room as one of its members sees it. `version` changes whenever the membership does."""

    code: str
    version: int
    max_members: int
    members: tuple[RoomMemberView, ...]
    activity: int = 0


class RoomCreated(_Out):
    """A new room's code and size."""

    code: str
    max_members: int


class RoomJoined(_Out):
    """The member's secret (shown once, sent back as the `X-Room-Token` header) and the room."""

    token: str
    member_id: str
    room: RoomView


class Facets(_Out):
    """Counts the UI shows next to its filters."""

    films: int  # titles of both kinds, the name kept for older pages
    kinds: dict[str, int] = Field(default_factory=dict)
    languages: dict[str, int]
    genres: dict[str, int]
    oldest_year: int | None
    newest_year: int | None
    # True when this build has a cast file, so the page knows people can be searched.
    cast: bool = False
    # True when this build knows where titles can be watched.
    availability: bool = False


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
