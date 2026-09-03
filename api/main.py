"""HTTP surface. Transport only — no business logic lives here.

Route handlers validate input, call into `cinewhy`, and serialise the result. Anything
that decides *what* to recommend belongs in `cinewhy.recsys`; anything that decides
*why* belongs in `cinewhy.absa`. Keeping this file thin is what lets the two halves of
the team work without colliding (ARCHITECTURE.md §5).

Error policy (CONSTRAINTS.md #8): never return `str(e)` or a traceback to a client. Log
the detail server-side against an opaque error id and return the id.

Phase E. Owner: see CONTRIBUTING.md.
"""

from __future__ import annotations

from cinewhy.schemas import (
    ArtifactManifest,
    Movie,
    MovieAspectProfile,
    RecommendRequest,
    RecommendResponse,
)


def load_artifacts() -> ArtifactManifest:
    """Load and verify every artifact, once, at process start.

    Called during application startup, never per request. Must raise rather than
    degrade if verification fails — a server that boots on corrupt artifacts serves
    confident nonsense (FLOW.md §4).

    Returns:
        The verified manifest.

    Raises:
        ManifestMismatchError: If any artifact fails verification.
    """
    raise NotImplementedError("Phase E")


def health() -> dict[str, str]:
    """Liveness probe.

    Returns the loaded manifest hash, not just a status string. `{"status": "ok"}` alone
    cannot distinguish a correctly-running server from one serving last week's
    artifacts, which makes it useless as a post-rollback check (ROLLBACK.md §6).

    Returns:
        `{"status": "ok", "manifest": "<hash>"}`.
    """
    raise NotImplementedError("Phase E")


def search(query: str, limit: int = 20) -> list[Movie]:
    """Find films by title.

    Args:
        query: User-supplied search string. Treat as untrusted.
        limit: Maximum results.

    Returns:
        Matching films, best match first.
    """
    raise NotImplementedError("Phase E")


def get_movie(movie_id: str) -> tuple[Movie, MovieAspectProfile]:
    """Return one film and its aspect profile.

    Args:
        movie_id: CineWhy internal id.

    Returns:
        The film and its aspect profile.

    Raises:
        KeyError: If no such film. The handler maps this to a 404 with no detail.
    """
    raise NotImplementedError("Phase E")


def recommend(request: RecommendRequest) -> RecommendResponse:
    """Rank films for a taste profile and attach the evidence for each.

    Must be deterministic: the same profile returns the same ordering, so a user who
    reloads does not see the list reshuffle and lose trust in it.

    A cold-start profile is not an error. Answer with a popularity fallback, set
    `cold_start=True`, and mark each item `is_fallback=True` so the UI can say "popular
    right now" instead of inventing a personalised rationale.

    Args:
        request: Taste profile, limit and exclusions.

    Returns:
        Ranked recommendations, each carrying its reasons.
    """
    raise NotImplementedError("Phase E")
