"""The contract between every module in CineWhy.

This file is the coordination point for the whole project. `cinewhy.absa` produces
objects defined here; `cinewhy.recsys` consumes them; `api` serialises them. Neither
half of the team can drift from the other while both import these types.

**Changing anything in this file is a two-person decision.** See CONTRIBUTING.md
"Changing the contract". Every other module may be rewritten freely; this one may not.

The load-bearing rule lives in `Reason.evidence`: a reason with no evidence sentences
is rejected at construction time. The product's entire claim is that recommendations
are grounded in what reviewers actually said, so an ungrounded reason must be
impossible to build, not merely discouraged (audit idea B-13).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Scores that express sentiment run -1 (uniformly negative) to +1 (uniformly positive).
Polarity = Annotated[float, Field(ge=-1.0, le=1.0)]
# Weights the user assigns to an aspect run 0 (don't care) to 1 (this is why I watch).
Weight = Annotated[float, Field(ge=0.0, le=1.0)]


class Aspect(StrEnum):
    """The dimensions a review can praise or criticise.

    Fixed and deliberately small. Every aspect here must be something a reviewer
    plausibly comments on AND a viewer plausibly chooses films by — an aspect that
    fails either half is noise in the explanation panel.

    Adding a member invalidates every stored aspect score, so it forces an artifact
    rebuild. Treat additions as a migration, not a tweak.
    """

    ACTING = "acting"
    PLOT = "plot"
    PACING = "pacing"
    VISUALS = "visuals"
    ENDING = "ending"
    SOUNDTRACK = "soundtrack"
    REWATCHABILITY = "rewatchability"


class _Frozen(BaseModel):
    """Base for value objects that must not mutate after construction.

    Aspect scores and evidence are read out of immutable artifacts and passed through
    several ranking stages. Making them frozen means a ranking bug cannot silently
    rewrite the evidence it was supposed to be explaining.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Movie(_Frozen):
    """A recommendable film, keyed by our internal id.

    `movie_id` is CineWhy's own identifier, not TMDB's or MovieLens'. Those live in
    the id-mapping table (Phase D) so that a change of upstream source does not
    invalidate stored aspect scores.
    """

    movie_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1878, le=2100)
    genres: tuple[str, ...] = ()
    poster_url: str | None = None


class EvidenceSentence(_Frozen):
    """One sentence from one real review, supporting one aspect judgement.

    This is the atom the product is built on. It is never generated, paraphrased, or
    summarised — it is quoted verbatim from `source_review_id` so a sceptical user can
    go and check it. See CONSTRAINTS.md #9.
    """

    text: str = Field(min_length=1, max_length=1000)
    aspect: Aspect
    polarity: Polarity
    source_review_id: str = Field(min_length=1)
    source_url: str | None = None


class AspectScore(_Frozen):
    """How a single film scores on a single aspect, across all its reviews.

    `support` is the number of review sentences the score was computed from. A score
    with low support is not wrong, it is uncertain — the UI must be able to tell the
    difference, so support travels with the score rather than being dropped.
    """

    aspect: Aspect
    score: Polarity
    support: int = Field(ge=0)


class MovieAspectProfile(_Frozen):
    """Everything `cinewhy.absa` knows about one film.

    Produced offline by the ABSA pipeline, stored in an artifact, and read at request
    time. Never computed inside a request handler (CONSTRAINTS.md #5).
    """

    movie_id: str = Field(min_length=1)
    scores: tuple[AspectScore, ...]
    total_reviews: int = Field(ge=0)

    @model_validator(mode="after")
    def _no_duplicate_aspects(self) -> Self:
        """Reject two scores for the same aspect.

        Duplicates would make ranking non-deterministic depending on which one the
        scorer happened to read first — a bug that surfaces as unstable
        recommendations long after it is introduced.
        """
        seen = [s.aspect for s in self.scores]
        if len(seen) != len(set(seen)):
            dupes = sorted({a for a in seen if seen.count(a) > 1})
            raise ValueError(f"duplicate aspect scores for {self.movie_id}: {dupes}")
        return self


class TasteProfile(BaseModel):
    """What the current viewer cares about.

    Lives in the browser (`localStorage`) and is posted with each request. v1 has no
    accounts and no database, which keeps auth, GDPR and a data store off the critical
    path (ARCHITECTURE.md §6).

    An empty profile is legal and means cold start — the API answers with a popularity
    fallback rather than an error.
    """

    model_config = ConfigDict(extra="forbid")

    aspect_weights: dict[Aspect, Weight] = Field(default_factory=dict)
    liked_movie_ids: tuple[str, ...] = ()
    disliked_movie_ids: tuple[str, ...] = ()

    @property
    def is_cold_start(self) -> bool:
        """True when there is nothing to personalise on."""
        return not self.aspect_weights and not self.liked_movie_ids


class Reason(_Frozen):
    """Why one film was recommended, on one aspect, with the sentences that show it.

    `evidence` may not be empty. A reason without evidence is precisely the
    unfalsifiable "because you watched X" that this product exists to replace, so it is
    rejected here rather than filtered out downstream where a caller might forget.
    """

    aspect: Aspect
    movie_score: Polarity
    user_weight: Weight
    evidence: tuple[EvidenceSentence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _evidence_matches_aspect(self) -> Self:
        """Reject evidence quoted for a different aspect than the reason claims.

        Without this, a ranking bug could attach pacing sentences to an acting reason
        and the UI would render a confident, well-formatted lie.
        """
        wrong = {e.aspect for e in self.evidence if e.aspect is not self.aspect}
        if wrong:
            raise ValueError(f"reason claims {self.aspect} but cites evidence for {sorted(wrong)}")
        return self


class Recommendation(_Frozen):
    """One ranked film plus the reasons it was chosen.

    `reasons` may be empty only when `is_fallback` is set — that is the cold-start
    path, where the honest answer is "this is popular", not a fabricated rationale.
    """

    movie: Movie
    score: float
    reasons: tuple[Reason, ...] = ()
    is_fallback: bool = False

    @model_validator(mode="after")
    def _personalised_results_carry_reasons(self) -> Self:
        """A non-fallback recommendation must explain itself."""
        if not self.is_fallback and not self.reasons:
            raise ValueError(
                f"{self.movie.movie_id}: personalised recommendation has no reasons; "
                "set is_fallback=True if this is the cold-start path"
            )
        return self


class RecommendRequest(BaseModel):
    """Request body for POST /recommend."""

    model_config = ConfigDict(extra="forbid")

    profile: TasteProfile
    limit: int = Field(default=20, ge=1, le=100)
    exclude_movie_ids: tuple[str, ...] = ()


class RecommendResponse(BaseModel):
    """Response body for POST /recommend.

    `manifest` identifies the exact artifact set that produced these results, so a
    surprising recommendation can be traced to the build that generated it.
    """

    model_config = ConfigDict(extra="forbid")

    items: tuple[Recommendation, ...]
    cold_start: bool
    manifest: str = Field(min_length=1)


class ArtifactManifest(BaseModel):
    """Content hashes of every artifact the API loads at boot.

    The API verifies these on startup and refuses to serve if any file's hash differs
    (FLOW.md §4). Serving stale or partially-written artifacts silently is worse than
    not starting.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_hash: str = Field(min_length=1)
    built_at: str = Field(min_length=1)
    files: dict[str, str]
    row_counts: dict[str, int] = Field(default_factory=dict)
