#!/usr/bin/env bash
# One-time Python setup on macOS or Linux (Windows: setup.bat). Full guide, including the data:
# README.md, "Set up on a new machine".
#
#   bash setup.sh          everything: the site, the tests and the development tools
#   bash setup.sh serve    only what is needed to RUN the site (a much smaller install)
#
set -eu
cd "$(dirname "$0")"

echo "===================================="
echo "  CineWhy setup"
echo "===================================="

# The project needs Python 3.13 or newer. Try the usual names, newest first.
PYBIN=""
for candidate in python3.14 python3.13 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)' 2>/dev/null; then
    PYBIN="$candidate"
    break
  fi
done
if [ -z "$PYBIN" ]; then
  echo "Python 3.13 or newer was not found."
  echo "macOS:  brew install python@3.13   (or the installer from https://www.python.org/downloads/)"
  echo "Then open a new terminal and run this again."
  exit 1
fi
echo "Using $($PYBIN --version) ($(command -v $PYBIN))"

echo "[1/3] Creating virtual environment..."
"$PYBIN" -m venv venv

# macOS and Linux put the venv's Python in venv/bin; Git Bash on Windows puts it in venv/Scripts.
VPY=venv/bin/python
[ -x "$VPY" ] || VPY=venv/Scripts/python.exe

echo "[2/3] Installing pinned packages..."
if [ "${1:-}" = "serve" ]; then
  "$VPY" -m pip install -r requirements-serve.txt
  echo "[3/3] Skipped the test tools (serve only)."
else
  "$VPY" -m pip install -r requirements.txt
  echo "[3/3] Installing the project and its test tools..."
  "$VPY" -m pip install -e ".[dev]"
fi

echo
echo "===================================="
echo "  Setup complete"
echo "===================================="
echo
echo "Next:"
echo "  1. Put the ready-made data in artifacts/v13  (README.md, \"Get the data\")"
echo "  2. bash start.sh"
echo "  Checks:  venv/bin/python -m pytest -p no:cacheprovider"
