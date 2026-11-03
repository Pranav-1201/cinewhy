"""The availability file: which cache lines are kept, how they group, and a build stays valid."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from cinewhy.artifacts.manifest import build, load_manifest, verify
from cinewhy.data import availability as module
from cinewhy.data.availability import (
    AVAILABILITY_FILE,
    Availability,
    Where,
    build_availability,
    load_availability,
    read_cache,
    where_from_record,
    write_availability,
)


def _record(imdb: int = 603, kind: str = "film", **where: Any) -> dict[str, Any]:
    return {"imdb": imdb, "found": True, "tmdb_id": 603, "kind": kind, "where": where}


def test_countries_are_grouped_by_platform_then_way_in_a_fixed_order() -> None:
    record = _record(
        US={"netflix": ["stream"], "apple": ["rent", "buy"]},
        GB={"netflix": ["stream"]},
        AD={"netflix": ["stream", "rent"]},
    )
    where = where_from_record(record)
    assert where == Where(
        "movie/603",
        {
            "netflix": {"stream": ("AD", "GB", "US"), "rent": ("AD",)},
            "apple": {"rent": ("US",), "buy": ("US",)},
        },
    )
    assert list(where.on) == ["netflix", "apple"]  # PLATFORMS order, not the order of the cache
    assert list(where.on["netflix"]) == ["stream", "rent"]


def test_a_series_links_to_the_tv_page() -> None:
    where = where_from_record(_record(kind="series", US={"hbo": ["stream"]}))
    assert where is not None and where.tmdb == "tv/603"


@pytest.mark.parametrize(
    "record",
    [
        {"imdb": 1, "found": False},  # TMDB had never heard of it
        _record(),  # known, but on none of the six anywhere
        _record(US={"somewhere-else": ["stream"]}),  # a platform that is not one of the six
        _record(US={"netflix": ["teleport"]}),  # a way that is not one we show
        _record(kind="game", US={"netflix": ["stream"]}),
        {"imdb": 1, "found": True, "kind": "film", "where": {"US": {"netflix": ["stream"]}}},
    ],
)
def test_lines_that_would_put_nothing_trustworthy_on_a_page_are_dropped(
    record: dict[str, Any],
) -> None:
    assert where_from_record(record) is None


def test_an_unknown_platform_beside_a_known_one_is_ignored_not_shown() -> None:
    where = where_from_record(_record(US={"netflix": ["stream"], "mystery": ["stream"]}))
    assert where is not None and list(where.on) == ["netflix"]


def test_a_title_seen_twice_keeps_its_last_line_and_a_later_empty_line_removes_it() -> None:
    records = [
        _record(1, US={"netflix": ["stream"]}),
        _record(1, GB={"hbo": ["stream"]}),
        _record(2, US={"netflix": ["stream"]}),
        _record(2),  # the title left every platform before the re-fetch
        {"imdb": "not-a-number"},
    ]
    result = build_availability(records, "2026-11-03")
    assert result.fetched == "2026-11-03"
    assert set(result.titles) == {1}
    assert result.titles[1].on == {"hbo": {"stream": ("GB",)}}


def test_the_file_round_trips_and_is_byte_stable(tmp_path: Path) -> None:
    original = build_availability(
        [_record(603, US={"netflix": ["stream"]}, GB={"netflix": ["stream", "buy"]})], "2026-11-03"
    )
    path = tmp_path / AVAILABILITY_FILE
    write_availability(path, original)
    first = path.read_bytes()
    assert load_availability(path) == original
    write_availability(path, original)
    assert path.read_bytes() == first
    document = json.loads(first)
    assert document["titles"]["603"]["on"]["netflix"] == {"buy": "GB", "stream": "GB US"}
    assert b" " not in first.replace(b"GB US", b"")  # compact: the only spaces separate countries


def test_a_torn_last_line_in_the_cache_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "providers.jsonl"
    path.write_text(json.dumps(_record(1, US={"hbo": ["stream"]})) + '\n{"imdb": 2, "fo', "utf-8")
    assert [r["imdb"] for r in read_cache(path)] == [1]


def _artifact_set(tmp_path: Path) -> Path:
    directory = tmp_path / "v1"
    directory.mkdir()
    (directory / "catalogue.json").write_text("{}", encoding="utf-8")
    build(directory, row_counts={"catalogue.json": 0}, names=["catalogue.json"])
    return directory


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["availability", *args])
    module.main()


def test_the_command_adds_availability_to_a_copy_and_the_new_manifest_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _artifact_set(tmp_path)
    before = (source / "manifest.json").read_bytes()
    providers = tmp_path / "providers.jsonl"
    providers.write_text(json.dumps(_record(603, US={"netflix": ["stream"]})) + "\n", "utf-8")
    out = tmp_path / "v2"
    _run(
        monkeypatch,
        "--artifacts", str(source),
        "--providers", str(providers),
        "--fetched", "2026-11-03",
        "--out", str(out),
    )  # fmt: skip
    manifest = load_manifest(out)
    verify(out, manifest)
    assert set(manifest.files) == {*load_manifest(source).files, AVAILABILITY_FILE}
    loaded = load_availability(out / AVAILABILITY_FILE)
    expected = Availability(
        "2026-11-03", {603: Where("movie/603", {"netflix": {"stream": ("US",)}})}
    )
    assert loaded == expected
    assert (source / "manifest.json").read_bytes() == before
    assert not (source / AVAILABILITY_FILE).exists()
    assert "availability for 1 titles as of 2026-11-03" in capsys.readouterr().out


def test_the_command_refuses_to_overwrite_an_existing_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _artifact_set(tmp_path)
    existing = tmp_path / "taken"
    existing.mkdir()
    nowhere = str(tmp_path / "no-providers.jsonl")
    with pytest.raises(SystemExit, match="already exists"):
        _run(
            monkeypatch,
            "--artifacts", str(source),
            "--providers", nowhere,
            "--out", str(existing),
        )  # fmt: skip
