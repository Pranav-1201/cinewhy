"""The gather step takes about 25 minutes on the real dumps, so its result is cached (FEATURE-004).

A cache that goes stale silently is worse than none: a change to the selection rules or a
re-downloaded dump would be hidden behind old data. So the cache is keyed on everything the
result depends on, and each way that key can change is tested.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import cinewhy.data.catalogue_sources as sources_module
from cinewhy.data.catalogue_sources import SourcePaths, gather, gather_cached
from tests.dumps import source_paths, tmdb_row

_REVIEW = "The pacing in Heat is superb, and the pacing never drags once in almost three hours."


def _paths(folder: Path) -> SourcePaths:
    return source_paths(
        folder,
        tmdb=[tmdb_row(949, 113277, "Heat", 1995)],
        # The film links to all three sources, so a cache that dropped any one would differ.
        rt_films=[("a1", 1995, "Heat", "2h 50m")],
        rt_reviews=[("a1", "Heat is a masterpiece of tension and character, beautifully made.")],
        ebd=[("Heat (1995)", "rw1", _REVIEW)],
        acl=[(113277, "An older review of Heat that mentions the shootout on the street.")],
    )


def test_a_cached_result_equals_a_fresh_one(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "dumps")
    cache = tmp_path / "gathered.jsonl"
    first = gather_cached(paths, cache)
    assert cache.is_file()
    again = gather_cached(paths, cache)
    fresh = gather(paths)
    assert again == first == fresh


def test_a_valid_cache_is_used_without_reading_the_dumps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path / "dumps")
    cache = tmp_path / "gathered.jsonl"
    gather_cached(paths, cache)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the dumps were read although the cache was valid")

    monkeypatch.setattr(sources_module, "gather", refuse)
    assert gather_cached(paths, cache).reviews  # served from the file


def test_a_changed_dump_invalidates_the_cache(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "dumps")
    cache = tmp_path / "gathered.jsonl"
    before = gather_cached(paths, cache)
    # Re-download of the ebD dump with one more review: same path, different size.
    _ = source_paths(
        tmp_path / "dumps",
        tmdb=[tmdb_row(949, 113277, "Heat", 1995)],
        rt_films=[("a1", 1995, "Heat", "2h 50m")],
        rt_reviews=[("a1", "Heat is a masterpiece of tension and character, beautifully made.")],
        ebd=[("Heat (1995)", "rw1", _REVIEW), ("Heat (1995)", "rw2", _REVIEW + " Second take.")],
        acl=[(113277, "An older review of Heat that mentions the shootout on the street.")],
    )
    after = gather_cached(paths, cache)
    assert len(after.reviews[113277]) == len(before.reviews[113277]) + 1


def test_a_different_cap_invalidates_the_cache(tmp_path: Path) -> None:
    paths = source_paths(
        tmp_path / "dumps",
        tmdb=[tmdb_row(949, 113277, "Heat", 1995)],
        # Two reviews, so a cap of 1 keeps fewer than a cap of 150 and the difference shows.
        ebd=[("Heat (1995)", "rw1", _REVIEW), ("Heat (1995)", "rw2", _REVIEW + " Second take.")],
    )
    cache = tmp_path / "gathered.jsonl"
    wide = gather_cached(paths, cache, cap=150)
    assert wide.report["reviews_per_source_after_cap"]["ebd"] == 2
    assert gather_cached(paths, cache, cap=1).report["reviews_per_source_after_cap"]["ebd"] == 1


def test_a_new_logic_version_invalidates_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path / "dumps")
    cache = tmp_path / "gathered.jsonl"
    gather_cached(paths, cache)
    monkeypatch.setattr(sources_module, "GATHER_VERSION", sources_module.GATHER_VERSION + 1)

    def regather(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("regathered")

    monkeypatch.setattr(sources_module, "gather", regather)
    with pytest.raises(RuntimeError, match="regathered"):
        gather_cached(paths, cache)


def test_a_cache_missing_its_last_film_is_ignored_and_rebuilt(tmp_path: Path) -> None:
    # Every remaining line is valid JSON, so only the entry count in the header can tell.
    paths = source_paths(
        tmp_path / "dumps",
        tmdb=[tmdb_row(949, 113277, "Heat", 1995), tmdb_row(950, 113278, "Ronin", 1998)],
        ebd=[("Heat (1995)", "rw1", _REVIEW), ("Ronin (1998)", "rw2", _REVIEW + " Ronin take.")],
    )
    cache = tmp_path / "gathered.jsonl"
    expected = gather_cached(paths, cache)
    assert len(expected.reviews) == 2
    lines = cache.read_text(encoding="utf-8").splitlines()
    cache.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    assert gather_cached(paths, cache) == expected


def test_a_damaged_cache_is_ignored_and_rebuilt(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "dumps")
    cache = tmp_path / "gathered.jsonl"
    expected = gather_cached(paths, cache)
    cache.write_text('{"key": "this line is cut off', encoding="utf-8")
    assert gather_cached(paths, cache) == expected
