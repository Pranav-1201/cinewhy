"""Build, hash and verify the artifact set the API loads at boot.

Everything expensive happens here, offline. The API only ever reads what this module
produced — no training, no embedding, no fitting inside a request handler. That rule is
what makes a free CPU tier viable (DECISIONS.md D-005).

Artifacts are content-hashed and immutable. Rolling back means pointing the manifest at
previous hashes, never mutating a file in place (ROLLBACK.md §4).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from cinewhy.schemas import ArtifactManifest

MANIFEST_NAME: Final[str] = "manifest.json"
_CHUNK: Final[int] = 1 << 20


class ManifestMismatchError(RuntimeError):
    """Raised when an artifact's hash does not match the manifest.

    This is deliberately fatal at boot. A partially-written or stale artifact set
    produces confidently wrong recommendations, which is worse than an outage because
    nobody notices it.
    """


def hash_file(path: Path) -> str:
    """Return the content hash of one artifact.

    Args:
        path: File to hash.

    Returns:
        SHA-256 hex digest of the file's exact bytes. Read in binary: text mode on
        Windows rewrites CRLF to LF, so the same file would hash differently here and on
        a Linux runner and the API would refuse to boot on one of them.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(files: dict[str, str]) -> str:
    """One digest over every (name, hash) pair, order-independent.

    The manifest hash is what `/health` reports, so it must change when any single
    artifact changes and must not depend on directory listing order.
    """
    joined = "\n".join(f"{name}:{files[name]}" for name in sorted(files))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def build(
    artifact_dir: Path,
    *,
    row_counts: dict[str, int] | None = None,
    names: Sequence[str] | None = None,
) -> ArtifactManifest:
    """Hash artifacts in `artifact_dir` and write manifest.json beside them.

    Args:
        artifact_dir: Directory containing the built artifacts.
        row_counts: Optional record counts per artifact, kept for the audit trail.
        names: Exactly which files are artifacts. Pass this whenever the directory also
            holds logs or scratch files: hashing a log that is still being written makes the
            manifest fail to verify on the very next boot. Defaults to every file.

    Returns:
        The manifest that was written.

    Raises:
        FileNotFoundError: If a name in `names` is not a file in the directory.
    """
    if names is None:
        chosen = [
            p.name
            for p in sorted(artifact_dir.iterdir())
            if p.is_file() and p.name != MANIFEST_NAME
        ]
    else:
        chosen = sorted(names)
        missing = [n for n in chosen if not (artifact_dir / n).is_file()]
        if missing:
            raise FileNotFoundError(f"artifacts not found in {artifact_dir}: {missing}")
    files = {name: hash_file(artifact_dir / name) for name in chosen}
    manifest = ArtifactManifest(
        manifest_hash=_combined_hash(files),
        built_at=datetime.now(UTC).isoformat(timespec="seconds"),
        files=files,
        row_counts=row_counts or {},
    )
    (artifact_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest.model_dump(), indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def load_manifest(artifact_dir: Path) -> ArtifactManifest:
    """Read manifest.json from `artifact_dir`.

    Raises:
        ManifestMismatchError: If the manifest is missing or unreadable.
    """
    path = artifact_dir / MANIFEST_NAME
    try:
        return ArtifactManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestMismatchError(f"cannot read {path}") from exc


def verify(artifact_dir: Path, manifest: ArtifactManifest) -> None:
    """Check every file against the manifest.

    Args:
        artifact_dir: Directory containing the built artifacts.
        manifest: Expected hashes.

    Raises:
        ManifestMismatchError: If any file is missing or its hash differs, or if the
            manifest's own combined hash no longer matches its file table (someone
            edited the manifest to bless a swapped artifact).
    """
    if _combined_hash(manifest.files) != manifest.manifest_hash:
        raise ManifestMismatchError("manifest file table does not match its own hash")
    for name, expected in manifest.files.items():
        path = artifact_dir / name
        if not path.is_file():
            raise ManifestMismatchError(f"artifact missing: {name}")
        if hash_file(path) != expected:
            raise ManifestMismatchError(f"artifact changed since the build: {name}")
