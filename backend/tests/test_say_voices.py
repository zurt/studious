"""The `say` voice pool: enhanced voices by default, per-card rotation, fallback."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import tts
from tests.test_anki_push import BODY, _seed, _use

client = TestClient(app)

KYOKO_E = "Kyoko (Enhanced)"
OREN_E = "O-Ren (Enhanced)"
OTOYA_E = "Otoya (Enhanced)"
KYOKO_P = "Kyoko (Japanese (Japan))"
EDDY = "Eddy (Japanese (Japan))"

LINES = {
    KYOKO_E: "Kyoko (Enhanced)    ja_JP    # こんにちは! 私の名前はKyokoです。",
    OREN_E: "O-Ren (Enhanced)    ja_JP    # こんにちは! 私の名前はO-Renです。",
    OTOYA_E: "Otoya (Enhanced)    ja_JP    # こんにちは! 私の名前はOtoyaです。",
    KYOKO_P: "Kyoko (Japanese (Japan)) ja_JP    # こんにちは! 私の名前はKyokoです。",
    EDDY: "Eddy (Japanese (Japan)) ja_JP    # こんにちは! 私の名前はEddyです。",
    "Flo": "Flo (Japanese (Japan)) ja_JP    # こんにちは! 私の名前はFloです。",
    "Samantha": "Samantha            en_US    # Hello! My name is Samantha.",
}
ALL = "\n".join(LINES.values()) + "\n"
THREE = "\n".join([LINES[KYOKO_E], LINES[OREN_E], LINES[OTOYA_E], LINES[KYOKO_P], LINES[EDDY], LINES["Flo"],
                   LINES["Samantha"], LINES[KYOKO_P]]) + "\n"  # the plain voice is listed twice
PLAIN_ONLY = "\n".join([LINES[KYOKO_P], LINES[EDDY], LINES["Flo"], LINES["Samantha"]]) + "\n"
NOTHING = LINES["Samantha"] + "\n"


class FakeSay:
    def __init__(self, fail: set[str] | None = None):
        self.calls: list[list[str]] = []
        self.fail = fail or set()

    @property
    def voices(self) -> list[str]:
        return [c[c.index("-v") + 1] for c in self.calls]

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if args[args.index("-v") + 1] in self.fail:
            return subprocess.CompletedProcess(args, 1, b"", b"voice failed")
        Path(args[args.index("-o") + 1]).write_bytes(b"\0" * 5000)
        return subprocess.CompletedProcess(args, 0, b"", b"")


def _setup(monkeypatch, listing, fail=None, setting=None):
    fake = FakeSay(fail)
    tts.reset_cache()
    monkeypatch.setattr(tts.sys, "platform", "darwin")
    monkeypatch.setattr(tts.shutil, "which", lambda n: "/usr/bin/say")
    monkeypatch.setattr(tts, "_voices_output", lambda: listing)
    monkeypatch.setattr(tts.subprocess, "run", fake)
    if setting is None:
        monkeypatch.delenv("STUDIOUS_TTS_VOICE", raising=False)
    else:
        monkeypatch.setenv("STUDIOUS_TTS_VOICE", setting)
    config.get_settings.cache_clear()
    return fake


@pytest.fixture
def three(monkeypatch, isolated_data_dir):
    yield _setup(monkeypatch, THREE)
    tts.reset_cache()


# ---------- parser ----------


class TestParser:
    def test_verbatim_lines(self):
        got = tts.parse_voices(THREE)
        assert got == [
            (KYOKO_E, "ja_JP"), (OREN_E, "ja_JP"), (OTOYA_E, "ja_JP"), (KYOKO_P, "ja_JP"),
            (EDDY, "ja_JP"), ("Flo (Japanese (Japan))", "ja_JP"), ("Samantha", "en_US"), (KYOKO_P, "ja_JP"),
        ]

    def test_names_keep_spaces_hyphens_and_nested_parentheses(self):
        names = [n for n, _ in tts.parse_voices(ALL)]
        assert "O-Ren (Enhanced)" in names and "Kyoko (Japanese (Japan))" in names

    def test_garbage_lines_are_skipped(self):
        assert tts.parse_voices("\n  \nnot a voice line\n") == []

    @pytest.mark.parametrize("name,expected", [("Kyoko", True), ("kyoko (enhanced)", True), ("Ky", False),
                                               ("O-Ren", True), ("Eddy", True), ("Nobody", False)])
    def test_voice_listed(self, name, expected):
        assert tts.voice_listed(ALL, name) is expected


# ---------- the pool ----------


class TestPool:
    def test_three_enhanced_sorted_novelty_never_chosen(self):
        assert tts.auto_pool(THREE) == [KYOKO_E, OREN_E, OTOYA_E]

    def test_premium_voices_count_too(self):
        listing = THREE + "Hattori (Premium)    ja_JP    # こんにちは!\n"
        assert tts.auto_pool(listing) == ["Hattori (Premium)", KYOKO_E, OREN_E, OTOYA_E]

    def test_non_japanese_enhanced_voice_is_ignored(self):
        assert tts.auto_pool("Ava (Enhanced)    en_US    # Hello!\n" + PLAIN_ONLY) == ["Kyoko"]

    def test_none_enhanced_falls_back_to_plain_kyoko(self):
        assert tts.auto_pool(PLAIN_ONLY) == ["Kyoko"]

    def test_nothing_gives_empty(self):
        assert tts.auto_pool(NOTHING) == []

    def test_explicit_list_used_as_given_dropping_missing(self):
        pool, note = tts.resolve_pool(THREE, f"{OTOYA_E}, Nobody ,{KYOKO_E}")
        assert pool == [OTOYA_E, KYOKO_E] and note == ""

    def test_explicit_list_all_missing_falls_back_to_auto_with_a_note(self):
        pool, note = tts.resolve_pool(THREE, "Nobody, Nobody Else")
        assert pool == [KYOKO_E, OREN_E, OTOYA_E] and "Nobody" in note and "automatic" in note

    def test_explicit_plain_name_resolves(self):
        assert tts.resolve_pool(THREE, "Kyoko")[0] == ["Kyoko"]

    def test_auto_setting_is_case_insensitive(self):
        assert tts.resolve_pool(THREE, "AUTO")[0] == [KYOKO_E, OREN_E, OTOYA_E]

    def test_label(self):
        assert tts.pool_label([KYOKO_E, OREN_E, OTOYA_E]) == "Kyoko, O-Ren, Otoya (Enhanced)"
        assert tts.pool_label(["Kyoko"]) == "Kyoko"
        assert tts.pool_label([KYOKO_E, "Hattori (Premium)"]) == f"{KYOKO_E}, Hattori (Premium)"


class TestStatus:
    def test_three_enhanced(self, three):
        st = client.get("/api/tts/status").json()
        assert st["available"] is True and st["engine"] == "say"
        assert st["voices"] == [KYOKO_E, OREN_E, OTOYA_E]
        assert st["voice"] == "Kyoko, O-Ren, Otoya (Enhanced)" and st["reason"] == "" and st["setting"] == "auto"
        assert KYOKO_P in st["installed"] and "Samantha" not in st["installed"]

    def test_plain_only(self, monkeypatch, isolated_data_dir):
        _setup(monkeypatch, PLAIN_ONLY)
        st = client.get("/api/tts/status").json()
        assert st["available"] and st["voices"] == ["Kyoko"] and st["voice"] == "Kyoko"

    def test_nothing_installed_is_unavailable_with_a_reason(self, monkeypatch, isolated_data_dir):
        _setup(monkeypatch, NOTHING)
        st = client.get("/api/tts/status").json()
        assert st["available"] is False and st["voices"] == [] and "No Japanese Mac voice" in st["reason"]

    def test_all_missing_explicit_list_reports_the_fallback(self, monkeypatch, isolated_data_dir):
        _setup(monkeypatch, THREE, setting="Nobody")
        st = client.get("/api/tts/status").json()
        assert st["available"] and st["voices"] == [KYOKO_E, OREN_E, OTOYA_E] and "Nobody" in st["reason"]

    def test_preview_audio_reports_the_pool(self, three, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        _use(monkeypatch)
        a = client.post("/api/anki/push/preview", json=BODY).json()["audio"]
        assert a["voices"] == [KYOKO_E, OREN_E, OTOYA_E] and a["voice"] == "Kyoko, O-Ren, Otoya (Enhanced)"


# ---------- rotation ----------


class TestRotation:
    def test_deterministic_and_spread(self):
        pool = [KYOKO_E, OREN_E, OTOYA_E]
        assert tts.pick_voices(pool, "嬉しい")[0] == tts.pick_voices(pool, "嬉しい")[0]
        firsts = {tts.pick_voices(pool, f"単語{i}")[0] for i in range(60)}
        assert firsts == set(pool)
        counts = [sum(tts.pick_voices(pool, f"単語{i}")[0] == v for i in range(300)) for v in pool]
        assert min(counts) > 60  # roughly even

    def test_the_chain_is_the_rest_of_the_pool_then_plain(self):
        chain = tts.pick_voices([KYOKO_E, OREN_E, OTOYA_E], "x")
        assert sorted(chain[:3]) == [KYOKO_E, OREN_E, OTOYA_E] and chain[3] == "Kyoko"
        assert tts.pick_voices(["Kyoko"], "x") == ["Kyoko"]
        assert tts.pick_voices([], "x", None) == []

    def test_stable_across_processes(self):
        code = (
            "from app.services import tts;"
            f"print(tts.pick_voices({[KYOKO_E, OREN_E, OTOYA_E]!r}, '嬉しい'))"
        )
        backend = str(Path(__file__).resolve().parents[1])
        outs = set()
        for hashseed in ("1", "2", "random"):
            env = {**os.environ, "PYTHONHASHSEED": hashseed, "PYTHONPATH": backend, "PYTHONIOENCODING": "utf-8"}
            outs.add(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                                    cwd=backend, check=True).stdout)
        assert len(outs) == 1
        assert outs == {f"{tts.pick_voices([KYOKO_E, OREN_E, OTOYA_E], '嬉しい')}\n"}

    def test_same_seed_same_voice_and_cached(self, three):
        a = tts.synthesize("犬です。", seed="犬")
        b = tts.synthesize("犬です。", seed="犬")
        assert a == b and len(three.calls) == 1
        assert three.voices[0] == tts.pick_voices([KYOKO_E, OREN_E, OTOYA_E], "犬")[0]

    def test_no_seed_hashes_the_text(self, three):
        tts.synthesize("猫です。")
        assert three.voices[0] == tts.pick_voices([KYOKO_E, OREN_E, OTOYA_E], "猫です。")[0]

    def test_different_voice_different_clip(self, three):
        a = tts.synthesize("犬です。", voice=KYOKO_E)
        b = tts.synthesize("犬です。", voice=OREN_E)
        assert a != b and three.voices == [KYOKO_E, OREN_E]

    def test_voice_name_is_one_exact_argument(self, three):
        tts.synthesize("犬です。", voice=OREN_E)
        args = three.calls[0]
        assert args[args.index("-v") + 1] == "O-Ren (Enhanced)"
        assert args[:2] == ["say", "-v"] and "--file-format=m4af" in args and "--data-format=aac" in args
        assert len(args) == 9

    def test_one_card_one_voice_for_word_and_sentence(self, three, isolated_data_dir, monkeypatch):
        from app.services import store

        ids = _seed(("犬", "猫", "鳥", "馬", "鹿"))
        for hw, item_id in zip(("犬", "猫", "鳥", "馬", "鹿"), ids, strict=True):
            store.update_item("vocab", item_id, example={
                "source": "generated", "sentence": f"{hw}がいる。", "surface": hw,
                "furigana": f"{hw}[x]がいる。".replace("[x]", "[いぬ]"), "gloss": "g"})
        _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["audio"]["attached"] == 10
        assert len(set(three.voices)) > 1  # different cards vary
        for hw in ("犬", "猫", "鳥", "馬", "鹿"):
            expected = tts.pick_voices([KYOKO_E, OREN_E, OTOYA_E], hw)[0]
            assert tts._key(hw, None, expected) in {p.stem for p in (isolated_data_dir / "audio").iterdir()}
            assert tts._key(f"{hw}がいる。", None, expected) in {p.stem for p in (isolated_data_dir / "audio").iterdir()}

    def test_row_play_endpoint_uses_the_cards_voice(self, three):
        from app.services import store

        item = store.create_item("vocab", headword="犬", reading="いぬ", meaning="dog")["id"]
        assert client.get(f"/api/vocab/{item}/audio?part=word").status_code == 200
        assert three.voices == [tts.pick_voices([KYOKO_E, OREN_E, OTOYA_E], "犬")[0]]


# ---------- fallback ----------


class TestFallback:
    def test_next_voice_then_plain_before_failing(self, monkeypatch, isolated_data_dir):
        fake = _setup(monkeypatch, THREE, fail={KYOKO_E, OREN_E, OTOYA_E})
        path = tts.synthesize("犬です。", seed="犬")
        order = tts.pick_voices([KYOKO_E, OREN_E, OTOYA_E], "犬", "Kyoko")
        assert fake.voices == order and fake.voices[-1] == "Kyoko" and path.exists()

    def test_first_failure_uses_the_next_voice(self, monkeypatch, isolated_data_dir):
        first = tts.pick_voices([KYOKO_E, OREN_E, OTOYA_E], "犬")[0]
        fake = _setup(monkeypatch, THREE, fail={first})
        tts.synthesize("犬です。", seed="犬")
        assert len(fake.voices) == 2 and fake.voices[0] == first and fake.voices[1] != first

    def test_everything_failing_raises(self, monkeypatch, isolated_data_dir):
        fake = _setup(monkeypatch, THREE, fail={KYOKO_E, OREN_E, OTOYA_E, "Kyoko"})
        with pytest.raises(tts.TtsError, match="exited with 1"):
            tts.synthesize("犬です。", seed="犬")
        assert len(fake.voices) == 4
        assert list((isolated_data_dir / "audio").iterdir()) == []

    def test_a_failed_clip_does_not_block_the_send(self, monkeypatch, isolated_data_dir):
        _setup(monkeypatch, THREE, fail={KYOKO_E, OREN_E, OTOYA_E, "Kyoko"})
        _seed(("犬",))
        _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["created"] == 1 and r["audio"]["failed"] == 1 and r["audio"]["attached"] == 0


# ---------- settings and the test endpoint ----------


class TestSettings:
    def test_preference_sets_and_clears_the_explicit_list(self, three):
        r = client.put("/api/preferences", json={"tts_voice": f"{OTOYA_E}, {KYOKO_E}"}).json()
        assert r["tts_voice"] == f"{OTOYA_E}, {KYOKO_E}"
        assert tts.pool() == [OTOYA_E, KYOKO_E]
        r = client.put("/api/preferences", json={"tts_voice": ""}).json()
        assert r["tts_voice"] == "auto" and tts.pool() == [KYOKO_E, OREN_E, OTOYA_E]

    def test_single_explicit_voice_means_every_card_uses_it(self, three):
        client.put("/api/preferences", json={"tts_voice": OREN_E})
        assert {tts.pick_voices(tts.pool(), f"w{i}")[0] for i in range(30)} == {OREN_E}

    def test_too_long_is_rejected(self, three):
        assert client.put("/api/preferences", json={"tts_voice": "a" * 201}).status_code == 400

    def test_test_endpoint_with_a_chosen_voice(self, three):
        r = client.post("/api/tts/test", json={"voice": OTOYA_E})
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mp4"
        assert three.voices == [OTOYA_E]
        assert Path(three.calls[0][three.calls[0].index("-f") + 1]).name.endswith(".txt")

    def test_test_endpoint_restricts_to_installed_japanese_voices(self, three):
        assert client.post("/api/tts/test", json={"voice": "Samantha"}).status_code == 400
        assert client.post("/api/tts/test", json={"voice": "-v Evil"}).status_code == 400
        assert client.post("/api/tts/test", json={"voice": "Kyoko (Premium)"}).status_code == 400
        assert three.calls == []

    def test_test_endpoint_without_a_voice_uses_the_pool(self, three):
        assert client.post("/api/tts/test").status_code == 200
        assert three.voices[0] in (KYOKO_E, OREN_E, OTOYA_E)

    def test_test_endpoint_voice_not_allowed_for_other_engines(self, three, monkeypatch):
        client.put("/api/preferences", json={"tts_engine": "voicevox"})
        assert client.post("/api/tts/test", json={"voice": KYOKO_E}).status_code == 400
