"""Fetch a built artifact set at container start, check it, and unpack it safely.

A free host gives a container no volume that already holds the 365 MB artifact set, and the set is
neither committed nor redistributable from this repository. So the container's start command runs

    python -m cinewhy.artifacts.download

before the server. If `$CINEWHY_ARTIFACTS` (default `artifacts`) already holds a manifest nothing
happens. Otherwise the zip at `$CINEWHY_ARTIFACTS_URL` is downloaded, its SHA-256 must equal
`$CINEWHY_ARTIFACTS_SHA256`, and it is unpacked into the folder. The server then verifies every
file against the manifest inside it before serving anything (FLOW.md section 4), so this module's
job is only to put the right bytes in the right place and refuse everything else.

What it refuses, each with a message and a non-zero exit: a URL that is not https; a download whose
hash differs from the one promised; a zip member that would land outside the folder (a path with
`..`, an absolute path, a symlink); an archive that unpacks to more than `MAX_UNPACKED_BYTES`; an
archive with no manifest. A half-finished unpack is removed, so a failed start never leaves a folder
that looks complete.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import IO, Final, cast

MAX_UNPACKED_BYTES: Final[int] = 3 * 1024**3  # the real set is about 0.9 GB unpacked
_CHUNK: Final[int] = 1024 * 1024
Opener = Callable[[str], IO[bytes]]


class ArtifactsError(RuntimeError):
    """The artifact set could not be put in place; the message says why."""


def _open_https(url: str) -> IO[bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "cinewhy-artifact-fetch"})
    return cast(IO[bytes], urllib.request.urlopen(request, timeout=60))


def _download(url: str, expected_sha256: str, target: Path, opener: Opener) -> None:
    """Stream `url` into `target`, failing if the SHA-256 is not `expected_sha256`."""
    digest = hashlib.sha256()
    with opener(url) as response, target.open("wb") as out:
        while chunk := response.read(_CHUNK):
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest().lower() != expected_sha256.strip().lower():
        raise ArtifactsError(
            f"the download's SHA-256 is {digest.hexdigest()}, not the {expected_sha256} that was "
            "promised; it was not unpacked"
        )


def _top_folder(names: list[str]) -> str:
    """The one folder every member sits in (a zip of `v3/`), or '' if files are at the top."""
    tops = {PurePosixPath(n).parts[0] for n in names if n.strip("/")}
    if len(tops) != 1:
        return ""
    top = next(iter(tops))
    # Strip it only when everything sits inside it: a file at the top level is not a folder.
    file_at_top = any(PurePosixPath(n).parts == (top,) and not n.endswith("/") for n in names)
    return "" if file_at_top else top


def _safe_target(root: Path, member: zipfile.ZipInfo, strip: str) -> Path:
    """Where `member` goes under `root`, or an error if it would escape or is a symlink."""
    name = member.filename
    mode = member.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise ArtifactsError(f"the archive contains a symbolic link ({name}); refusing it")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise ArtifactsError(f"the archive has a path that could escape the folder ({name})")
    if strip and relative.parts[:1] == (strip,):
        relative = PurePosixPath(*relative.parts[1:])
    resolved_root = root.resolve()
    target = (root / relative).resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise ArtifactsError(f"the archive has a path that could escape the folder ({name})")
    return target


def _unpack(archive: Path, directory: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
            raise ArtifactsError("the archive would unpack to more than the allowed size")
        strip = _top_folder([m.filename for m in members])
        directory.mkdir(parents=True, exist_ok=True)
        for member in members:
            target = _safe_target(directory, member, strip)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
    if not (directory / "manifest.json").is_file():
        raise ArtifactsError("the archive holds no manifest.json, so it is not an artifact set")


def ensure_artifacts(
    directory: Path, url: str | None, sha256: str | None, *, opener: Opener = _open_https
) -> bool:
    """Make sure `directory` holds an artifact set, fetching one if it does not.

    Args:
        directory: Where the server reads artifacts from.
        url: https address of the zip, used only when `directory` has no manifest.
        sha256: The zip's SHA-256 in hex; required whenever a download happens.
        opener: Opens a URL for reading; replaced in tests so no network is needed.

    Returns:
        True if something was downloaded, False if the folder was already complete.

    Raises:
        ArtifactsError: If nothing is there and nothing can be fetched, or the download or the
            archive fails any of the checks in the module docstring. The folder is left without a
            manifest in that case.
    """
    if (directory / "manifest.json").is_file():
        return False
    if not url or not sha256:
        raise ArtifactsError(
            f"{directory} holds no artifacts and CINEWHY_ARTIFACTS_URL / CINEWHY_ARTIFACTS_SHA256 "
            "are not both set, so there is nothing to start from"
        )
    if not url.startswith("https://"):
        raise ArtifactsError("the artifact URL must be https")
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory.parent) as scratch:
        archive = Path(scratch) / "artifacts.zip"
        _download(url, sha256, archive, opener)
        try:
            _unpack(archive, directory)
        except (ArtifactsError, zipfile.BadZipFile):
            shutil.rmtree(directory, ignore_errors=True)  # never leave something that looks whole
            raise
    return True


def main() -> None:
    """Command line: read the three environment variables and make sure the artifacts are there."""
    directory = Path(os.environ.get("CINEWHY_ARTIFACTS", "artifacts"))
    try:
        fetched = ensure_artifacts(
            directory,
            os.environ.get("CINEWHY_ARTIFACTS_URL"),
            os.environ.get("CINEWHY_ARTIFACTS_SHA256"),
        )
    except (ArtifactsError, zipfile.BadZipFile, OSError) as err:
        print(f"artifact fetch failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err
    print(f"artifacts {'downloaded to' if fetched else 'already in'} {directory}")


if __name__ == "__main__":
    main()
