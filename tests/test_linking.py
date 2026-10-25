"""The title-and-year join rules (FEATURE-004).

Every rule here exists because a measurement showed the naive version attaching reviews to the
wrong film: ebD includes TV series ("(1968-  )"), RT's runtime disagrees with TMDB's for the
wrong film but not the right one, and a title shared by two candidates cannot be resolved.
"""

from __future__ import annotations

from dataclasses import dataclass

from cinewhy.data.linking import (
    Candidate,
    ambiguous_candidate_keys,
    match_film,
    parse_ebd_movie,
    runtimes_agree,
    title_key,
)

# ebD writes a series' open range with an en dash; built from a code point so the file stays ASCII.
_EN_DASH = chr(0x2013)


@dataclass(frozen=True)
class _Item:
    name: str
    runtime: float | None


def _runtime(item: _Item) -> float | None:
    return item.runtime


def _cand(
    title: str = "Heat", year: int = 1995, language: str = "en", runtime: float = 170.0
) -> Candidate:
    return Candidate(imdb_id=113277, title=title, year=year, language=language, runtime=runtime)


def test_title_key_ignores_case_punctuation_and_spacing() -> None:
    assert title_key("Spider-Man: Far From Home") == title_key("spider man far from home")
    assert title_key("Heat") != title_key("Heat 2")


def test_parse_ebd_movie_accepts_a_film() -> None:
    assert parse_ebd_movie("Kill Bill: Vol. 2 (2004)") == ("Kill Bill: Vol. 2", 2004)


def test_parse_ebd_movie_rejects_series_and_other_formats() -> None:
    # A TV series carries an open year range; letting it match a film with the same title
    # would hand a series' reviews to a film (measured: 5.5% of English text counts).
    assert parse_ebd_movie(f"Journey to the Unknown (1968{_EN_DASH} )") is None
    assert parse_ebd_movie(f"Some Show (2009{_EN_DASH}2013)") is None
    assert parse_ebd_movie("A Video Release (2009 Video)") is None
    assert parse_ebd_movie("No year at all") is None


def test_runtimes_agree_when_close_or_unknown() -> None:
    assert runtimes_agree(100.0, 108.0, tolerance=15.0)
    assert not runtimes_agree(100.0, 140.0, tolerance=15.0)
    # Unknown on either side means the check has no evidence either way; it must not reject.
    assert runtimes_agree(None, 140.0, tolerance=15.0)
    assert runtimes_agree(100.0, 0.0, tolerance=15.0)


def test_exact_year_match_is_accepted() -> None:
    index = {title_key("Heat") + "1995": [_Item("rt-heat", 170.0)]}
    result = match_film(_cand(), index, _runtime)
    assert result.status == "exact"
    assert result.item == _Item("rt-heat", 170.0)


def test_adjacent_year_is_used_for_english_only() -> None:
    index = {title_key("Heat") + "1996": [_Item("rt-heat", 170.0)]}
    assert match_film(_cand(language="en"), index, _runtime).status == "adjacent"
    # Hindi adjacent-year matches agreed with runtime only 57.9% of the time (n=19).
    assert match_film(_cand(language="hi"), index, _runtime).status == "none"


def test_exact_year_wins_over_adjacent() -> None:
    index = {
        title_key("Heat") + "1995": [_Item("exact", 170.0)],
        # Year BEFORE the film: the one an adjacent-first search order would reach first.
        title_key("Heat") + "1994": [_Item("adjacent", 170.0)],
    }
    assert match_film(_cand(), index, _runtime).item == _Item("exact", 170.0)


def test_two_hits_for_one_key_are_ambiguous_not_guessed() -> None:
    index = {title_key("Heat") + "1995": [_Item("a", 170.0), _Item("b", 170.0)]}
    result = match_film(_cand(), index, _runtime)
    assert result.status == "ambiguous"
    assert result.item is None


def test_runtime_mismatch_rejects_even_an_exact_year_hit() -> None:
    # Same title and year, but a 40-minute gap: a different film (a short, a remake).
    index = {title_key("Heat") + "1995": [_Item("short", 130.0)]}
    result = match_film(_cand(runtime=170.0), index, _runtime)
    assert result.status == "runtime_rejected"
    assert result.item is None


def test_no_hit_is_none() -> None:
    assert match_film(_cand(), {}, _runtime).status == "none"


def test_candidates_sharing_a_key_are_flagged() -> None:
    a = Candidate(1, "Don", 2006, "hi", 170.0)
    b = Candidate(2, "Don", 2006, "hi", 120.0)
    c = Candidate(3, "Dangal", 2016, "hi", 161.0)
    assert ambiguous_candidate_keys([a, b, c]) == {title_key("Don") + "2006"}
