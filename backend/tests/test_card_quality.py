"""Card-quality changes for the Anki send: short meanings, する/な stems,
verb/adjective forms in generated sentences, and Mac-voice audio."""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import anki, anki_push, examples, freq, shortlist, store, tts
from tests.test_anki_push import BODY, FakePush, _seed, _use

client = TestClient(app)


# ---------- 1. short meanings ----------


class TestCardMeaning:
    def test_first_three_glosses(self):
        assert anki_push.card_meaning("to obtain; to get; to procure; to win; to secure") == "to obtain, to get, to procure"

    def test_stops_before_passing_forty_characters(self):
        m = "to obtain; to get hold of something; to procure goods"
        assert anki_push.card_meaning(m) == "to obtain, to get hold of something"
        assert len(anki_push.card_meaning(m)) <= 40

    def test_first_gloss_always_kept(self):
        long = "x" * 80
        assert anki_push.card_meaning(f"{long}; short") == long

    def test_exactly_forty_allowed(self):
        a, b = "a" * 20, "b" * 18  # 20 + 2 + 18 = 40
        assert anki_push.card_meaning(f"{a}; {b}") == f"{a}, {b}"
        assert anki_push.card_meaning(f"{a}; {b}b") == a

    def test_semicolon_inside_parentheses_does_not_split(self):
        assert anki_push.card_meaning("run (a; b); go; work") == "run (a; b), go, work"
        assert anki_push.card_meaning("to run (of a machine; engine); to operate; to work") == (
            "to run (of a machine; engine)"
        )
        assert anki_push.split_glosses("a (b; c (d; e)); f") == ["a (b; c (d; e))", "f"]

    def test_fullwidth_semicolon_and_blanks(self):
        assert anki_push.split_glosses("a；b;; ;c") == ["a", "b", "c"]
        assert anki_push.card_meaning("") == ""

    @pytest.mark.parametrize("source,shortened", [("jmdict", True), ("llm", False), ("user", False), (None, False)])
    def test_only_dictionary_meanings_are_shortened(self, source, shortened):
        item = {"headword": "得る", "reading": "える", "meaning": "to obtain; to get; to procure; to win",
                "meaning_source": source}
        f = anki_push.build_note(item)["fields"]
        assert (f["Word Meaning"] == "to obtain, to get, to procure") is shortened
        if not shortened:
            assert f["Word Meaning"] == item["meaning"]

    def test_store_meaning_untouched(self, isolated_data_dir, monkeypatch):
        ids = _seed(("犬",))
        store.update_item("vocab", ids[0], meaning="a; b; c; d", meaning_source="jmdict", meaning_context="")
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["items"][0]["fields"]["Word Meaning"] == "a, b, c"
        assert store.get_item("vocab", ids[0])["meaning"] == "a; b; c; d"


# ---------- 2. する / な stems ----------


class TestStem:
    @pytest.mark.parametrize(
        "word,reading,expected",
        [
            ("管理する", "かんりする", ("管理", "かんり")),
            ("管理(する)", "かんり", ("管理", "かんり")),
            ("管理（する）", "かんり", ("管理", "かんり")),
            ("重要な", "じゅうような", ("重要", "じゅうよう")),
            ("重要（な）", "じゅうよう", ("重要", "じゅうよう")),
            ("シンプルな", "", ("シンプル", "")),
            ("する", "", None),
            ("きれいな", "きれいな", None),
            ("ようなな", "", None),
            ("食べる", "たべる", None),
            ("管理", "かんり", None),
        ],
    )
    def test_stem_parts(self, word, reading, expected):
        assert store.stem_parts(word, reading) == expected

    def test_variants(self):
        assert store.stem_variants("管理する", "かんりする") == [("管理", "かんり"), ("管理な", "かんりな")]
        assert store.stem_variants("管理", "かんり") == [("管理する", "かんりする"), ("管理な", "かんりな")]
        assert store.stem_variants("重要な", "じゅうような") == [("重要", "じゅうよう"), ("重要する", "じゅうようする")]
        assert store.stem_variants("コーヒー", "") == [("コーヒーする", ""), ("コーヒーな", "")]

    @pytest.mark.parametrize("word", ["する", "きれいな", "ひらがな", "食べる", "お願い", ""])
    def test_no_variants_for_kana_only_and_mixed_words(self, word):
        assert store.stem_variants(word, "") == []

    def test_freq_uses_the_shared_helper(self):
        assert freq._stem("管理する", "かんりする") == store.stem_parts("管理する", "かんりする")
        assert freq._stem("する", "") is None


