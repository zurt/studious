"""The `say_remote` speech engine: the Mac voices through the helper, with the
last voice listing kept on disk and cached clips served while the Mac is away."""
from __future__ import annotations

import urllib.error
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import anki_push, say_remote, store, tts
from tests.conftest import MAC_AUDIO as AUDIO
from tests.test_anki_push import BODY, _seed, _use
from tests.test_card_quality import GEN, _addnotes
from tests.test_say_voices import KYOKO_E, OREN_E, THREE, FakeSay
from tests.test_voicevox import FakeEngine

client = TestClient(app)


def _local_say(monkeypatch, listing=THREE):
    fake = FakeSay()
    monkeypatch.setenv("STUDIOUS_TTS_ENGINE", "say")
    config.get_settings.cache_clear()
    tts.reset_cache()
    monkeypatch.setattr(tts.sys, "platform", "darwin")
    monkeypatch.setattr(tts.shutil, "which", lambda n: "/usr/bin/say")
    monkeypatch.setattr(tts, "_voices_output", lambda: listing)
    monkeypatch.setattr(tts.subprocess, "run", fake)
    return fake


# ---------- configuration ----------


class TestConfig:
    def test_env_accepts_say_remote_and_helper_url(self, mac):
        assert config.get_settings().tts_engine == "say_remote"
        assert tts.engine() == "say_remote" and tts.helper_url() == "http://mac.example:8766"

    def test_defaults(self, isolated_data_dir, monkeypatch):
        monkeypatch.delenv("STUDIOUS_SAY_HELPER_URL", raising=False)
        monkeypatch.delenv("STUDIOUS_TTS_PREGENERATE", raising=False)
        config.get_settings.cache_clear()
        s = config.get_settings()
        assert s.say_helper_url == "http://127.0.0.1:8766" and s.tts_pregenerate is True

    @pytest.mark.parametrize("raw", ["0", "false", "No", "OFF"])
    def test_pregenerate_off(self, isolated_data_dir, monkeypatch, raw):
        monkeypatch.setenv("STUDIOUS_TTS_PREGENERATE", raw)
        config.get_settings.cache_clear()
        assert config.get_settings().tts_pregenerate is False

    def test_preferences_accept_say_remote(self, isolated_data_dir):
        r = client.put("/api/preferences", json={"tts_engine": "say_remote"})
        assert r.status_code == 200 and r.json()["tts_engine"] == "say_remote"
        assert tts.engine() == "say_remote"


# ---------- availability and the last-known listing ----------


class TestAvailability:
    def test_available_from_the_helper_listing(self, mac):
        assert tts.is_available() is True
        st = tts.status()
        assert st["engine"] == "say_remote" and st["helper_url"] == "http://mac.example:8766"
        assert st["voices"] == [KYOKO_E, OREN_E, "Otoya (Enhanced)"] and st["pending"] == 0
        assert KYOKO_E in st["installed"] and st["voice"].startswith("Kyoko")

    def test_listing_is_written_to_disk(self, mac):
        tts.is_available()
        assert (tts.audio_dir() / "say-voices.txt").read_text(encoding="utf-8") == mac.listing

    def test_listing_is_cached_for_the_ttl_then_refreshed(self, mac, monkeypatch):
        calls = []
        real = mac.__call__
        monkeypatch.setattr(say_remote, "_open", lambda req, timeout: calls.append(1) or real(req, timeout))
        tts.is_available()
        tts.is_available()
        assert len(calls) == 1
        now = tts.time.monotonic()
        monkeypatch.setattr(tts.time, "monotonic", lambda: now + tts.AVAILABILITY_TTL + 1)
        tts.is_available()
        assert len(calls) == 2

    def test_unreachable_with_no_file_has_no_pool(self, mac):
        mac.up = False
        assert tts.is_available() is False
        assert "make say-helper" in tts.unavailable_reason() and "this Mac" not in tts.unavailable_reason()
        assert tts.pool() == [] and tts.status()["voices"] == []

    def test_unreachable_uses_the_last_known_listing(self, mac):
        tts.is_available()
        mac.up = False
        tts.reset_cache()
        assert tts.is_available() is False
        st = tts.status()
        assert st["available"] is False and "not reachable" in st["reason"]
        assert st["voices"] == [KYOKO_E, OREN_E, "Otoya (Enhanced)"]
        assert tts._pool_info()["plain"] is True

    def test_no_japanese_voice(self, mac):
        mac.listing = "Samantha            en_US    # Hello!\n"
        assert tts.is_available() is False and "No Japanese voice" in tts.unavailable_reason()

    def test_voice_setting_is_shared_with_say(self, mac, monkeypatch):
        monkeypatch.setenv("STUDIOUS_TTS_VOICE", "O-Ren")
        config.get_settings.cache_clear()
        tts.reset_cache()
        assert tts.pool() == ["O-Ren"] and tts.speaker_label() == "O-Ren"


