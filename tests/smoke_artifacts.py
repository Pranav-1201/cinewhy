"""Write a tiny, hash-verified artifact set for boot checks.

Usage: `python -m tests.smoke_artifacts --out DIR`.

The CI "docker" job boots the real image against this set. The real build is several hours of
work and 365 MB of data that CI cannot have, but a container only needs SOME verified artifacts to
prove the image starts, verifies a manifest, and answers requests. It is the same six-film set the
unit tests use (`tests/conftest.py`), so what CI boots is already covered by the suite.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cinewhy.artifacts.manifest import build as build_manifest
from cinewhy.recsys.catalogue import write_catalogue
from tests.conftest import _toy_polarity_model, make_catalogue


def write_smoke_artifacts(out: Path) -> Path:
    """Write the six-film artifact set into `out` (created if missing) and return it."""
    out.mkdir(parents=True, exist_ok=True)
    write_catalogue(out, make_catalogue())
    _toy_polarity_model().save(out / "polarity.joblib")
    (out / "eval.json").write_text(json.dumps({"catalogue": {"films": 6}}), encoding="utf-8")
    build_manifest(out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(f"wrote smoke artifacts to {write_smoke_artifacts(args.out)}")


if __name__ == "__main__":
    main()
