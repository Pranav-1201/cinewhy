"""Fetching the artifact set at container start (cinewhy/artifacts/download.py), with no network.

A fake opener hands back an in-memory zip, so every refusal can be exercised: a wrong hash, a path
that would escape the folder, a symlink, an oversize archive, a zip with no manifest, a plain-http
address.
"""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import IO

import pytest

from cinewhy.artifacts import download
from cinewhy.artifacts.download import ArtifactsError, ensure_artifacts

URL = "https://example.test/cinewhy-artifacts.zip"


def _zip(members: dict[str, bytes], *, folder: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(f"{folder}{name}", data)
    return buffer.getvalue()


def _opener(blob: bytes, calls: list[str] | None = None) -> Callable[[str], IO[bytes]]:
    def open_url(url: str) -> IO[bytes]:
        if calls is not None:
            calls.append(url)
        return io.BytesIO(blob)

    return open_url


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


GOOD = {"manifest.json": b"{}", "catalogue.json": b"[]"}


def test_an_existing_artifact_set_is_left_alone_and_nothing_is_fetched(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}")
    calls: list[str] = []
    assert ensure_artifacts(tmp_path, None, None, opener=_opener(b"", calls)) is False
    assert calls == []


def test_a_good_archive_is_unpacked(tmp_path: Path) -> None:
    blob = _zip(GOOD)
    target = tmp_path / "artifacts"
    assert ensure_artifacts(target, URL, _sha(blob), opener=_opener(blob)) is True
    assert (target / "manifest.json").read_bytes() == b"{}"
    assert (target / "catalogue.json").read_bytes() == b"[]"


def test_a_zip_of_a_single_folder_is_unpacked_without_that_folder(tmp_path: Path) -> None:
    blob = _zip(GOOD, folder="v3/")
    target = tmp_path / "artifacts"
    ensure_artifacts(target, URL, _sha(blob), opener=_opener(blob))
    assert (target / "manifest.json").is_file() and not (target / "v3").exists()


def test_the_hash_is_compared_case_and_space_insensitively(tmp_path: Path) -> None:
    blob = _zip(GOOD)
    ensure_artifacts(tmp_path / "a", URL, f"  {_sha(blob).upper()} ", opener=_opener(blob))
    assert (tmp_path / "a" / "manifest.json").is_file()


def test_nothing_there_and_nothing_to_fetch_is_an_error(tmp_path: Path) -> None:
    for url, sha in ((None, None), (URL, None), (None, "abc")):
        with pytest.raises(ArtifactsError, match="nothing to start from"):
            ensure_artifacts(tmp_path / "a", url, sha, opener=_opener(b""))


def test_a_download_with_the_wrong_hash_is_refused_and_leaves_no_manifest(tmp_path: Path) -> None:
    blob = _zip(GOOD)
    target = tmp_path / "artifacts"
    with pytest.raises(ArtifactsError, match="SHA-256"):
        ensure_artifacts(target, URL, "0" * 64, opener=_opener(blob))
    assert not (target / "manifest.json").exists()


def test_only_https_is_accepted(tmp_path: Path) -> None:
    blob = _zip(GOOD)
    for url in ("http://example.test/a.zip", "file:///etc/passwd", "ftp://example.test/a.zip"):
        with pytest.raises(ArtifactsError, match="https"):
            ensure_artifacts(tmp_path / "a", url, _sha(blob), opener=_opener(blob))


@pytest.mark.parametrize(
    "name", ["../evil.txt", "ok/../../evil.txt", "/abs/evil.txt", "a\\..\\evil.txt"]
)
def test_a_member_that_could_escape_the_folder_is_refused(tmp_path: Path, name: str) -> None:
    blob = _zip({**GOOD, name: b"x"})
    target = tmp_path / "sub" / "artifacts"
    with pytest.raises(ArtifactsError, match="escape"):
        ensure_artifacts(target, URL, _sha(blob), opener=_opener(blob))
    assert not (tmp_path / "sub" / "evil.txt").exists() and not (tmp_path / "evil.txt").exists()
    assert not (target / "manifest.json").exists()


def test_a_symlink_member_is_refused(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("manifest.json", b"{}")
        link = zipfile.ZipInfo("link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(link, "/etc/passwd")
    blob = buffer.getvalue()
    with pytest.raises(ArtifactsError, match="symbolic link"):
        ensure_artifacts(tmp_path / "a", URL, _sha(blob), opener=_opener(blob))
    assert not (tmp_path / "a" / "manifest.json").exists()


def test_an_archive_that_unpacks_too_large_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download, "MAX_UNPACKED_BYTES", 3)
    blob = _zip(GOOD)  # 2 + 2 = 4 bytes of content against a limit of 3
    with pytest.raises(ArtifactsError, match="more than the allowed size"):
        ensure_artifacts(tmp_path / "a", URL, _sha(blob), opener=_opener(blob))


def test_an_archive_without_a_manifest_is_refused_and_cleaned_up(tmp_path: Path) -> None:
    blob = _zip({"catalogue.json": b"[]"})
    target = tmp_path / "artifacts"
    with pytest.raises(ArtifactsError, match=r"no manifest\.json"):
        ensure_artifacts(target, URL, _sha(blob), opener=_opener(blob))
    assert not target.exists()


def test_bytes_that_are_not_a_zip_are_refused(tmp_path: Path) -> None:
    blob = b"this is not a zip file"
    with pytest.raises(zipfile.BadZipFile):
        ensure_artifacts(tmp_path / "a", URL, _sha(blob), opener=_opener(blob))
    assert not (tmp_path / "a" / "manifest.json").exists()


def test_the_command_exits_non_zero_with_a_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CINEWHY_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.delenv("CINEWHY_ARTIFACTS_URL", raising=False)
    monkeypatch.delenv("CINEWHY_ARTIFACTS_SHA256", raising=False)
    with pytest.raises(SystemExit) as stopped:
        download.main()
    assert stopped.value.code == 1
    assert "nothing to start from" in capsys.readouterr().err
