"""Which artifacts the server loads by default, and that browsers revalidate scripts and styles.

The TMDB-based build lives in artifacts/v2 and the build it replaced sits directly in artifacts/.
`start.bat` runs uvicorn with no environment variable, so the default decides what a visitor sees.
The scripts under web/ have no hashed names, so without `Cache-Control: no-cache` a browser can run
JavaScript from before a change (seen once while checking the new front end).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main


def _make_build(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text("{}", encoding="utf-8")


def test_the_environment_variable_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _make_build(tmp_path / "artifacts" / "v2")
    monkeypatch.setenv("CINEWHY_ARTIFACTS", str(tmp_path / "elsewhere"))
    assert api_main.default_artifacts_dir() == tmp_path / "elsewhere"


def test_v2_is_preferred_when_it_has_a_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CINEWHY_ARTIFACTS", raising=False)
    _make_build(tmp_path / "artifacts" / "v2")
    assert api_main.default_artifacts_dir() == Path("artifacts") / "v2"


def test_an_empty_v2_folder_does_not_hide_the_older_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CINEWHY_ARTIFACTS", raising=False)
    (tmp_path / "artifacts" / "v2").mkdir(parents=True)  # no manifest: a half-made build
    assert api_main.default_artifacts_dir() == Path("artifacts")


def test_the_highest_numbered_build_wins_and_numbers_compare_as_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CINEWHY_ARTIFACTS", raising=False)
    for name in ("v2", "v3", "v10"):  # as text "v10" sorts before "v2"; as numbers it is newest
        _make_build(tmp_path / "artifacts" / name)
    (tmp_path / "artifacts" / "v11").mkdir()  # newest but half-made: no manifest, so skipped
    (tmp_path / "artifacts" / "vnext").mkdir()  # not a version number at all
    assert api_main.default_artifacts_dir() == Path("artifacts") / "v10"


@pytest.fixture
def client(artifact_dir: Path) -> Iterator[TestClient]:
    with TestClient(api_main.create_app(artifact_dir)) as test_client:
        yield test_client
    api_main._state = None


def test_static_files_must_be_revalidated(client: TestClient) -> None:
    response = client.get("/js/main.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "etag" in response.headers  # what makes the revalidation a cheap 304


def test_a_conditional_request_gets_a_304(client: TestClient) -> None:
    first = client.get("/cinewhy.css")
    again = client.get("/cinewhy.css", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304


def test_api_answers_are_not_cached_either(client: TestClient) -> None:
    assert client.get("/health").headers["cache-control"] == "no-cache"


def test_every_file_the_page_loads_is_served_with_the_right_type(client: TestClient) -> None:
    # A page whose stylesheet or script is missing or served as the wrong type does not fail
    # loudly: it renders unstyled, which is exactly how a stale or renamed asset looked broken.
    html = client.get("/").text
    assets = re.findall(r'(?:href|src)="([^"#:]+\.[a-z0-9]+)"', html)
    assert "cinewhy.css" in assets and "js/main.js" in assets
    expected = {"css": "text/css", "js": "javascript", "html": "text/html"}
    for asset in assets:
        response = client.get("/" + asset.lstrip("/"))
        assert response.status_code == 200, asset
        kind = asset.rsplit(".", 1)[1]
        if kind in expected:
            assert expected[kind] in response.headers["content-type"], asset