# ---------- cache keys ----------


class TestKeys:
    def test_legacy_say_key_is_pinned(self, isolated_data_dir, monkeypatch):
        _local_say(monkeypatch)
        assert tts._key("犬", None, KYOKO_E) == "d261bb02949b29ff8ee0"

    def test_say_and_say_remote_share_keys(self, isolated_data_dir, monkeypatch):
        _local_say(monkeypatch)
        local = tts._key("犬", "いぬ", KYOKO_E)
        monkeypatch.setenv("STUDIOUS_TTS_ENGINE", "say_remote")
        config.get_settings.cache_clear()
        assert tts._key("犬", "いぬ", KYOKO_E) == local == "d261bb02949b29ff8ee0"

    def test_a_clip_made_by_say_is_found_by_say_remote(self, mac, monkeypatch):
        local = _local_say(monkeypatch)
        made = tts.synthesize("犬")
        assert local.voices
        monkeypatch.setenv("STUDIOUS_TTS_ENGINE", "say_remote")
        config.get_settings.cache_clear()
        monkeypatch.setattr(say_remote, "_open", mac)
        tts.reset_cache()
        assert tts.synthesize("犬") == made
        assert mac.say_calls == []


# ---------- synthesize ----------


class TestSynthesize:
    def test_generates_through_the_helper_and_caches(self, mac):
        path = tts.synthesize("犬", seed="犬")
        assert path.suffix == ".m4a" and path.read_bytes() == AUDIO
        assert len(mac.say_calls) == 1
        assert tts.synthesize("犬", seed="犬") == path
        assert len(mac.say_calls) == 1
        assert not [p for p in tts.audio_dir().iterdir() if p.suffix == ".tmp"]

    def test_rotation_matches_the_say_engine(self, mac, monkeypatch):
        tts.synthesize("犬", seed="seed-a")
        remote_voice = mac.voices[0]
        local = _local_say(monkeypatch)
        tts.synthesize("猫", seed="seed-a")
        assert local.voices[0] == remote_voice

    def test_falls_back_through_the_chain(self, mac):
        mac.fail_voices = {KYOKO_E, OREN_E, "Otoya (Enhanced)"}
        path = tts.synthesize("犬", seed="x")
        assert path.exists()
        assert mac.voices[-1] == "Kyoko" and len(mac.voices) == 4  # the whole pool, then plain Kyoko

    def test_every_voice_failing_is_a_plain_error(self, mac):
        mac.fail_voices = {KYOKO_E, OREN_E, "Otoya (Enhanced)", "Kyoko"}
        with pytest.raises(tts.TtsError) as err:
            tts.synthesize("犬")
        assert not isinstance(err.value, tts.TtsUnavailable)

    def test_tiny_audio_is_rejected(self, mac):
        mac.audio = b"x"
        with pytest.raises(tts.TtsError, match="no usable audio"):
            tts.synthesize("犬")
        assert not list(tts.audio_dir().glob("*.m4a"))

    def test_unreachable_mid_call_is_unavailable_and_forgets_the_listing(self, mac):
        tts.is_available()
        mac.up = False
        with pytest.raises(tts.TtsUnavailable):
            tts.synthesize("犬")
        assert not [k for k in tts._info if k[0] == "say_remote"]

    def test_not_cached_and_down_raises_unavailable(self, mac):
        mac.up = False
        with pytest.raises(tts.TtsUnavailable, match="not reachable"):
            tts.synthesize("犬")

    def test_cached_clip_is_served_with_the_mac_asleep(self, mac):
        made = tts.synthesize("犬", seed="犬")
        mac.up = False
        tts.reset_cache()
        assert tts.is_available() is False
        assert tts.synthesize("犬", seed="犬") == made
        assert tts.cached_clip("犬", seed="犬") == made
        assert tts.cached_clip("猫", seed="猫") is None

    def test_text_is_validated_before_the_cache(self, mac):
        mac.up = False
        with pytest.raises(tts.TtsError, match="limit") as err:
            tts.synthesize("あ" * 201)
        assert not isinstance(err.value, tts.TtsUnavailable)
        with pytest.raises(tts.TtsError, match="nothing"):
            tts.synthesize(" ")

    def test_cached_clip_ignores_bad_text(self, mac):
        assert tts.cached_clip("") is None and tts.cached_clip("あ" * 300) is None

    def test_forced_voice(self, mac):
        tts.synthesize(tts.TEST_SENTENCE, voice=OREN_E)
        assert mac.voices == [OREN_E]


