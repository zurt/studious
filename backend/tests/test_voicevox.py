"""The VOICEVOX-compatible speech engine, with a fake HTTP engine and a fake afconvert."""
from __future__ import annotations

import io
import json
import subprocess
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import anki_push, store, tts, voicevox
from tests.test_anki_push import BODY, _seed, _use

client = TestClient(app)

SPEAKERS = [
    {"name": "四国めたん", "speaker_uuid": "u1", "styles": [{"name": "ノーマル", "id": 2}, {"name": "あまあま", "id": 0}]},
    {"name": "ずんだもん", "speaker_uuid": "u2", "styles": [{"name": "ノーマル", "id": 3}]},
]
WAV = b"RIFF" + b"\0" * 5000


class FakeEngine:
    """Replaces voicevox._open. `kana` maps text -> the kana the engine reports."""

    def __init__(self):
        self.requests: list[dict[str, Any]] = []
        self.kana: dict[str, str] = {}
        self.error: Exception | None = None
        self.wav = WAV
        self.version_error: Exception | None = None

    def __call__(self, req, timeout):
        parts = urllib.parse.urlsplit(req.full_url)
        params = dict(urllib.parse.parse_qsl(parts.query))
        self.requests.append(
            {"path": parts.path, "query": parts.query, "params": params, "method": req.get_method(),
             "data": req.data, "timeout": timeout, "headers": dict(req.header_items())}
        )
        if self.error:
            raise self.error
        if parts.path == "/version":
            if self.version_error:
                raise self.version_error
            return b'"0.21.1"'
        if parts.path == "/speakers":
            return json.dumps(SPEAKERS).encode()
        if parts.path == "/audio_query":
            text = params["text"]
            return json.dumps({"accent_phrases": [], "kana": self.kana.get(text, "テスト'/、_"), "text": text}).encode()
        if parts.path == "/synthesis":
            return self.wav
        raise AssertionError(parts.path)

    def paths(self):
        return [r["path"] for r in self.requests]


