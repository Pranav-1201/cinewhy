"""Dataset download: pinned hashes decide what is accepted, never the hostname."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cinewhy.data.fetch import SOURCES, HashMismatchError, Source, fetch, sha256_of


def _source(tmp_path: Path, payload: bytes, *, claimed: bytes | None = None) -> Source:
    origin = tmp_path / "origin.bin"
    origin.write_bytes(payload)
    digest = hashlib.sha256(claimed if claimed is not None else payload).hexdigest()
    return Source("data.bin", (origin.as_uri(),), digest, len(payload))


def test_downloads_and_verifies(tmp_path: Path) -> None:
    source = _source(tmp_path, b"hello")
    path = fetch(source, tmp_path / "raw")
    assert path.read_bytes() == b"hello"


def test_a_wrong_hash_is_rejected_and_leaves_nothing_under_the_real_name(tmp_path: Path) -> None:
    source = _source(tmp_path, b"tampered", claimed=b"the real dataset")
    with pytest.raises(HashMismatchError):
        fetch(source, tmp_path / "raw")
    assert not (tmp_path / "raw" / "data.bin").exists()
    assert not list((tmp_path / "raw").glob("*.part"))


def test_a_good_file_already_present_is_kept_without_downloading(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "data.bin").write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    source = Source("data.bin", ("file:///does/not/exist",), digest, 5)
    assert fetch(source, raw) == raw / "data.bin"


def test_a_corrupt_file_is_replaced(tmp_path: Path) -> None:
    source = _source(tmp_path, b"hello")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "data.bin").write_bytes(b"corrupt")
    assert fetch(source, raw).read_bytes() == b"hello"


def test_unreachable_mirrors_raise_a_plain_error_not_a_hash_error(tmp_path: Path) -> None:
    source = Source("x.bin", ("file:///no/such/file",), "0" * 64, 1)
    with pytest.raises(RuntimeError) as info:
        fetch(source, tmp_path)
    assert not isinstance(info.value, HashMismatchError)


def test_the_pinned_hashes_match_the_files_the_results_came_from() -> None:
    local = Path("Data/raw")
    checked = 0
    for source in SOURCES:
        path = local / source.filename
        if path.is_file():  # only present on a machine that has already fetched
            assert sha256_of(path) == source.sha256
            checked += 1
    if not checked:
        pytest.skip("no raw data on this machine")
