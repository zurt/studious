from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import anki, jmdict, refs_build, store
from tests.test_jmdict import _sense, _word

client = TestClient(app)
# Captured at import, before conftest's autouse guard replaces anki._post.
REAL_POST = anki._post


def _card(cid, note, word, reading=None, *, deck="Kaishi 1.5k", model="Kaishi", type=2, queue=2,
          interval=30, word_name="Word", reading_name="Word Reading"):
    fields: dict[str, Any] = {word_name: {"value": word, "order": 0}}
    if reading is not None:
        fields[reading_name] = {"value": reading, "order": 1}
    return {"cardId": cid, "note": note, "deckName": deck, "modelName": model, "type": type,
            "queue": queue, "interval": interval, "due": 0, "reps": 1, "lapses": 0, "fields": fields}


class FakeAnki:
    def __init__(self, cards):
        self.cards = cards
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, action, params=None, *, timeout=0):
        self.calls.append((action, params or {}))
        if action == "version":
            return 6
        if action == "findCards":
            return [c["cardId"] for c in self.cards]
        if action == "cardsInfo":
            wanted = set(params["cards"])
            return [c for c in self.cards if c["cardId"] in wanted]
        raise AssertionError(f"unexpected (non-read) action {action}")


def _sync(monkeypatch, cards):
    fake = FakeAnki(cards)
    monkeypatch.setattr(anki, "_post", fake)
    anki.sync()
    return fake


def _snap_cards():
    return json.loads(anki.snapshot_path().read_text("utf-8"))["cards"]


class TestFields:
    def test_kaishi_names_and_html(self, isolated_data_dir, monkeypatch):
        _sync(monkeypatch, [_card(1, 10, "<b>勉強</b>&nbsp;", "べん<br>きょう ")])
        c = _snap_cards()[0]
        assert (c["word"], c["reading"], c["deck"], c["note_id"], c["card_id"]) == (
            "勉強", "べんきょう", "Kaishi 1.5k", 10, 1)
        assert anki.status()["note_types"]["Kaishi"] == {
            "word_field": "Word", "reading_field": "Word Reading"}

    def test_expression_reading_case_insensitive(self, isolated_data_dir, monkeypatch):
        _sync(monkeypatch, [_card(1, 10, "食べる", "たべる", model="Core", word_name="expression",
                                  reading_name="READING")])
        assert anki.status()["note_types"]["Core"] == {
            "word_field": "expression", "reading_field": "READING"}
        assert _snap_cards()[0]["reading"] == "たべる"

    def test_fallback_to_first_field_no_reading(self, isolated_data_dir, monkeypatch):
        card = _card(1, 10, "x", model="Odd")
        card["fields"] = {"Back": {"value": "meaning", "order": 1}, "Q": {"value": "犬", "order": 0}}
        _sync(monkeypatch, [card])
        assert anki.status()["note_types"]["Odd"] == {"word_field": "Q", "reading_field": None}
        c = _snap_cards()[0]
        assert (c["word"], c["reading"]) == ("犬", "")


class TestSkipAndState:
    def test_skip_rules(self, isolated_data_dir, monkeypatch):
        _sync(monkeypatch, [
            _card(1, 1, "<br> "),
            _card(2, 2, "あ" * 31),
            _card(3, 3, "あ" * 30),
        ])
        assert [c["card_id"] for c in _snap_cards()] == [3]

    def test_every_state(self, isolated_data_dir, monkeypatch):
        _sync(monkeypatch, [
            _card(1, 1, "a", type=0, queue=0, interval=0),
            _card(2, 2, "b", type=1, queue=1, interval=0),
            _card(3, 3, "c", type=3, queue=1, interval=0),
            _card(4, 4, "d", type=2, interval=20),
            _card(5, 5, "e", type=2, interval=21),
            _card(6, 6, "f", type=2, queue=-1, interval=100),
        ])
        states = {c["word"]: c["state"] for c in _snap_cards()}
        assert states == {"a": "new", "b": "learning", "c": "learning",
                          "d": "young", "e": "mature", "f": "suspended"}
        st = anki.status()
        assert st["counts"] == {"suspended": 1, "new": 1, "learning": 2, "young": 1, "mature": 1}
        assert st["total_cards"] == 6
        assert st["decks"]["Kaishi 1.5k"]["learning"] == 2

    def test_chunking_and_read_only(self, isolated_data_dir, monkeypatch):
        cards = [_card(i, i, f"語{i}") for i in range(1, 1202)]
        fake = _sync(monkeypatch, cards)
        assert [a for a, _ in fake.calls].count("cardsInfo") == 3
        assert {a for a, _ in fake.calls} <= {"version", "findCards", "cardsInfo"}
        assert len(_snap_cards()) == 1201