@pytest.fixture
def engine(isolated_data_dir, monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(voicevox, "_open", fake)
    monkeypatch.setenv("STUDIOUS_TTS_ENGINE", "voicevox")
    monkeypatch.setenv("STUDIOUS_TTS_SPEAKER", "3")
    config.get_settings.cache_clear()
    tts.reset_cache()
    yield fake
    tts.reset_cache()


class FakeAfconvert:
    def __init__(self, returncode=0, size=5000):
        self.calls: list[list[str]] = []
        self.returncode, self.size = returncode, size

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        assert kw.get("timeout") and kw.get("shell") in (None, False)
        if self.returncode == 0:
            Path(args[-1]).write_bytes(b"\0" * self.size)
        return subprocess.CompletedProcess(args, self.returncode, b"", b"err")


@pytest.fixture
def afconvert(monkeypatch):
    fake = FakeAfconvert()
    monkeypatch.setattr(tts.shutil, "which", lambda n: "/usr/bin/afconvert" if n == "afconvert" else None)
    monkeypatch.setattr(tts.subprocess, "run", fake)
    return fake


# ---------- availability ----------


class TestAvailability:
    def test_available(self, engine):
        assert tts.is_available() is True
        st = tts.status()
        assert st["engine"] == "voicevox" and st["speaker"] == 3 and st["voice"] == "ずんだもん — ノーマル"
        assert st["reason"] == "" and st["url"] == "http://127.0.0.1:50021"

    def test_speaker_unset(self, engine, monkeypatch):
        monkeypatch.delenv("STUDIOUS_TTS_SPEAKER")
        config.get_settings.cache_clear()
        tts.reset_cache()
        assert tts.is_available() is False
        assert "speaker must be chosen" in tts.unavailable_reason()
        assert engine.requests == []

    def test_engine_down(self, engine):
        engine.error = urllib.error.URLError("refused")
        assert tts.is_available() is False
        assert "not reachable" in tts.unavailable_reason()

    def test_unknown_speaker_id(self, engine, monkeypatch):
        monkeypatch.setenv("STUDIOUS_TTS_SPEAKER", "99")
        config.get_settings.cache_clear()
        tts.reset_cache()
        assert tts.is_available() is False and "Speaker 99" in tts.unavailable_reason()

    def test_answer_is_cached_briefly(self, engine):
        tts.is_available(), tts.is_available()
        assert engine.paths() == ["/version", "/speakers"]

    def test_status_when_unavailable_has_a_reason(self, engine):
        engine.error = OSError("down")
        st = client.get("/api/tts/status").json()
        assert st["available"] is False and "not reachable" in st["reason"] and st["engine"] == "voicevox"

    def test_env_defaults(self, isolated_data_dir, monkeypatch):
        for k in ("STUDIOUS_TTS_ENGINE", "STUDIOUS_TTS_URL", "STUDIOUS_TTS_SPEAKER"):
            monkeypatch.delenv(k, raising=False)
        config.get_settings.cache_clear()
        s = config.get_settings()
        assert (s.tts_engine, s.tts_url, s.tts_speaker) == ("say", "http://127.0.0.1:50021", None)
        monkeypatch.setenv("STUDIOUS_TTS_ENGINE", "bogus")
        config.get_settings.cache_clear()
        assert config.get_settings().tts_engine == "say"


# ---------- client ----------


class TestClient_:
    def test_query_then_synthesis_with_encoded_text(self, engine):
        voicevox_text = "今日は いい&天気=?"
        q = voicevox.audio_query("http://127.0.0.1:50021", voicevox_text, 3)
        assert q["text"] == voicevox_text
        voicevox.synthesis("http://127.0.0.1:50021", q, 3)
        aq, syn = engine.requests
        assert aq["method"] == "POST" and aq["data"] == b"" and aq["params"] == {"text": voicevox_text, "speaker": "3"}
        assert "%E4%BB%8A" in aq["query"] and " " not in aq["query"] and "&天" not in aq["query"]
        assert syn["path"] == "/synthesis" and syn["params"] == {"speaker": "3"}
        assert json.loads(syn["data"]) == q
        assert syn["headers"]["Content-type"] == "application/json"
        assert syn["timeout"] == voicevox.SYNTHESIS_TIMEOUT and aq["timeout"] == voicevox.CONNECT_TIMEOUT

    def test_speakers_flatten_with_labels(self, engine):
        assert voicevox.speakers("http://x") == [
            {"id": 2, "character": "四国めたん", "style": "ノーマル", "label": "四国めたん — ノーマル"},
            {"id": 0, "character": "四国めたん", "style": "あまあま", "label": "四国めたん — あまあま"},
            {"id": 3, "character": "ずんだもん", "style": "ノーマル", "label": "ずんだもん — ノーマル"},
        ]

    def test_only_http_urls(self, engine):
        with pytest.raises(voicevox.EngineError, match="http"):
            voicevox.version("file:///etc/passwd")
        assert engine.requests == []

    def test_http_error_is_clear(self, engine):
        engine.error = urllib.error.HTTPError("u", 500, "x", {}, io.BytesIO(b"boom"))
        with pytest.raises(voicevox.EngineError, match="answered 500 to /version: boom"):
            voicevox.version("http://x")

    def test_timeout_is_clear(self, engine):
        engine.error = TimeoutError()
        with pytest.raises(voicevox.EngineError, match="timed out"):
            voicevox.version("http://x")

    def test_non_json(self, engine):
        engine.error = None
        engine.wav = b""
        with pytest.raises(voicevox.EngineError, match="no audio"):
            voicevox.synthesis("http://x", {}, 1)


# ---------- synthesis, conversion, cache ----------


class TestSynthesize:
    def test_converts_to_m4a(self, engine, afconvert):
        path = tts.synthesize("今日はいい天気ですね。")
        assert path.suffix == ".m4a" and path.stat().st_size == 5000
        (call,) = afconvert.calls
        assert call[:5] == ["afconvert", "-f", "m4af", "-d", "aac"] and call[5].endswith(".wav")
        assert sorted(p.suffix for p in path.parent.iterdir()) == [".m4a"]  # the wav and temp files are gone
        assert tts.media_type(path) == "audio/mp4"
        assert engine.paths()[-2:] == ["/audio_query", "/synthesis"]

    def test_wav_fallback_without_afconvert(self, engine):
        path = tts.synthesize("犬です。")
        assert path.suffix == ".wav" and tts.media_type(path) == "audio/wav"
        assert path.read_bytes() == WAV

    def test_wav_fallback_when_conversion_fails(self, engine, afconvert):
        afconvert.returncode = 1
        path = tts.synthesize("犬です。")
        assert path.suffix == ".wav"
        assert sorted(p.suffix for p in path.parent.iterdir()) == [".wav"]

    def test_small_output_fails(self, engine):
        engine.wav = b"RIFF"
        with pytest.raises(tts.TtsError):
            tts.synthesize("犬")

    def test_cached_second_call_makes_no_requests(self, engine, afconvert):
        a = tts.synthesize("犬です。")
        n = len(engine.requests)
        assert tts.synthesize("犬です。") == a and len(engine.requests) == n and len(afconvert.calls) == 1

    def test_cache_key_includes_engine_speaker_and_text(self, engine, monkeypatch):
        a = tts.synthesize("犬")
        assert tts.synthesize("猫") != a
        client.put("/api/preferences", json={"tts_speaker": 2})
        b = tts.synthesize("犬")
        assert b != a and a.exists()
        client.put("/api/preferences", json={"tts_engine": "say", "tts_speaker": ""})
        assert tts._key("犬", None) not in (a.stem, b.stem)

    def test_engine_errors_become_tts_errors(self, engine):
        tts.is_available()
        engine.error = urllib.error.URLError("gone")
        with pytest.raises(tts.TtsError, match="not reachable"):
            tts.synthesize("犬")

    def test_limits_still_apply(self, engine):
        with pytest.raises(tts.TtsError, match="nothing"):
            tts.synthesize("")
        with pytest.raises(tts.TtsError, match="limit"):
            tts.synthesize("あ" * 201)

    def test_unavailable_raises_the_reason(self, engine, monkeypatch):
        monkeypatch.delenv("STUDIOUS_TTS_SPEAKER")
        config.get_settings.cache_clear()
        tts.reset_cache()
        with pytest.raises(tts.TtsError, match="speaker must be chosen"):
            tts.synthesize("犬")


# ---------- reading check ----------


class TestNormalizer:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("とうきょう", "トーキョー"),
            ("おおさか", "オーサカ"),
            ("おうさま", "オーサマ"),
            ("せんせい", "センセー"),
            ("えいが", "エーガ"),
            ("ゆうめい", "ユーメイ"),
            ("こんにちは", "コンニチワ"),
            ("かれは", "カレワ"),
            ("ほんを", "ホンオ"),
            ("ありがとう", "アリガトー"),
        ],
    )
    def test_long_vowel_and_particle_spellings_are_equal(self, a, b):
        assert tts.normalize_reading(a) == tts.normalize_reading(b)

    @pytest.mark.parametrize("a,b", [("かんり", "カンリー"), ("いく", "ユク"), ("こうえん", "コウエン"[:3])])
    def test_different_readings_differ(self, a, b):
        assert tts.normalize_reading(a) != tts.normalize_reading(b)

    def test_non_kana_is_dropped(self):
        assert tts.normalize_reading("テ'スト/、_ 1") == "てすと"
        assert tts.kana_of_query({"kana": "テ'スト/ガ、_ー"}) == "テストガー"
        assert tts.kana_of_query({}) == ""


