"""HTTP surface. Transport only — no business logic lives here.

Route handlers validate input, call into `cinewhy`, and serialise the result. Anything
that decides *what* to recommend belongs in `cinewhy.recsys`; anything that decides
*why* belongs in `cinewhy.absa`. Keeping this file thin is what lets the two halves of
the team work without colliding (ARCHITECTURE.md §5).

Error policy (CONSTRAINTS.md #8): never return `str(e)` or a traceback to a client. Log
the detail server-side against an opaque error id and return the id.

Boot policy (FLOW.md §4): artifacts are loaded and hash-verified once, at startup. A
mismatch stops the process; serving stale or half-written artifacts would produce
confidently wrong recommendations.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.models import (
    ASPECT_INFO,
    AnalyzeRequest,
    AnalyzeResponse,
    AspectDetail,
    AspectInfo,
    AspectMention,
    AspectSummary,
    ClauseAnalysis,
    Deck,
    DeckCard,
    DeckRequest,
    DiscoverRequest,
    ErrorResponse,
    Facets,
    MovieDetail,
    PersonHit,
    PersonRef,
    QuizRequest,
    ResultCard,
    RoomCreated,
    RoomCreateRequest,
    RoomJoined,
    RoomJoinRequest,
    RoomMemberView,
    RoomResults,
    RoomView,
    SentenceAnalysis,
    ShelvesRequest,
    SwipeAck,
    SwipeRequest,
    WatchOption,
    WhereToWatch,
)
from cinewhy.absa.extract import (
    MIN_OPINION,
    aspect_polarity,
    detect_aspects,
    split_clauses,
    split_sentences,
)
from cinewhy.absa.polarity import PolarityModel
from cinewhy.artifacts.manifest import load_manifest, verify
from cinewhy.data.fetch_providers import PLATFORMS, WAY_ORDER
from cinewhy.recsys import discover, rank
from cinewhy.recsys.catalogue import Catalogue, load_catalogue
from cinewhy.recsys.discover import DiscoverItem, DiscoverResult
from cinewhy.recsys.group import Member, Quiz, recommend_group
from cinewhy.recsys.people import cast_of, imdb_number, search_people
from cinewhy.recsys.rooms import Room, RoomError, RoomStore
from cinewhy.recsys.shelves import ShelvesResult, build_shelves
from cinewhy.schemas import (
    ArtifactManifest,
    Aspect,
    Movie,
    MovieAspectProfile,
    RecommendRequest,
    RecommendResponse,
)

log = logging.getLogger("cinewhy.api")

# A taste profile is a few hundred bytes, but a long library sends up to 3,000 liked, disliked and
# watched ids (about 13 bytes each, so about 120 KB at the extreme); this leaves room for that.
_MAX_BODY_BYTES = 160 * 1024
_RATE_WINDOW_SECONDS = 60.0
_RATE_LIMIT = 120  # POSTs per client per window; POST is where the real work happens
_SWIPE_LIMIT = 240  # swipes per room member per window (about four a second, faster than a hand)
_SEARCH_LIMIT_MAX = 50
_PEOPLE_LIMIT_MAX = 20
_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@dataclass
class _State:
    """Everything loaded at boot. Read-only afterwards."""

    manifest: ArtifactManifest
    catalogue: Catalogue
    metrics: dict[str, Any]
    polarity: PolarityModel | None


_state: _State | None = None


def default_artifacts_dir() -> Path:
    """Where to load artifacts from.

    `$CINEWHY_ARTIFACTS` if set; otherwise the highest-numbered `artifacts/vN` that has a
    manifest (the TMDB-based builds live there, newest last, so `start.bat` serves the current
    catalogue without a rename); otherwise `artifacts/`, where the aclImdb-only build sits. A
    folder without a manifest is a half-made build and is skipped.
    """
    chosen = os.environ.get("CINEWHY_ARTIFACTS")
    if chosen:
        return Path(chosen)
    builds = [
        (int(found.group(1)), path)
        for path in Path("artifacts").glob("v*")
        if (found := re.fullmatch(r"v(\d+)", path.name)) and (path / "manifest.json").is_file()
    ]
    return max(builds)[1] if builds else Path("artifacts")


def load_artifacts(directory: Path | None = None) -> ArtifactManifest:
    """Load and verify every artifact, once, at process start.

    Called during application startup, never per request. Raises rather than degrades if
    verification fails — a server that boots on corrupt artifacts serves confident
    nonsense (FLOW.md §4).

    Args:
        directory: Artifact directory. Defaults to `default_artifacts_dir()`.

    Returns:
        The verified manifest.

    Raises:
        ManifestMismatchError: If any file is missing, changed, or the manifest was edited.
    """
    global _state
    root = directory or default_artifacts_dir()
    manifest = load_manifest(root)
    verify(root, manifest)  # BEFORE anything below reads (or unpickles) a file
    metrics_path = root / "eval.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else {}
    polarity = (
        PolarityModel.load(root / "polarity.joblib")
        if "polarity.joblib" in manifest.files
        else None
    )
    # `meta.json` is read only when the verified manifest lists it: a stray file on disk is
    # unverified, and its poster paths end up in URLs the browser loads.
    catalogue = load_catalogue(
        root,
        with_meta="meta.json" in manifest.files,
        with_ratings_only="ratings_only.json" in manifest.files,
        with_cast="cast.json" in manifest.files,
        with_availability="availability.json" in manifest.files,
    )
    _state = _State(manifest, catalogue, metrics, polarity)
    log.info(
        "artifacts verified: manifest=%s films=%d",
        manifest.manifest_hash[:12],
        len(_state.catalogue.movies),
    )
    return manifest


def _loaded() -> _State:
    if _state is None:
        raise RuntimeError("artifacts are not loaded; start the app or call load_artifacts()")
    return _state


def health() -> dict[str, str]:
    """Liveness probe.

    Returns the loaded manifest hash, not just a status string. `{"status": "ok"}` alone
    cannot distinguish a correctly-running server from one serving last week's
    artifacts, which makes it useless as a post-rollback check (ROLLBACK.md §6).

    Returns:
        `{"status": "ok", "manifest": "<hash>"}`.
    """
    return {"status": "ok", "manifest": _loaded().manifest.manifest_hash}


def search(query: str, limit: int = 20) -> list[Movie]:
    """Find films by title.

    Args:
        query: User-supplied search string. Treated as untrusted and matched literally.
        limit: Maximum results.

    Returns:
        Matching films, best match first.
    """
    return rank.search(_loaded().catalogue, query, limit)


def get_movie(movie_id: str) -> tuple[Movie, MovieAspectProfile]:
    """Return one film and its aspect profile.

    Args:
        movie_id: CineWhy internal id.

    Returns:
        The film and its aspect profile.

    Raises:
        KeyError: If no such film. The handler maps this to a 404 with no detail.
    """
    movie, profile, _ = rank.movie_detail(_loaded().catalogue, movie_id)
    return movie, profile


_RT_PREFIX = "https://www.rottentomatoes.com/m/"


def _rotten_tomatoes_url(value: object) -> str | None:
    """A Rotten Tomatoes film page, or None: only that address may become a link in the UI."""
    return value if isinstance(value, str) and value.startswith(_RT_PREFIX) else None


def _cast(catalogue: Catalogue, movie_id: str) -> tuple[PersonRef, ...]:
    """The billed actors and actresses of a title, or nobody when the build has no cast file."""
    return tuple(PersonRef(id=person, name=name) for person, name in cast_of(catalogue, movie_id))


_TMDB_PAGE = re.compile(r"(?:movie|tv)/[0-9]{1,9}")


def _where(catalogue: Catalogue, movie_id: str) -> WhereToWatch | None:
    """Where a title can be watched among the six platforms, or None when the build has no data.

    A title missing from a build that has the data is on none of the six, so it gets an empty
    list (the page says so) rather than None (which would mean "we do not know"). The TMDB path
    comes from a hash-verified file, but only a plain `movie/123` or `tv/123` may become a link.
    Platforms and ways come out in the fixed order of `PLATFORMS` and `WAY_ORDER`: the file is
    written with sorted keys, so its own order says nothing.
    """
    number = imdb_number(movie_id)
    if catalogue.availability is None or number is None:
        return None
    fetched = catalogue.availability.fetched
    found = catalogue.availability.titles.get(number)
    if found is None:
        return WhereToWatch(fetched=fetched, tmdb_url=None, platforms=())
    link = f"https://www.themoviedb.org/{found.tmdb}/watch"
    return WhereToWatch(
        fetched=fetched,
        tmdb_url=link if _TMDB_PAGE.fullmatch(found.tmdb) else None,
        platforms=tuple(
            WatchOption(
                platform=platform,
                ways={
                    way: found.on[platform][way] for way in WAY_ORDER if way in found.on[platform]
                },
            )
            for platform in PLATFORMS
            if platform in found.on
        ),
    )


def _ratings_only_detail(catalogue: Catalogue, movie_id: str) -> MovieDetail:
    """The movie page for a film we hold only ratings for: facts and IMDb numbers, no receipt."""
    film = catalogue.ratings_only_at(catalogue.all_index[movie_id])
    return MovieDetail(
        movie=film.movie,
        imdb_url=f"https://www.imdb.com/title/tt{film.imdb_id:07d}/",
        rating_count=0,
        mean_rating=0.0,
        review_count=0,
        aspects=(),
        overview=film.overview,
        language=film.language,
        release_date=film.release_date,
        runtime_minutes=film.runtime,
        ratings_only=True,
        imdb_rating=film.imdb_rating,
        imdb_votes=film.imdb_votes,
        cast=_cast(catalogue, movie_id),
        where_to_watch=_where(catalogue, movie_id),
    )


def movie_detail(movie_id: str) -> MovieDetail:
    """The movie page: the film, its stats, and every reported aspect with its quotes.

    Raises:
        KeyError: If no such film.
    """
    state = _loaded()
    if movie_id not in state.catalogue.index and movie_id in state.catalogue.all_index:
        return _ratings_only_detail(state.catalogue, movie_id)
    movie, profile, evidence = rank.movie_detail(state.catalogue, movie_id)
    stats = state.catalogue.stats[state.catalogue.index[movie_id]]
    extra = state.catalogue.meta.get(movie_id, {})
    runtime = extra.get("runtime")
    return MovieDetail(
        movie=movie,
        imdb_url=f"https://www.imdb.com/title/tt{stats.imdb_id:07d}/",
        rating_count=stats.rating_count,
        mean_rating=round(stats.bayes_mean, 2),
        review_count=stats.review_count,
        overview=extra.get("overview") or None,
        language=extra.get("language") or None,
        release_date=extra.get("release_date") or None,
        runtime_minutes=int(runtime) if isinstance(runtime, int | float) and runtime > 0 else None,
        rt_url=_rotten_tomatoes_url(extra.get("rt_url")),
        reviews_by_source=dict(extra.get("reviews_by_source", {})),
        aspects=tuple(
            AspectDetail(
                aspect=s.aspect,
                score=s.score,
                support=s.support,
                evidence=evidence.get(s.aspect, ()),
            )
            for s in sorted(profile.scores, key=lambda s: (-s.support, s.aspect.value))
        ),
        cast=_cast(state.catalogue, movie_id),
        where_to_watch=_where(state.catalogue, movie_id),
    )


def recommend(request: RecommendRequest) -> RecommendResponse:
    """Rank films for a taste profile and attach the evidence for each.

    Deterministic: the same profile returns the same ordering, so a user who reloads does
    not see the list reshuffle and lose trust in it.

    A cold-start profile is not an error. It gets a popularity fallback with
    `cold_start=True`, each item marked `is_fallback=True`, so the UI can say "popular"
    instead of inventing a personalised rationale.

    Args:
        request: Taste profile, limit and exclusions.

    Returns:
        Ranked recommendations, each carrying its reasons.
    """
    state = _loaded()
    return rank.recommend(state.catalogue, request, state.manifest.manifest_hash)


def discover_films(request: DiscoverRequest) -> DiscoverResult:
    """Discovery list: what is worth watching now, with a say over era, language and genre.

    Deterministic, like `recommend`. See `cinewhy.recsys.discover` for what the ranking does and
    why filters narrow the list but never the catalogue.
    """
    state = _loaded()
    return discover.discover(
        state.catalogue,
        request.profile,
        limit=request.limit,
        recency=request.recency,
        languages=request.languages,
        genres=request.genres,
        kinds=request.kinds,
        from_year=request.from_year,
        to_year=request.to_year,
        exclude=request.exclude_movie_ids,
        person_id=request.person_id,
        receipts_only=request.receipts_only,
        manifest=state.manifest.manifest_hash,
    )


def shelves(request: ShelvesRequest) -> ShelvesResult:
    """Every shelf of the home page in one answer, with no film on two shelves.

    Deterministic, like `recommend`. See `cinewhy.recsys.shelves` for which shelves exist and why a
    short one is left out.
    """
    state = _loaded()
    return build_shelves(
        state.catalogue,
        request.profile,
        recency=request.recency,
        languages=request.languages,
        genres=request.genres,
        kinds=request.kinds,
        from_year=request.from_year,
        to_year=request.to_year,
        exclude=request.exclude_movie_ids,
        manifest=state.manifest.manifest_hash,
        only=request.only,
        more_limit=request.limit,
    )


def facets() -> Facets:
    """Counts for the UI's filters, and whether this build has a cast file."""
    catalogue = _loaded().catalogue
    return Facets.model_validate(
        {
            **discover.catalogue_facets(catalogue),
            "cast": catalogue.cast is not None,
            "availability": catalogue.availability is not None,
        }
    )


