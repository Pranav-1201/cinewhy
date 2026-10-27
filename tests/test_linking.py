"""The title-and-year join rules (FEATURE-004).

Every rule here exists because a measurement showed the naive version attaching reviews to the
wrong film: ebD includes TV series ("(1968-  )"), RT's runtime disagrees with TMDB's for the
wrong film but not the right one, and a title shared by two candidates cannot be resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cinewhy.data.linking import (
    Candidate,
    ambiguous_candidate_keys,
    match_film,
    parse_ebd_movie,
    runtimes_agree,
    title_key,
    with_unique_original_titles,
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


def test_adjacent_year_needs_a_runtime_to_confirm_it() -> None:
    # A source with no runtime (ebD) gives an adjacent-year hit nothing to be checked against;
    # a title that merely recurs a year apart (a remake, a re-release) would be accepted blind.
    index = {title_key("Heat") + "1996": [_Item("no-runtime", None)]}
    assert match_film(_cand(), index, _runtime).status == "none"
    # ...but the same hit with a known, agreeing runtime is accepted.
    confirmed = {title_key("Heat") + "1996": [_Item("confirmed", 172.0)]}
    assert match_film(_cand(), confirmed, _runtime).status == "adjacent"
    # An unknown runtime on the candidate side is equally unconfirmed.
    assert match_film(_cand(runtime=0.0), confirmed, _runtime).status == "none"


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


def test_title_key_folds_accents_instead_of_dropping_the_letter() -> None:
    # Dropping gave "amlie", so a title written with and without its accent was two keys.
    assert title_key("Am" + chr(0xE9) + "lie") == title_key("Amelie") == "amelie"
    assert title_key("Stra" + chr(0xDF) + "e") == "strasse"
    assert title_key(chr(0xC6) + "on Flux") == "aeonflux"
    assert (
        title_key("Cr" + chr(0xE8) + "me Br" + chr(0xFB) + "l" + chr(0xE9) + "e") == "cremebrulee"
    )
    assert title_key("".join(chr(c) for c in (0x30A2, 0x30CB, 0x30E1))) == ""  # kana: no key at all


def test_the_original_title_is_tried_only_when_the_english_one_finds_nothing() -> None:
    original = "Sen to Chihiro"
    index = {title_key(original) + "2001": [_Item("found-on-original", 125.0)]}
    plain = _cand(title="Spirited Away", year=2001, language="ja", runtime=125.0)
    assert match_film(plain, index, _runtime).status == "none"
    both = replace(plain, original_title=original)
    result = match_film(both, index, _runtime)
    assert result.status == "exact" and result.via_original is True
    assert result.item == _Item("found-on-original", 125.0)


def test_a_runtime_refusal_on_the_english_title_is_final_too() -> None:
    # Same English title and year, but a 40-minute gap: a different film. The original title has an
    # agreeing record; taking it would turn "that is a different film" into a link.
    index = {
        title_key("Spirited Away") + "2001": [_Item("a-short", 85.0)],
        title_key("Sen to Chihiro") + "2001": [_Item("agrees", 125.0)],
    }
    film = _cand(title="Spirited Away", year=2001, language="ja", runtime=125.0)
    film = replace(film, original_title="Sen to Chihiro")
    result = match_film(film, index, _runtime)
    assert result.status == "runtime_rejected" and result.item is None


def test_the_english_title_wins_and_a_refusal_on_it_is_final() -> None:
    index = {
        title_key("Spirited Away") + "2001": [_Item("english", 125.0)],
        title_key("Sen to Chihiro") + "2001": [_Item("original", 125.0)],
    }
    both = _cand(title="Spirited Away", year=2001, language="ja", runtime=125.0)
    both = replace(both, original_title="Sen to Chihiro")
    won = match_film(both, index, _runtime)
    assert won.item == _Item("english", 125.0) and won.via_original is False
    # An ambiguous English title ends the search: falling through to the original would turn a
    # refusal into a guess.
    index[title_key("Spirited Away") + "2001"] = [_Item("a", 125.0), _Item("b", 125.0)]
    assert match_film(both, index, _runtime).status == "ambiguous"


def test_an_original_title_with_the_same_key_is_not_tried_twice() -> None:
    both = replace(_cand(), original_title="HEAT!")
    assert match_film(both, {}, _runtime).status == "none"


def test_an_original_title_another_film_also_uses_is_given_up() -> None:
    a = replace(_cand(title="Film A", year=2001), original_title="Shared Name")
    b = replace(_cand(title="Film B", year=2001), original_title="Shared Name")
    c = replace(_cand(title="Shared Name", year=2001), original_title=None)
    d = replace(_cand(title="Film D", year=2001), original_title="Only Mine")
    kept = {x.title: x.original_title for x in with_unique_original_titles([a, b, c, d])}
    assert kept == {
        "Film A": None,
        "Film B": None,
        "Shared Name": None,
        "Film D": "Only Mine",
    }
    # A different YEAR is a different key, so the same original title in another year is fine.
    e = replace(_cand(title="Film E", year=2005), original_title="Shared Name")
    assert with_unique_original_titles([a, e])[1].original_title == "Shared Name"


def test_a_title_with_no_latin_letters_never_links_on_the_year_alone() -> None:
    # The key keeps only ASCII letters and digits, so a kana title is the bare year "2001" and
    # would link to the one source record of that year whose own title is also all non-Latin.
    kana = "".join(chr(code) for code in (0x30A2, 0x30CB, 0x30E1))
    index = {"2001": [_Item("some-other-film", 100.0)]}
    result = match_film(_cand(title=kana, year=2001, language="ja", runtime=100.0), index, _runtime)
    assert result.status == "none"
    assert result.item is None


def test_candidates_sharing_a_key_are_flagged() -> None:
    a = Candidate(1, "Don", 2006, "hi", 170.0)
    b = Candidate(2, "Don", 2006, "hi", 120.0)
    c = Candidate(3, "Dangal", 2016, "hi", 161.0)
    assert ambiguous_candidate_keys([a, b, c]) == {title_key("Don") + "2006"}
