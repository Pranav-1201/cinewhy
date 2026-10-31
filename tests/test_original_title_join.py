"""A foreign film's reviews are found under its own-language title (cinewhy/data/linking.py).

End to end through `gather` on tiny synthetic dumps: the French film is listed by TMDB under an
English title and by ebD under the French one, which the exact-title join alone never links.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cinewhy.data import spine
from cinewhy.data.catalogue_sources import Gathered, gather
from tests.dumps import source_paths, tmdb_row

_FRENCH = "Le Fabuleux Destin d'Am" + chr(0xE9) + "lie Poulain"
_REVIEW = (
    "The pacing in this film is wonderful, and the story never drags once in two whole hours of it."
)


@pytest.fixture(autouse=True)
def _french_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The build selects only English and Hindi today; these tests need French in the selection."""
    monkeypatch.setattr(spine, "LANGUAGES", ("en", "hi", "fr"))


def _gather(
    tmp_path: Path, tmdb: list[dict[str, str]], ebd: list[tuple[str, str, str]]
) -> Gathered:
    paths = source_paths(tmp_path, tmdb=tmdb, ebd=ebd)
    return gather(paths, quota_for=lambda _language, _year: 50)


def test_a_french_film_links_through_its_original_title(tmp_path: Path) -> None:
    gathered = _gather(
        tmp_path,
        [tmdb_row(1, 211915, "Amelie", 2001, lang="fr", original_title=_FRENCH, runtime=122.0)],
        [(f"{_FRENCH} (2001)", "r1", _REVIEW)],
    )
    assert [r[0] for r in gathered.reviews[211915]] == ["ebd/r1"]
    assert gathered.report["links_via_original_title"] == {"ebd/fr": 1}


def test_without_the_original_title_the_same_film_does_not_link(tmp_path: Path) -> None:
    gathered = _gather(
        tmp_path,
        [tmdb_row(1, 211915, "Amelie", 2001, lang="fr", original_title="", runtime=122.0)],
        [(f"{_FRENCH} (2001)", "r1", _REVIEW)],
    )
    assert 211915 not in gathered.reviews
    assert gathered.report["links_via_original_title"] == {}


def test_an_accent_on_one_side_only_still_links(tmp_path: Path) -> None:
    gathered = _gather(
        tmp_path,
        [tmdb_row(1, 211915, "Am" + chr(0xE9) + "lie", 2001, lang="fr")],
        [("Amelie (2001)", "r1", _REVIEW)],
    )
    assert [r[0] for r in gathered.reviews[211915]] == ["ebd/r1"]


def test_an_original_title_that_is_another_films_english_title_links_neither_wrongly(
    tmp_path: Path,
) -> None:
    # B's own-language title is exactly A's English title, in the same year. The ebD record is A's.
    # B must not claim it; A must keep it.
    gathered = _gather(
        tmp_path,
        [
            tmdb_row(1, 100, "Shared Name", 2001, lang="en", runtime=100.0),
            tmdb_row(2, 200, "Another Name", 2001, lang="fr", original_title="Shared Name"),
        ],
        [("Shared Name (2001)", "r1", _REVIEW)],
    )
    assert 100 in gathered.reviews and 200 not in gathered.reviews