def people(query: str, limit: int = 8) -> list[PersonHit]:
    """Find actors and actresses by name; empty when the build has no cast file."""
    return [
        PersonHit(id=hit.person_id, name=hit.name, titles=hit.titles)
        for hit in search_people(_loaded().catalogue, query, limit)
    ]


_LIKES_SHOWN = 50  # how many of a member's likes their friends can see; the count is not capped


def room_view(room: Room, you: str) -> RoomView:
    """A room as the member `you` sees it: everyone's name and likes (friends see each other's)."""
    return RoomView(
        code=room.code,
        version=room.version,
        max_members=room.max_members,
        activity=room.activity,
        members=tuple(
            RoomMemberView(
                member_id=e.member_id,
                name=e.name,
                is_host=e.member_id == room.host_id,
                is_you=e.member_id == you,
                liked_movie_ids=e.member.taste.liked_movie_ids[:_LIKES_SHOWN],
                watched_count=len(e.member.watched),
                want_count=len(e.member.want),
                quiz_done=e.quiz is not None,
                swipe_count=len(e.swipes) + (1 if e.top else 0),
                has_top=e.top is not None,
            )
            for e in room.members.values()
        ),
    )


_RESULTS_TOP = 5  # the titles shown first on the results screen
_RESULTS_CLOSE = 15  # then the next-closest ones


