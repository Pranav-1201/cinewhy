"""TV series on the page: a films-or-series choice, a marker on each tile, and their own shelf."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_SERIES_SHELF = "section.rail[data-rail='series']"


def test_the_page_offers_films_and_series_and_asks_for_series_only_when_chosen(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    page.wait_for_selector("#rails .tile", timeout=20_000)
    assert page.locator("#kind-chips .chip").all_inner_texts() == ["Films", "Series"]
    bodies: list[dict[str, Any]] = []
    page.on(
        "request",
        lambda r: bodies.append(r.post_data_json) if r.url.endswith("/shelves") else None,
    )
    page.click("#kind-chips .chip >> text=Series")
    page.wait_for_function(
        "() => document.querySelectorAll('#rails .tile').length > 0"
        " && !document.querySelector('#rails [aria-busy=true]')"
    )
    page.wait_for_timeout(900)
    assert bodies[-1]["kinds"] == ["series"]
    marks = [t for t in page.locator("#rails .tile-meta").all_inner_texts() if t]
    assert marks and all(t.endswith("Series") for t in marks), marks


def test_a_series_is_marked_on_its_tile_and_has_a_shelf_of_its_own(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    page.wait_for_selector(f"{_SERIES_SHELF} .tile", timeout=20_000)
    assert page.inner_text(f"{_SERIES_SHELF} h2") == "Top series"
    marks = page.locator(f"{_SERIES_SHELF} .tile-meta").all_inner_texts()
    dot = chr(0xB7)
    assert len(marks) >= 4 and all(t.endswith(f" {dot} Series") for t in marks), marks
    # A film's tile carries just its year, with no kind.
    films = page.locator("section.rail[data-rail='picks'] .tile-meta").all_inner_texts()
    assert films and not any("Series" in t for t in films), films


def test_the_film_page_of_a_series_says_it_is_a_series(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    page.wait_for_selector(f"{_SERIES_SHELF} .tile", timeout=20_000)
    page.click(f"{_SERIES_SHELF} .tile-btn >> nth=0")
    page.wait_for_selector("#film-body .ratings-only-note", timeout=10_000)
    text = page.inner_text("#film-body")
    assert "TV series" in text and "this series yet" in text and "this film" not in text


def test_the_choice_is_kept_when_the_page_is_reloaded(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    page.wait_for_selector("#kind-chips .chip", timeout=20_000)
    page.click("#kind-chips .chip >> text=Series")
    page.reload()
    page.wait_for_selector("#kind-chips .chip", timeout=20_000)
    assert page.get_attribute("#kind-chips .chip >> text=Series", "aria-pressed") == "true"
    assert page.get_attribute("#kind-chips .chip >> text=Films", "aria-pressed") == "false"
