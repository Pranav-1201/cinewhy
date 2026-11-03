"""Pack a built artifact set into the zip a teammate downloads, and prove the zip works.

The data is not in the git repository (its licences forbid republishing it), so a teammate gets one
zip from the owner and unpacks it into `artifacts/vN`. That zip must always match the newest build:
run this after ANY change to an `artifacts/vN` folder (a new build, an edited file, a new version):

    python -m cinewhy.artifacts.package            # the newest artifacts/vN
    python -m cinewhy.artifacts.package artifacts/v13

What it does, in order, and refuses at the first failure:

1. verifies the folder against its own manifest (a half-edited folder is never packed);
2. writes `cinewhy-artifacts-vN.zip` next to the folder: only `manifest.json` and the files the
   manifest lists (so a stray log never travels), flat, with fixed timestamps, so the same data
   always gives the same zip and the same SHA-256;
3. unpacks the zip into a temporary folder and verifies that copy against the manifest, which is
   what the teammate's server does at start;
4. writes `<zip>.sha256` and prints the hash and size for the README (step 4, "Get the data").

The zip is flat (`manifest.json` at its root), so unzipping it INTO `artifacts/vN` is all a teammate
does. `cinewhy.artifacts.download` reads the same layout.
"""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cinewhy.artifacts.manifest import MANIFEST_NAME, load_manifest, verify
from cinewhy.schemas import ArtifactManifest

_CHUNK: Final[int] = 1 << 20
# A fixed timestamp makes the zip reproducible: unchanged data gives the same bytes and hash.
_STAMP: Final[tuple[int, int, int, int, int, int]] = (2020, 1, 1, 0, 0, 0)
_VERSION: Final[re.Pattern[str]] = re.compile(r"v(\d+)")


class PackageError(RuntimeError):
    """The artifact folder could not be packed; the message says why."""


@dataclass(frozen=True)
class Packaged:
    """What was written: the zip, its SHA-256 (upper case, as the README prints it) and its size."""

    path: Path
    sha256: str
    size_bytes: int


def newest_artifacts(root: Path = Path("artifacts")) -> Path:
    """The highest-numbered `vN` folder under `root` that has a manifest (what the server loads)."""
    found = [
        (int(match.group(1)), path)
        for path in root.glob("v*")
        if (match := _VERSION.fullmatch(path.name)) and (path / MANIFEST_NAME).is_file()
    ]
    if not found:
        raise PackageError(f"no artifacts/vN folder with a manifest under {root}")
    return max(found)[1]


def _members(manifest: ArtifactManifest) -> list[str]:
    """The manifest first, then every file it lists, in a fixed order."""
    return [MANIFEST_NAME, *sorted(manifest.files)]


def _write_zip(source: Path, names: list[str], target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with (
                (source / name).open("rb") as handle,
                bundle.open(info, "w", force_zip64=True) as out,
            ):
                while chunk := handle.read(_CHUNK):
                    out.write(chunk)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest().upper()


def package(artifact_dir: Path, out_dir: Path | None = None, *, check: bool = True) -> Packaged:
    """Pack `artifact_dir` into `cinewhy-artifacts-<name>.zip` and (by default) prove it unpacks.

    Args:
        artifact_dir: A built folder such as `artifacts/v13`, with its manifest.
        out_dir: Where the zip goes; default is the folder that holds `artifact_dir`.
        check: Unpack the finished zip to a temporary folder and verify it against the manifest.

    Raises:
        PackageError: If the folder does not verify, or the zip does not unpack to a verified copy.
    """
    manifest = load_manifest(artifact_dir)
    try:
        verify(artifact_dir, manifest)
    except RuntimeError as err:
        raise PackageError(
            f"{artifact_dir} does not match its manifest, so it was not packed: {err}"
        ) from err
    out = out_dir or artifact_dir.parent
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"cinewhy-artifacts-{artifact_dir.name}.zip"
    partial = target.with_name(target.name + ".partial")
    try:
        _write_zip(artifact_dir, _members(manifest), partial)
        if check:
            with tempfile.TemporaryDirectory() as scratch:
                with zipfile.ZipFile(partial) as bundle:
                    bundle.extractall(scratch)
                try:
                    verify(Path(scratch), load_manifest(Path(scratch)))
                except RuntimeError as err:
                    raise PackageError(
                        f"the zip does not unpack to a verified copy: {err}"
                    ) from err
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    digest = _sha256(target)
    note = target.with_name(target.name + ".sha256")
    note.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return Packaged(target, digest, target.stat().st_size)


def main(argv: list[str] | None = None) -> None:
    """Command line: pack the folder given, or the newest `artifacts/vN`."""
    args = sys.argv[1:] if argv is None else argv
    try:
        folder = Path(args[0]) if args else newest_artifacts()
        result = package(folder)
    except (PackageError, RuntimeError, OSError) as err:
        print(f"packaging failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err
    megabytes = result.size_bytes / 1_000_000
    print(f"wrote {result.path} ({megabytes:,.0f} MB)")
    print(f"SHA-256 {result.sha256}")
    print("Now put that hash and size in README.md, step 4 (Get the data), and share the zip.")


if __name__ == "__main__":
    main()