class TestFailures:
    def test_unreachable_keeps_old_snapshot(self, isolated_data_dir, monkeypatch):
        _sync(monkeypatch, [_card(1, 1, "犬", "いぬ")])
        before = anki.snapshot_path().read_text("utf-8")

        def down(action, params=None, *, timeout=0):
            raise anki.AnkiUnavailable("Anki is not reachable")

        monkeypatch.setattr(anki, "_post", down)
        with pytest.raises(anki.AnkiUnavailable):
            anki.sync()
        assert anki.snapshot_path().read_text("utf-8") == before

    def test_midway_failure_keeps_old_snapshot(self, isolated_data_dir, monkeypatch):
        _sync(monkeypatch, [_card(1, 1, "犬", "いぬ")])
        before = anki.snapshot_path().read_text("utf-8")
        fake = FakeAnki([_card(2, 2, "猫")])

        def flaky(action, params=None, *, timeout=0):
            if action == "cardsInfo":
                raise anki.AnkiUnavailable("boom")
            return fake(action, params)

        monkeypatch.setattr(anki, "_post", flaky)
        with pytest.raises(anki.AnkiUnavailable):
            anki.sync()
        assert anki.snapshot_path().read_text("utf-8") == before

    def test_transport_connection_refused_message(self, isolated_data_dir, monkeypatch):
        def refuse(*a, **k):
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(urllib.request, "urlopen", refuse)
        with pytest.raises(anki.AnkiUnavailable, match="Anki is not reachable at http://127.0.0.1:8765"):
            REAL_POST("version")

    def test_error_response(self, isolated_data_dir, monkeypatch):
        body = json.dumps({"result": None, "error": "bad query"}).encode()
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(body))
        with pytest.raises(anki.AnkiUnavailable, match="bad query"):
            REAL_POST("findCards", {"query": "x"})


class TestLookup:
    def _seed(self, monkeypatch):
        _sync(monkeypatch, [
            _card(1, 1, "食べる", "タベル", type=0, queue=0, interval=0),
            _card(2, 2, "食べる", "たべる", interval=40),
            _card(3, 3, "行く", "いく", type=1, queue=1, interval=0),
            _card(4, 4, "行く", "いく", queue=-1, interval=90),
        ])

    def test_exact_katakana_reading_and_most_advanced(self, isolated_data_dir, monkeypatch):
        self._seed(monkeypatch)
        r = anki.lookup("食べる", "タベル")
        assert r == {"state": "mature", "deck": "Kaishi 1.5k", "interval": 40, "match": "exact"}
        assert anki.lookup("行く", "いく")["state"] == "learning"

    def test_headword_fallback(self, isolated_data_dir, monkeypatch):
        self._seed(monkeypatch)
        r = anki.lookup("食べる", "ちがう")
        assert r["match"] == "headword" and r["state"] == "mature"
        assert anki.lookup("飲む", "のむ") is None

    def test_no_snapshot(self, isolated_data_dir):
        assert anki.lookup("犬", "いぬ") is None
        s = anki.status()
        assert s["has_snapshot"] is False and s["total_cards"] == 0

    def test_index_rebuilt_when_snapshot_changes(self, isolated_data_dir, monkeypatch):
        self._seed(monkeypatch)
        assert anki.lookup("犬", "いぬ") is None
        _sync(monkeypatch, [_card(9, 9, "犬", "いぬ")])
        assert anki.lookup("犬", "いぬ")["state"] == "mature"


