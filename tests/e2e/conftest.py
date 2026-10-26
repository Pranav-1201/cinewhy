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
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.smoke_artifacts import write_smoke_artifacts

_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start the app on synthetic artifacts; yield its base URL; stop it afterwards."""
    artifacts = write_smoke_artifacts(tmp_path_factory.mktemp("e2e-artifacts"))
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
