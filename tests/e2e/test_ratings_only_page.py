"""Films we hold only ratings for say so on the page, and are never offered as a pick."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_JAPANESE_SHELF = "section.rail[data-rail='lang-ja']"


def test_a_ratings_only_tile_is_labelled_and_never_the_spotlight(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    page.wait_for_selector(f"{_JAPANESE_SHELF} .tile", timeout=20_000)
    labels = page.locator(f"{_JAPANESE_SHELF} .tile-why").all_inner_texts()
    assert len(labels) >= 4 and set(labels) == {"Ratings only"}
    assert "Anime film" not in page.inner_text("#spotlight")
    picks = page.locator("section.rail[data-rail='picks'] .tile-title").all_inner_texts()
    assert not [t for t in picks if t.startswith("Anime film")], picks


def test_the_japanese_chip_asks_for_japanese_and_the_posters_say_so(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    page.wait_for_selector(f"{_JAPANESE_SHELF} .tile", timeout=20_000)
    assert page.locator("#lang-chips .chip").all_inner_texts()[-2:] == ["Japanese", "French"]
    bodies: list[dict[str, Any]] = []
    page.on(
        "request",
        lambda r: bodies.append(r.post_data_json) if r.url.endswith("/shelves") else None,
    )
    page.click("#lang-chips .chip >> text=Japanese")
    page.wait_for_function(
        "() => document.querySelectorAll('#rails .tile').length > 0"
        " && !document.querySelector('#rails [aria-busy=true]')"
    )
    page.wait_for_timeout(900)
    assert bodies[-1]["languages"] == ["ja"]
    badges = set(page.locator("#rails .badge.lang").all_inner_texts())
    assert badges == {"Japanese"}, badges


def test_the_film_page_of_a_ratings_only_film_gives_its_imdb_numbers_and_no_receipt(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    page.wait_for_selector(f"{_JAPANESE_SHELF} .tile", timeout=20_000)
    page.click(f"{_JAPANESE_SHELF} .tile-btn >> nth=0")
    page.wait_for_selector("#film-body .ratings-only-note", timeout=10_000)
    text = page.inner_text("#film-body")
    assert "not read reviews of this film" in text
    assert "IMDb rating" in text and "votes" in text
    assert "What reviewers say" not in text
