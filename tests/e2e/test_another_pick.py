"""'Show me another' on the top pick: it walks the ranking, never repeats, leaves lists alone."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_TITLE = "#spotlight .spotlight h1"
_BUTTONS = "#spotlight .spotlight .actions"


def _ready(page: Any) -> str:
    page.wait_for_selector(f"{_BUTTONS} .btn", timeout=20_000)
    return str(page.inner_text(_TITLE))


def _click_and_wait_for_change(page: Any, label: str, before: str) -> str:
    page.click(f"{_BUTTONS} .btn >> text='{label}'")
    page.wait_for_function(
        "(t) => { const h = document.querySelector('#spotlight .spotlight h1');"
        " return h && h.textContent !== t; }",
        arg=before,
        timeout=10_000,
    )
    page.wait_for_selector(f"{_BUTTONS} .btn", timeout=10_000)
    return str(page.inner_text(_TITLE))


def _profile(page: Any) -> dict[str, Any]:
    return page.evaluate("JSON.parse(localStorage.getItem('cinewhy.profile.v3') || '{}')")  # type: ignore[no-any-return]


def test_the_button_walks_down_the_picks_and_never_shows_a_title_twice(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    titles = [_ready(page)]
    for _ in range(12):  # the smoke set holds six films, so the walk must end well before this
        button = page.locator(f"{_BUTTONS} .btn", has_text="Show me another")
        if button.is_disabled():
            break
        page.click(f"{_BUTTONS} .btn >> text='Show me another'")
        # Either the title changes, or this click found the end: the title stays and the button is
        # disabled with its note (it only learns there is no more by asking the server).
        page.wait_for_function(
            "(t) => { const h = document.querySelector('#spotlight .spotlight h1');"
            " const b = [...document.querySelectorAll('#spotlight .actions .btn')]"
            ".find((x) => x.textContent === 'Show me another');"
            " return h && ((h.textContent !== t) || (b && b.disabled)); }",
            arg=titles[-1],
            timeout=10_000,
        )
        now = str(page.inner_text(_TITLE))
        if now != titles[-1]:
            titles.append(now)
    assert len(titles) >= 4, titles
    assert len(set(titles)) == len(titles), f"a title came back: {titles}"
    # At the end the button is disabled and says why.
    assert page.locator(f"{_BUTTONS} .btn", has_text="Show me another").is_disabled()
    assert "every pick" in page.inner_text("#spotlight .pick-note")


def test_asking_for_more_picks_wants_receipts_only_and_names_everything_already_shown(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    bodies: list[dict[str, Any]] = []
    page.on(
        "request",
        lambda r: bodies.append(r.post_data_json) if r.url.endswith("/discover") else None,
    )
    titles = [_ready(page)]
    for _ in range(12):
        if page.locator(f"{_BUTTONS} .btn", has_text="Show me another").is_disabled():
            break
        page.click(f"{_BUTTONS} .btn >> text='Show me another'")
        page.wait_for_timeout(600)
        titles.append(str(page.inner_text(_TITLE)))
    assert bodies, "the walk ran out of picks, so the page must have asked the server for more"
    request = bodies[-1]
    # The top pick promises the sentences behind it: ratings-only titles must be refused up front.
    assert request["receipts_only"] is True
    # Everything already shown is named, so the server does not hand the same titles back.
    assert len(request["exclude_movie_ids"]) >= len(set(titles))


def test_previous_pick_goes_back_and_is_absent_on_the_first_pick(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    first = _ready(page)
    assert page.locator(f"{_BUTTONS} .btn", has_text="Previous pick").count() == 0
    second = _click_and_wait_for_change(page, "Show me another", first)
    assert second != first
    back = _click_and_wait_for_change(page, "Previous pick", second)
    assert back == first


def test_the_row_under_the_pick_never_lists_the_title_on_show(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    first = _ready(page)
    page.wait_for_selector("#rails [data-rail='picks'] .tile-title", timeout=10_000)
    on_row = page.locator("#rails [data-rail='picks'] .tile-title").all_inner_texts()
    assert first not in on_row
    second = _click_and_wait_for_change(page, "Show me another", first)
    page.wait_for_timeout(300)
    on_row = page.locator("#rails [data-rail='picks'] .tile-title").all_inner_texts()
    assert second not in on_row and first not in on_row  # nothing passed or on show is listed


def test_marking_a_pick_want_to_watch_keeps_it_and_the_button_does_not_remove_it(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    first = _ready(page)
    page.click(f"{_BUTTONS} .btn >> text='Want to watch'")
    page.wait_for_timeout(1800)  # the page redraws a moment after an answer; the pick must not jerk
    assert page.inner_text(_TITLE) == first
    assert len(_profile(page)["want"]) == 1
    _click_and_wait_for_change(page, "Show me another", first)
    assert len(_profile(page)["want"]) == 1  # still on the list: looking on is not rejecting


def test_liking_the_pick_moves_on_to_the_next_best_rather_than_repeating(
    open_page: Callable[..., Any],
) -> None:
    page = open_page(1280)
    first = _ready(page)
    page.click(f"{_BUTTONS} .btn >> text='Like'")
    page.wait_for_function(
        "(t) => { const h = document.querySelector('#spotlight .spotlight h1');"
        " return h && h.textContent !== t; }",
        arg=first,
        timeout=10_000,
    )
    assert page.inner_text(_TITLE) != first
