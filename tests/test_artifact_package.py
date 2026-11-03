"""Packing a built artifact set into the zip a teammate downloads.

The real set is 1.8 GB; these use a few small files and the real manifest code, so every refusal
and the round trip (pack, unpack, verify) are checked without it.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from cinewhy.artifacts import package as package_module
from cinewhy.artifacts.manifest import build, load_manifest, verify
from cinewhy.artifacts.package import PackageError, newest_artifacts, package


def _build(root: Path, name: str = "v1") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "a.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "b.bin").write_bytes(bytes(range(256)) * 50)
    (folder / "server.log").write_text("not an artifact", encoding="utf-8")
    build(folder, names=["a.json", "b.bin"])
    return folder


def test_the_zip_holds_the_manifest_and_the_listed_files_flat_and_nothing_else(
    tmp_path: Path,
) -> None:
    folder = _build(tmp_path)
    result = package(folder)
    with zipfile.ZipFile(result.path) as bundle:
        assert bundle.namelist() == ["manifest.json", "a.json", "b.bin"]  # no log, no folders
    assert result.path == tmp_path / "cinewhy-artifacts-v1.zip"


def test_unzipping_into_a_fresh_folder_gives_a_set_that_verifies(tmp_path: Path) -> None:
    result = package(_build(tmp_path))
    fresh = tmp_path / "teammate" / "artifacts" / "v1"
    with zipfile.ZipFile(result.path) as bundle:
        bundle.extractall(fresh)
    verify(fresh, load_manifest(fresh))  # what the teammate's server does at start


def test_every_member_carries_the_fixed_timestamp_so_the_zip_does_not_depend_on_the_clock(
    tmp_path: Path,
) -> None:
    # Two zips made in the same second would match even with a wall-clock stamp, so check the stamp.
    with zipfile.ZipFile(package(_build(tmp_path)).path) as bundle:
        assert {info.date_time for info in bundle.infolist()} == {(2020, 1, 1, 0, 0, 0)}


def test_the_same_data_gives_the_same_zip_and_hash(tmp_path: Path) -> None:
    folder = _build(tmp_path)
    first = package(folder, tmp_path / "one")
    second = package(folder, tmp_path / "two")
    assert first.sha256 == second.sha256
    assert first.path.read_bytes() == second.path.read_bytes()


def test_the_reported_hash_and_size_are_those_of_the_file_and_are_written_beside_it(
    tmp_path: Path,
) -> None:
    result = package(_build(tmp_path))
    assert result.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest().upper()
    assert result.size_bytes == result.path.stat().st_size
    note = result.path.with_name(result.path.name + ".sha256").read_text(encoding="utf-8")
    assert note == f"{result.sha256}  {result.path.name}\n"


def test_a_changed_file_is_refused_and_no_zip_is_left_behind(tmp_path: Path) -> None:
    folder = _build(tmp_path)
    (folder / "a.json").write_text('{"a": 2}', encoding="utf-8")  # edited after the build
    with pytest.raises(PackageError, match="does not match its manifest"):
        package(folder)
    assert not list(tmp_path.glob("*.zip*"))


@pytest.mark.filterwarnings("ignore:Duplicate name")  # the corruption below adds one on purpose
def test_a_zip_that_does_not_unpack_to_a_verified_copy_is_never_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _build(tmp_path)
    real = package_module._write_zip

    def corrupt(source: Path, names: list[str], target: Path) -> None:
        real(source, names, target)
        with zipfile.ZipFile(target, "a") as bundle:  # a second, different a.json wins on unpack
            bundle.writestr("a.json", '{"a": 999}')

    monkeypatch.setattr(package_module, "_write_zip", corrupt)
    with pytest.raises(PackageError, match="does not unpack to a verified copy"):
        package(folder)
    assert not list(tmp_path.glob("*.zip*"))  # neither the zip nor the half-written file


def test_the_newest_folder_with_a_manifest_is_chosen(tmp_path: Path) -> None:
    _build(tmp_path, "v2")
    _build(tmp_path, "v13")
    (tmp_path / "v99").mkdir()  # a half-made build with no manifest is skipped
    (tmp_path / "vnext").mkdir()
    assert newest_artifacts(tmp_path).name == "v13"  # numeric order, not alphabetical


def test_with_no_build_at_all_it_says_so(tmp_path: Path) -> None:
    with pytest.raises(PackageError, match="no artifacts/vN folder"):
        newest_artifacts(tmp_path)


def test_the_command_exits_non_zero_on_a_folder_that_cannot_be_packed(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stopped:
        package_module.main([str(tmp_path / "missing")])
    assert stopped.value.code == 1


def test_the_command_packs_the_given_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _build(tmp_path)
    package_module.main([str(folder)])
    out = capsys.readouterr().out
    assert "cinewhy-artifacts-v1.zip" in out and "SHA-256" in out
