"""Dictionary linking: no reading-only mislinks, one-time re-enrichment of
existing items, and the textbook-context meaning (``meaning_context``)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import anki_push, enrich, examples, jmdict, refs_build, store
from tests.test_jmdict import _sense, _word

client = TestClient(app)


def w(wid: str, kanji: str | None, kana: str, gloss: str, pos: str = "n") -> dict:
    return _word(
        wid,
        [{"common": True, "text": kanji, "tags": []}] if kanji else None,
        [{"common": True, "text": kana, "tags": []}],
        [_sense([pos], [gloss])],
    )


# Homophone pairs: the wrong entry always has the lower sequence number.
WORDS = [
    w("1", "性交", "せいこう", "sexual intercourse"),
    w("2", "成功", "せいこう", "success", "vs"),
    w("3", "虫", "むし", "insect"),
    w("4", "無視", "むし", "disregard; ignore", "vs"),
    w("5", "官吏", "かんり", "government official"),
    w("6", "管理", "かんり", "control; management", "vs"),
    w("7", "帰る", "かえる", "to return home", "v5r"),
    w("8", "買う", "かう", "to buy", "v5u"),
    w("9", "硬度", "こうど", "hardness"),
    w("10", "高度", "こうど", "altitude; sophisticated", "adj-na"),
    w("11", "感嘆", "かんたん", "admiration"),
    w("12", "簡単", "かんたん", "simple", "adj-na"),
    w("13", "洗濯", "せんたく", "laundry"),
    w("14", "選択", "せんたく", "choice", "vs"),
    w("15", "師事", "しじ", "to study under"),
    w("16", "志望", "しぼう", "wish; aspiration", "vs"),
    w("17", "及ぶ", "およぶ", "to extend; to reach", "v5b"),
    w("18", "及ぼす", "およぼす", "to exert", "v5s"),
    w("19", "当てはまる", "あてはまる", "to apply", "v5r"),
    w("20", "責任を果たす", "せきにんをはたす", "to fulfil one's responsibility", "exp"),
    w("21", "身に付く", "みにつく", "to be acquired", "exp"),
    w("22", "病", "やまい", "illness"),
    w("23", "暴飲暴食", "ぼういんぼうしょく", "gluttony", "n"),
    w("24", "二週間", "にしゅうかん", "two weeks"),
    w("25", "子供の頃", "こどものころ", "childhood", "exp"),
    w("26", "突き当たる", "つきあたる", "to run into", "v5r"),
    w("27", "睡眠を取る", "すいみんをとる", "to sleep", "exp"),
    w("28", "上手く行く", "うまくいく", "to go well", "exp"),
    w("29", "目の敵にする", "めのかたきにする", "to be hostile to", "exp"),
    w("30", "取り入れる", "とりいれる", "to adopt", "v1"),
    w("31", "飛び越える", "とびこえる", "to jump over", "v1"),
    w("32", "美しい", "うつくしい", "beautiful", "adj-i"),
    w("33", "受け手", "うけて", "recipient"),
]


@pytest.fixture
def db(isolated_data_dir: Path, tmp_path: Path) -> Path:
    src = tmp_path / "jmdict.json"
    src.write_text(json.dumps({"version": "t", "dictDate": "2026-01-01", "words": WORDS}), encoding="utf-8")
    csv = tmp_path / "n3.csv"
    csv.write_text("expression,reading,meaning,tags\n成功,せいこう,success,JLPT JLPT_3\n", encoding="utf-8")
    out = refs_build.jmdict_db_path()
    refs_build.build_sqlite(src, {3: csv}, out, version="t")
    jmdict.close()
    yield out
    jmdict.close()


def hit(surface: str, reading: str = ""):
    return jmdict.lookup(surface, reading)


class TestLookupNoMislinks:
    @pytest.mark.parametrize(
        "surface,reading,seq,match",
        [
            ("成功する", "せいこう", 2, "stem"),
            ("無視する", "むし", 4, "stem"),
            ("管理する", "かんり", 6, "stem"),
            ("高度な", "こうど", 10, "stem"),
            ("簡単な", "かんたん", 12, "stem"),
            ("管理(する)", "かんり", 6, "stem"),
            ("成功", "せいこう", 2, "surface"),
            ("③ 選択する", "せんたく", 14, "stem"),
            ("① 志望する", "しぼう", 16, "stem"),
            ("＊責任を果たす", "", 20, "marker"),
            ("*身に付く", "", 21, "marker"),
            ("a. 病", "やまい", 22, "marker"),
            ("c. 暴飲暴食", "", 23, "marker"),
            ("〜に及ぶ", "およぶ", 17, "pattern"),
            ("〜を及ぼす", "およぼす", 18, "pattern"),
            ("~に当てはまる", "あてはまる", 19, "pattern"),
        ],
    )
    def test_correct_entry_and_how_it_matched(self, db, surface, reading, seq, match):
        h = hit(surface, reading)
        assert h is not None and h["seq"] == seq and h["match"] == match

    @pytest.mark.parametrize(
        "surface,reading,seq",
        [
            ("2週間", "にしゅうかん", 24),
            ("子供のころ", "こどものころ", 25),
            ("つき当る", "つきあたる", 26),
            ("睡眠をとる", "すいみんをとる", 27),
            ("上手くいく", "うまくいく", 28),
            ("とび越える", "とびこえる", 31),
        ],
    )
    def test_legitimate_variants_still_found_by_reading(self, db, surface, reading, seq):
        h = hit(surface, reading)
        assert h is not None and h["seq"] == seq and h["match"] == "reading"

    @pytest.mark.parametrize(
        "surface,reading",
        [
            ("買える", "かえる"),  # not 帰る
            ("採り入れる", "とりいれる"),  # 採 is not 取
            ("目の仇にする", "めのかたきにする"),  # 仇 is not 敵
        ],
    )
    def test_implausible_reading_hits_are_rejected(self, db, surface, reading):
        assert hit(surface, reading) is None

    def test_homophone_never_wins_without_a_matching_kanji(self, db):
        # 性交 / 虫 / 官吏 would have won on the reading alone.
        for surface, reading in [("成功する", "せいこう"), ("無視する", "むし"), ("管理する", "かんり")]:
            assert hit(surface, reading)["gloss"] not in ("sexual intercourse", "insect", "government official")

    def test_kana_only_headword_still_falls_back_by_reading(self, db):
        h = hit("うつくしぃ", "うつくしい")
        assert h is not None and h["seq"] == 32 and h["match"] == "reading"

    def test_marker_only_surface_form_matches(self, db):
        h = hit("② 美しい", "うつくしい")
        assert h["seq"] == 32 and h["match"] in ("marker", "surface")

    def test_digit_directly_before_a_word_is_kept(self):
        assert store.strip_list_marker("2週間") == "2週間"
        assert store.strip_list_marker("② 2週間") == "2週間"

    def test_jlpt_uses_the_stem(self, db):
        assert jmdict.jlpt_level("成功する", "せいこう") == 3
        assert jmdict.jlpt_level("③ 成功", "せいこう") == 3


class TestMarkers:
    @pytest.mark.parametrize(
        "raw,clean",
        [
            ("③ 選択する", "選択する"),
            ("①志望する", "志望する"),
            ("＊責任を果たす", "責任を果たす"),
            ("*身に付く", "身に付く"),
            ("a. 病", "病"),
            ("c. 暴飲暴食", "暴飲暴食"),
            ("1. 食べる", "食べる"),
            ("(2) 食べる", "食べる"),
            ("• 食べる", "食べる"),
            ("食べる", "食べる"),
            ("a病", "a病"),
            ("〜に及ぶ", "〜に及ぶ"),
        ],
    )
    def test_strip_list_marker(self, raw, clean):
        assert store.strip_list_marker(raw) == clean


# ---------- re-enrichment ----------


def _wrong(headword, reading, wrong_seq, wrong_gloss, ctx, *, source="llm"):
    """An item as the old loose fallback left it."""
    item = store.create_item("vocab", headword=headword, reading=reading, meaning=ctx, meaning_source=source)
    store.update_item(
        "vocab", item["id"], jmdict_seq=wrong_seq, meaning=wrong_gloss, meaning_source="jmdict", pos=["n"],
        classifications={"jmdict_common": True, "jlpt": "N1"}, enriched_at="2026-01-01",
    )
    return item["id"]


def _line_count():
    return len(store.store_path("vocab").read_text(encoding="utf-8").splitlines())


class TestReenrich:
    def test_relinks_to_the_right_entry_and_keeps_context(self, db):
        i = _wrong("成功する", "せいこう", 1, "sexual intercourse", "to succeed")
        out = enrich.enrich_pending()
        got = store.get_item("vocab", i)
        assert out["attempted"] == 1
        assert got["jmdict_seq"] == 2
        assert got["meaning"] == "success" and got["meaning_source"] == "jmdict"
        assert got["meaning_context"] == "to succeed"
        assert got["enrich_version"] == enrich.ENRICH_VERSION
        assert got["classifications"]["jlpt"] == "N3"  # from the right entry, not the stale N1
        assert got["pos"] == ["vs"]

    def test_unlinks_and_restores_the_textbook_meaning(self, db):
        i = _wrong("買える", "かえる", 7, "to return home", "to be able to buy")
        enrich.enrich_pending()
        got = store.get_item("vocab", i)
        assert got["jmdict_seq"] is None and got["pos"] == []
        assert got["meaning"] == "to be able to buy" and got["meaning_source"] == "llm"
        assert "jlpt" not in got["classifications"] and "jmdict_common" not in got["classifications"]
        assert got["priority_group"] == 5

    def test_context_backfilled_from_history_with_a_later_user_edit(self, db):
        item = store.create_item("vocab", headword="買える", reading="かえる", meaning="llm sense")
        store.update_item("vocab", item["id"], meaning="owner sense", meaning_source="user")
        # enrichment of an older build overwrote it with a dictionary gloss
        store.update_item("vocab", item["id"], jmdict_seq=7, meaning="to return home", meaning_source="jmdict",
                          meaning_context=None, enriched_at="2026-01-01")
        assert store.meaning_history()[item["id"]] == ("owner sense", "user")
        enrich.enrich_pending()
        got = store.get_item("vocab", item["id"])
        assert got["meaning_context"] == "owner sense"
        assert got["meaning"] == "owner sense" and got["meaning_source"] == "user"

    def test_runs_once_and_skips_noop_writes(self, db):
        _wrong("成功する", "せいこう", 1, "sexual intercourse", "to succeed")
        _wrong("買える", "かえる", 7, "to return home", "to be able to buy")
        assert enrich.enrich_pending()["attempted"] == 2
        n = _line_count()
        assert enrich.enrich_pending()["attempted"] == 0
        assert _line_count() == n
        assert enrich.enrich_pending(force=True)["attempted"] == 2
        assert _line_count() == n  # nothing changed, so nothing appended

    def test_user_meaning_is_never_overwritten(self, db):
        item = store.create_item("vocab", headword="成功する", reading="せいこう", meaning="mine", meaning_source="user")
        enrich.enrich_pending()
        got = store.get_item("vocab", item["id"])
        assert got["meaning"] == "mine" and got["meaning_source"] == "user"
        assert got["meaning_context"] == "mine" and got["jmdict_seq"] == 2

    def test_new_item_keeps_context_when_enrichment_replaces_meaning(self, db):
        item = store.create_item("vocab", headword="成功", reading="せいこう", meaning="success (of a plan)")
        assert item["meaning_context"] == "success (of a plan)"
        enrich.enrich_pending()
        got = store.get_item("vocab", item["id"])
        assert got["meaning"] == "success" and got["meaning_context"] == "success (of a plan)"

    def test_summary_is_logged(self, db, caplog):
        _wrong("成功する", "せいこう", 1, "x", "to succeed")
        _wrong("買える", "かえる", 7, "x", "buy")
        keep = store.create_item("vocab", headword="管理", reading="かんり", meaning="manage")
        store.update_item("vocab", keep["id"], jmdict_seq=6, enriched_at="2026-01-01")
        with caplog.at_level("INFO", logger="studious.enrich"):
            enrich.enrich_pending()
        rec = next(r for r in caplog.records if r.getMessage() == "enrich_done")
        assert (rec.relinked, rec.unlinked, rec.unchanged) == (1, 1, 1)


class TestMeaningHistory:
    def test_single_pass_and_cached(self, isolated_data_dir, monkeypatch):
        a = store.create_item("vocab", headword="a", reading="", meaning="one")["id"]
        b = store.create_item("vocab", headword="b", reading="", meaning="two")["id"]
        store.update_item("vocab", a, meaning="gloss", meaning_source="jmdict")
        calls = []
        real = store._iter_lines
        monkeypatch.setattr(store, "_iter_lines", lambda p: calls.append(p) or real(p))
        h = store.meaning_history()
        assert h == {a: ("one", "llm"), b: ("two", "llm")}
        store.meaning_history()
        assert len(calls) == 1

    def test_patch_and_create_set_context(self, isolated_data_dir):
        r = client.post("/api/vocab", json={"headword": "犬", "reading": "いぬ", "meaning": "dog"}).json()
        assert r["meaning_context"] == "dog"
        r = client.patch(f"/api/vocab/{r['id']}", json={"meaning": "hound"}).json()
        assert r["meaning_source"] == "user" and r["meaning_context"] == "hound"


# ---------- card meaning and example prompt ----------


class TestCardMeaningPreference:
    def test_context_beats_the_dictionary_gloss(self):
        item = {"meaning": "satisfaction; pride; triumph", "meaning_source": "jmdict",
                "meaning_context": "good at; one's specialty"}
        assert anki_push.word_meaning(item) == "good at, one's specialty"

    def test_long_context_is_shortened(self):
        ctx = "; ".join([f"a fairly long gloss number {i}" for i in range(5)])
        out = anki_push.word_meaning({"meaning_context": ctx, "meaning": "x"})
        assert out == "a fairly long gloss number 0" and len(ctx.replace("; ", ", ")) > 60

    def test_exactly_sixty_is_kept_whole(self):
        ctx = "a" * 28 + "; " + "b" * 28  # joined: 28 + 2 + 28 = 58
        assert anki_push.word_meaning({"meaning_context": ctx}) == "a" * 28 + ", " + "b" * 28

    def test_without_context_the_old_rules_apply(self):
        assert anki_push.word_meaning({"meaning": "a; b; c; d", "meaning_source": "jmdict"}) == "a, b, c"
        assert anki_push.word_meaning({"meaning": "a; b; c; d", "meaning_source": "llm"}) == "a; b; c; d"
        assert anki_push.word_meaning({"meaning": "a; b", "meaning_source": "jmdict", "meaning_context": ""}) == "a, b"

    def test_note_uses_it(self):
        note = anki_push.build_note({"headword": "得意な", "reading": "とくいな", "meaning": "pride; triumph",
                                     "meaning_source": "jmdict", "meaning_context": "good at; one's specialty"})
        assert note["fields"]["Word Meaning"] == "good at, one's specialty"

    def test_example_prompt_uses_context(self):
        item = {"id": "i", "headword": "得意な", "reading": "とくいな", "meaning": "pride",
                "meaning_context": "good at", "pos": []}
        assert examples._word_payload(item)["meaning"] == "good at"
        assert examples._word_payload({**item, "meaning_context": ""})["meaning"] == "pride"
