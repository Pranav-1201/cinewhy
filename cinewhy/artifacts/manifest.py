"""Build, hash and verify the artifact set the API loads at boot.

Everything expensive happens here, offline. The API only ever reads what this module
produced — no training, no embedding, no fitting inside a request handler. That rule is
what makes a free CPU tier viable (DECISIONS.md D-005).

Artifacts are content-hashed and immutable. Rolling back means pointing the manifest at
previous hashes, never mutating a file in place (ROLLBACK.md §4).
"""

from __future__ import annotations

from pathlib import Path

from cinewhy.schemas import ArtifactManifest


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
        Hex digest, stable across platforms — hash bytes, never text, so CRLF/LF
        differences between Pranav's and Lakshay's checkouts cannot change it.
    """
    raise NotImplementedError("Phase D")


def build(artifact_dir: Path) -> ArtifactManifest:
    """Hash every artifact in `artifact_dir` and write manifest.json beside them.

    Args:
        artifact_dir: Directory containing the built artifacts.

    Returns:
        The manifest that was written.
    """
    raise NotImplementedError("Phase D")


def verify(artifact_dir: Path, manifest: ArtifactManifest) -> None:
    """Check every file against the manifest.

    Args:
        artifact_dir: Directory containing the built artifacts.
        manifest: Expected hashes.

    Raises:
        ManifestMismatchError: If any file is missing or its hash differs.
    """
    raise NotImplementedError("Phase D")
