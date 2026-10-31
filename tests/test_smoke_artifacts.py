"""The artifact set the CI boot check uses must verify and serve.

If this fails, the docker job would fail for the wrong reason: a broken fixture, not a broken image.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.artifacts.manifest import load_manifest, verify
from tests.smoke_artifacts import write_smoke_artifacts


def test_smoke_artifacts_verify_and_serve(tmp_path: Path) -> None:
    out = write_smoke_artifacts(tmp_path / "smoke")
    manifest = load_manifest(out)
    verify(out, manifest)
    assert len(manifest.files) >= 4  # catalogue, profiles, evidence, similarity, polarity, eval
    with TestClient(api_main.create_app(out)) as client:
        health = client.get("/health").json()
        assert health["manifest"] == manifest.manifest_hash
        assert len(health["manifest"]) == 64
        answer = client.post("/recommend", json={"profile": {}}).json()
        assert answer["cold_start"] is True