class TestOtherEnginesServeTheCacheWhenDown:
    def test_say(self, isolated_data_dir, monkeypatch):
        _local_say(monkeypatch)
        made = tts.synthesize("犬", seed="犬")
        monkeypatch.setattr(tts, "_state", lambda: (False, "the voice is gone"))
        assert tts.synthesize("犬", seed="犬") == made
        with pytest.raises(tts.TtsUnavailable, match="gone"):
            tts.synthesize("猫", seed="猫")

    def test_voicevox(self, isolated_data_dir, monkeypatch):
        fake = FakeEngine()
        monkeypatch.setattr(tts.voicevox, "_open", fake)
        monkeypatch.setenv("STUDIOUS_TTS_ENGINE", "voicevox")
        monkeypatch.setenv("STUDIOUS_TTS_SPEAKER", "3")
        config.get_settings.cache_clear()
        tts.reset_cache()
        made = tts.synthesize("犬")
        fake.error = urllib.error.URLError("refused")
        tts.reset_cache()
        assert tts.synthesize("犬") == made
        with pytest.raises(tts.TtsUnavailable):
            tts.synthesize("猫")


# ---------- endpoints ----------


def _item(**kw) -> dict:
    item = store.create_item("vocab", headword="犬", reading="いぬ", meaning="dog")
    return store.update_item("vocab", item["id"], **kw) or item


class TestEndpoints:
    def test_audio_endpoint_serves_cache_while_down(self, mac):
        item = _item()
        r = client.get(f"/api/vocab/{item['id']}/audio")
        assert r.status_code == 200 and r.content == AUDIO
        mac.up = False
        tts.reset_cache()
        again = client.get(f"/api/vocab/{item['id']}/audio")
        assert again.status_code == 200 and again.content == AUDIO

    def test_audio_endpoint_503_when_down_and_not_cached(self, mac):
        item = _item()
        mac.up = False
        r = client.get(f"/api/vocab/{item['id']}/audio")
        assert r.status_code == 503 and "make say-helper" in r.json()["detail"]

    def test_audio_endpoint_uses_clip_specs(self, mac):
        item = _item(example=GEN)
        specs = anki_push.clip_specs(item)
        assert [s[0] for s in specs] == ["word", "sentence"]
        client.get(f"/api/vocab/{item['id']}/audio?part=sentence")
        assert mac.say_calls[-1][1] == GEN["sentence"]
        assert tts.cached_clip(specs[1][1], specs[1][2], seed=specs[1][3]) is not None

    def test_audio_endpoint_404_without_sentence(self, mac):
        item = _item()
        assert client.get(f"/api/vocab/{item['id']}/audio?part=sentence").status_code == 404

    def test_tts_test_with_a_named_voice(self, mac):
        r = client.post("/api/tts/test", json={"voice": KYOKO_E})
        assert r.status_code == 200 and mac.voices == [KYOKO_E]
        assert client.post("/api/tts/test", json={"voice": "Nobody"}).status_code == 400

    def test_tts_status_has_pending_and_helper_url(self, mac):
        d = client.get("/api/tts/status").json()
        assert d["pending"] == 0 and d["helper_url"] == "http://mac.example:8766"


# ---------- Anki push with the Mac away ----------


