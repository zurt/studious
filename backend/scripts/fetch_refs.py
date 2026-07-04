"""Fetch pinned reference datasets (JMdict, JLPT lists) and build the
local lookup index at data/refs/jmdict/jmdict.sqlite.

Usage: uv run python scripts/fetch_refs.py [--force]

Artifacts are pinned by URL + SHA-256 in backend/refs.lock.json; a
checksum mismatch aborts the build. `--force` rebuilds even when the
index already matches the pinned JMdict version.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ for `app` imports

from app.services import refs_build  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild even if up to date")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = refs_build.fetch_and_build(force=args.force)
    print(f"refs: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
