"""Download the two raw archives and verify them against pinned hashes.

Neither dataset is committed (CONSTRAINTS.md #6) and MovieLens forbids redistribution, so a
fresh checkout, CI job or Docker build fetches them here. Every file is checked against the
SHA-256 of the exact bytes the published numbers were produced from: a silently different
dataset would make every figure in `eval.json` unrepeatable.

Mirrors are tried in order. aclImdb's home (ai.stanford.edu) was unreachable from the
development machine on 2026-10-22, so a Hugging Face mirror of the same tarball is listed
second; the hash is what makes a mirror trustworthy, not its hostname.

Run: `python -m cinewhy.data.fetch`
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 1 << 20


@dataclass(frozen=True)
class Source:
    """One archive: where to get it and what it must hash to."""

    filename: str
    urls: tuple[str, ...]
    sha256: str
    size: int


SOURCES: tuple[Source, ...] = (
    Source(
        "aclImdb_v1.tar.gz",
        (
            "https://ai.stanford.edu/~amaas/data/sentiment/aclImdb_v1.tar.gz",
            "https://huggingface.co/datasets/NolanChai/aclImdb_v1/resolve/main/aclImdb_v1.tar.gz",
        ),
        "c40f74a18d3b61f90feba1e17730e0d38e8b97c05fde7008942e91923d1658fe",
        84_125_825,
    ),
    Source(
        "ml-25m.zip",
        ("https://files.grouplens.org/datasets/movielens/ml-25m.zip",),
        "8b21cfb7eb1706b4ec0aac894368d90acf26ebdfb6aced3ebd4ad5bd1eb9c6aa",
        261_978_986,
    ),
)


class HashMismatchError(RuntimeError):
    """Raised when a downloaded file is not the dataset the results were produced from."""


def sha256_of(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(source: Source, directory: Path) -> Path:
    """Ensure `source` exists in `directory` with the pinned hash, downloading if needed.

    A file already present is verified and kept; a corrupt one is replaced. A download is
    written to a temporary name and moved into place only after its hash checks out, so a
    partial or tampered file never sits under the real name.

    Args:
        source: The archive to obtain.
        directory: Destination directory (created if missing).

    Returns:
        Path to the verified file.

    Raises:
        HashMismatchError: If every mirror served bytes with the wrong hash.
        RuntimeError: If every mirror failed to respond.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.filename
    if target.is_file() and sha256_of(target) == source.sha256:
        return target

    failures: list[str] = []
    for url in source.urls:
        partial = target.with_suffix(target.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:
                shutil.copyfileobj(response, out, _CHUNK)
        except OSError as exc:
            failures.append(f"{url}: {exc}")
            continue
        if sha256_of(partial) == source.sha256:
            partial.replace(target)
            return target
        failures.append(f"{url}: wrong hash")
        partial.unlink(missing_ok=True)
    detail = "; ".join(failures)
    if any("wrong hash" in f for f in failures):
        raise HashMismatchError(f"{source.filename} did not match its pinned hash ({detail})")
    raise RuntimeError(f"could not download {source.filename} ({detail})")


def main() -> None:
    """Fetch every source into `Data/raw` (or `--dir`)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--dir", type=Path, default=Path("Data/raw"))
    args = parser.parse_args()
    for source in SOURCES:
        path = fetch(source, args.dir)
        print(f"ok {path} ({path.stat().st_size} bytes, sha256 verified)")


if __name__ == "__main__":
    main()