class TestPushWhileDown:
    def test_cached_clips_are_attached_and_the_rest_counted(self, mac, monkeypatch):
        ids = _seed(("犬", "猫"))
        word = anki_push.clip_specs(store.get_item("vocab", ids[0]))[0]
        made = tts.synthesize(word[1], word[2], seed=word[3])  # only 犬 is cached
        mac.up = False
        tts.reset_cache()
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["created"] == 2
        assert r["audio"] == {
            "enabled": True, "unavailable": True, "attached": 1, "failed": 0,
            "reading_corrected": 0, "missing": 1,
        }
        notes = _addnotes(fake)
        attached = [n for n in notes if n.get("audio")]
        assert len(attached) == 1 and attached[0]["audio"][0]["filename"] == f"studious_{made.stem}.m4a"
        assert mac.say_calls and len(mac.say_calls) == 1  # nothing generated during the send

    def test_a_helper_that_drops_mid_send_counts_missing_not_failed(self, mac, monkeypatch):
        _seed(("犬", "猫", "鳥"))
        mac.up = True
        tts.is_available()  # up when the send starts
        real = mac.__call__

        def drop_after_listing(req, timeout):
            if urllib.parse.urlsplit(req.full_url).path == "/say":
                mac.up = False
            return real(req, timeout)

        monkeypatch.setattr(say_remote, "_open", drop_after_listing)
        _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["created"] == 3
        assert r["audio"]["unavailable"] is True and r["audio"]["failed"] == 0
        assert r["audio"]["attached"] + r["audio"]["missing"] == 3

    def test_audio_status_in_the_preview_has_pending(self, mac, monkeypatch):
        _seed(("犬",))
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["audio"]["engine"] == "say_remote" and d["audio"]["pending"] == 0


def test_error_messages_name_the_remote_option(isolated_data_dir):
    assert "say_remote" in tts.unavailable_reason()


# ---------- cached clips cost no network call ----------


class TestNoNetworkForCachedClips:
    def _count(self, mac, monkeypatch):
        calls: list[str] = []
        real = mac.__call__
        monkeypatch.setattr(say_remote, "_open", lambda req, timeout: calls.append(req.full_url) or real(req, timeout))
        return calls

    def test_cold_memory_listing_on_disk(self, mac, monkeypatch):
        made = tts.synthesize("犬", seed="犬")
        mac.up = False
        tts.reset_cache()
        calls = self._count(mac, monkeypatch)
        assert tts.synthesize("犬", seed="犬") == made
        assert tts.cached_clip("犬", seed="犬") == made
        assert calls == []

    def test_expired_memory_entry_is_still_used(self, mac, monkeypatch):
        made = tts.synthesize("犬", seed="犬")
        mac.up = False
        now = tts.time.monotonic()
        monkeypatch.setattr(tts.time, "monotonic", lambda: now + tts.AVAILABILITY_TTL + 100)
        calls = self._count(mac, monkeypatch)
        assert tts.synthesize("犬", seed="犬") == made
        assert tts.cached_clip("犬", seed="犬") == made
        assert calls == []

    def test_miss_with_a_changed_listing_uses_the_fresh_pool(self, mac):
        tts.synthesize("犬", seed="犬")  # the stale pool: three Enhanced voices
        old_pool = tts.pool()
        new_pool = sorted([*old_pool, "Hattori (Enhanced)"])
        mac.listing += "Hattori (Enhanced)    ja_JP    # こんにちは!\n"
        tts._info[next(iter(tts._info))]["_at"] -= tts.AVAILABILITY_TTL + 1
        seed = next(
            s for s in map(str, range(500)) if tts.pick_voices(new_pool, s)[0] != tts.pick_voices(old_pool, s)[0]
        )
        path = tts.synthesize("猫", seed=seed)
        assert mac.say_calls[-1][0] == tts.pick_voices(new_pool, seed)[0]
        mac.up = False
        tts.reset_cache()  # the pool now comes from the refreshed file on disk
        assert tts.cached_clip("猫", seed=seed) == path

    def test_miss_with_the_helper_down_is_unavailable(self, mac):
        tts.synthesize("犬", seed="犬")
        mac.up = False
        tts.reset_cache()
        with pytest.raises(tts.TtsUnavailable):
            tts.synthesize("猫", seed="猫")
