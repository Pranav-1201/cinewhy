"""The home page gets all its shelves in one request and never shows a film twice."""

from __future__ import annotations

from typing import Any


def test_the_page_makes_one_shelves_request_and_no_film_repeats(
    browser: Any, server_url: str
) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    requests: list[str] = []
    page.on("request", lambda r: requests.append(f"{r.method} {r.url.removeprefix(server_url)}"))
    page.goto(server_url)
    page.wait_for_selector("#onboard-dialog[open]", timeout=20_000)
    page.click("#onboard-form button[value=skip]")
    page.wait_for_selector("#rails .tile", timeout=20_000)
    shown = (
        page.locator("#spotlight h1").all_inner_texts()
        + page.locator("#rails .tile-title").all_inner_texts()
    )
    context.close()
    assert requests.count("POST /shelves") == 1, requests
    assert not [r for r in requests if r.startswith("POST /discover")], requests
    assert len(shown) >= 3 and len(shown) == len(set(shown)), shown