class TestCorrection:
    def test_matching_reading_makes_one_query(self, engine):
        engine.kana["今日"] = "キョー'"
        report: dict[str, Any] = {}
        tts.synthesize("今日", "きょう", report=report)
        assert engine.paths().count("/audio_query") == 1 and not report

    def test_mismatch_requeries_with_the_reading_and_reports(self, engine):
        engine.kana["今日"] = "コンニチ'"
        report: dict[str, Any] = {}
        tts.synthesize("今日", "きょう", report=report)
        queries = [r["params"]["text"] for r in engine.requests if r["path"] == "/audio_query"]
        assert queries == ["今日", "きょう"] and report == {"corrected": True}
        syn = next(r for r in engine.requests if r["path"] == "/synthesis")
        assert json.loads(syn["data"])["text"] == "きょう"

    def test_no_expected_reading_no_check(self, engine):
        tts.synthesize("今日")
        assert engine.paths().count("/audio_query") == 1

    def test_say_engine_never_checks(self, isolated_data_dir):
        # (with the conftest guard there is no say; the point is no engine request is made)
        with pytest.raises(tts.TtsError):
            tts.synthesize("今日", "きょう")

    def test_expected_reading_helper(self):
        assert anki_push.expected_reading("かれにあえて。") == "かれにあえて。"
        assert anki_push.expected_reading("てん100") is None
        assert anki_push.expected_reading("") is None


# ---------- anki push ----------