ENTRY_WORDS = [
    _word("1", [{"common": True, "text": "嬉しい", "tags": []}],
          [{"common": True, "text": "うれしい", "tags": []}], [_sense(["adj-i"], ["happy"])]),
    _word("2", [{"common": True, "text": "漢字", "tags": []}],
          [{"common": True, "text": "かんじ", "tags": []}], [_sense(["n"], ["kanji"])]),
    _word("3", [{"common": True, "text": "感じ", "tags": []}],
          [{"common": True, "text": "かんじ", "tags": []}], [_sense(["n"], ["feeling"])]),
    _word("4", [{"common": True, "text": "ご飯", "tags": []}],
          [{"common": True, "text": "ごはん", "tags": []}], [_sense(["n"], ["rice"])]),
]


def _build_jmdict(tmp_path):
    src = tmp_path / "jm.json"
    src.write_text(json.dumps({"version": "t", "dictDate": "d", "words": ENTRY_WORDS}), encoding="utf-8")
    refs_build.build_sqlite(src, {}, refs_build.jmdict_db_path(), version="t")
    jmdict.close()


class TestEntryTier:
    def test_variant_spelling_matches_by_entry(self, isolated_data_dir, tmp_path, monkeypatch):
        _build_jmdict(tmp_path)
        _sync(monkeypatch, [_card(1, 1, "嬉しい", "うれしい"), _card(2, 2, "ご飯", "ごはん")])
        r = anki.lookup("うれしい", "うれしい", 1)
        assert r["match"] == "entry" and r["state"] == "mature"
        assert anki.lookup("ごはん", "ごはん", 4)["match"] == "entry"

    def test_same_reading_other_word_does_not_match(self, isolated_data_dir, tmp_path, monkeypatch):
        _build_jmdict(tmp_path)
        _sync(monkeypatch, [_card(1, 1, "感じ", "かんじ")])
        assert anki.lookup("漢字", "かんじ", 2) is None
        assert anki.lookup("感じ", "かんじ", 3)["match"] == "exact"

    def test_card_without_reading_or_unconfirmed_reading_is_not_resolved(
        self, isolated_data_dir, tmp_path, monkeypatch
    ):
        _build_jmdict(tmp_path)
        _sync(monkeypatch, [_card(1, 1, "嬉しい"), _card(2, 2, "漢字", "ちがう")])
        assert anki.lookup("うれしい", "うれしい", 1) is None
        assert anki.lookup("かんじ", "かんじ", 2) is None

    def test_unavailable_jmdict_skips_tier(self, isolated_data_dir, monkeypatch):
        jmdict.close()
        _sync(monkeypatch, [_card(1, 1, "嬉しい", "うれしい")])
        assert anki.lookup("うれしい", "うれしい", 1) is None
        assert anki.get_index()[1] == {}

    def test_tier_order_exact_then_entry_then_headword(self, isolated_data_dir, tmp_path, monkeypatch):
        _build_jmdict(tmp_path)
        _sync(monkeypatch, [
            _card(1, 1, "嬉しい", "うれしい", interval=5),
            _card(2, 2, "うれしい", "うれしい", interval=50),
        ])
        assert anki.lookup("うれしい", "うれしい", 1)["match"] == "exact"
        assert anki.lookup("嬉しい", "ちがう", 1)["match"] == "entry"
        assert anki.lookup("嬉しい", "ちがう", None)["match"] == "headword"

    def test_index_picks_up_jmdict_built_later(self, isolated_data_dir, tmp_path, monkeypatch):
        jmdict.close()
        _sync(monkeypatch, [_card(1, 1, "嬉しい", "うれしい")])
        assert anki.lookup("うれしい", "うれしい", 1) is None
        _build_jmdict(tmp_path)
        assert anki.lookup("うれしい", "うれしい", 1)["match"] == "entry"


