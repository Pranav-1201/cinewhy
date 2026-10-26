"""What a visitor does with the profile, in a real browser: mark films, rate them, keep a library.

Every test starts from a first visit (a fresh browser profile) on the six-film synthetic catalogue.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

SHELF_TITLES = "#rails .tile-title"
# The page's security policy forbids evaluating bare expression strings, so these are functions.
# True only when the shelves have been redrawn WITH films and `t` is not among them: while the page
# reloads the shelves it shows loading placeholders with no titles, which must not count as "gone".
_GONE_FROM_FRESH_SHELVES = (
    "t => document.querySelector('#rails .tile-title') !== null"
    " && ![...document.querySelectorAll('#rails .tile-title')].some(e => e.textContent === t)"
    " && document.querySelector('#spotlight h1')?.textContent !== t"
)
_WATCHED_COUNT_IS_1 = (
    "() => JSON.parse(localStorage.getItem('cinewhy.profile.v3')).watched.length === 1"
)
_WATCHED_COUNT_IS_0 = (
    "() => JSON.parse(localStorage.getItem('cinewhy.profile.v3')).watched.length === 0"
)


def _profile(page: Any) -> dict[str, Any]:
    raw = page.evaluate("localStorage.getItem('cinewhy.profile.v3')")
    assert raw, "no profile was saved"
    return json.loads(raw)  # type: ignore[no-any-return]


def _first_shelf_film(page: Any) -> tuple[Any, str]:
    page.wait_for_selector("#rails .tile")
    tile = page.locator("#rails .tile").first
    return tile, tile.locator(".tile-title").inner_text()


def _shown_anywhere(page: Any, title: str) -> bool:
    shelves = page.locator(SHELF_TITLES).all_inner_texts()
    return title in shelves or title == page.locator("#spotlight h1").inner_text()


def test_a_watched_film_leaves_the_shelves_and_is_kept_in_the_library(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1024)
    tile, title = _first_shelf_film(page)
    tile.hover()
    tile.locator(".tile-act.seen").click()
    page.wait_for_function(_GONE_FROM_FRESH_SHELVES, arg=title, timeout=10_000)
    assert not _shown_anywhere(page, title)
    assert len(_profile(page)["watched"]) == 1

    page.click("#library-btn")
    page.wait_for_selector("#library-list .lib-row")
    assert title in page.locator("#library-list .lib-row .name").first.inner_text()
    page.click("#library-list .row-actions .btn")  # "Not watched"
    page.wait_for_selector("#library-list .note")
    assert _profile(page)["watched"] == []


def test_watched_films_come_back_when_the_visitor_asks_to_see_them(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1024)
    tile, title = _first_shelf_film(page)
    tile.hover()
    tile.locator(".tile-act.seen").click()
    page.wait_for_function(_GONE_FROM_FRESH_SHELVES, arg=title, timeout=10_000)
    page.click("#seen-chips .chip")  # "Hide films I've watched": off
    page.wait_for_function(
        "t => [...document.querySelectorAll('#rails .tile-title')].some(e => e.textContent === t)"
        " || document.querySelector('#spotlight h1')?.textContent === t",
        arg=title,
        timeout=10_000,
    )
    assert _profile(page)["hideWatched"] is False


def test_rating_a_film_in_rate_films_marks_it_watched_and_liked(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1024)
    page.click("#rate-btn")
    page.wait_for_selector("#rate-card h3")
    assert "Film 1 of" in page.inner_text(".rate-progress")
    page.click("#rate-card .star:nth-child(5)")
    page.wait_for_function(
        "() => document.querySelector('.rate-progress').textContent.startsWith('Film 2')"
    )
    saved = _profile(page)
    assert len(saved["watched"]) == 1 and len(saved["liked"]) == 1
    assert list(saved["ratings"].values()) == [5]


def test_the_first_visit_can_lead_straight_into_rating_films(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1024, skip_questions=False)
    page.click("#ob-lang .chip")  # the first language chip
    page.click("#onboard-form button[value=rate]")
    page.wait_for_selector("#rate-dialog[open]")
    page.wait_for_selector("#rate-card h3")
    saved = _profile(page)
    assert saved["onboarded"] is True and len(saved["languages"]) == 1


def test_the_profile_survives_a_download_reset_and_load(
    open_page: Callable[..., Any], tmp_path: Path
) -> None:
    page = open_page(1024)
    tile, _ = _first_shelf_film(page)
    tile.hover()
    tile.locator(".tile-act.seen").click()
    page.wait_for_function(_WATCHED_COUNT_IS_1)

    page.click("#profile-btn")
    with page.expect_download() as download:
        page.click("#profile-export")
    saved = tmp_path / "profile.json"
    download.value.save_as(saved)
    exported = json.loads(saved.read_text(encoding="utf-8"))
    assert exported["app"] == "cinewhy" and len(exported["profile"]["watched"]) == 1

    page.click("#profile-reset")
    page.click("#profile-reset")  # a second press confirms
    page.wait_for_function(_WATCHED_COUNT_IS_0)

    page.set_input_files("#profile-import", str(saved))
    page.wait_for_function(_WATCHED_COUNT_IS_1)
    assert "Profile loaded" in page.inner_text("#profile-message")


def test_a_file_that_is_not_a_profile_is_refused_with_a_reason(
    open_page: Callable[..., Any], tmp_path: Path
) -> None:
    page = open_page(1024)
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": "world"}', encoding="utf-8")
    page.click("#profile-btn")
    page.set_input_files("#profile-import", str(bad))
    page.wait_for_function(
        "() => document.querySelector('#profile-message').textContent.length > 0"
    )
    assert "not a CineWhy profile" in page.inner_text("#profile-message")
