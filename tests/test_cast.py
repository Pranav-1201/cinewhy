"""The cast file: who is kept from IMDb's credits, in what order, and that a build stays valid."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

from cinewhy.artifacts.manifest import build, load_manifest, verify
from cinewhy.data import cast as cast_module
from cinewhy.data.cast import (
    CAST_FILE,
    Cast,
    build_cast,
    imdb_numbers,
    load_cast,
    read_names,
    read_principals,
    write_cast,
)

_HEADER = "tconst\tordering\tnconst\tcategory\tjob\tcharacters\n"
_NAMES_HEADER = "nconst\tprimaryName\tbirthYear\tdeathYear\tprimaryProfession\tknownForTitles\n"


def _principals(
    tmp_path: Path, rows: list[tuple[str, int, str, str]], name: str = "p.tsv.gz"
) -> Path:
    path = tmp_path / name
    body = "".join(f"{t}\t{o}\t{n}\t{c}\t\\N\t\\N\n" for t, o, n, c in rows)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(_HEADER + body)
    return path


def _names(tmp_path: Path, people: dict[str, str], name: str = "n.tsv.gz") -> Path:
    path = tmp_path / name
    body = "".join(f"{n}\t{full}\t1970\t\\N\tactor\ttt0000001\n" for n, full in people.items())
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(_NAMES_HEADER + body)
    return path


def test_actors_and_actresses_are_kept_and_other_credits_are_not(tmp_path: Path) -> None:
    rows = [
        ("tt0000603", 1, "nm0000001", "actor"),
        ("tt0000603", 2, "nm0000002", "director"),
        ("tt0000603", 3, "nm0000003", "actress"),
        ("tt0000603", 4, "nm0000004", "self"),
        ("tt0000603", 5, "nm0000005", "writer"),
    ]
    got = read_principals(_principals(tmp_path, rows), {603})
    assert got == {603: (1, 3)}


def test_people_come_in_billing_order_not_file_order_and_the_top_few_are_kept(
    tmp_path: Path,
) -> None:
    rows = [("tt0000010", order, f"nm{order:07d}", "actor") for order in (5, 2, 9, 1, 7)]
    assert read_principals(_principals(tmp_path, rows), {10}, top=3) == {10: (1, 2, 5)}


def test_only_the_wanted_titles_are_read(tmp_path: Path) -> None:
    rows = [("tt0000010", 1, "nm0000001", "actor"), ("tt0000011", 1, "nm0000002", "actor")]
    assert read_principals(_principals(tmp_path, rows), {11}) == {11: (2,)}


def test_a_header_short_lines_and_bad_ids_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "p.tsv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(_HEADER)
        handle.write("tt0000010\t1\tnm0000001\tactor\t\\N\t\\N\n")
        handle.write("tt0000010\tone\tnm0000002\tactor\t\\N\t\\N\n")  # ordering is not a number
        handle.write("ttXYZ\t1\tnm0000003\tactor\t\\N\t\\N\n")  # not an IMDb number
        handle.write("tt0000010\t2\n")  # too short
    assert read_principals(path, {10}) == {10: (1,)}


def test_names_are_read_only_for_the_people_needed(tmp_path: Path) -> None:
    path = _names(tmp_path, {"nm0000001": "Fred Astaire", "nm0000002": "Lauren Bacall"})
    assert read_names(path, {2}) == {2: "Lauren Bacall"}


def test_a_person_with_no_name_is_dropped_and_a_title_left_empty_goes_with_them(
    tmp_path: Path,
) -> None:
    rows = [
        ("tt0000010", 1, "nm0000001", "actor"),
        ("tt0000010", 2, "nm0000002", "actress"),  # no name in the names file
        ("tt0000011", 1, "nm0000003", "actor"),  # no name either: the title has nobody left
    ]
    names = _names(tmp_path, {"nm0000001": "Fred Astaire"})
    cast = build_cast(_principals(tmp_path, rows), names, {10, 11})
    assert cast.titles == {10: (1,)}
    assert cast.people == {1: "Fred Astaire"}


def test_the_index_from_a_person_to_their_titles_is_derived() -> None:
    cast = Cast({30: (1, 2), 10: (1,), 20: (2, 1)}, {1: "A", 2: "B"})
    assert cast.by_person == {1: (10, 20, 30), 2: (20, 30)}


def test_the_file_round_trips_and_is_byte_for_byte_reproducible(tmp_path: Path) -> None:
    cast = Cast({603: (2, 1), 10: (1,)}, {1: "Fred Astaire", 2: "Zoë Saldaña"})
    flipped = Cast(
        dict(reversed(list(cast.titles.items()))), dict(reversed(list(cast.people.items())))
    )
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    write_cast(first, cast)
    write_cast(second, flipped)
    assert first.read_bytes() == second.read_bytes()  # insertion order never changes the file
    assert load_cast(first) == cast
    assert "Zoë Saldaña" in first.read_text(encoding="utf-8")  # names are kept as written
    assert json.loads(first.read_text(encoding="utf-8"))["titles"]["603"] == [2, 1]  # billing order


def test_both_tiers_of_catalogue_id_give_the_same_imdb_number() -> None:
    assert imdb_numbers(["cw-0000603", "ro-0000603", "ro-0000010"]) == {603, 10}


def _artifact_set(tmp_path: Path) -> Path:
    directory = tmp_path / "v1"
    directory.mkdir()
    (directory / "catalogue.json").write_text(
        json.dumps({"movies": [{"movie_id": "cw-0000010"}]}), encoding="utf-8"
    )
    (directory / "ratings_only.json").write_text(
        json.dumps([{"movie_id": "ro-0000011", "imdb_id": 11}]), encoding="utf-8"
    )
    (directory / "eval.json").write_text("{}", encoding="utf-8")
    names = ["catalogue.json", "ratings_only.json", "eval.json"]
    build(directory, row_counts={"catalogue.json": 1}, names=names)
    return directory


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["cast", *args])
    cast_module.main()


def test_the_command_adds_the_cast_to_a_copy_and_the_new_manifest_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _artifact_set(tmp_path)
    before = (source / "manifest.json").read_bytes()
    rows = [("tt0000010", 1, "nm0000001", "actor"), ("tt0000011", 1, "nm0000002", "actress")]
    cast_dir = tmp_path / "cast"
    cast_dir.mkdir()
    _principals(cast_dir, rows, "title.principals.tsv.gz")
    people = {"nm0000001": "Fred Astaire", "nm0000002": "Lauren Bacall"}
    _names(cast_dir, people, "name.basics.tsv.gz")
    out = tmp_path / "v2"
    _run(monkeypatch, "--artifacts", str(source), "--cast-dir", str(cast_dir), "--out", str(out))
    manifest = load_manifest(out)
    verify(out, manifest)  # the new file is hashed into the manifest the API checks
    assert set(manifest.files) == {*load_manifest(source).files, CAST_FILE}
    assert load_cast(out / CAST_FILE).titles == {10: (1,), 11: (2,)}  # both tiers covered
    assert (source / "manifest.json").read_bytes() == before  # the source build is untouched
    assert not (source / CAST_FILE).exists()
    assert "cast for 2 of 2 titles" in capsys.readouterr().out


def test_the_command_refuses_to_overwrite_an_existing_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _artifact_set(tmp_path)
    existing = tmp_path / "taken"
    existing.mkdir()
    nowhere = str(tmp_path / "no-cast-files")  # a regression must never reach the real IMDb files
    with pytest.raises(SystemExit, match="already exists"):
        _run(monkeypatch, "--artifacts", str(source), "--cast-dir", nowhere, "--out", str(existing))


def test_the_command_refuses_a_source_build_that_fails_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _artifact_set(tmp_path)
    (source / "eval.json").write_text('{"tampered": true}', encoding="utf-8")
    nowhere = str(tmp_path / "no-cast-files")  # a regression must never reach the real IMDb files
    with pytest.raises(Exception, match="changed since the build"):
        _run(
            monkeypatch,
            "--artifacts",
            str(source),
            "--cast-dir",
            nowhere,
            "--out",
            str(tmp_path / "v2"),
        )
    assert not (tmp_path / "v2").exists()
