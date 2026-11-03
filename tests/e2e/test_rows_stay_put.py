"""Rows stay put until the visitor asks for new titles (D-045).

The owner's rule: liking or marking a title must not redraw the page, because the visitor may still
want another title from the same row. New suggestions arrive when the page is reloaded, a filter
changes, or "Show more" is pressed on one row, which ADDS titles after the last one. Every row
starts from its first title after a filter change.

Runs on the set with 30 ratings-only Japanese titles, so the Japanese row has more to show.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

JAPANESE = "section.rail[data-rail='lang-ja']"
_SCROLLER = "document.querySelector(\"section.rail[data-rail='lang-ja'] .rail-scroll\")"
_REDRAWN = (
    "() => document.querySelectorAll('#rails .tile').length > 0"
    " && !document.querySelector('#rails [aria-busy=true]')"
)


def _settle(page: Any) -> None:
    """Wait for the first draw and for the first-visit sheet's own delayed refresh to finish."""
    page.wait_for_selector(f"{JAPANESE} .tile", timeout=20_000)
    page.wait_for_function(_REDRAWN)
    page.wait_for_timeout(900)


def _titles(page: Any) -> list[str]:
    rows: list[str] = page.locator("#rails .tile-title").all_inner_texts()
    return [page.inner_text("#spotlight h1"), *rows]


def _row_titles(page: Any) -> list[str]:
    titles: list[str] = page.locator(f"{JAPANESE} .tile:not(.more) .tile-title").all_inner_texts()
    return titles


def _profile(page: Any) -> dict[str, Any]:
    raw = page.evaluate("() => localStorage.getItem('cinewhy.profile.v3')")
    return json.loads(raw)  # type: ignore[no-any-return]


def _item(n: int) -> dict[str, Any]:
    """A title shaped like the server's DiscoverItem, for a stubbed 'Show more' answer."""
    movie = {
        "movie_id": f"cw-stub-{n}",
        "title": f"Stub {n}",
        "year": 2001,
        "genres": [],
        "kind": "film",
    }
    return {"movie": movie, "language": "ja", "is_new": False, "score": 0.1, "reasons": [],
            "is_fallback": True, "because": None, "ratings_only": True}  # fmt: skip


def test_acting_on_a_title_changes_nothing_on_the_page_until_the_visitor_reloads(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    _settle(page)
    before = _titles(page)
    tiles = page.locator(f"{JAPANESE} .tile")
    first, second = tiles.nth(0), tiles.nth(1)
    watched_title = first.locator(".tile-title").inner_text()
    first.hover()
    first.locator(".tile-act.seen").click()
    second.hover()
    second.locator(".tile-act.like").click()
    page.wait_for_timeout(2500)  # longer than the old automatic refresh would have taken
    assert _titles(page) == before  # the row the visitor is browsing is exactly as it was
    assert first.locator(".tile-act.seen").get_attribute("aria-pressed") == "true"
    assert second.locator(".tile-act.like").get_attribute("aria-pressed") == "true"
    assert len(_profile(page)["watched"]) == 1 and len(_profile(page)["liked"]) == 1

    page.reload()  # the answers are kept, and now the suggestions use them
    _settle(page)
    assert watched_title not in _titles(page)


def test_show_more_adds_titles_after_the_last_one_and_says_when_there_are_none(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    _settle(page)
    first = page.locator(f"{JAPANESE} .tile").nth(0)
    first.hover()
    first.locator(".tile-act.seen").click()
    asked: list[dict[str, Any]] = []

    def answer(route: Any) -> None:
        body = route.request.post_data_json
        if not body.get("only"):
            route.continue_()
            return
        asked.append(body)
        shelf = {"id": "lang-ja", "title": "x", "subtitle": "", "items": [_item(1), _item(2)]}
        reply = {"shelves": [shelf], "cold_start": True, "manifest": "m"}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(reply))

    page.route("**/shelves", answer)  # the server's own "next titles" logic is unit-tested
    before = _row_titles(page)
    page.click(f"{JAPANESE} .tile.more button")
    page.wait_for_function(f"() => {_SCROLLER}.textContent.includes('Stub 2')", timeout=20_000)
    assert _row_titles(page) == [*before, "Stub 1", "Stub 2"]  # added after the last, none replaced
    assert page.locator(f"{JAPANESE} .tile").last.get_attribute("class") == "tile more"
    assert asked[0]["only"] == "lang-ja" and asked[0]["limit"] == 20
    assert _profile(page)["watched"][0] in asked[0]["exclude_movie_ids"]  # just-watched is left out
    everything = page.locator("#rails .tile-title").all_inner_texts()
    assert len(everything) == len(set(everything))  # nothing is offered twice on the page

    page.click(f"{JAPANESE} .tile.more button")  # the stub repeats itself: nothing new this time
    page.wait_for_selector(f"{JAPANESE} .tile.more .note")
    assert "everything for now" in page.inner_text(f"{JAPANESE} .tile.more")
    assert page.locator(f"{JAPANESE} .tile.more button").count() == 0


def test_show_more_on_the_real_server_never_repeats_a_title(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    _settle(page)
    before = _row_titles(page)
    page.click(f"{JAPANESE} .tile.more button")
    idle = "section.rail[data-rail='lang-ja'] .tile.more button:disabled"
    page.wait_for_function(f'() => !document.querySelector("{idle}")', timeout=20_000)
    everything = page.locator("#rails .tile-title").all_inner_texts()
    assert len(everything) == len(set(everything))
    assert _row_titles(page)[: len(before)] == before  # whatever was added, nothing was replaced
    assert page.locator(f"{JAPANESE} .tile").last.get_attribute("class") == "tile more"


def test_after_a_filter_change_every_row_starts_from_its_first_title(
    open_ratings_only_page: Callable[..., Any],
) -> None:
    page = open_ratings_only_page(1280)
    _settle(page)
    moved = page.evaluate(
        f"() => {{ const el = {_SCROLLER}; window.__old = el; el.scrollLeft = el.scrollWidth;"
        " return el.scrollLeft; }"
    )
    assert moved > 0  # the row really was scrolled to its end
    page.click("#seen-chips .chip")  # any filter change redraws every row
    page.wait_for_function(
        f"() => {_SCROLLER} !== window.__old && !document.querySelector('#rails [aria-busy=true]')",
        timeout=20_000,
    )
    page.wait_for_timeout(400)  # a position restored on the next animation frame would show by now
    positions = page.evaluate(
        "() => [...document.querySelectorAll('#rails .rail-scroll')].map((el) => el.scrollLeft)"
    )
    assert positions and set(positions) == {0}
