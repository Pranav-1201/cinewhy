"""Where to watch in the browser: the picker, the per-country list, the date and the credit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _open_first_film(page: Any) -> None:
    page.wait_for_selector("#rails .tile-btn", timeout=20_000)
    page.click("#rails .tile-btn >> nth=0")
    page.wait_for_selector("#film-body .film-actions", timeout=10_000)


def test_the_film_page_lists_platforms_for_the_visitors_country(
    open_watch_page: Callable[..., Any],
) -> None:
    page = open_watch_page(1280)
    _open_first_film(page)
    page.wait_for_selector("#film-body .watch .watch-list", timeout=10_000)
    # The first guess is the browser's own region when the title is on offer there; this machine's
    # locale decides which that is, so the test reads it rather than assuming one.
    tag = page.evaluate("navigator.language")
    region = tag.split("-")[1].upper() if "-" in tag else None
    expected = region if region in ("IN", "US") else "IN"
    assert page.locator("#film-body .watch select").input_value() == expected
    page.select_option("#film-body .watch select", "US")
    rows = page.locator("#film-body .watch-list").inner_text()
    assert "Netflix" in rows and "Stream · Rent" in rows
    assert "Amazon Prime Video" in rows and "Buy" in rows
    assert "Crunchyroll" not in rows  # only what is offered here, never the other platforms


def test_choosing_another_country_changes_the_list_and_is_remembered(
    open_watch_page: Callable[..., Any],
) -> None:
    page = open_watch_page(1280)
    _open_first_film(page)
    page.wait_for_selector("#film-body .watch select", timeout=10_000)
    # Pick the country that is NOT the first guess, so remembering it is a real change.
    other = "US" if page.locator("#film-body .watch select").input_value() == "IN" else "IN"
    page.select_option("#film-body .watch select", "IN")
    rows = page.locator("#film-body .watch-list").inner_text()
    assert "Netflix" in rows and "Stream" in rows and "Rent" not in rows
    assert "Amazon Prime Video" not in rows
    page.select_option("#film-body .watch select", other)
    page.keyboard.press("Escape")
    page.click("#rails .tile-btn >> nth=1")
    page.wait_for_selector("#film-body .watch select", timeout=10_000)
    assert page.locator("#film-body .watch select").input_value() == other


def test_the_list_is_dated_credited_and_links_to_tmdb(open_watch_page: Callable[..., Any]) -> None:
    page = open_watch_page(1280)
    _open_first_film(page)
    page.wait_for_selector("#film-body .watch-note", timeout=10_000)
    note = page.inner_text("#film-body .watch-note")
    assert "As of 2026-11-03" in note and "powered by JustWatch" in note
    link = page.locator("#film-body .watch-note a")
    assert link.get_attribute("href") == "https://www.themoviedb.org/movie/603/watch"
    assert link.get_attribute("rel") == "noopener noreferrer"


def test_a_build_without_availability_shows_no_where_to_watch(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    _open_first_film(page)
    assert page.locator("#film-body .watch").count() == 0
