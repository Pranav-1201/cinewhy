"""The page must stay usable at every width: nothing off screen, search wide enough to type in.

Regression for two defects measured on 2026-10-27 (docs/ROADMAP-2026-10-27.md, U2): at 800 px the
search box was 110 px wide beside three text buttons, and at 375 px the theme toggle sat outside
the screen. It also pins the first-visit behaviour: the questions open by themselves on a clean
browser profile and stay closed once answered or skipped.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

WIDTHS = [320, 375, 640, 641, 768, 960, 1024, 1440]
PHONE_MAX = 640  # at or below this width the tools live in the bottom bar
MIN_SEARCH_PX = 200
MIN_TOUCH_PX = 44

_MEASURE = """() => {
  const shown = (e) =>
    getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
  const box = (e) => {
    const b = e.getBoundingClientRect();
    return { left: b.left, right: b.right, width: b.width, height: b.height };
  };
  return {
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
    search: box(document.querySelector('#q')).width,
    barControls: [...document.querySelectorAll('.bar a, .bar input, .bar button')]
      .filter(shown).map(box),
    navShown: !!document.querySelector('.bottom-nav')
      && shown(document.querySelector('.bottom-nav')),
    navItems: [...document.querySelectorAll('.bottom-nav .nav-item')].filter(shown).map(box),
    toolButtons: [...document.querySelectorAll('.bar-actions .text-btn')]
      .filter(shown).length,
  };
}"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_api.sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


def _open(browser: Any, url: str, width: int, *, skip_questions: bool = True) -> tuple[Any, Any]:
    """A fresh browser profile at `width`, on the page, with the first-visit sheet dealt with."""
    context = browser.new_context(viewport={"width": width, "height": 800})
    page = context.new_page()
    page.goto(url)
    page.wait_for_selector("#onboard-dialog[open]", timeout=20_000)
    if skip_questions:
        page.click("#onboard-form button[value=skip]")
        page.wait_for_selector("#onboard-dialog:not([open])", state="attached")
    return context, page


@pytest.mark.parametrize("width", WIDTHS)
def test_header_fits_at_every_width(browser: Any, server_url: str, width: int) -> None:
    context, page = _open(browser, server_url, width)
    try:
        m = page.evaluate(_MEASURE)
    finally:
        context.close()
    assert m["scroll"] <= m["client"], f"page scrolls sideways at {width} px: {m['scroll']} wide"
    assert m["search"] >= MIN_SEARCH_PX, f"search box is {m['search']:.0f} px wide at {width} px"
    for control in m["barControls"]:
        assert control["left"] >= 0, f"a header control starts off screen at {width} px"
        assert control["right"] <= m["client"], f"a header control ends off screen at {width} px"
    assert m["navShown"] == (width <= PHONE_MAX)
    if m["navShown"]:
        assert len(m["navItems"]) == 3
        for item in m["navItems"]:
            assert item["right"] <= m["client"] and item["left"] >= 0
            assert item["height"] >= MIN_TOUCH_PX
    else:
        assert m["toolButtons"] == 3, "the three tools should sit in the top bar on wide screens"


def test_phone_tools_reachable_from_profile_sheet(browser: Any, server_url: str) -> None:
    context, page = _open(browser, server_url, 375)
    try:
        page.click("#nav-profile")
        page.wait_for_selector("#profile-dialog[open]")
        names = page.locator("#profile-dialog [data-tool]").all_inner_texts()
        assert len(names) == 4
        page.click("#profile-dialog [data-tool=about]")
        page.wait_for_selector("#about-dialog[open]")
        assert not page.evaluate("document.querySelector('#profile-dialog').open")
    finally:
        context.close()


def test_wide_screen_keeps_tool_names(browser: Any, server_url: str) -> None:
    context, page = _open(browser, server_url, 1440)
    try:
        assert "Your taste" in page.inner_text("#taste-btn")
        assert "How it works" in page.inner_text("#about-btn")
    finally:
        context.close()


def test_first_visit_questions_open_once(browser: Any, server_url: str) -> None:
    context, page = _open(browser, server_url, 1024, skip_questions=False)
    try:
        page.click("#onboard-form button[value=skip]")
        page.reload()
        page.wait_for_selector("#rails .rail, #status:not([hidden])", timeout=20_000)
        assert not page.evaluate("document.querySelector('#onboard-dialog').open")
    finally:
        context.close()