def _exact_index(*cards):
    exact = {store.vocab_key(w, r): {"state": "new", "deck": "D", "interval": 0} for w, r in cards}
    return exact, {}, {}


class TestAnkiStemLookup:
    def test_bare_word_in_anki_matches_suru_form(self):
        r = anki.lookup("管理する", "かんりする", index=_exact_index(("管理", "かんり")))
        assert r["match"] == "stem"

    def test_suru_form_in_anki_matches_bare_word(self):
        assert anki.lookup("管理", "かんり", index=_exact_index(("管理する", "かんりする")))["match"] == "stem"

    def test_na_and_bracket_forms(self):
        assert anki.lookup("重要な", "じゅうような", index=_exact_index(("重要", "じゅうよう")))["match"] == "stem"
        assert anki.lookup("管理(する)", "かんり", index=_exact_index(("管理", "かんり")))["match"] == "stem"

    def test_exact_tier_wins_and_other_words_do_not_match(self):
        idx = _exact_index(("管理", "かんり"), ("管理する", "かんりする"))
        assert anki.lookup("管理する", "かんりする", index=idx)["match"] == "exact"
        assert anki.lookup("理解する", "りかいする", index=idx) is None

    def test_kana_only_and_suru_itself_untouched(self):
        idx = _exact_index(("する", "する"), ("きれい", "きれい"))
        assert anki.lookup("きれいな", "きれいな", index=idx) is None
        assert anki.lookup("する", "する", index=({}, {}, {})) is None
        assert anki.lookup("ふつう", "ふつう", index=_exact_index(("ふつうする", ""))) is None

    def test_stem_beats_entry_tier(self):
        exact = _exact_index(("管理", "かんり"))[0]
        r = anki.lookup("管理する", "かんりする", 5, index=(exact, {5: {"state": "mature", "deck": "E", "interval": 9}}, {}))
        assert r["match"] == "stem" and r["deck"] == "D"

    def test_shortlist_excludes_stem_match(self):
        item = {"status": "unreviewed", "jmdict_seq": 1, "pos": ["vs"], "headword": "管理する"}
        assert shortlist.assess(item, {"state": "new", "match": "stem"}) == "in_anki"

    def test_anki_in_stem_hides_from_shortlist_list(self, isolated_data_dir, monkeypatch):
        from app.api import store as store_api

        ids = _seed(("管理する", "犬"))
        store.update_item("vocab", ids[0], reading="かんりする")
        index = _exact_index(("管理", "かんり"))
        monkeypatch.setattr(anki, "get_index", lambda: index)
        out = store_api._list_items(
            "vocab", status=None, q=None, doc_id="doc1", chapter_id="ch1", source=None, sort="recent",
            limit=50, offset=0, shortlist=True,
        )
        assert [i["id"] for i in out["items"]] == [ids[1]]
        out = store_api._list_items(
            "vocab", status=None, q=None, doc_id=None, chapter_id=None, source=None, sort="recent",
            limit=50, offset=0, anki_filter="any",
        )
        assert [i["headword"] for i in out["items"]] == ["管理する"]


