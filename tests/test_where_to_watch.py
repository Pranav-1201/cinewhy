"""Where to watch through the API: only from a verified manifest, dated, and never invented."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from cinewhy.data.availability import AVAILABILITY_FILE, Availability, Where, write_availability
from cinewhy.recsys.catalogue import load_catalogue
from tests.smoke_artifacts import write_smoke_artifacts

_FETCHED = "2026-11-03"


def _availability() -> Availability:
    return Availability(
        _FETCHED,
        {
            1: Where(
                "movie/603",
                {"netflix": {"stream": ("GB", "US"), "rent": ("US",)}, "hbo": {"stream": ("US",)}},
            ),
            2: Where("tv/1396", {"crunchyroll": {"free": ("JP",)}}),
            3: Where("../../evil", {"netflix": {"stream": ("US",)}}),  # must never become a link
        },
    )


def _boot(out: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api_main, "_state", None)
    api_main.load_artifacts(out)
    return TestClient(api_main.create_app())  # no `with`: the artifacts are already in place


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return _boot(write_smoke_artifacts(tmp_path / "v", availability=_availability()), monkeypatch)


def test_a_film_page_lists_its_platforms_ways_and_countries(client: TestClient) -> None:
    where = client.get("/movie/cw-1").json()["where_to_watch"]
    assert where["fetched"] == _FETCHED
    assert where["tmdb_url"] == "https://www.themoviedb.org/movie/603/watch"
    assert where["platforms"] == [
        {"platform": "netflix", "ways": {"stream": ["GB", "US"], "rent": ["US"]}},
        {"platform": "hbo", "ways": {"stream": ["US"]}},
    ]


def test_a_series_links_to_its_tv_page(client: TestClient) -> None:
    where = client.get("/movie/cw-2").json()["where_to_watch"]
    assert where["tmdb_url"] == "https://www.themoviedb.org/tv/1396/watch"


def test_a_title_on_none_of_the_six_says_so_and_has_no_link(client: TestClient) -> None:
    where = client.get("/movie/cw-4").json()["where_to_watch"]
    assert where == {"fetched": _FETCHED, "tmdb_url": None, "platforms": []}


def test_only_a_plain_tmdb_path_can_become_a_link(client: TestClient) -> None:
    where = client.get("/movie/cw-3").json()["where_to_watch"]
    assert where["tmdb_url"] is None
    assert [p["platform"] for p in where["platforms"]] == ["netflix"]  # the data still shows


def test_a_ratings_only_film_also_gets_its_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = write_smoke_artifacts(tmp_path / "v", ratings_only=3, availability=_availability())
    _boot(out, monkeypatch)
    ro_id = api_main._loaded().catalogue.ratings_only[0].movie.movie_id
    detail = api_main.movie_detail(ro_id)
    assert detail.ratings_only and detail.where_to_watch is not None
    assert detail.where_to_watch.fetched == _FETCHED


def test_a_build_without_availability_says_nothing_rather_than_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = _boot(write_smoke_artifacts(tmp_path / "v"), monkeypatch)
    assert bare.get("/movie/cw-1").json()["where_to_watch"] is None
    assert bare.get("/facets").json()["availability"] is False


def test_facets_say_the_build_knows_where_to_watch(client: TestClient) -> None:
    assert client.get("/facets").json()["availability"] is True


def test_boot_ignores_an_availability_file_the_manifest_does_not_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = write_smoke_artifacts(tmp_path / "v")
    write_availability(out / AVAILABILITY_FILE, _availability())  # a stray, unverified file
    _boot(out, monkeypatch)
    assert api_main._loaded().catalogue.availability is None


def test_the_loader_reads_availability_only_when_asked(tmp_path: Path) -> None:
    out = write_smoke_artifacts(tmp_path / "v", availability=_availability())
    assert load_catalogue(out, with_availability=True).availability == _availability()
    assert load_catalogue(out).availability is None
