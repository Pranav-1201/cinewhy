"""Watch together in real browsers: two people, each in their own browser profile, one room.

Each person is a separate Playwright context (separate localStorage and sessionStorage), so what one
of them sees of the other can only have come through the server. The flow under test: join, read the
rules, answer the mood quiz, swipe cards (buttons, arrow keys, mouse drags), name one top pick, and
open the group's picks, which only change when Refresh is pressed.
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
_CARD = ".sw-card:not(.sw-behind)"


class _Visitors:
    """Opens pages in fresh browser profiles and closes them afterwards."""

    def __init__(self, browser: Any, url: str) -> None:
        self._browser, self.url = browser, url
        self._contexts: list[Any] = []

    def visit(self, *, watched: list[str], liked: list[str], path: str = "") -> Any:
        context = self._browser.new_context(viewport={"width": 1100, "height": 1000})
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


def _profile(page: Any) -> dict[str, Any]:
    raw = page.evaluate("() => localStorage.getItem('cinewhy.profile.v3')")
    return json.loads(raw)  # type: ignore[no-any-return]


def _open_dialog(page: Any) -> None:
    """Open Watch together from the Profile sheet.

    The top bar holds three tools and `tests/e2e/test_layout.py` pins that, so the entry lives in
    the sheet (and in invite links).
    """
    page.click("#profile-btn")
    page.click("#profile-dialog [data-open=together]")
    page.wait_for_selector("#together-dialog[open]")


def _agree_and_go(page: Any, name: str) -> None:
    page.fill("#tg-name", name)
    page.check("#tg-agree")
    page.click("#together-body .btn.primary")


def _host_room(visitors: _Visitors, **library: Any) -> tuple[Any, str]:
    page = visitors.visit(**library)
    _open_dialog(page)
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


def _to_cards(page: Any) -> None:
    """From the room to the first card: rules (once), then the quiz, skipped."""
    page.click("#tg-start")
    if page.locator("#tg-rules-ok").count():
        page.click("#tg-rules-ok")
    if page.locator("#tg-quiz-skip").count():
        page.click("#tg-quiz-skip")
    page.wait_for_selector(_CARD, timeout=20_000)


def _title(page: Any) -> str:
    return str(page.inner_text(f"{_CARD} h3"))


def _answer(page: Any, action: str) -> str:
    """Press an answer button and wait for the next card; returns the title that was answered."""
    title = _title(page)
    page.click(f".sw-btn[data-action={action}]")
    page.wait_for_function(
        "t => { const e = document.querySelector('.sw-card:not(.sw-behind) h3');"
        " return !e || e.textContent !== t; }",
        arg=title,
        timeout=10_000,
    )
    return title


def _count(page: Any) -> int:
    return int(page.inner_text("#sw-count").split()[0])


# --- joining and agreeing ---------------------------------------------------------------------


def test_nothing_is_sent_until_the_person_agrees(visitors: _Visitors) -> None:
    page = visitors.visit(watched=["cw-1"], liked=["cw-2"])
    sent: list[str] = []
    page.on("request", lambda request: sent.append(request.url))
    _open_dialog(page)
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


# --- the rules, the quiz and the cards --------------------------------------------------------


def test_the_rules_are_shown_before_the_quiz_and_before_any_card(visitors: _Visitors) -> None:
    host, _ = _host_room(visitors, watched=[], liked=[])
    host.click("#tg-start")
    text = host.inner_text("#together-body").lower()
    for phrase in (
        "four swipes", "right", "left", "up", "down", "only one top pick", "refresh",
        "stays in this room", "nothing changes in your own profile", "not a like",
    ):  # fmt: skip
        assert phrase in text, phrase
    assert host.locator(".sw-card").count() == 0 and host.locator("#tg-quiz-skip").count() == 0
    host.click("#tg-rules-ok")
    host.wait_for_selector("#tg-quiz-skip")  # then the quiz
    assert "feel like tonight" in host.inner_text("#together-body").lower()


def test_the_rules_are_not_shown_again_in_the_same_room(visitors: _Visitors) -> None:
    host, _ = _host_room(visitors, watched=[], liked=[])
    _to_cards(host)
    host.click("#sw-people")
    host.click("#tg-start")  # "Keep swiping": no rules, no quiz, straight back to the cards
    host.wait_for_selector(_CARD)
    assert host.locator("#tg-rules-ok").count() == 0


def test_a_card_shows_the_title_its_facts_and_four_buttons(visitors: _Visitors) -> None:
    host, _ = _host_room(visitors, watched=[], liked=[])
    _to_cards(host)
    assert _title(host)
    assert host.locator(f"{_CARD} .sw-poster").count() == 1
    assert host.locator(f"{_CARD} .meta .chip").count() >= 1
    labels = host.locator(".sw-btn").all_inner_texts()
    assert [label.split("\n")[-1] for label in labels] == [
        "Not for me", "Already watched", "My top pick", "Want to watch"
    ]  # fmt: skip


def test_every_answer_counts_and_none_of_them_touches_the_persons_own_profile(
    visitors: _Visitors,
) -> None:
    host, _ = _host_room(visitors, watched=["cw-1"], liked=[])
    before = _profile(host)
    _to_cards(host)
    for expected, action in enumerate(("want", "pass", "seen", "top"), start=1):
        _answer(host, action)
        assert _count(host) == expected
    assert _profile(host) == before  # nothing was liked, watched or wanted in their own library


def test_arrow_keys_answer_like_the_buttons(visitors: _Visitors) -> None:
    host, _ = _host_room(visitors, watched=[], liked=[])
    _to_cards(host)
    first = _title(host)
    host.keyboard.press("ArrowRight")
    host.wait_for_function("() => document.querySelector('#sw-count').textContent.startsWith('1 ')")
    assert _title(host) != first


def test_a_long_drag_answers_and_a_short_one_does_not(visitors: _Visitors) -> None:
    host, _ = _host_room(visitors, watched=[], liked=[])
    _to_cards(host)
    box = host.locator(_CARD).bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    title = _title(host)

    host.mouse.move(x, y)
    host.mouse.down()
    host.mouse.move(x + 30, y, steps=4)  # far less than a swipe
    host.mouse.up()
    host.wait_for_timeout(500)
    assert _title(host) == title and _count(host) == 0  # the card sprang back

    host.mouse.move(x, y)
    host.mouse.down()
    host.mouse.move(x + 260, y + 10, steps=8)  # a clear drag to the right
    host.mouse.up()
    host.wait_for_function("() => document.querySelector('#sw-count').textContent.startsWith('1 ')")
    assert _title(host) != title


def test_a_second_top_pick_asks_first_and_the_answer_decides(visitors: _Visitors) -> None:
    host, _ = _host_room(visitors, watched=[], liked=[])
    _to_cards(host)
    first = _answer(host, "top")
    assert _count(host) == 1
    second = _title(host)
    sent: list[str] = []
    host.on("request", lambda r: sent.append(r.url) if r.url.endswith("/swipe") else None)
    host.click(".sw-btn[data-action=top]")
    host.wait_for_selector("#sw-confirm:not([hidden])")
    host.wait_for_timeout(600)
    assert not sent  # the question comes first: nothing is sent, and the card never leaves
    assert host.locator(".sw-card.flying").count() == 0
    assert first in host.inner_text("#sw-confirm") and second in host.inner_text("#sw-confirm")
    host.click("#sw-replace-no")
    assert _title(host) == second and _count(host) == 1  # nothing changed

    host.click(".sw-btn[data-action=top]")
    host.click("#sw-replace-yes")
    host.wait_for_function("() => document.querySelector('#sw-count').textContent.startsWith('2 ')")
    assert _title(host) != second


# --- the group's picks ------------------------------------------------------------------------


def test_the_group_picks_name_everyone_and_change_only_when_refreshed(visitors: _Visitors) -> None:
    host, code = _host_room(visitors, watched=[], liked=[])
    guest = _guest_joins(visitors, code, "Ben", watched=[], liked=[])
    _to_cards(host)
    _to_cards(guest)
    top_title = _answer(host, "top")
    _answer(guest, "want")

    host.click("#sw-results")
    host.wait_for_selector("#tg-top .tg-card", timeout=20_000)
    rows = host.locator("#tg-results .tg-card")
    assert rows.count() >= 1
    for chips in rows.locator(".tg-fits").all():
        assert [c.split(":")[0] for c in chips.locator("li").all_inner_texts()] == ["Ann", "Ben"]
    mine = host.locator("#tg-results .tg-card", has_text=top_title)
    assert "Ann: top pick" in mine.inner_text()

    shown = host.locator("#tg-results .tg-card .name").all_inner_texts()
    _answer(guest, "pass")  # Ben keeps swiping while Ann looks at the list
    host.wait_for_selector("#tg-stale:not(:empty)", timeout=20_000)  # she is told it is behind
    assert "Refresh" in host.inner_text("#tg-stale")
    assert host.locator("#tg-results .tg-card .name").all_inner_texts() == shown  # it did not move

    host.click("#tg-refresh")
    host.wait_for_function(
        "() => document.querySelector('#tg-stale').textContent === ''", timeout=20_000
    )


def test_results_can_be_opened_before_anyone_has_swiped(visitors: _Visitors) -> None:
    host, _ = _host_room(visitors, watched=[], liked=[])
    host.click("#tg-open-results")
    host.wait_for_selector("#tg-top .tg-card", timeout=20_000)
    assert host.locator("#tg-refresh").is_enabled()


# --- leaving, closing, reloading --------------------------------------------------------------


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
    host.wait_for_selector("#profile-btn")
    _open_dialog(host)
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
