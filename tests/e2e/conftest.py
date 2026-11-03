"""Fixtures for browser tests: a real server on the synthetic artifact set, and Playwright.

Browser tests need the `playwright` package and a downloaded Chromium (`pip install -e ".[e2e]"`,
then `python -m playwright install chromium`). The test modules skip themselves when playwright is
missing, so the ordinary suite still runs on a machine without it. The server runs in a separate
process, exactly as `start.bat` runs it, on a free port, with the six-film set from
`tests/smoke_artifacts.py`: the layout does not depend on which films exist.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from cinewhy.data.availability import Availability, Where
from cinewhy.data.cast import Cast
from tests.smoke_artifacts import write_smoke_artifacts

_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start the app on synthetic artifacts; yield its base URL; stop it afterwards."""
    yield from _serve(write_smoke_artifacts(tmp_path_factory.mktemp("e2e-artifacts")))


@pytest.fixture(scope="session")
def ratings_only_server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The same app on a set that also holds 30 films with ratings but no reviews."""
    artifacts = write_smoke_artifacts(tmp_path_factory.mktemp("e2e-ratings-only"), ratings_only=30)
    yield from _serve(artifacts)


@pytest.fixture(scope="session")
def cast_server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The same app on a set that also knows who is in films 1 to 5 (cw-1 to cw-5)."""
    cast = Cast(
        {1: (1, 2), 2: (1,), 3: (2,), 4: (1,), 5: (3,)},
        {1: "Ann Actor", 2: "Ben Actor", 3: "Cara Actress"},
    )
    yield from _serve(write_smoke_artifacts(tmp_path_factory.mktemp("e2e-cast"), cast=cast))


@pytest.fixture(scope="session")
def availability_server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The same app on a set where all six films share one availability entry."""
    where = Where(
        "movie/603",
        {"netflix": {"stream": ("IN", "US"), "rent": ("US",)}, "prime": {"buy": ("US",)}},
    )
    # Film 2 is offered only in the US, so it is the one title that is NOT on offer in India.
    us_only = Where("movie/603", {"netflix": {"stream": ("US",)}})
    data = Availability("2026-11-03", {n: us_only if n == 2 else where for n in range(1, 7)})
    artifacts = write_smoke_artifacts(tmp_path_factory.mktemp("e2e-watch"), availability=data)
    yield from _serve(artifacts)


@pytest.fixture(scope="session")
def rich_server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The same app on a set that has BOTH a cast and where-to-watch for all six films."""
    people = {1: "Ann Actor", 2: "Ben Actor"}
    cast = Cast({n: (1, 2) for n in range(1, 7)}, people)
    where = Where("movie/603", {"netflix": {"stream": ("IN", "US")}, "prime": {"buy": ("US",)}})
    availability = Availability("2026-11-03", {n: where for n in range(1, 7)})
    artifacts = write_smoke_artifacts(
        tmp_path_factory.mktemp("e2e-rich"), cast=cast, availability=availability
    )
    yield from _serve(artifacts)


def _serve(artifacts: Path) -> Iterator[str]:
    """Run uvicorn on `artifacts` in its own process, as `start.bat` does; stop it afterwards."""
    port = _free_port()
    env = {**os.environ, "CINEWHY_ARTIFACTS": str(artifacts), "PYTHONUTF8": "1"}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(port)],
        cwd=_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError(f"the test server exited early with code {process.returncode}")
            try:
                with urllib.request.urlopen(f"{url}/health", timeout=2):
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.5)
        else:
            raise RuntimeError("the test server did not answer /health within 60 seconds")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    """One Chromium for the whole run; tests skip themselves when playwright is not installed."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def open_page(browser: Any, server_url: str) -> Iterator[Callable[..., Any]]:
    """`open_page(width=1024, skip_questions=True)` gives a page in a fresh browser profile.

    Each call is a new profile (no saved answers), so a test starts from a first visit. The
    first-visit sheet is dismissed with Skip unless `skip_questions=False`.
    """
    yield from _pages(browser, server_url)


@pytest.fixture
def open_ratings_only_page(
    browser: Any, ratings_only_server_url: str
) -> Iterator[Callable[..., Any]]:
    """`open_page`, against the set that holds ratings-only films."""
    yield from _pages(browser, ratings_only_server_url)


@pytest.fixture
def open_cast_page(browser: Any, cast_server_url: str) -> Iterator[Callable[..., Any]]:
    """`open_page`, against the set that holds a cast file."""
    yield from _pages(browser, cast_server_url)


@pytest.fixture
def open_watch_page(browser: Any, availability_server_url: str) -> Iterator[Callable[..., Any]]:
    """`open_page`, against the set that holds availability."""
    yield from _pages(browser, availability_server_url)


@pytest.fixture
def open_rich_page(browser: Any, rich_server_url: str) -> Iterator[Callable[..., Any]]:
    """`open_page`, against the set that has both a cast and where-to-watch."""
    yield from _pages(browser, rich_server_url)


def _pages(browser: Any, url: str) -> Iterator[Callable[..., Any]]:
    contexts: list[Any] = []

    def make(width: int = 1024, *, skip_questions: bool = True, height: int = 800) -> Any:
        context = browser.new_context(
            viewport={"width": width, "height": height}, accept_downloads=True
        )
        contexts.append(context)
        page = context.new_page()
        page.goto(url)
        page.wait_for_selector("#onboard-dialog[open]", timeout=20_000)
        if skip_questions:
            page.click("#onboard-form button[value=skip]")
            page.wait_for_selector("#onboard-dialog:not([open])", state="attached")
        return page

    yield make
    for context in contexts:
        context.close()
