"""The four language choices, and Telugu travelling with Hindi (cinewhy/recsys/discover.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.models import DiscoverRequest, ShelvesRequest
from cinewhy.recsys import shelves as shelves_module
from cinewhy.recsys.discover import expand_languages
from cinewhy.recsys.shelves import build_shelves
from cinewhy.schemas import TasteProfile
from tests.test_ratings_only import _extra, _items, _with_extras


@pytest.fixture(autouse=True)
def _small_world_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shelves_module, "MIN_LANGUAGE_FILMS", 5)


def test_a_hindi_choice_also_stands_for_telugu_and_nothing_else_widens() -> None:
    assert expand_languages(["hi"]) == {"hi", "te"}
    assert expand_languages(["en"]) == {"en"}
    assert expand_languages(["ja", "fr"]) == {"ja", "fr"}
    assert expand_languages([]) == set()


def test_discover_and_shelves_accept_all_four_languages_and_nothing_more() -> None:
    for model in (DiscoverRequest, ShelvesRequest):
        assert model(languages=("en", "hi", "ja", "fr")).languages == ("en", "hi", "ja", "fr")
        with pytest.raises(ValidationError):
            model(languages=("de",))  # type: ignore[arg-type]  # the point: German is refused


def test_the_hindi_shelf_holds_telugu_films_and_is_named_for_both() -> None:
    telugu = [_extra(i, language="te", year=2005, votes=40_000 - 100 * i) for i in range(6)]
    result = build_shelves(_with_extras(*telugu), TasteProfile(), manifest="m", languages=("hi",))
    shelf = next(s for s in result.shelves if s.id == "lang-hi")
    assert shelf.title == "Best of Hindi and Telugu"
    assert {i.language for i in shelf.items} >= {"te", "hi"}


def test_without_telugu_the_hindi_shelf_keeps_its_plain_name() -> None:
    result = build_shelves(_with_extras(), TasteProfile(), manifest="m", languages=("hi",))
    assert next(s for s in result.shelves if s.id == "lang-hi").title == "Best of Hindi"


def test_telugu_alone_can_give_the_hindi_shelf_enough_films() -> None:
    # Few Hindi films and a lot of Telugu: the shelf still earns its place by their combined count.
    result = build_shelves(
        _with_extras(*[_extra(i, language="te", year=2005) for i in range(6)]),
        TasteProfile(),
        manifest="m",
    )
    assert any(i.language == "te" for i in _items(result, "lang-hi"))


def test_a_french_choice_shows_only_french_films() -> None:
    french = [_extra(i, language="fr", year=2005) for i in range(6)]
    result = build_shelves(
        _with_extras(*french, _extra(50, language="ja", year=2005)),
        TasteProfile(),
        manifest="m",
        languages=("fr",),
    )
    assert {i.language for s in result.shelves for i in s.items} == {"fr"}
    assert [s.id for s in result.shelves if s.id.startswith("lang-")] == ["lang-fr"]