class TestApi:
    def _vocab(self, headword, reading):
        store.replace_region_sightings(
            "vocab", doc_id="d1", chapter_id="c1", region_id=f"r-{headword}", source="breakdown",
            entries=[{"headword": headword, "reading": reading, "meaning": "m", "sentence_index": 0,
                      "surface": headword, "sentence_text": headword}])

    def test_status_before_sync(self, isolated_data_dir):
        r = client.get("/api/refs/anki/status")
        assert r.status_code == 200 and r.json()["has_snapshot"] is False

    def test_sync_503_message(self, isolated_data_dir):
        # The autouse guard makes the transport raise AnkiUnavailable.
        r = client.post("/api/refs/anki/sync")
        assert r.status_code == 503
        assert r.json()["detail"]

    def test_sync_success_and_filters(self, isolated_data_dir, monkeypatch):
        for hw, rd in [("食べる", "たべる"), ("行く", "いく"), ("飲む", "のむ"), ("見る", "みる")]:
            self._vocab(hw, rd)
        monkeypatch.setattr(anki, "_post", FakeAnki([
            _card(1, 1, "食べる", "たべる", interval=40),
            _card(2, 2, "行く", "いく", type=0, queue=0, interval=0),
            _card(3, 3, "見る", "ちがう", interval=5),
        ]))
        r = client.post("/api/refs/anki/sync")
        assert r.status_code == 200
        body = r.json()
        assert body["total_cards"] == 3 and body["matched"] == 3
        assert client.get("/api/refs/anki/status").json()["total_cards"] == 3

        items = {i["headword"]: i for i in client.get("/api/vocab").json()["items"]}
        assert items["食べる"]["anki"]["state"] == "mature"
        assert items["見る"]["anki"]["match"] == "headword"
        assert items["飲む"]["anki"] is None

        def heads(q):
            d = client.get(f"/api/vocab?anki={q}").json()
            return d["total"], {i["headword"] for i in d["items"]}

        assert heads("any") == (3, {"食べる", "行く", "見る"})
        assert heads("none") == (1, {"飲む"})
        assert heads("mature") == (1, {"食べる"})
        assert heads("young") == (1, {"見る"})
        assert heads("new") == (1, {"行く"})
        assert heads("learning") == (0, set())
        assert heads("suspended") == (0, set())
        paged = client.get("/api/vocab?anki=any&limit=2&offset=2").json()
        assert paged["total"] == 3 and len(paged["items"]) == 1

    def test_sync_matched_counts_entry_matches(self, isolated_data_dir, tmp_path, monkeypatch):
        _build_jmdict(tmp_path)
        self._vocab("うれしい", "うれしい")
        store.update_item("vocab", store.list_items("vocab")[0]["id"], jmdict_seq=1)
        monkeypatch.setattr(anki, "_post", FakeAnki([_card(1, 1, "嬉しい", "うれしい")]))
        assert client.post("/api/refs/anki/sync").json()["matched"] == 1
        item = client.get("/api/vocab?anki=any").json()["items"][0]
        assert item["anki"]["match"] == "entry"

    def test_invalid_filter(self, isolated_data_dir):
        assert client.get("/api/vocab?anki=bogus").status_code == 400

    def test_store_file_not_modified(self, isolated_data_dir, monkeypatch):
        self._vocab("食べる", "たべる")
        before = store.store_path("vocab").read_text("utf-8")
        monkeypatch.setattr(anki, "_post", FakeAnki([_card(1, 1, "食べる", "たべる")]))
        client.post("/api/refs/anki/sync")
        client.get("/api/vocab")
        assert store.store_path("vocab").read_text("utf-8") == before