def deck_card(item: DiscoverItem) -> DeckCard:
    """A swipe card: the film page's facts in one piece (a card skips the aspects and quotes)."""
    detail = movie_detail(item.movie.movie_id)
    return DeckCard(
        movie=item.movie,
        language=detail.language or item.language,
        overview=detail.overview,
        runtime_minutes=detail.runtime_minutes,
        imdb_rating=detail.imdb_rating,
        imdb_votes=detail.imdb_votes,
        rating_count=detail.rating_count,
        mean_rating=detail.mean_rating,
        ratings_only=detail.ratings_only,
        cast=detail.cast[:5],
        where_to_watch=detail.where_to_watch,
        because=item.because,
    )


def paired(members: list[Member]) -> list[Member]:
    """The engine needs two people; a member alone in a room is paired with a copy of themself.

    Their deck and results are then simply their own taste, until a friend joins.
    """
    if len(members) >= 2:
        return members
    return [*members, replace(members[0], name=f"{members[0].name} ")]


def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Break a pasted review into clauses, aspects and polarities.

    Inference only: the polarity model was trained offline and is loaded at boot
    (CONSTRAINTS.md #5). Uses the same splitting, lexicon and rules as the offline build,
    so what the viewer sees here is what produced the film pages.

    Raises:
        RuntimeError: If this build shipped without a polarity model.
    """
    state = _loaded()
    if state.polarity is None:
        raise RuntimeError("no polarity model in this build")
    pieces = [(s, split_clauses(s)) for s in split_sentences(request.text)]
    flat = [c for _, clauses in pieces for c in clauses]
    scores = iter(state.polarity.score_many(flat))
    sentences: list[SentenceAnalysis] = []
    opinions: dict[Aspect, list[float]] = defaultdict(list)
    for sentence, clauses in pieces:
        analysed: list[ClauseAnalysis] = []
        for clause in clauses:
            score = next(scores)
            mentions = tuple(
                AspectMention(aspect=a, polarity=aspect_polarity(a, clause, score))
                for a in sorted(detect_aspects(clause), key=lambda a: a.value)
            )
            for m in mentions:
                if abs(m.polarity) >= MIN_OPINION:
                    opinions[m.aspect].append(m.polarity)
            analysed.append(ClauseAnalysis(text=clause, polarity=score, mentions=mentions))
        sentences.append(SentenceAnalysis(text=sentence, clauses=tuple(analysed)))
    overall = state.polarity.score_many([request.text])[0]
    summary = tuple(
        AspectSummary(aspect=a, polarity=sum(v) / len(v), mentions=len(v))
        for a, v in sorted(opinions.items(), key=lambda kv: kv[0].value)
    )
    return AnalyzeResponse(overall=overall, sentences=tuple(sentences), summary=summary)


class _RateLimiter:
    """Sliding-window limiter per client address. In-process: fine for one worker.

    The demo runs one process, so a shared store would be machinery without a user. Behind
    several workers each would allow its own budget, which is still a bound.
    """

    def __init__(self, limit: int, window: float) -> None:
        self._limit, self._window = limit, window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client: str, now: float | None = None) -> bool:
        """Record a hit and say whether the client is still within budget."""
        moment = time.monotonic() if now is None else now
        hits = self._hits[client]
        while hits and moment - hits[0] > self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(moment)
        return True


def create_app(artifacts: Path | None = None, *, rate_limit: int = _RATE_LIMIT) -> FastAPI:
    """Build the FastAPI application.

    Args:
        artifacts: Artifact directory to load at startup (default: see `load_artifacts`).
        rate_limit: POST requests per minute per client.

    Returns:
        The app. Artifacts are verified when the server starts, not at import time, so
        importing this module never touches the disk.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        load_artifacts(artifacts)
        yield

    app = FastAPI(title="CineWhy", version="0.1.0", lifespan=lifespan)
    limiter = _RateLimiter(rate_limit, _RATE_WINDOW_SECONDS)
    swipe_limiter = _RateLimiter(_SWIPE_LIMIT, _RATE_WINDOW_SECONDS)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        declared = request.headers.get("content-length", "0")
        if declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        # Swipes have their own per-person limit (in the route), so they skip the per-address one.
        if request.method == "POST" and not request.url.path.endswith("/swipe"):
            client = request.client.host if request.client else "unknown"
            if not limiter.allow(client):
                return JSONResponse({"detail": "too many requests"}, status_code=429)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # The scripts and styles have no hashed file names, so a browser must revalidate them
        # (StaticFiles sends an ETag, making that a cheap 304) or it can run last week's JavaScript.
        if request.method == "GET" and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-cache"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: https://image.tmdb.org; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        error_id = uuid.uuid4().hex[:12]
        log.error("unhandled error %s", error_id, exc_info=exc)
        return JSONResponse(ErrorResponse(error_id=error_id).model_dump(), status_code=500)

    @app.get("/health")
    def health_route() -> dict[str, str]:
        return health()

    @app.get("/aspects")
    def aspects_route() -> list[AspectInfo]:
        return [
            AspectInfo(aspect=a, label=label, description=desc)
            for a, (label, desc) in ASPECT_INFO.items()
        ]

    @app.get("/search")
    def search_route(q: str = "", limit: int = 20) -> list[Movie]:
        return search(q[:100], max(1, min(limit, _SEARCH_LIMIT_MAX)))

    @app.get("/people")
    def people_route(q: str = "", limit: int = 8) -> list[PersonHit]:
        return people(q[:100], max(1, min(limit, _PEOPLE_LIMIT_MAX)))

    @app.get("/movie/{movie_id}")
    def movie_route(movie_id: str) -> MovieDetail:
        try:
            return movie_detail(movie_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="not found") from None

    @app.post("/recommend")
    def recommend_route(request: RecommendRequest) -> RecommendResponse:
        return recommend(request)

    @app.post("/discover")
    def discover_route(request: DiscoverRequest) -> DiscoverResult:
        return discover_films(request)

    @app.post("/shelves")
    def shelves_route(request: ShelvesRequest) -> ShelvesResult:
        return shelves(request)

    @app.get("/facets")
    def facets_route() -> Facets:
        return facets()

    # --- Watch together: temporary rooms, in memory, no accounts (D-044) -----------------------
    # Sync routes run on a thread pool and the store is not thread-safe, so every touch of it
    # goes through this one lock. The slow part (scoring) happens outside it, on a snapshot.
    rooms = RoomStore()
    rooms_lock = threading.Lock()

    def room_failure(error: RoomError) -> HTTPException:
        status = {
            "not_found": 404,
            "full": 409,
            "forbidden": 403,
            "busy": 503,
            "top_exists": 409,
            "bad_action": 422,
        }
        return HTTPException(status_code=status.get(error.kind, 400), detail=error.kind)

    @app.post("/rooms")
    def room_create_route(request: RoomCreateRequest) -> RoomCreated:
        try:
            with rooms_lock:
                room = rooms.create(request.max_members)
        except RoomError as error:
            raise room_failure(error) from None
        return RoomCreated(code=room.code, max_members=room.max_members)

    @app.post("/rooms/{code}/join")
    def room_join_route(code: str, request: RoomJoinRequest) -> RoomJoined:
        # Consent is enforced here, on the server: a client that skips its own dialog still cannot
        # put a library into a room without saying it agreed.
        if not request.consent:
            raise HTTPException(status_code=400, detail="consent required")
        member = Member(
            name="",
            taste=request.profile,
            watched=frozenset(request.watched_movie_ids),
            want=frozenset(request.want_movie_ids),
            languages=request.languages,
            kinds=request.kinds,
        )
        try:
            with rooms_lock:
                entry = rooms.join(code, request.name, member)
                view = room_view(rooms.get(code), entry.member_id)
        except RoomError as error:
            raise room_failure(error) from None
        return RoomJoined(token=entry.token, member_id=entry.member_id, room=view)

    @app.get("/rooms/{code}")
    def room_get_route(
        code: str, room_token: Annotated[str, Header(alias="X-Room-Token")] = ""
    ) -> RoomView:
        try:
            with rooms_lock:
                room, entry = rooms.authenticate(code, room_token)
                return room_view(room, entry.member_id)
        except RoomError as error:
            raise room_failure(error) from None

    @app.post("/rooms/{code}/quiz")
    def room_quiz_route(
        code: str,
        request: QuizRequest,
        room_token: Annotated[str, Header(alias="X-Room-Token")] = "",
    ) -> RoomView:
        quiz = Quiz(request.kinds, request.languages, request.genres)
        try:
            with rooms_lock:
                entry = rooms.set_quiz(code, room_token, quiz)
                return room_view(rooms.get(code), entry.member_id)
        except RoomError as error:
            raise room_failure(error) from None

    @app.post("/rooms/{code}/swipe")
    def room_swipe_route(
        code: str,
        request: SwipeRequest,
        room_token: Annotated[str, Header(alias="X-Room-Token")] = "",
    ) -> SwipeAck:
        # Swipes are far more frequent than other requests, and behind a tunnel every friend arrives
        # from one address, so they are limited per person (the member's secret), not per address.
        if not swipe_limiter.allow(room_token or "none"):
            raise HTTPException(status_code=429, detail="too many requests")
        if request.movie_id not in _loaded().catalogue.all_index:
            raise HTTPException(status_code=404, detail="unknown_title")
        try:
            with rooms_lock:
                entry = rooms.swipe(
                    code, room_token, request.movie_id, request.action, replace=request.replace
                )
                return SwipeAck(
                    swipe_count=len(entry.swipes) + (1 if entry.top else 0), top=entry.top
                )
        except RoomError as error:
            raise room_failure(error) from None

    @app.post("/rooms/{code}/deck")
    def room_deck_route(
        code: str,
        request: DeckRequest,
        room_token: Annotated[str, Header(alias="X-Room-Token")] = "",
    ) -> Deck:
        """The next cards for this member: the group's best titles that they have not answered."""
        try:
            with rooms_lock:
                room, entry = rooms.authenticate(code, room_token)
                members = RoomStore.members_of(room)
                leave_out = RoomStore.seen_by(entry) | set(request.held_movie_ids)
        except RoomError as error:
            raise room_failure(error) from None
        result = recommend_group(
            _loaded().catalogue, paired(members), limit=request.count, exclude=leave_out
        )
        cards = tuple(deck_card(g.item) for g in result.items)
        return Deck(cards=cards, exhausted=len(cards) < request.count)

    @app.post("/rooms/{code}/results")
    def room_results_route(
        code: str, room_token: Annotated[str, Header(alias="X-Room-Token")] = ""
    ) -> RoomResults:
        """The group's best titles right now, then the next-closest, with each member's stand."""
        try:
            with rooms_lock:
                room, _ = rooms.authenticate(code, room_token)
                members = RoomStore.members_of(room)
                activity = room.activity
        except RoomError as error:
            raise room_failure(error) from None
        result = recommend_group(
            _loaded().catalogue, paired(members), limit=_RESULTS_TOP + _RESULTS_CLOSE
        )
        cards = [
            ResultCard(
                card=deck_card(g.item), members=g.members[: len(members)], score=g.item.score
            )
            for g in result.items
        ]
        return RoomResults(
            activity=activity,
            members=len(members),
            top=tuple(cards[:_RESULTS_TOP]),
            close=tuple(cards[_RESULTS_TOP:]),
            notes=result.notes,
        )

    @app.post("/rooms/{code}/leave")
    def room_leave_route(
        code: str, room_token: Annotated[str, Header(alias="X-Room-Token")] = ""
    ) -> dict[str, str]:
        try:
            with rooms_lock:
                rooms.leave(code, room_token)
        except RoomError as error:
            raise room_failure(error) from None
        return {"status": "left"}

    @app.post("/rooms/{code}/close")
    def room_close_route(
        code: str, room_token: Annotated[str, Header(alias="X-Room-Token")] = ""
    ) -> dict[str, str]:
        try:
            with rooms_lock:
                rooms.close(code, room_token)
        except RoomError as error:
            raise room_failure(error) from None
        return {"status": "closed"}

    @app.post("/analyze")
    def analyze_route(request: AnalyzeRequest) -> AnalyzeResponse:
        try:
            return analyze(request)
        except RuntimeError:
            raise HTTPException(status_code=503, detail="analysis unavailable") from None

    @app.get("/metrics")
    def metrics_route() -> dict[str, Any]:
        return _loaded().metrics

    if _WEB_DIR.is_dir():  # mounted last, so it never shadows an API route
        app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
    return app


app = create_app()
