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
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
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
    DiscoverRequest,
    ErrorResponse,
    Facets,
    MovieDetail,
    SentenceAnalysis,
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
from cinewhy.recsys import discover, rank
from cinewhy.recsys.catalogue import Catalogue, load_catalogue
from cinewhy.recsys.discover import DiscoverResult
from cinewhy.schemas import (
    ArtifactManifest,
    Aspect,
    Movie,
    MovieAspectProfile,
    RecommendRequest,
    RecommendResponse,
)

log = logging.getLogger("cinewhy.api")

_MAX_BODY_BYTES = 64 * 1024  # a taste profile is a few hundred bytes; this is generous
_RATE_WINDOW_SECONDS = 60.0
_RATE_LIMIT = 120  # POSTs per client per window; POST is where the real work happens
_SEARCH_LIMIT_MAX = 50
_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@dataclass
class _State:
    """Everything loaded at boot. Read-only afterwards."""

    manifest: ArtifactManifest
    catalogue: Catalogue
    metrics: dict[str, Any]
    polarity: PolarityModel | None


_state: _State | None = None


def load_artifacts(directory: Path | None = None) -> ArtifactManifest:
    """Load and verify every artifact, once, at process start.

    Called during application startup, never per request. Raises rather than degrades if
    verification fails — a server that boots on corrupt artifacts serves confident
    nonsense (FLOW.md §4).

    Args:
        directory: Artifact directory. Defaults to `$CINEWHY_ARTIFACTS`, then `artifacts/`.

    Returns:
        The verified manifest.

    Raises:
        ManifestMismatchError: If any file is missing, changed, or the manifest was edited.
    """
    global _state
    root = directory or Path(os.environ.get("CINEWHY_ARTIFACTS", "artifacts"))
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
    catalogue = load_catalogue(root, with_meta="meta.json" in manifest.files)
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


def movie_detail(movie_id: str) -> MovieDetail:
    """The movie page: the film, its stats, and every reported aspect with its quotes.

    Raises:
        KeyError: If no such film.
    """
    state = _loaded()
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
        from_year=request.from_year,
        to_year=request.to_year,
        exclude=request.exclude_movie_ids,
        manifest=state.manifest.manifest_hash,
    )


def facets() -> Facets:
    """Counts for the UI's filters: films per language and genre, and the year range."""
    return Facets.model_validate(discover.catalogue_facets(_loaded().catalogue))


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

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        declared = request.headers.get("content-length", "0")
        if declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        if request.method == "POST":
            client = request.client.host if request.client else "unknown"
            if not limiter.allow(client):
                return JSONResponse({"detail": "too many requests"}, status_code=429)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
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

    @app.get("/facets")
    def facets_route() -> Facets:
        return facets()

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