class TestPushStemDuplicates:
    def test_in_batch_only_first_of_the_pair_is_sent(self, isolated_data_dir, monkeypatch):
        ids = _seed(("管理", "管理する", "重要な", "犬"))
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        by = {i["id"]: i for i in d["items"]}
        assert by[ids[0]]["can_add"] is True
        assert by[ids[1]]["can_add"] is False
        assert "管理" in by[ids[1]]["reason"] and "same word" in by[ids[1]]["reason"].lower()
        assert by[ids[2]]["can_add"] and by[ids[3]]["can_add"]

    def test_reverse_order_keeps_the_first_in_shortlist_order(self, isolated_data_dir, monkeypatch):
        _seed(("管理する", "管理"))
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert [i["can_add"] for i in d["items"]] == [True, False]
        assert "管理する" in d["items"][1]["reason"]

    def test_variant_already_in_anki_is_reported_as_duplicate(self, isolated_data_dir, monkeypatch):
        _seed(("管理する", "重要", "犬"))
        fake = _use(monkeypatch, duplicates={"管理", "重要な"})
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert [i["can_add"] for i in d["items"]] == [False, False, True]
        assert "already in Anki" in d["items"][0]["reason"]
        # still one read-only call, with the variants as extra entries
        calls = [p for a, p in fake.calls if a == "canAddNotesWithErrorDetail"]
        assert len(calls) == 1
        words = [n["fields"]["Word"] for n in calls[0]["notes"]]
        assert words[:3] == ["管理する", "重要", "犬"]
        assert {"管理", "管理な", "重要する", "重要な"} <= set(words[3:])
        assert not {"createDeck", "addNotes"} & set(fake.actions)

    def test_kana_only_and_plain_words_add_no_variant_queries(self, isolated_data_dir, monkeypatch):
        _seed(("ひらがな", "する"))
        fake = _use(monkeypatch)
        client.post("/api/anki/push/preview", json=BODY)
        (call,) = [p for a, p in fake.calls if a == "canAddNotesWithErrorDetail"]
        assert len(call["notes"]) == 2

    def test_push_skips_the_variant_duplicate(self, isolated_data_dir, monkeypatch):
        _seed(("管理", "管理する"))
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["created"] == 1 and len(r["skipped"]) == 1
        notes = next(p for a, p in fake.calls if a == "addNotes")["notes"]
        assert [n["fields"]["Word"] for n in notes] == ["管理"]


# ---------- 3. verbs used as verbs ----------

OPERATE = {
    "sentence": "このパソコンは操作が簡単だ。",
    "surface": "操作",
    "furigana": "このパソコンは 操作[そうさ]が 簡単[かんたん]だ。",
    "gloss": "This computer is easy to operate.",
}
OPERATE_OK = {
    "sentence": "毎日パソコンを操作しています。",
    "surface": "操作しています",
    "furigana": "毎日[まいにち]パソコンを 操作[そうさ]しています。",
    "gloss": "I use a computer every day.",
}