class TestPushWithEngine:
    def test_word_reading_passed_and_corrections_counted(self, engine, afconvert, isolated_data_dir, monkeypatch):
        ids = _seed(("犬", "猫"))
        store.update_item("vocab", ids[0], reading="いぬ")
        store.update_item("vocab", ids[1], reading="ねこ")
        engine.kana["犬"] = "ワンワン"  # wrong reading for 犬; 猫 falls through to the default kana
        engine.kana["猫"] = "ネコ"
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["audio"]["enabled"] is True and r["audio"]["attached"] >= 2
        assert r["audio"]["reading_corrected"] == 1
        notes = next(p for a, p in fake.calls if a == "addNotes")["notes"]
        assert notes[0]["audio"][0]["filename"].endswith(".m4a")

    def test_wav_clips_keep_their_extension_in_anki(self, engine, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        fake = _use(monkeypatch)
        client.post("/api/anki/push", json={**BODY, "confirm": True})
        notes = next(p for a, p in fake.calls if a == "addNotes")["notes"]
        assert notes[0]["audio"][0]["filename"].endswith(".wav")

    def test_preview_reports_engine_and_reason(self, engine, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        _use(monkeypatch)
        a = client.post("/api/anki/push/preview", json=BODY).json()["audio"]
        assert a["engine"] == "voicevox" and a["available"] is True and a["voice"] == "ずんだもん — ノーマル"
        engine.error = OSError("down")
        tts.reset_cache()
        a = client.post("/api/anki/push/preview", json=BODY).json()["audio"]
        assert a["available"] is False and "not reachable" in a["reason"]


# ---------- settings and endpoints ----------


class TestPreferences:
    def test_preferences_override_env(self, engine):
        assert (tts.engine(), tts.speaker()) == ("voicevox", 3)
        r = client.put("/api/preferences", json={"tts_engine": "say", "tts_url": "http://localhost:10101/",
                                                 "tts_speaker": 7}).json()
        assert (r["tts_engine"], r["tts_url"], r["tts_speaker"]) == ("say", "http://localhost:10101", 7)
        assert tts.url() == "http://localhost:10101" and tts.speaker() == 7 and tts.engine() == "say"
        assert json.loads((store.store_path("vocab").parent.parent / "preferences.json").read_text())["tts_speaker"] == 7

    def test_empty_string_clears_back_to_env(self, engine):
        client.put("/api/preferences", json={"tts_engine": "say", "tts_url": "http://h:1", "tts_speaker": 7})
        r = client.put("/api/preferences", json={"tts_engine": "", "tts_url": "", "tts_speaker": ""}).json()
        assert (r["tts_engine"], r["tts_url"], r["tts_speaker"]) == ("voicevox", "http://127.0.0.1:50021", 3)
        assert r["tts_engine_override"] is None

    def test_unspecified_fields_stay(self, engine):
        client.put("/api/preferences", json={"tts_speaker": 2})
        client.put("/api/preferences", json={"vlm_model": ""})
        assert tts.speaker() == 2

    @pytest.mark.parametrize(
        "body",
        [{"tts_engine": "espeak"}, {"tts_url": "ftp://x"}, {"tts_url": "file:///x"}, {"tts_speaker": -1},
         {"tts_speaker": "abc"}, {"tts_url": "http://" + "a" * 300}],
    )
    def test_validation(self, engine, body):
        assert client.put("/api/preferences", json=body).status_code == 400

    def test_changing_the_preference_resets_availability(self, engine):
        assert tts.is_available() is True
        client.put("/api/preferences", json={"tts_speaker": 99})
        assert tts.is_available() is False


class TestEndpoints:
    def test_speakers(self, engine):
        d = client.get("/api/tts/speakers").json()
        assert d["speaker"] == 3 and [s["label"] for s in d["speakers"]][-1] == "ずんだもん — ノーマル"

    def test_speakers_say_engine_is_400(self, isolated_data_dir):
        assert client.get("/api/tts/speakers").status_code == 400

    def test_speakers_engine_down_is_503(self, engine):
        engine.error = OSError("down")
        r = client.get("/api/tts/speakers")
        assert r.status_code == 503 and "not reachable" in r.json()["detail"]

    def test_test_voice_plays_the_fixed_sentence(self, engine, afconvert):
        r = client.post("/api/tts/test")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mp4"
        aq = next(x for x in engine.requests if x["path"] == "/audio_query")
        assert aq["params"]["text"] == "今日はいい天気ですね。" == tts.TEST_SENTENCE and aq["params"]["speaker"] == "3"

    def test_test_voice_wav_content_type(self, engine):
        assert client.post("/api/tts/test").headers["content-type"] == "audio/wav"

    def test_test_voice_unavailable_is_503(self, engine):
        engine.error = OSError("down")
        assert client.post("/api/tts/test").status_code == 503

    def test_vocab_audio_content_type_follows_the_format(self, engine):
        item = store.create_item("vocab", headword="嬉しい", reading="うれしい", meaning="glad")["id"]
        r = client.get(f"/api/vocab/{item}/audio?part=word")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
        aq = next(x for x in engine.requests if x["path"] == "/audio_query")
        assert aq["params"]["text"] == "嬉しい"

    def test_vocab_audio_unavailable_reports_the_reason(self, engine):
        engine.error = OSError("down")
        item = store.create_item("vocab", headword="嬉しい", reading="うれしい", meaning="glad")["id"]
        r = client.get(f"/api/vocab/{item}/audio?part=word")
        assert r.status_code == 503 and "not reachable" in r.json()["detail"]
