"""The top pick shows what the film page shows, and the reasons sit behind one yellow button."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_SPOTLIGHT = "#spotlight .spotlight"


def _wait(page: Any) -> None:
    page.wait_for_selector(f"{_SPOTLIGHT} h1", timeout=20_000)
    page.wait_for_selector(f"{_SPOTLIGHT} .film-actions", timeout=20_000)


def test_the_top_pick_shows_cast_answers_links_and_where_to_watch(
    open_rich_page: Callable[..., Any],
) -> None:
    page = open_rich_page(1280)
    _wait(page)
    pick = page.locator(_SPOTLIGHT)
    assert pick.locator(".starring").inner_text().startswith("Starring")
    assert pick.locator(".starring .link-btn").all_inner_texts() == ["Ann Actor", "Ben Actor"]
    row = pick.locator(".actions").inner_text()
    for label in ("Like", "Not for me", "I've watched it", "Want to watch", "IMDb"):
        assert label in row, row
    assert pick.locator(".watch .watch-list").count() == 1
    assert (
        pick.locator(".watch select").input_value() == "IN"
    )  # India unless the visitor chose another
    assert "powered by JustWatch" in pick.locator(".watch-note").inner_text()


def test_the_yellow_button_is_called_why_we_chose_this_and_the_receipts_are_gone(
    open_rich_page: Callable[..., Any],
) -> None:
    page = open_rich_page(1280)
    _wait(page)
    pick = page.locator(_SPOTLIGHT)
    assert pick.locator(".btn.primary").all_inner_texts() == ["Why we chose this"]
    # The excerpt of reasons is no longer on the pick itself.
    assert pick.locator(".receipt, .receipts").count() == 0
    assert "Why we picked this" not in pick.inner_text()
    assert "See all the receipts" not in pick.inner_text()


def test_why_we_chose_this_opens_the_film_page_at_its_receipts(
    open_rich_page: Callable[..., Any],
) -> None:
    # A window so short that the receipt, below the poster, cast, answers and where-to-watch, is
    # off screen unless the page scrolled to it: without the scroll this fails.
    height = 380
    page = open_rich_page(1280, height=height)
    _wait(page)
    page.click(f"{_SPOTLIGHT} .btn.primary")
    page.wait_for_selector("#film-body .receipt", timeout=10_000)
    page.wait_for_timeout(300)
    top = page.evaluate("document.querySelector('#film-body .receipt').getBoundingClientRect().top")
    assert 0 <= top < height, f"the receipt is not in view (top={top})"


def test_an_answer_on_the_top_pick_is_a_real_answer(open_rich_page: Callable[..., Any]) -> None:
    page = open_rich_page(1280)
    _wait(page)
    like = page.locator(f"{_SPOTLIGHT} .actions .btn", has_text="Like").first
    assert like.get_attribute("aria-pressed") == "false"
    like.click()
    assert like.get_attribute("aria-pressed") == "true"
    assert like.inner_text() == "Liked"


def test_a_build_without_cast_or_availability_still_has_the_answers_and_the_button(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    _wait(page)
    pick = page.locator(_SPOTLIGHT)
    assert pick.locator(".starring").count() == 0
    assert pick.locator(".watch").count() == 0
    assert pick.locator(".btn.primary").all_inner_texts() == ["Why we chose this"]
    assert "I've watched it" in pick.locator(".actions").inner_text()
