"""Cast in the browser: the Starring line, finding a person by name, and a person's titles."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def test_search_offers_people_and_their_page_lists_titles(
    open_cast_page: Callable[..., Any],
) -> None:
    page = open_cast_page(1280)
    assert "actor" in page.get_attribute("#q", "placeholder").lower()
    page.fill("#q", "Ann Act")
    page.wait_for_selector("#results .thumb.person", timeout=10_000)
    assert page.locator("#results .group-label").first.inner_text().lower() == "people"
    assert "Ann Actor" in page.inner_text("#results")
    page.click("#results button:has(.thumb.person)")
    page.wait_for_selector("#film-body ul.person-grid .tile", timeout=10_000)
    assert page.inner_text("#film-title") == "Ann Actor"
    # Ann is billed in films 1, 2 and 4; the other two films have different casts.
    assert 1 <= page.locator("#film-body ul.person-grid .tile").count() <= 3


def test_a_film_page_names_its_cast_and_a_name_opens_that_person(
    open_cast_page: Callable[..., Any],
) -> None:
    page = open_cast_page(1280)
    page.fill("#q", "Ann Act")
    page.wait_for_selector("#results .thumb.person", timeout=10_000)
    page.click("#results button:has(.thumb.person)")
    page.wait_for_selector("#film-body ul.person-grid .tile-btn", timeout=10_000)
    page.click("#film-body ul.person-grid .tile-btn >> nth=0")
    page.wait_for_selector("#film-body .starring", timeout=10_000)
    assert page.inner_text("#film-body .starring").startswith("Starring")
    page.click("#film-body .starring .link-btn >> nth=0")
    page.wait_for_function(
        "() => document.querySelector('#film-body ul.person-grid') !== null", timeout=10_000
    )


def test_a_name_that_matches_nobody_says_so(open_cast_page: Callable[..., Any]) -> None:
    page = open_cast_page(1280)
    page.fill("#q", "Zzzyx Qwv")
    page.wait_for_selector("#results .note", timeout=10_000)
    assert "No film, series or person" in page.inner_text("#results")


def test_a_build_without_cast_shows_no_people_and_no_actor_placeholder(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    assert "actor" not in (page.get_attribute("#q", "placeholder") or "").lower()
    page.fill("#q", "Ann")
    page.wait_for_selector("#results:not([hidden])", timeout=10_000)
    assert page.locator("#results .thumb.person").count() == 0
