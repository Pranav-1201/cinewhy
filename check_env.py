r"""Run this script INSIDE your activated venv to verify the environment.

Windows:   venv\Scripts\activate      ->  python check_env.py
Mac/Linux: source venv/bin/activate   ->  python check_env.py

This script previously declared a minimum version for each package and then never
compared against it — `min_ver` was bound and unused, so an out-of-date package printed
a tick and the summary said "All packages present". It now actually enforces the floor
(audit finding C-9; docs/TEST_CHECKLIST.md).
"""

import sys

# (module import name) -> (minimum version, pip name)
REQUIRED: dict[str, tuple[str, str]] = {
    "numpy": ("2.1.0", "numpy"),
    "pandas": ("2.2.3", "pandas"),
    "nltk": ("3.8.0", "nltk"),
    "sklearn": ("1.5.2", "scikit-learn"),
    "seaborn": ("0.12.0", "seaborn"),
    "matplotlib": ("3.7.0", "matplotlib"),
    "jupyter": ("1.0.0", "jupyter"),
    "ipykernel": ("6.0.0", "ipykernel"),
}


def _parse(version: str) -> tuple[int, ...]:
    """Turn a version string into a comparable tuple.

    Deliberately tolerant: trailing suffixes like "2.1.0rc1" or "1.5.2.post1" contribute
    only their leading digits, and anything unparseable yields an empty tuple, which
    compares as older than every real version. A version we cannot read should surface
    as a warning, never as a silent pass.

    Args:
        version: A version string such as "2.2.3".

    Returns:
        Tuple of integers suitable for comparison.
    """
    parts: list[int] = []
    for chunk in version.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def main() -> int:
    """Check every required package is importable and new enough.

    Returns:
        0 if every package meets its floor, 1 otherwise. The exit code matters — this
        is meant to be usable as a gate, not only read by a human.
    """
    print("=" * 58)
    print("  Environment Diagnostic")
    print("=" * 58)
    print(f"\nPython: {sys.version}")
    print(f"Executable: {sys.executable}\n")

    missing: list[str] = []
    outdated: list[str] = []

    for module, (min_ver, pip_name) in REQUIRED.items():
        try:
            mod = __import__(module)
        except ImportError:
            print(f"  [MISSING]  {pip_name:<20} (need >= {min_ver})")
            missing.append(pip_name)
            continue

        found = getattr(mod, "__version__", "")
        if not found:
            print(f"  [?]        {pip_name:<20} version unknown (need >= {min_ver})")
            continue

        if _parse(found) < _parse(min_ver):
            print(f"  [OLD]      {pip_name:<20} {found}  (need >= {min_ver})")
            outdated.append(f"{pip_name}>={min_ver}")
        else:
            print(f"  [ok]       {pip_name:<20} {found}")

    print()
    if not missing and not outdated:
        print("All packages present and current.")
        print("If the notebook is still stuck, check VS Code is using THIS venv as the")
        print("kernel: kernel selector (top right) -> Select Another Kernel ->")
        print("Python Environments -> choose the venv Python.")
        print("=" * 58)
        return 0

    if missing:
        print(f"Missing: {', '.join(missing)}")
    if outdated:
        print(f"Outdated: {', '.join(outdated)}")
    print("\nRun inside the venv:  pip install -r requirements.txt")
    print("=" * 58)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
