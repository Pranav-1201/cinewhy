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
    # A new profile is India's, whatever the browser's own language says.
    assert page.locator("#film-body .watch select").input_value() == "IN"
    rows = page.locator("#film-body .watch-list").inner_text()
    assert "Netflix" in rows and "Stream" in rows and "Rent" not in rows
    assert "Amazon Prime Video" not in rows  # the fixture sells it only in the US
    page.select_option("#film-body .watch select", "US")
    rows = page.locator("#film-body .watch-list").inner_text()
    assert "Netflix" in rows and "Stream · Rent" in rows
    assert "Amazon Prime Video" in rows and "Buy" in rows
    assert "Crunchyroll" not in rows  # only what is offered here, never the other platforms


def test_a_new_visitor_opens_on_india_even_with_another_browser_language(
    browser: Any, availability_server_url: str
) -> None:
    context = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800})
    try:
        page = context.new_page()
        page.goto(availability_server_url)
        page.wait_for_selector("#onboard-dialog[open]", timeout=20_000)
        page.click("#onboard-form button[value=skip]")
        _open_first_film(page)
        page.wait_for_selector("#film-body .watch select", timeout=10_000)
        assert page.evaluate("navigator.language") == "en-US"
        assert page.locator("#film-body .watch select").input_value() == "IN"
    finally:
        context.close()


def test_choosing_another_country_is_saved_to_the_profile(
    open_watch_page: Callable[..., Any],
) -> None:
    page = open_watch_page(1280)
    _open_first_film(page)
    page.wait_for_selector("#film-body .watch select", timeout=10_000)
    page.select_option("#film-body .watch select", "US")
    saved = page.evaluate("JSON.parse(localStorage.getItem('cinewhy.profile.v3')).country")
    assert saved == "US"
    page.keyboard.press("Escape")
    page.click("#rails .tile-btn >> nth=1")
    page.wait_for_selector("#film-body .watch select", timeout=10_000)
    assert page.locator("#film-body .watch select").input_value() == "US"


def test_a_title_not_offered_in_the_visitors_country_says_so_instead_of_showing_another(
    open_watch_page: Callable[..., Any],
) -> None:
    page = open_watch_page(1280)
    page.wait_for_selector("#rails .tile-btn", timeout=20_000)
    # cw-2 is offered only in the US in this build; the visitor is in India.
    page.evaluate("import('/js/film.js').then((m) => m.openFilm('cw-2'))")
    page.wait_for_selector("#film-body .watch select", timeout=10_000)
    assert page.locator("#film-body .watch select").input_value() == "IN"
    assert "India" in page.locator("#film-body .watch-none").inner_text()
    assert page.locator("#film-body .watch-list").count() == 0  # no other country's list
    options = page.locator("#film-body .watch select option").all_inner_texts()
    assert "India" in options and "United States" in options  # and the picker can still go there
    page.select_option("#film-body .watch select", "US")
    assert "Netflix" in page.locator("#film-body .watch-list").inner_text()


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
