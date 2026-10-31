"""The home page gets all its shelves in one request and never shows a film twice."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_OUT = "document.querySelector('.range-out')"


def test_the_year_bar_and_presets_drive_the_request(open_page: Callable[..., Any]) -> None:
    page = open_page(1280)
    page.wait_for_selector(".range input")
    bodies: list[dict[str, Any]] = []
    page.on(
        "request",
        lambda r: bodies.append(r.post_data_json) if r.url.endswith("/shelves") else None,
    )
    assert page.inner_text(".range-out") == "Any year"
    assert "quiet" in page.get_attribute(".range-out", "class")

    page.click("#era-chips .chip >> text=Old school")
    page.wait_for_function(f"() => {_OUT}.textContent === 'Before 1990'")
    page.wait_for_timeout(900)  # the shelves refresh a moment after the last change
    assert bodies[-1].get("to_year") == 1989 and "from_year" not in bodies[-1]

    page.click("#era-chips .chip >> text=Old school")  # pressing the lit preset clears it
    page.wait_for_function(f"() => {_OUT}.textContent === 'Any year'")
    page.wait_for_timeout(900)
    assert "from_year" not in bodies[-1] and "to_year" not in bodies[-1]

    page.evaluate(
        "() => { const [lo, hi] = document.querySelectorAll('.range input');"
        " lo.value = '1990'; lo.dispatchEvent(new Event('input', {bubbles: true}));"
        " hi.value = '2010'; hi.dispatchEvent(new Event('input', {bubbles: true})); }"
    )
    page.wait_for_function(f"() => {_OUT}.textContent === '1990 to 2010'")
    page.wait_for_timeout(900)
    assert (bodies[-1].get("from_year"), bodies[-1].get("to_year")) == (1990, 2010)
    assert all(
        1990 <= int(y) <= 2010
        for y in page.locator("#rails .tile-meta").all_inner_texts()
        if y.isdigit()
    )


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
