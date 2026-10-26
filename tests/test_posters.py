"""Posters and TMDB metadata reaching the browser (FEATURE-004, step 2).

`meta.json` is a build artifact like the others: it is only read when the hash manifest lists
it, because an unverified file on disk must never change what the server tells a browser. A
poster path ends up inside a URL the browser loads, so it is validated, not trusted.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.artifacts.manifest import build as build_manifest
from cinewhy.recsys.catalogue import load_catalogue

_BASE = "https://image.tmdb.org/t/p/w342"


def _meta() -> dict[str, dict[str, object]]:
    common = {
        "tmdb_id": 1,
        "imdb_id": 100,
        "language": "en",
        "release_date": "1995-06-01",
        "popularity": 9.0,
        "vote_count": 100,
        "runtime": 170.0,
        "overview": "A heist film.",
        "rt_url": "https://www.rottentomatoes.com/m/alpha",
        "reviews_by_source": {"ebd": 6, "rt": 4},
        "rating_count": 900,
    }
    return {
        "cw-1": {**common, "poster_path": "/alpha.jpg"},
        "cw-2": {**common, "poster_path": "/../../etc/passwd"},  # tries to leave the poster path
        # No poster at TMDB, a link that is not Rotten Tomatoes, and an unknown (zero) runtime.
        "cw-3": {
            **common,
            "poster_path": None,
            "rt_url": "https://evil.example/m/alpha",
            "runtime": 0.0,
        },
        "cw-4": {**common, "poster_path": "/ok-name_1.png", "language": "hi"},
    }


@pytest.fixture
def meta_dir(artifact_dir: Path) -> Path:
    """The six-film artifact set with a `meta.json` that the manifest covers."""
    (artifact_dir / "meta.json").write_text(json.dumps(_meta()), encoding="utf-8")
    build_manifest(artifact_dir)
    return artifact_dir


@pytest.fixture
def client(meta_dir: Path) -> Iterator[TestClient]:
    with TestClient(api_main.create_app(meta_dir)) as test_client:
        yield test_client
    api_main._state = None


def test_posters_are_built_from_a_validated_tmdb_path(meta_dir: Path) -> None:
    posters = {m.movie_id: m.poster_url for m in load_catalogue(meta_dir, with_meta=True).movies}
    assert posters["cw-1"] == f"{_BASE}/alpha.jpg"
    assert posters["cw-4"] == f"{_BASE}/ok-name_1.png"
    assert posters["cw-2"] is None  # a path with ".." never becomes a URL
    assert posters["cw-3"] is None
    assert posters["cw-5"] is None  # no entry in meta.json at all


def test_meta_is_not_read_unless_asked_to(meta_dir: Path) -> None:
    catalogue = load_catalogue(meta_dir)
    assert all(m.poster_url is None for m in catalogue.movies)
    assert catalogue.meta == {}


def test_search_recommend_and_movie_page_all_carry_the_poster(client: TestClient) -> None:
    searched = client.get("/search", params={"q": "alp"}).json()
    assert searched[0]["poster_url"] == f"{_BASE}/alpha.jpg"
    detail = client.get("/movie/cw-1").json()
    assert detail["movie"]["poster_url"] == f"{_BASE}/alpha.jpg"
    recommended = client.post("/recommend", json={"profile": {}, "limit": 6}).json()["items"]
    by_id = {i["movie"]["movie_id"]: i["movie"]["poster_url"] for i in recommended}
    assert by_id["cw-1"] == f"{_BASE}/alpha.jpg"


def test_the_movie_page_carries_the_tmdb_details(client: TestClient) -> None:
    detail = client.get("/movie/cw-1").json()
    assert detail["overview"] == "A heist film."
    assert detail["language"] == "en"
    assert detail["release_date"] == "1995-06-01"
    assert detail["runtime_minutes"] == 170
    assert detail["rt_url"] == "https://www.rottentomatoes.com/m/alpha"
    assert detail["reviews_by_source"] == {"ebd": 6, "rt": 4}
    assert client.get("/movie/cw-4").json()["language"] == "hi"


def test_only_rotten_tomatoes_links_and_real_runtimes_reach_the_page(client: TestClient) -> None:
    detail = client.get("/movie/cw-3").json()
    assert detail["rt_url"] is None  # the file said another site; the UI must not link to it
    assert detail["runtime_minutes"] is None  # zero means unknown, not a film of no length


def test_a_film_with_no_meta_entry_still_has_a_page(client: TestClient) -> None:
    detail = client.get("/movie/cw-5").json()
    assert detail["movie"]["poster_url"] is None
    assert detail["overview"] is None
    assert detail["reviews_by_source"] == {}


def test_artifacts_without_meta_json_still_serve(artifact_dir: Path) -> None:
    with TestClient(api_main.create_app(artifact_dir)) as plain:
        assert plain.get("/search", params={"q": "alp"}).json()[0]["poster_url"] is None
        assert plain.get("/movie/cw-1").json()["overview"] is None
    api_main._state = None


def test_a_meta_file_outside_the_manifest_is_ignored(artifact_dir: Path) -> None:
    # Written after the manifest was built, so it is unverified input and must change nothing.
    (artifact_dir / "meta.json").write_text(json.dumps(_meta()), encoding="utf-8")
    with TestClient(api_main.create_app(artifact_dir)) as plain:
        assert plain.get("/search", params={"q": "alp"}).json()[0]["poster_url"] is None
    api_main._state = None


def test_the_security_policy_lets_the_browser_load_tmdb_images_and_nothing_else_new(
    client: TestClient,
) -> None:
    policy = client.get("/health").headers["content-security-policy"]
    assert "img-src 'self' data: https://image.tmdb.org;" in policy
    assert "default-src 'self'" in policy  # everything else stays same-origin
    assert "script-src" not in policy  # no relaxation of scripts
