"""Shared, I/O-touching helpers used by every model_eval subcommand.

Mirrors the conventions in benchmarks/run_benchmark.py: Keychain fallback for
the API key, short git sha for provenance, and inserting backend/ onto
sys.path so `app.*` imports work when this package is invoked from the repo
root as `python -m benchmarks.model_eval`.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
MODEL_EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BACKEND_DIR / "data"
DEFAULT_DATASET_DIR = MODEL_EVAL_DIR / "dataset"
DEFAULT_RUNS_DIR = MODEL_EVAL_DIR / "runs"


def ensure_backend_on_path() -> None:
    backend = str(BACKEND_DIR)
    if backend not in sys.path:
        sys.path.insert(0, backend)


def ensure_anthropic_api_key() -> None:
    """Populate ANTHROPIC_API_KEY from macOS Keychain if not already set.

    Copied from benchmarks/run_benchmark.py: `make` and non-interactive
    subshells don't source the shell rc files where the key is normally
    exported, so fall back to a direct Keychain lookup.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    user = os.environ.get("USER")
    if not user or sys.platform != "darwin":
        return
    try:
        value = subprocess.check_output(
            ["security", "find-generic-password", "-s", "ANTHROPIC_API_KEY", "-a", user, "-w"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    if value:
        os.environ["ANTHROPIC_API_KEY"] = value


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=str(REPO_ROOT),
        ).strip()
    except Exception:
        return "unknown"
