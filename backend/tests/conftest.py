from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STUDIOUS_DATA_DIR", str(tmp_path))
    # Reset the cached settings since they capture the env at first call.
    from app import config

    config.get_settings.cache_clear()
    return tmp_path
