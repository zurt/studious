from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
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
def _no_real_anthropic_key(monkeypatch: pytest.MonkeyPatch):
    """Transcription jobs now run a follow-up region check on the "anthropic"
    provider. Without a key the real provider cannot be built, so a test that
    forgets to mock it fails the (swallowed) check instead of calling the API."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_real_anki(monkeypatch: pytest.MonkeyPatch):
    """Tests must never reach a real AnkiConnect (Anki may be open on the
    dev machine). Tests that need Anki replace anki._post themselves."""
    from app.services import anki

    def refuse(action, params=None, *, timeout=0):
        raise anki.AnkiUnavailable("test: real AnkiConnect is blocked")

    monkeypatch.setattr(anki, "_post", refuse)


@pytest.fixture(autouse=True)
def _no_real_say(monkeypatch: pytest.MonkeyPatch):
    """Tests must never run the real `say`: audio is unavailable unless a test
    fakes the subprocess itself."""
    from app.services import say_remote, tts, voicevox

    def refuse(req, timeout):
        raise OSError("test: a real speech engine is blocked")

    tts.reset_cache()
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)  # no `say`, no `afconvert`
    monkeypatch.setattr(voicevox, "_open", refuse)
    monkeypatch.setattr(say_remote, "_open", refuse)


@pytest.fixture(autouse=True)
def _no_background_drain(monkeypatch: pytest.MonkeyPatch):
    """kick() would start a drain thread that outlives the test's temp data dir.
    By default it starts nothing (the pending list is still written); speech-queue
    tests opt in by replacing speech_queue._start_thread (e.g. to run it inline)."""
    from app.services import speech_queue

    started: list = []
    monkeypatch.setattr(speech_queue, "_start_thread", started.append)



# ---------- a fake Mac speech helper, for the say_remote engine ----------

DEFAULT_LISTING = (
    "Kyoko (Enhanced)    ja_JP    # こんにちは!\n"
    "O-Ren (Enhanced)    ja_JP    # こんにちは!\n"
    "Otoya (Enhanced)    ja_JP    # こんにちは!\n"
    "Kyoko (Japanese (Japan)) ja_JP    # こんにちは!\n"
    "Samantha            en_US    # Hello!\n"
)
MAC_AUDIO = b"\0" * 5000


class FakeMac:
    """Replaces say_remote._open: a Mac helper that can be up or down."""

    def __init__(self, listing: str | None = None):
        self.up = True
        self.listing = listing if listing is not None else DEFAULT_LISTING
        self.say_calls: list[tuple[str, str]] = []
        self.fail_voices: set[str] = set()
        self.audio = MAC_AUDIO

    def __call__(self, req, timeout):
        if not self.up:
            raise urllib.error.URLError("connection refused")
        path = urllib.parse.urlsplit(req.full_url).path
        if path == "/voices":
            return json.dumps({"listing": self.listing}).encode()
        if path == "/health":
            return b'{"ok": true}'
        assert path == "/say", path
        data = json.loads(req.data.decode())
        self.say_calls.append((data["voice"], data["text"]))
        if data["voice"] in self.fail_voices:
            raise urllib.error.HTTPError(req.full_url, 502, "bad", {}, io.BytesIO(b'{"detail": "say failed"}'))
        return self.audio

    @property
    def voices(self) -> list[str]:
        return [v for v, _ in self.say_calls]


@pytest.fixture
def mac(isolated_data_dir, monkeypatch):
    from app import config
    from app.services import say_remote, tts

    fake = FakeMac()
    monkeypatch.setenv("STUDIOUS_TTS_ENGINE", "say_remote")
    monkeypatch.setenv("STUDIOUS_SAY_HELPER_URL", "http://mac.example:8766")
    monkeypatch.delenv("STUDIOUS_TTS_VOICE", raising=False)
    config.get_settings.cache_clear()
    tts.reset_cache()
    monkeypatch.setattr(say_remote, "_open", fake)
    yield fake
    tts.reset_cache()
    config.get_settings.cache_clear()


