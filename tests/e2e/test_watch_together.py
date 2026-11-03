"""Watch together in real browsers: two people, each in their own browser profile, one room.

Each person is a separate Playwright context (separate localStorage and sessionStorage), so what one
of them sees of the other can only have come through the server.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

# The profile shape web/js/profile.js saves (version 3). `onboarded` stays true so the first-visit
# sheet does not open on top of the room dialog.
_BASE_PROFILE: dict[str, Any] = {
    "version": 3, "weights": {}, "liked": [], "disliked": [], "watched": [], "want": [],
    "ratings": {}, "titles": {}, "languages": [], "kinds": [], "favouriteGenres": [],
    "genres": [], "yearFrom": None, "yearTo": None, "recency": 0.5, "recencyTouched": False,
    "age": None, "region": None, "sex": None, "hindiFirst": False, "onboarded": True,
    "hideWatched": True,
}  # fmt: skip
_SECOND_MEMBER = "#tg-members li:nth-child(2)"
_TWO_MEMBERS = "() => document.querySelectorAll('#tg-members li').length === 2"
_ONE_MEMBER = "() => document.querySelectorAll('#tg-members li').length === 1"


class _Visitors:
    """Opens pages in fresh browser profiles and closes them afterwards."""

    def __init__(self, browser: Any, url: str) -> None:
        self._browser, self.url = browser, url
        self._contexts: list[Any] = []

    def visit(self, *, watched: list[str], liked: list[str], path: str = "") -> Any:
        context = self._browser.new_context(viewport={"width": 1100, "height": 900})
        self._contexts.append(context)
        profile = {**_BASE_PROFILE, "watched": watched, "liked": liked}
        context.add_init_script(
            "if (!localStorage.getItem('cinewhy.profile.v3'))"
            f" localStorage.setItem('cinewhy.profile.v3', {json.dumps(json.dumps(profile))});"
        )
        page = context.new_page()
        page.goto(self.url + path)
        return page

    def close(self) -> None:
        for context in self._contexts:
            context.close()


@pytest.fixture
def visitors(browser: Any, server_url: str) -> Iterator[_Visitors]:
    people = _Visitors(browser, server_url)
    yield people
    people.close()


def _agree_and_go(page: Any, name: str) -> None:
    page.fill("#tg-name", name)
    page.check("#tg-agree")
    page.click("#together-body .btn.primary")


def _host_room(visitors: _Visitors, **library: Any) -> tuple[Any, str]:
    page = visitors.visit(**library)
    page.click("#together-btn")
    page.click("text=Start a room")
    _agree_and_go(page, "Ann")
    page.wait_for_selector("#tg-code-text")
    return page, page.inner_text("#tg-code-text")


def _guest_joins(visitors: _Visitors, code: str, name: str, **library: Any) -> Any:
    page = visitors.visit(path=f"#room={code}", **library)
    page.wait_for_selector("#together-dialog[open]", timeout=20_000)
    _agree_and_go(page, name)
    page.wait_for_selector(_SECOND_MEMBER)
    return page


def test_nothing_is_sent_until_the_person_agrees(visitors: _Visitors) -> None:
    page = visitors.visit(watched=["cw-1"], liked=["cw-2"])
    sent: list[str] = []
    page.on("request", lambda request: sent.append(request.url))
    page.click("#together-btn")
    page.click("text=Start a room")
    assert page.is_disabled("#together-body .btn.primary")  # no agreement, no button
    page.fill("#tg-name", "Ann")
    assert page.is_disabled("#together-body .btn.primary")  # a name alone is not agreement
    assert not [url for url in sent if "/rooms" in url]
    page.check("#tg-agree")
    assert page.is_enabled("#together-body .btn.primary")


def test_a_friend_joins_by_link_and_sees_the_host_and_the_host_sees_them(
    visitors: _Visitors,
) -> None:
    host, code = _host_room(visitors, watched=["cw-1"], liked=["cw-2"])
    assert host.input_value("#tg-link").endswith(f"#room={code}")

    guest = visitors.visit(watched=["cw-3"], liked=["cw-4"], path=f"#room={code}")
    guest.wait_for_selector("#together-dialog[open]", timeout=20_000)
    assert guest.is_disabled("#together-body .btn.primary")  # the link does not skip agreeing
    _agree_and_go(guest, "Ben")
    guest.wait_for_selector(_SECOND_MEMBER)
    assert guest.locator(".tg-name").all_inner_texts() == ["Ann", "Ben"]

    host.wait_for_selector(_SECOND_MEMBER, timeout=15_000)  # found by the host's own poll
    assert host.locator(".tg-name").all_inner_texts() == ["Ann", "Ben"]
    assert "#room=" not in guest.url  # the code was taken out of the address once read


def test_the_group_list_names_everyone_and_changes_when_asked_for_others(
    visitors: _Visitors,
) -> None:
    host, code = _host_room(visitors, watched=["cw-1"], liked=["cw-2"])
    _guest_joins(visitors, code, "Ben", watched=[], liked=["cw-3"])
    host.wait_for_selector(_SECOND_MEMBER, timeout=15_000)
    assert host.is_enabled("#tg-find")

    host.click("#tg-find")
    host.wait_for_selector(".tg-card", timeout=20_000)
    first = host.locator(".tg-card .name").all_inner_texts()
    assert first
    for card in host.locator(".tg-card").all():
        fits = card.locator(".tg-fit").all_inner_texts()
        assert [fit.split(" ")[0] for fit in fits] == ["Ann", "Ben"]  # both stand on every title

    if host.locator("#tg-more").count():
        host.click("#tg-more")
        host.wait_for_function("() => !document.querySelector('#tg-find').disabled", timeout=20_000)
        assert not set(first) & set(host.locator(".tg-card .name").all_inner_texts())


def test_one_person_alone_cannot_ask_for_a_list(visitors: _Visitors) -> None:
    host, _ = _host_room(visitors, watched=[], liked=[])
    assert host.is_disabled("#tg-find")
    assert "Waiting for a second person" in host.inner_text("#tg-results")


def test_leaving_takes_you_out_for_everyone_and_forgets_the_secret(visitors: _Visitors) -> None:
    host, code = _host_room(visitors, watched=[], liked=["cw-1"])
    guest = _guest_joins(visitors, code, "Ben", watched=[], liked=["cw-2"])
    host.wait_for_function(_TWO_MEMBERS, timeout=15_000)

    guest.click("#tg-leave")
    guest.wait_for_selector("text=You left the room")
    assert guest.evaluate("sessionStorage.getItem('cinewhy.room')") is None
    host.wait_for_function(_ONE_MEMBER, timeout=15_000)
    assert host.locator(".tg-name").all_inner_texts() == ["Ann"]


def test_a_reload_keeps_you_in_the_room(visitors: _Visitors) -> None:
    host, code = _host_room(visitors, watched=[], liked=["cw-1"])
    host.reload()
    host.wait_for_selector("#together-btn")
    host.click("#together-btn")
    host.wait_for_selector("#tg-code-text")
    assert host.inner_text("#tg-code-text") == code


def test_only_the_host_is_offered_closing_and_it_ends_the_room(visitors: _Visitors) -> None:
    host, code = _host_room(visitors, watched=[], liked=["cw-1"])
    guest = _guest_joins(visitors, code, "Ben", watched=[], liked=["cw-2"])
    assert not guest.is_visible("#tg-close")
    assert host.is_visible("#tg-close")

    host.click("#tg-close")
    host.wait_for_selector("text=The room is closed")
    guest.wait_for_selector("text=closed or has expired", timeout=15_000)
