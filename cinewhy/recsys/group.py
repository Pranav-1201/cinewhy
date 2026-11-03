"""Recommendations for a group sitting down to watch something together.

Each member is scored with the same machinery as a single visitor (`discover.score_films`), each
member's scores are turned into percentiles among the titles that could be shown (so someone with
500 likes does not outvote someone with five), and the percentiles are combined into one group
score. Three things are decided here by rule, not measured:

* **Who has seen or disliked it.** With two people a title either has watched (or liked, which means
  they know it) or disliked is out. With three or more, a title is out only when a MAJORITY of the
  group (`majority`, n // 2 + 1) is in that position; below a majority it stays in with a small
  penalty per person, because most of the group would still enjoy it.
* **Want to watch.** A title on a member's want list gets a small bonus: it is stated intent.
* **Shared filters.** Languages and kinds are the intersection of what the members asked for, or
  their union with a note when the intersection is empty.

How the percentiles are combined (`combine`) is NOT decided here: `cinewhy.recsys.group_eval`
measures the candidates on MovieLens groups and the default in `GroupConfig` is the one it chose
(D-043). Nothing is stored: a group result is computed from the members' profiles for one request
and is gone.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict
from scipy.stats import rankdata

from cinewhy.recsys.catalogue import Catalogue
from cinewhy.recsys.discover import (
    DiscoverItem,
    Scored,
    expand_languages,
    film_years,
    genre_masks,
    language_codes,
    languages_of,
    score_films,
    select_items,
)
from cinewhy.recsys.discover import _closest_liked as closest_liked
from cinewhy.schemas import Aspect, TasteProfile

Strategy = Literal["mean", "least_misery", "geometric", "blend", "lower_quartile", "intersection"]
STRATEGIES: Final[tuple[Strategy, ...]] = (
    "mean",
    "least_misery",
    "geometric",
    "blend",
    "lower_quartile",
    "intersection",
)
MIN_GROUP: Final[int] = 2
MAX_GROUP: Final[int] = (
    5  # the owner's limit for now; 20 later (D-043 measures the rule at that size)
)


def majority(n: int) -> int:
    """How many members make a majority: a single one for a pair, then more than half."""
    return 1 if n <= 2 else n // 2 + 1


@dataclass(frozen=True)
class Quiz:
    """What a member feels like watching tonight. An empty choice means no preference."""

    kinds: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()


@dataclass(frozen=True)
class Member:
    """One person's library as a group request sees it, plus what they did in the room.

    The room fields are layered on by `rooms.RoomStore.members_of` and live only in the room:
    `signals_liked` are titles swiped right (they steer similarity like a like, but are NOT "seen",
    which a real like would be); `passed` are titles swiped left; `top` is the one title they
    nominated above all others and `former_tops` the ones it replaced.
    """

    name: str
    taste: TasteProfile
    watched: frozenset[str] = frozenset()
    want: frozenset[str] = frozenset()
    languages: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    quiz: Quiz = Quiz()
    signals_liked: tuple[str, ...] = ()
    passed: frozenset[str] = frozenset()
    top: str | None = None
    former_tops: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GroupConfig:
    """The knobs of a group request; the defaults are the measured and chosen ones."""

    # "mean", chosen on validation groups of 2, 3 and 5 by the rule fixed in `group_eval` before the
    # run (D-043). It is the simplest of the candidates and was never measurably behind the best;
    # it is NOT shown to beat the others at 2 or 3, where the metric is at its ceiling.
    strategy: Strategy = "mean"
    # Weight of the group mean against the least-happy member in the "blend" strategy.
    blend: float = 0.5
    recency: float = 0.5
    receipts_only: bool = True
    # Penalties and the bonus are on the percentile scale (0 to 1) and scale with the share of the
    # group they apply to: "a little", by the owner's rule. Design choices, not measured values.
    seen_penalty: float = 0.10
    dislike_penalty: float = 0.20
    want_bonus: float = 0.15
    # A member's one top pick counts four times a plain "want"; a top pick they later replaced keeps
    # a smaller bonus, still above a plain want (owner's rule, 2026-11-04). Design choices.
    top_bonus: float = 0.60
    former_top_bonus: float = 0.25
    # Per quiz category (kind, language, genre): a title loses up to this much, in proportion to how
    # few of the people who answered that category chose what the title is. Never excludes.
    quiz_penalty: float = 0.20
    # How deep each member's list goes for the "intersection" baseline.
    intersection_depth: int = 50


@dataclass(frozen=True)
class MemberVectors:
    """One member over the candidate titles: their percentile and what they have said about each."""

    pct: npt.NDArray[np.float64]
    seen: npt.NDArray[np.bool_]  # watched, or liked (which means they know it)
    disliked: npt.NDArray[np.bool_]
    wants: npt.NDArray[np.bool_]
    tops: npt.NDArray[np.bool_] | None = None  # the member's one top pick
    former: npt.NDArray[np.bool_] | None = None  # top picks they replaced


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MemberFit(_Frozen):
    """How one member stands to a title in the group's list."""

    name: str
    percentile: float  # 1.0 is their best title among the candidates
    saw_it: bool
    disliked: bool
    wants: bool
    because: str | None = None  # the title they liked that this is closest to
    top: bool = False  # this is the member's one top pick


