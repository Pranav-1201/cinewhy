"""Run the front end's pure-logic tests (tests/web/*.test.mjs) as part of the normal test run.

Node's built-in test runner needs no dependency. The count of passed tests is read and must be
above zero: a runner that found no test file exits 0, which would look like a green suite.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_WEB_TESTS = Path(__file__).parent / "web"
_MIN_EXPECTED = 10


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_front_end_logic_tests_pass() -> None:
    files = sorted(str(p) for p in _WEB_TESTS.glob("*.test.mjs"))
    assert files, "no front-end test files found"
    result = subprocess.run(
        ["node", "--test", "--test-reporter=tap", *files],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    passed = re.search(r"^# pass (\d+)", result.stdout, flags=re.MULTILINE)
    failed = re.search(r"^# fail (\d+)", result.stdout, flags=re.MULTILINE)
    assert passed is not None, f"no summary in the runner output:\n{result.stdout}\n{result.stderr}"
    assert failed is not None and int(failed.group(1)) == 0, result.stdout
    assert int(passed.group(1)) >= _MIN_EXPECTED, f"only {passed.group(1)} tests ran"
    assert result.returncode == 0