class TestFormRules:
    def test_noun_use_of_a_suru_verb_is_rejected_with_a_specific_reason(self):
        reason = examples.validate_entry(OPERATE, "操作する")
        assert reason and "する verb" in reason and "操作した" in reason

    def test_inflected_suru_forms_pass(self):
        assert examples.validate_entry(OPERATE_OK, "操作する") is None
        for tail, form in [("した", "操作した"), ("します", "操作します"), ("して", "操作して"),
                           ("される", "操作される"), ("できる", "操作できる"), ("せず", "操作せず")]:
            sentence = f"彼はそれを{form}。"
            e = {"sentence": sentence, "surface": form, "furigana": f"彼[かれ]はそれを 操作[そうさ]{tail}。",
                 "gloss": "He did it."}
            assert examples.validate_entry(e, "操作する") is None, form

    def test_surface_equal_to_stem_or_followed_by_a_particle_fails(self):
        e = {**OPERATE_OK, "surface": "操作"}
        assert examples.validate_entry(e, "操作する")
        e = {"sentence": "操作で遊ぶ。", "surface": "操作で", "furigana": "操作[そうさ]で 遊[あそ]ぶ。", "gloss": "Play."}
        assert examples.validate_entry(e, "操作する")

    def test_bracketed_suru_headword(self):
        assert examples.validate_entry(OPERATE_OK, "操作(する)") is None
        assert examples.validate_entry(OPERATE, "操作（する）")

    NA = {
        "sentence": "これは重要な問題です。",
        "surface": "重要な",
        "furigana": "これは 重要[じゅうよう]な 問題[もんだい]です。",
        "gloss": "This is an important problem.",
    }

    def test_na_adjective_forms(self):
        assert examples.validate_entry(self.NA, "重要な") is None
        for sentence, furi in [
            ("この問題は重要だ。", "この 問題[もんだい]は 重要[じゅうよう]だ。"),
            ("それは重要でした。", "それは 重要[じゅうよう]でした。"),
            ("重要に考える。", "重要[じゅうよう]に 考[かんが]える。"),
        ]:
            e = {"sentence": sentence, "surface": "重要", "furigana": furi, "gloss": "It matters."}
            assert examples.validate_entry(e, "重要な") is None, sentence

    def test_bare_stem_before_the_full_stop_is_rejected(self):
        e = {"sentence": "これが一番重要。", "surface": "重要", "furigana": "これが 一番[いちばん] 重要[じゅうよう]。",
             "gloss": "This matters most."}
        reason = examples.validate_entry(e, "重要な")
        assert reason and "な-adjective" in reason

    def test_noun_followed_by_something_else_is_rejected(self):
        e = {"sentence": "重要書類を送る。", "surface": "重要", "furigana": "重要[じゅうよう] 書類[しょるい]を 送[おく]る。",
             "gloss": "Send the papers."}
        assert examples.validate_entry(e, "重要な")

    def test_plain_and_hiragana_headwords_are_not_form_checked(self):
        assert examples._form_reason("嬉しい", "嬉しい", "嬉しい。") is None
        assert examples._form_reason("きれいな", "きれい", "きれい。") is None
        assert examples._form_reason("する", "し", "し。") is None

    def test_prompt_states_the_rule(self):
        from app.config import EXAMPLE_SENTENCES_PROMPT as p

        assert "used as a verb" in p and "操作が簡単だ" in p and "重要だ" in p


# ---------- 4. audio ----------


SAY_LIST = (
    "Eddy (Japanese (Japan)) ja_JP    # こんにちは！\n"
    "Kyoko               ja_JP    # こんにちは、私の名前はKyokoです。\n"
    "Samantha            en_US    # Hello!\n"
)


class FakeSay:
    """Replaces subprocess.run inside tts: records argv, writes a fake AAC file."""

    def __init__(self, size: int = 5000, returncode: int = 0):
        self.calls: list[list[str]] = []
        self.inputs: list[str] = []
        self.size, self.returncode = size, returncode

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        out = args[args.index("-o") + 1]
        self.inputs.append(Path(args[args.index("-f") + 1]).read_text(encoding="utf-8"))
        assert kw.get("timeout")
        assert kw.get("shell") in (None, False)
        Path(out).write_bytes(b"\0" * self.size)
        return subprocess.CompletedProcess(args, self.returncode, b"", b"boom" if self.returncode else b"")


@pytest.fixture
def say(monkeypatch, isolated_data_dir):
    fake = FakeSay()
    tts.reset_cache()
    monkeypatch.setattr(tts.sys, "platform", "darwin")
    monkeypatch.setattr(tts.shutil, "which", lambda n: "/usr/bin/say")
    monkeypatch.setattr(tts, "_voices_output", lambda: SAY_LIST)
    monkeypatch.setattr(tts.subprocess, "run", fake)
    yield fake
    tts.reset_cache()