class GroupItem(_Frozen):
    """A title in the group's list, with the group's score and where each member stands."""

    item: DiscoverItem
    members: tuple[MemberFit, ...]
    seen_by: int
    disliked_by: int
    wanted_by: int
    penalty: float


class GroupResult(_Frozen):
    """The group's ranked titles and the rules that produced them."""

    items: tuple[GroupItem, ...]
    members: int
    majority: int
    strategy: str
    notes: tuple[str, ...] = ()


def percentiles(scores: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Each score as its rank from 0 (lowest) to 1 (highest); ties share their average rank."""
    if scores.size <= 1:
        return np.ones_like(scores, dtype=np.float64)
    ranks = np.asarray(rankdata(scores, method="average"), dtype=np.float64)
    return (ranks - 1.0) / (scores.size - 1)


def combine(
    pct: npt.NDArray[np.float64],
    strategy: Strategy,
    *,
    blend: float = 0.5,
    depth: int = 50,
) -> npt.NDArray[np.float64]:
    """One group score per title from the members' percentiles (`pct` is members x titles).

    * ``mean``: the average member.
    * ``least_misery``: the least-happy member.
    * ``geometric``: the geometric mean, which punishes a low score more than the mean does.
    * ``blend``: `blend` x mean + (1 - `blend`) x least-happy.
    * ``lower_quartile``: the mean of the least-happy quarter of the group (at least one person):
      the least-misery idea without letting one mild dislike decide a large group.
    * ``intersection``: the naive baseline. Titles in EVERY member's top `depth` come first, ranked
      by mean; everything else follows, ranked by mean.
    """
    mean = pct.mean(axis=0)
    if strategy == "mean":
        return np.asarray(mean, dtype=np.float64)
    if strategy == "least_misery":
        return np.asarray(pct.min(axis=0), dtype=np.float64)
    if strategy == "geometric":
        return np.asarray(np.exp(np.log(pct + 1e-6).mean(axis=0)), dtype=np.float64)
    if strategy == "blend":
        return np.asarray(blend * mean + (1.0 - blend) * pct.min(axis=0), dtype=np.float64)
    if strategy == "lower_quartile":
        k = max(1, int(np.ceil(pct.shape[0] / 4)))
        return np.asarray(np.sort(pct, axis=0)[:k].mean(axis=0), dtype=np.float64)
    if strategy == "intersection":
        depth = min(depth, pct.shape[1])
        cutoff = np.sort(pct, axis=1)[:, -depth][:, None]
        in_every_list = (pct >= cutoff).all(axis=0)
        return np.asarray(mean + 10.0 * in_every_list, dtype=np.float64)
    raise ValueError(f"unknown strategy {strategy!r}")


def group_scores(
    vectors: Sequence[MemberVectors], config: GroupConfig | None = None
) -> npt.NDArray[np.float64]:
    """The group's score for every candidate title, minus infinity where the rule rules it out."""
    config = config or GroupConfig()
    n = len(vectors)
    pct = np.vstack([v.pct for v in vectors])
    base = combine(pct, config.strategy, blend=config.blend, depth=config.intersection_depth)
    knows = np.vstack([v.seen | v.disliked for v in vectors]).sum(axis=0)
    disliked = np.vstack([v.disliked for v in vectors]).sum(axis=0)
    seen_only = np.vstack([v.seen & ~v.disliked for v in vectors]).sum(axis=0)
    wanted = np.vstack([v.wants for v in vectors]).sum(axis=0)
    zero = np.zeros_like(wanted)
    tops = np.vstack([v.tops if v.tops is not None else zero > 0 for v in vectors]).sum(axis=0)
    former = np.vstack([v.former if v.former is not None else zero > 0 for v in vectors]).sum(
        axis=0
    )
    penalty = config.seen_penalty * (seen_only / n) + config.dislike_penalty * (disliked / n)
    bonus = (
        config.want_bonus * wanted + config.top_bonus * tops + config.former_top_bonus * former
    ) / n
    final = base - penalty + bonus
    final[knows >= majority(n)] = -np.inf
    return np.asarray(final, dtype=np.float64)


def _agreed(choices: list[set[str]], what: str, notes: list[str]) -> set[str]:
    """What the members who chose anything agree on, or all they named when they share nothing."""
    stated = [c for c in choices if c]
    if not stated:
        return set()
    common = set.intersection(*stated)
    if common:
        return common
    notes.append(f"The group shares no {what}, so titles in any {what} asked for are shown.")
    return set.union(*stated)


def eligible_titles(
    catalogue: Catalogue,
    members: Sequence[Member],
    config: GroupConfig,
    exclude: Collection[str] = (),
) -> tuple[npt.NDArray[np.bool_], list[str]]:
    """Which titles may be shown to this group at all, and any notes about the filters used.

    Languages and kinds are what the members agree on; where they share nothing the union is used
    and a note says so, so a group with no common language still gets an answer.
    """
    n = len(catalogue.all_movies)
    allowed = np.ones(n, dtype=bool)
    notes: list[str] = []
    if config.receipts_only:
        allowed[len(catalogue.movies) :] = False
    chosen_languages = _agreed([set(m.languages) for m in members], "language", notes)
    if chosen_languages:
        allowed &= np.isin(language_codes(catalogue), list(expand_languages(chosen_languages)))
    chosen_kinds = _agreed([set(m.kinds) for m in members], "kind", notes)
    if chosen_kinds == {"series"}:
        allowed &= catalogue.is_series
    elif chosen_kinds == {"film"}:
        allowed &= ~catalogue.is_series
    for movie_id in exclude:
        position = catalogue.all_index.get(movie_id)
        if position is not None:
            allowed[position] = False
    return allowed, notes


def member_vectors(
    catalogue: Catalogue, member: Member, candidates: npt.NDArray[np.intp], *, recency: float
) -> tuple[MemberVectors, Scored]:
    """One member's percentiles and answers over the candidate titles (`candidates` positions)."""
    taste = member.taste
    if member.signals_liked or member.passed:
        # Right swipes steer similarity like likes and left swipes like dislikes, for this request
        # only (the member's own library is never changed).
        taste = TasteProfile(
            aspect_weights=taste.aspect_weights,
            liked_movie_ids=(*taste.liked_movie_ids, *member.signals_liked),
            disliked_movie_ids=(*taste.disliked_movie_ids, *sorted(member.passed)),
        )
    scored = score_films(catalogue, taste, recency=recency)
    slot = np.full(len(catalogue.all_movies), -1, dtype=np.intp)
    slot[candidates] = np.arange(candidates.size)

    def mask(ids: Collection[str]) -> npt.NDArray[np.bool_]:
        out = np.zeros(candidates.size, dtype=bool)
        for movie_id in ids:
            position = catalogue.all_index.get(movie_id)
            if position is not None and slot[position] >= 0:
                out[slot[position]] = True
        return out

    vectors = MemberVectors(
        pct=percentiles(scored.score[candidates]),
        seen=mask(member.watched) | mask(member.taste.liked_movie_ids),
        disliked=mask(member.taste.disliked_movie_ids) | mask(member.passed),
        wants=mask(member.want),
        tops=mask([member.top] if member.top else []),
        former=mask(member.former_tops),
    )
    return vectors, scored


def quiz_penalties(
    catalogue: Catalogue,
    members: Sequence[Member],
    candidates: npt.NDArray[np.intp],
    config: GroupConfig,
) -> npt.NDArray[np.float64]:
    """How much each candidate title loses for not matching the group's quiz answers.

    For each category (kind, language, genre) only the members who chose something count. A title's
    share is the fraction of them who chose what it is (for genres, its best-liked genre), and it
    loses `quiz_penalty` x (1 - share): comedy picked by one person of three costs about two thirds
    of the penalty, and a title nobody's choice matches costs all of it. Nothing is ruled out, and
    a category nobody answered costs nothing.
    """
    out = np.zeros(candidates.size, dtype=np.float64)

    def share_by_choice(choices: list[set[str]]) -> dict[str, float]:
        stated = [c for c in choices if c]
        if not stated:
            return {}
        every = set().union(*stated)
        return {name: sum(1 for c in stated if name in c) / len(stated) for name in every}

    kind_share = share_by_choice([set(m.quiz.kinds) for m in members])
    if kind_share:
        is_series = catalogue.is_series[candidates]
        share = np.where(is_series, kind_share.get("series", 0.0), kind_share.get("film", 0.0))
        out += config.quiz_penalty * (1.0 - share)
    language_share = share_by_choice([set(expand_languages(m.quiz.languages)) for m in members])
    if language_share:
        codes = language_codes(catalogue)[candidates]
        share = np.array([language_share.get(str(code), 0.0) for code in codes], dtype=np.float64)
        out += config.quiz_penalty * (1.0 - share)
    genre_share = share_by_choice([set(m.quiz.genres) for m in members])
    if genre_share:
        masks = genre_masks(catalogue)
        best = np.zeros(candidates.size, dtype=np.float64)
        for genre, value in genre_share.items():
            if genre in masks:
                best = np.maximum(best, np.where(masks[genre][candidates], value, 0.0))
        out += config.quiz_penalty * (1.0 - best)
    return out


def _group_weights(weights: Sequence[dict[Aspect, float]]) -> dict[Aspect, float]:
    """The members' aspect weights averaged, so the reasons on a card speak for the group."""
    total: dict[Aspect, float] = {}
    for member_weights in weights:
        for aspect, weight in member_weights.items():
            total[aspect] = total.get(aspect, 0.0) + weight / len(weights)
    return total


def recommend_group(
    catalogue: Catalogue,
    members: Sequence[Member],
    *,
    limit: int = 10,
    config: GroupConfig | None = None,
    exclude: Collection[str] = (),
) -> GroupResult:
    """The titles best for this group, with each member's standing on each.

    Args:
        catalogue: The loaded catalogue.
        members: Two or more members (the cap is the caller's rule: `MAX_GROUP`).
        limit: Most titles to return.
        config: The strategy and the penalty and bonus sizes.
        exclude: Title ids never to return (the ones already shown in this session).

    Raises:
        ValueError: If there are fewer than two members.
    """
    config = config or GroupConfig()
    if len(members) < MIN_GROUP:
        raise ValueError(f"a group needs at least {MIN_GROUP} people")
    n = len(members)
    allowed, notes = eligible_titles(catalogue, members, config, exclude)
    candidates = np.flatnonzero(allowed)
    if candidates.size == 0:
        return GroupResult(
            items=(), members=n, majority=majority(n), strategy=config.strategy, notes=tuple(notes)
        )
    prepared = [member_vectors(catalogue, m, candidates, recency=config.recency) for m in members]
    final = group_scores([v for v, _ in prepared], config)
    final = final - quiz_penalties(catalogue, members, candidates, config)
    full = np.full(len(catalogue.all_movies), -np.inf)
    full[candidates] = final
    finite = np.flatnonzero(np.isfinite(full))
    order = finite[np.lexsort((finite, -full[finite]))].tolist()
    scored_group = Scored(
        score=full,
        weights=_group_weights([s.weights for _, s in prepared]),
        cold=all(s.cold for _, s in prepared),
        years=film_years(catalogue),
        language_of=languages_of(catalogue),
        order=order,
        liked=[],
        n_core=len(catalogue.movies),
    )
    items = select_items(
        catalogue,
        scored_group,
        limit=limit,
        include_ratings_only=not config.receipts_only,
        order=order,
    )
    slot = {int(p): k for k, p in enumerate(candidates)}
    out: list[GroupItem] = []
    for item in items:
        position = catalogue.all_index[item.movie.movie_id]
        k = slot[position]
        fits = tuple(
            MemberFit(
                name=m.name,
                percentile=float(v.pct[k]),
                saw_it=bool(v.seen[k]),
                disliked=bool(v.disliked[k]),
                wants=bool(v.wants[k]),
                because=closest_liked(catalogue, s.liked, position),
                top=bool(v.tops[k]) if v.tops is not None else False,
            )
            for m, (v, s) in zip(members, prepared, strict=True)
        )
        seen_by = sum(1 for f in fits if f.saw_it and not f.disliked)
        disliked_by = sum(1 for f in fits if f.disliked)
        penalty = config.seen_penalty * seen_by / n + config.dislike_penalty * disliked_by / n
        out.append(
            GroupItem(
                item=item,
                members=fits,
                seen_by=seen_by,
                disliked_by=disliked_by,
                wanted_by=sum(1 for f in fits if f.wants),
                penalty=penalty,
            )
        )
    return GroupResult(
        items=tuple(out),
        members=n,
        majority=majority(n),
        strategy=config.strategy,
        notes=tuple(notes),
    )
