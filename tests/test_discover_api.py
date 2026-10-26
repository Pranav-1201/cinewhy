"""The discovery routes: POST /discover and GET /facets (FEATURE-005).

Request bodies come from a browser, so every field is bounded and unknown fields are refused.
Filters narrow a list and never the catalogue; a film with no entry in `meta.json` simply has
no language and is dropped by a language filter rather than guessed at. The conftest films carry
no year of their own, so years here come from each film's release date in `meta.json`, which is
also the fallback the server uses.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.artifacts.manifest import build as build_manifest

# id -> (language, imdb_rating, imdb_votes, release year). Titles and ids come from conftest.
_FILMS = {
    "cw-1": ("en", 8.0, 200_000, 1990),
    "cw-2": ("en", 7.5, 300_000, 2021),
    "cw-3": ("hi", 8.2, 80_000, 2019),
    "cw-4": ("hi", 6.0, 900, 2022),
    "cw-5": ("en", 7.0, 120_000, 2012),
    "cw-6": ("en", 6.5, 50_000, 2005),
}


@pytest.fixture
def client(artifact_dir: Path) -> Iterator[TestClient]:
    meta = {
        movie_id: {
            "language": language,
            "imdb_rating": rating,
            "imdb_votes": votes,
            "release_date": f"{year}-01-01",
            "poster_path": f"/{movie_id.replace('-', '')}.jpg",
        }
        for movie_id, (language, rating, votes, year) in _FILMS.items()
    }
    (artifact_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    build_manifest(artifact_dir)
    with TestClient(api_main.create_app(artifact_dir)) as test_client:
        yield test_client
    api_main._state = None


def _ids(body: dict[str, Any]) -> list[str]:
    return [item["movie"]["movie_id"] for item in body["items"]]


def test_an_empty_request_is_a_cold_start_discovery_list(client: TestClient) -> None:
    response = client.post("/discover", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["cold_start"] is True
    assert len(body["items"]) == 6
    assert all(item["is_fallback"] for item in body["items"])
    assert len(body["manifest"]) == 64


def test_each_card_has_what_the_ui_needs(client: TestClient) -> None:
    item = client.post("/discover", json={"limit": 1}).json()["items"][0]
    assert set(item) == {
        "movie", "language", "is_new", "score", "reasons", "is_fallback", "because", "ratings_only",
    }  # fmt: skip
    assert item["movie"]["poster_url"].startswith("https://image.tmdb.org/t/p/w342/cw")
    assert item["language"] in {"en", "hi"}


def test_the_language_filter_narrows_the_list(client: TestClient) -> None:
    body = client.post("/discover", json={"languages": ["hi"]}).json()
    assert set(_ids(body)) == {"cw-3", "cw-4"}


def test_the_from_year_filter_uses_the_release_date_when_a_film_has_no_year(
    client: TestClient,
) -> None:
    body = client.post("/discover", json={"from_year": 2012, "recency": 1.0}).json()
    assert set(_ids(body)) == {"cw-2", "cw-3", "cw-4", "cw-5"}
    newest = {i["movie"]["movie_id"]: i["is_new"] for i in body["items"]}
    assert newest["cw-4"] is True  # 2022 is the newest film
    assert newest["cw-5"] is False  # 2012 is more than seven years before it


def test_to_year_gives_the_classics_shelf(client: TestClient) -> None:
    body = client.post("/discover", json={"to_year": 2005}).json()
    assert set(_ids(body)) == {"cw-1", "cw-6"}


def test_a_genre_filter_that_matches_nothing_returns_nothing(client: TestClient) -> None:
    assert client.post("/discover", json={"genres": ["Nonexistent"]}).json()["items"] == []


def test_a_taste_profile_personalises_the_list(client: TestClient) -> None:
    body = client.post(
        "/discover", json={"profile": {"liked_movie_ids": ["cw-1"]}, "recency": 0.0}
    ).json()
    assert body["cold_start"] is False
    assert "cw-1" not in _ids(body)
    assert body["items"]
    assert all(not item["is_fallback"] for item in body["items"])


def test_the_same_request_gives_the_same_list(client: TestClient) -> None:
    request = {"recency": 0.7, "languages": ["en"], "limit": 4}
    first = client.post("/discover", json=request).json()
    assert first == client.post("/discover", json=request).json()


@pytest.mark.parametrize(
    "bad",
    [
        {"languages": ["fr"]},  # only English and Hindi are offered
        {"languages": ["en", "hi", "en"]},  # more than the two there are
        {"recency": 1.5},
        {"recency": -0.1},
        {"from_year": 1500},
        {"from_year": 3000},
        {"to_year": 1500},
        {"to_year": 3000},
        {"limit": 0},
        {"limit": 101},
        {"genres": ["x"] * 11},
        {"genres": ["y" * 41]},
        {"exclude_movie_ids": ["cw-1"] * 3001},  # one over the cap (profile.js LIST_CAP)
        {"nonsense": True},  # unknown fields are refused, not ignored
    ],
)
def test_out_of_bounds_requests_are_refused(client: TestClient, bad: dict[str, object]) -> None:
    assert client.post("/discover", json=bad).status_code == 422


def test_an_oversized_body_is_refused_before_it_is_parsed(client: TestClient) -> None:
    body = {"exclude_movie_ids": ["x" * 1000] * 200}  # about 200 KB, over the 160 KB cap
    assert client.post("/discover", json=body).status_code == 413


def test_the_largest_library_the_browser_can_send_is_accepted(client: TestClient) -> None:
    """3,000 liked, 3,000 disliked and 3,000 watched ids (web/js/profile.js LIST_CAP each)."""
    ids = [f"cw-{n:07d}" for n in range(3000)]
    body = {
        "profile": {"liked_movie_ids": ids, "disliked_movie_ids": ids},
        "exclude_movie_ids": ids,
    }
    response = client.post("/discover", json=body)
    assert len(response.content) > 0 and response.status_code == 200


def test_facets_count_languages_and_years(client: TestClient) -> None:
    body = client.get("/facets").json()
    assert body["languages"] == {"en": 4, "hi": 2}
    assert body["films"] == 6
    assert (body["oldest_year"], body["newest_year"]) == (1990, 2022)
    assert body["genres"] == {}  # the conftest films carry no genres


def test_without_meta_json_discovery_still_works_but_language_is_unknown(
    artifact_dir: Path,
) -> None:
    with TestClient(api_main.create_app(artifact_dir)) as plain:
        assert plain.post("/discover", json={}).json()["items"]
        assert plain.post("/discover", json={"languages": ["en"]}).json()["items"] == []
        assert plain.get("/facets").json()["languages"] == {}
    api_main._state = None