class TestTtsAvailability:
    def test_available_when_voice_listed(self, say):
        assert tts.is_available() is True

    def test_not_macos(self, say, monkeypatch):
        monkeypatch.setattr(tts.sys, "platform", "linux")
        tts.reset_cache()
        assert tts.is_available() is False

    def test_say_missing(self, say, monkeypatch):
        monkeypatch.setattr(tts.shutil, "which", lambda n: None)
        tts.reset_cache()
        assert tts.is_available() is False

    def test_voice_missing(self, say, monkeypatch):
        monkeypatch.setenv("STUDIOUS_TTS_VOICE", "Otoya")
        from app import config

        config.get_settings.cache_clear()
        assert tts.voice() == "Otoya" and tts.is_available() is False

    def test_voice_listing_parse(self):
        assert tts.voice_listed(SAY_LIST, "Kyoko")
        assert tts.voice_listed(SAY_LIST, "eddy")  # "Eddy (Japanese (Japan))"
        assert not tts.voice_listed(SAY_LIST, "Ky")
        assert not tts.voice_listed("", "Kyoko")

    def test_answer_is_cached(self, say, monkeypatch):
        calls = []
        monkeypatch.setattr(tts, "_voices_output", lambda: calls.append(1) or SAY_LIST)
        tts.reset_cache()
        tts.is_available(), tts.is_available()
        assert len(calls) == 1

    def test_probe_failure_means_unavailable(self, say, monkeypatch):
        def boom():
            raise OSError("no")

        monkeypatch.setattr(tts, "_voices_output", boom)
        tts.reset_cache()
        assert tts.is_available() is False

    def test_defaults(self, isolated_data_dir, monkeypatch):
        from app import config

        monkeypatch.delenv("STUDIOUS_TTS_VOICE", raising=False)
        monkeypatch.delenv("ANKI_PUSH_AUDIO", raising=False)
        config.get_settings.cache_clear()
        s = config.get_settings()
        assert s.tts_voice == "Kyoko" and s.anki_push_audio is True
        monkeypatch.setenv("ANKI_PUSH_AUDIO", "false")
        config.get_settings.cache_clear()
        assert config.get_settings().anki_push_audio is False


class TestSynthesize:
    def test_exact_argument_list_and_cache_path(self, say, isolated_data_dir):
        path = tts.synthesize("やっとチケットを手に入れた。")
        (args,) = say.calls
        assert args[:2] == ["say", "-v"] and args[2] == "Kyoko"
        assert args[3:5] == ["--file-format=m4af", "--data-format=aac"]
        assert args[5] == "-o" and args[7] == "-f" and len(args) == 9
        assert say.inputs == ["やっとチケットを手に入れた。"]
        assert path.parent == isolated_data_dir / "audio" and path.suffix == ".m4a"
        assert path.stat().st_size == 5000
        assert not list(path.parent.glob("*.txt")) and len(list(path.parent.iterdir())) == 1

    def test_second_call_does_not_spawn(self, say):
        a = tts.synthesize("犬です。")
        b = tts.synthesize("犬です。")
        assert a == b and len(say.calls) == 1

    def test_hash_depends_on_voice_and_text(self, say, monkeypatch):
        from app import config

        a = tts.synthesize("犬")
        assert tts.synthesize("猫") != a
        monkeypatch.setenv("STUDIOUS_TTS_VOICE", "Eddy")
        config.get_settings.cache_clear()
        tts.reset_cache()
        assert tts.synthesize("犬") != a

    def test_small_file_is_a_failure_and_deleted(self, say, isolated_data_dir):
        say.size = 500
        with pytest.raises(tts.TtsError, match="no usable audio"):
            tts.synthesize("犬")
        assert list((isolated_data_dir / "audio").iterdir()) == []

    def test_nonzero_exit_fails(self, say, isolated_data_dir):
        say.returncode = 1
        with pytest.raises(tts.TtsError, match="exited with 1"):
            tts.synthesize("犬")
        assert list((isolated_data_dir / "audio").iterdir()) == []

    def test_timeout_fails(self, say, monkeypatch):
        def slow(args, **kw):
            raise subprocess.TimeoutExpired(args, 1)

        monkeypatch.setattr(tts.subprocess, "run", slow)
        with pytest.raises(tts.TtsError):
            tts.synthesize("犬")

    def test_text_starting_with_a_dash_is_never_an_argument(self, say):
        tts.synthesize("-v Eddy --version")
        (args,) = say.calls
        assert "-v Eddy --version" not in args and not any("Eddy" in a for a in args)
        assert say.inputs == ["-v Eddy --version"]

    def test_length_limits_and_empty(self, say):
        with pytest.raises(tts.TtsError, match="nothing"):
            tts.synthesize("  <b></b> ")
        with pytest.raises(tts.TtsError, match="limit"):
            tts.synthesize("あ" * 201)
        tts.synthesize("あ" * 200)
        assert len(say.calls) == 1

    def test_html_is_stripped(self, say):
        tts.synthesize("彼に会えて<b>嬉しかった</b>。")
        assert say.inputs == ["彼に会えて嬉しかった。"]

    def test_unavailable(self, isolated_data_dir):
        with pytest.raises(tts.TtsError, match="needs macOS"):
            tts.synthesize("犬")


