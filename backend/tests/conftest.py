from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("STUDIOUS_DATA_DIR", str(tmp_path))
    # Reset the cached settings since they capture the env at first call.
    from app import config

    config.get_settings.cache_clear()
    return tmp_path


@pytest.fixture(autouse=True)
def _no_real_anki(monkeypatch: pytest.MonkeyPatch):
    """Tests must never reach a real AnkiConnect (Anki may be open on the
    dev machine). Tests that need Anki replace anki._post themselves."""
    from app.services import anki

    def refuse(action, params=None, *, timeout=0):
        raise anki.AnkiUnavailable("test: real AnkiConnect is blocked")

    monkeypatch.setattr(anki, "_post", refuse)