GEN = {
    "sentence": "彼に会えて嬉しかった。", "surface": "嬉しかった",
    "furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった。", "gloss": "Glad.", "source": "generated",
}


def _addnotes(fake: FakePush):
    return next(p for a, p in fake.calls if a == "addNotes")["notes"]


class TestPushAudio:
    def test_spoken_texts(self):
        assert anki_push.speech_word("料理(する)") == "料理"
        assert anki_push.speech_word("重要（な）") == "重要"
        assert anki_push.speech_word("嬉しい") == "嬉しい"
        note = anki_push.build_note({"headword": "嬉しい", "reading": "うれしい", "example": GEN})
        assert note["word_text"] == "嬉しい" and note["sentence_text"] == "彼に会えて嬉しかった。"
        assert "<" not in note["sentence_text"] and "[" not in note["sentence_text"]

    def test_attach_audio_payload_shape(self, tmp_path):
        a, b = tmp_path / "aaa.m4a", tmp_path / "bbb.m4a"
        a.write_bytes(b"AAA")
        b.write_bytes(b"BBB")
        note = anki_push.attach_audio({"fields": {"Word Audio": ""}}, [("Word Audio", a), ("Sentence Audio", b)])
        assert note["audio"] == [
            {"filename": "studious_aaa.m4a", "data": base64.b64encode(b"AAA").decode(), "fields": ["Word Audio"]},
            {"filename": "studious_bbb.m4a", "data": base64.b64encode(b"BBB").decode(), "fields": ["Sentence Audio"]},
        ]
        assert note["fields"]["Word Audio"] == ""
        assert anki_push.attach_audio({"x": 1}, []) == {"x": 1}

    def test_send_attaches_clips_but_checks_without_them(self, isolated_data_dir, monkeypatch, say):
        ids = _seed(("犬", "猫"))
        store.update_item("vocab", ids[0], example=GEN)
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["audio"] == {"enabled": True, "attached": 3, "failed": 0, "reading_corrected": 0}  # 犬: word+sentence, 猫: word
        notes = _addnotes(fake)
        assert [a["fields"] for a in notes[0]["audio"]] == [["Word Audio"], ["Sentence Audio"]]
        assert [a["fields"] for a in notes[1]["audio"]] == [["Word Audio"]]
        assert notes[0]["audio"][0]["filename"].startswith("studious_") and notes[0]["audio"][0]["filename"].endswith(".m4a")
        assert notes[0]["fields"]["Word Audio"] == "" and notes[0]["fields"]["Sentence Audio"] == ""
        for a, p in fake.calls:
            if a.startswith("canAdd"):
                assert all("audio" not in n for n in p["notes"])
        assert not {"createDeck", "addNotes"} - set(fake.actions)
        assert set(fake.actions) <= {"modelNames", "modelFieldNames", "deckNames", "canAddNotesWithErrorDetail",
                                    "createDeck", "addNotes", "version", "findCards", "cardsInfo"}

    def test_one_failed_clip_does_not_block_the_send(self, isolated_data_dir, monkeypatch, say):
        _seed(("犬", "猫"))
        real = tts.synthesize

        def flaky(text, *a, **kw):
            if text == "犬":
                raise tts.TtsError("boom")
            return real(text, *a, **kw)

        monkeypatch.setattr(tts, "synthesize", flaky)
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["created"] == 2 and r["audio"] == {"enabled": True, "attached": 1, "failed": 1, "reading_corrected": 0}
        notes = _addnotes(fake)
        assert "audio" not in notes[0] and len(notes[1]["audio"]) == 1

    def test_audio_false_in_body(self, isolated_data_dir, monkeypatch, say):
        _seed(("犬",))
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True, "audio": False}).json()
        assert r["audio"]["enabled"] is False and say.calls == []
        assert "audio" not in _addnotes(fake)[0]

    def test_setting_off_is_the_default(self, isolated_data_dir, monkeypatch, say):
        from app import config

        monkeypatch.setenv("ANKI_PUSH_AUDIO", "0")
        config.get_settings.cache_clear()
        _seed(("犬",))
        fake = _use(monkeypatch)
        client.post("/api/anki/push", json={**BODY, "confirm": True})
        assert "audio" not in _addnotes(fake)[0] and say.calls == []
        client.post("/api/anki/push", json={**BODY, "confirm": True, "audio": True})

    def test_unavailable_voice_sends_without_audio(self, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert r["created"] == 1 and r["audio"] == {"enabled": False, "attached": 0, "failed": 0, "reading_corrected": 0}
        assert "audio" not in _addnotes(fake)[0]

    def test_preview_reports_audio_without_synthesizing(self, isolated_data_dir, monkeypatch, say):
        _seed(("犬",))
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["audio"] == {"enabled": True, "available": True, "voice": "Kyoko", "engine": "say", "reason": ""}
        assert say.calls == []
        assert all(not k.startswith("_") for k in d["items"][0])

    def test_preview_audio_unavailable(self, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        _use(monkeypatch)
        assert client.post("/api/anki/push/preview", json=BODY).json()["audio"]["available"] is False


class TestAudioEndpoints:
    def _item(self, **kw):
        return store.create_item("vocab", headword="嬉しい", reading="うれしい", meaning="glad")["id"]

    def test_status(self, say):
        st = client.get("/api/tts/status").json()
        assert st["available"] is True and st["voice"] == "Kyoko" and st["engine"] == "say" and st["reason"] == ""

    def test_status_unavailable(self, isolated_data_dir):
        assert client.get("/api/tts/status").json()["available"] is False

    def test_word_clip(self, say):
        item_id = self._item()
        r = client.get(f"/api/vocab/{item_id}/audio?part=word")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mp4" and len(r.content) == 5000
        assert say.inputs == ["嬉しい"]

    def test_sentence_clip_uses_the_stored_example(self, say):
        item_id = self._item()
        store.update_item("vocab", item_id, example=GEN)
        assert client.get(f"/api/vocab/{item_id}/audio?part=sentence").status_code == 200
        assert say.inputs == ["彼に会えて嬉しかった。"]

    def test_no_sentence_is_404(self, say):
        item_id = self._item()
        assert client.get(f"/api/vocab/{item_id}/audio?part=sentence").status_code == 404
        assert client.get("/api/vocab/nope/audio").status_code == 404
        assert say.calls == []

    def test_bad_part_is_400(self, say):
        assert client.get(f"/api/vocab/{self._item()}/audio?part=x").status_code == 400

    def test_unavailable_is_503(self, isolated_data_dir):
        r = client.get(f"/api/vocab/{self._item()}/audio?part=word")
        assert r.status_code == 503

    def test_synthesis_failure_is_503(self, say):
        say.size = 10
        assert client.get(f"/api/vocab/{self._item()}/audio?part=word").status_code == 503


def test_anki_write_allow_list_unchanged():
    assert frozenset({"createDeck", "addNotes"}) == anki_push.WRITE_ACTIONS


def test_data_audio_is_git_ignored():
    root = Path(__file__).resolve().parents[2]
    ignore = (root / ".gitignore").read_text().splitlines()
    assert "data/" in ignore  # covers data/audio/


def _unused(*_: Any) -> None:  # keep the import list honest for linters
    return None
