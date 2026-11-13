from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import anki, anki_push, storage, store

client = TestClient(app)

DOC, CH = "doc1", "ch1"


# ---------- furigana ----------


class TestFurigana:
    @pytest.mark.parametrize(
        "word,reading,expected",
        [
            ("嬉しい", "うれしい", "嬉[うれ]しい"),
            ("手に入れる", "てにいれる", "手[て]に 入[い]れる"),
            ("追いかける", "おいかける", "追[お]いかける"),
            ("お客さん", "おきゃくさん", "お 客[きゃく]さん"),
            ("ひらがな", "ひらがな", "ひらがな"),
            ("コーヒー", "こーひー", "コーヒー"),
            ("勉強", "べんきょう", "勉強[べんきょう]"),
            ("食べ物", "たべもの", "食[た]べ 物[もの]"),
            ("人々", "ひとびと", "人々[ひとびと]"),
            ("ガス管", "がすかん", "ガス 管[かん]"),
        ],
    )
    def test_examples(self, word, reading, expected):
        assert anki_push.furigana(word, reading) == expected

    def test_empty_reading_returns_word(self):
        assert anki_push.furigana("勉強", "") == "勉強"

    def test_empty_word(self):
        assert anki_push.furigana("", "あ") == ""

    def test_reading_shorter_than_kana_falls_back(self):
        assert anki_push.furigana("嬉しい", "うれ") == "嬉[うれ]しい"

    def test_kana_mismatch_falls_back(self):
        assert anki_push.furigana("嬉しい", "うれしく") == "嬉[うれしく]しい"

    def test_ambiguous_alignment_falls_back(self):
        # The middle に can sit at several places, so there is no single alignment.
        assert anki_push.furigana("日に日", "ににににに") == "日に日[ににににに]"
        assert anki_push.furigana("日に日", "ににに") == "日[に]に 日[に]"

    def test_digits_and_latin_stay_in_the_unaligned_run(self):
        assert anki_push.furigana("3日", "みっか") == "3日[みっか]"
        assert anki_push.furigana("Tシャツ", "てぃーしゃつ") == "T[てぃー]シャツ"

    def test_katakana_folded_when_comparing(self):
        assert anki_push.furigana("食べる", "タベル") == "食[タ]べる"

    def test_never_raises(self):
        for w, r in [(None, None), ("x", None), (None, "x"), ("\u0000", "\u0000")]:
            assert isinstance(anki_push.furigana(w, r), str)  # type: ignore[arg-type]


class TestSuffixGroup:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("料理(する)", "料理"),
            ("料理（する）", "料理"),
            ("静か(な)", "静か"),
            ("静か（な）", "静か"),
            ("勉強する", "勉強する"),
            ("静かな", "静かな"),
            ("料理", "料理"),
        ],
    )
    def test_strip(self, text, expected):
        assert anki_push.strip_suffix_group(text) == expected


# ---------- sentence html ----------


class TestSentenceHtml:
    def test_bold_first_occurrence_only(self):
        assert anki_push.sentence_html("嬉しい嬉しい", "嬉しい") == "<b>嬉しい</b>嬉しい"

    def test_escapes_everything(self):
        out = anki_push.sentence_html("a<b>&c 嬉しい", "嬉しい")
        assert out == "a&lt;b&gt;&amp;c <b>嬉しい</b>"

    def test_surface_with_html_chars_is_escaped(self):
        assert anki_push.sentence_html("x<y", "<") == "x<b>&lt;</b>y"

    def test_surface_missing_falls_back_to_headword_then_plain(self):
        assert anki_push.sentence_html("嬉しい。", "ない", "嬉しい") == "<b>嬉しい</b>。"
        assert anki_push.sentence_html("嬉しい。", "ない") == "嬉しい。"


# ---------- note building ----------


@pytest.fixture
def textbook(isolated_data_dir: Path):
    """A real document + chapter with a breakdown, so notes and glosses resolve."""
    pdf = isolated_data_dir / "x.pdf"
    pdf.write_bytes(b"")
    doc = storage.create_document(name="Genki <I>", source_type="pdf", page_count=3, original_path=pdf)
    chapter = storage.create_chapter(doc["id"], title="第14課", page_start=1, page_end=3)
    return doc["id"], chapter["id"]


class TestBuildNote:
    def test_field_completeness_and_values(self, textbook):
        doc, ch = textbook
        item = {
            "headword": "嬉しい",
            "reading": "うれしい",
            "meaning": "happy, glad",
            "notes": "line1\nline2",
            "classifications": {"freq_rank": 355},
            "example": {
                "source": "generated",
                "sentence": "彼に会えて嬉しかった。",
                "surface": "嬉しかった",
                "furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった。",
                "gloss": "I was glad to meet him.",
            },
        }
        note = anki_push.build_note(item, doc, ch)
        f = note["fields"]
        assert tuple(f) == anki_push.KAISHI_FIELDS
        assert f["Word"] == "嬉しい" and f["Word Reading"] == "うれしい"
        assert f["Word Meaning"] == "happy, glad"
        assert f["Word Furigana"] == "嬉[うれ]しい"
        assert f["Sentence"] == "彼に会えて<b>嬉しかった</b>。"
        assert f["Sentence Furigana"] == "彼[かれ]に 会[あ]えて<b>嬉[うれ]しかった</b>。"
        assert f["Sentence Meaning"] == "I was glad to meet him."
        assert f["Notes"] == "line1<br>line2"
        assert f["Frequency"] == "355"
        for empty in ("Word Audio", "Sentence Audio", "Pitch Accent", "Pitch Accent Notes", "Picture"):
            assert f[empty] == ""
        assert note["tags"] == ["studious", f"studious::{doc}::{ch}"]
        assert note["has_sentence"] is True



    def test_no_sentence(self, textbook):
        doc, ch = textbook
        note = anki_push.build_note({"headword": "犬", "reading": "いぬ", "meaning": "dog"}, doc, ch)
        f = note["fields"]
        assert (f["Sentence"], f["Sentence Furigana"], f["Sentence Meaning"]) == ("", "", "")
        assert f["Notes"] == ""
        assert f["Frequency"] == ""
        assert note["has_sentence"] is False

    def test_suffix_group_stripped_and_escaped(self, textbook):
        doc, ch = textbook
        item = {"headword": "料理(する)", "reading": "りょうり(する)", "meaning": "cook <1> & more"}
        f = anki_push.build_note(item, doc, ch)["fields"]
        assert f["Word"] == "料理" and f["Word Reading"] == "りょうり"
        assert f["Word Furigana"] == "料理[りょうり]"
        assert f["Word Meaning"] == "cook &lt;1&gt; &amp; more"

    def test_html_in_headword_escaped(self, textbook):
        doc, ch = textbook
        f = anki_push.build_note({"headword": "a<b", "reading": "x&y"}, doc, ch)["fields"]
        assert f["Word"] == "a&lt;b" and f["Word Reading"] == "x&amp;y"
        assert "<b" not in f["Word Furigana"].replace("&lt;b", "")

    def test_unknown_document_still_builds(self, isolated_data_dir):
        f = anki_push.build_note({"headword": "犬", "reading": "いぬ"}, "nodoc", "noch")["fields"]
        assert f["Notes"] == ""

    def test_no_context_means_no_chapter_tag(self, isolated_data_dir):
        assert anki_push.build_note({"headword": "犬", "reading": "いぬ"})["tags"] == ["studious"]


# ---------- fake AnkiConnect ----------


class FakePush:
    def __init__(self, *, models=("Kaishi 1.5k",), fields=anki_push.KAISHI_FIELDS, decks=("Default",),
                 duplicates=(), detail=True, add_results=None, sync_fails=False):
        self.models = list(models)
        self.fields = list(fields)
        self.decks = list(decks)
        self.duplicates = set(duplicates)
        self.detail = detail
        self.add_results = add_results
        self.sync_fails = sync_fails
        self.calls: list[tuple[str, dict]] = []
        self.hold: threading.Event | None = None
        self.entered = threading.Event()

    @property
    def actions(self):
        return [a for a, _ in self.calls]

    def __call__(self, action, params=None, *, timeout=0):
        params = params or {}
        self.calls.append((action, params))
        if action == "modelNames":
            return self.models
        if action == "modelFieldNames":
            return self.fields
        if action == "deckNames":
            return self.decks
        if action == "canAddNotesWithErrorDetail":
            if not self.detail:
                raise anki.AnkiUnavailable("AnkiConnect error on canAddNotesWithErrorDetail: unsupported action")
            out = []
            for n in params["notes"]:
                if n["deckName"] not in self.decks:
                    out.append({"canAdd": False, "error": f"deck was not found: {n['deckName']}"})
                elif n["fields"]["Word"] in self.duplicates:
                    out.append({"canAdd": False, "error": "cannot create note because it is a duplicate"})
                else:
                    out.append({"canAdd": True})
            return out
        if action == "canAddNotes":
            return [n["deckName"] in self.decks and n["fields"]["Word"] not in self.duplicates
                    for n in params["notes"]]
        if action == "createDeck":
            if params["deck"] not in self.decks:
                self.decks.append(params["deck"])
            return 1
        if action == "addNotes":
            self.entered.set()
            if self.hold:
                self.hold.wait(5)
            if self.add_results is not None:
                return self.add_results
            return [1000 + i for i, _ in enumerate(params["notes"])]
        if action in ("version", "findCards", "cardsInfo"):
            if self.sync_fails:
                raise anki.AnkiUnavailable("Anki went away")
            return 6 if action == "version" else []
        raise AssertionError(f"unexpected action {action}")


def _seed(headwords=("犬", "猫", "鳥"), *, with_sentence=False):
    """Candidates for DOC/CH, ranked in the order given."""
    ids = []
    for rank, hw in enumerate(headwords, start=1):
        item = store.create_item("vocab", headword=hw, reading=hw, meaning=f"m-{hw}")
        sightings = [{"doc_id": DOC, "chapter_id": CH, "region_id": "r", "sentence_index": 0,
                      "surface": hw, "sentence_text": f"{hw}がいる。", "source": "breakdown"}]
        extra = {}
        if with_sentence:  # a stored generated example
            extra["example"] = {"source": "generated", "sentence": f"{hw}がいる。", "surface": hw,
                                "furigana": f"{hw}がいる。", "gloss": "There is one."}
        store.update_item("vocab", item["id"], jmdict_seq=rank, pos=["n"], sightings=sightings,
                          classifications={"freq_rank": rank * 100}, **extra)
        ids.append(item["id"])
    return ids


def _use(monkeypatch, **kw) -> FakePush:
    fake = FakePush(**kw)
    monkeypatch.setattr(anki, "_post", fake)
    return fake


BODY = {"doc_id": DOC, "chapter_id": CH}
WRITES = {"createDeck", "addNotes"}


# ---------- preview ----------


class TestPreview:
    def test_reads_only_and_shape(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push/preview", json=BODY)
        assert r.status_code == 200
        d = r.json()
        assert not WRITES & set(fake.actions)
        assert d["deck"] == "Studious" and d["note_type"] == "Kaishi 1.5k"
        assert d["deck_exists"] is False and d["will_create_deck"] is True
        assert d["counts"] == {"candidates": 3, "will_add": 3, "skipped": 0, "without_sentence": 3,
                               "headword_match": 0, "with_sentence": 0, "with_gloss": 0,
                               "needs_example": 3, "needs_example_ids": [i["id"] for i in d["items"]]}
        assert [i["headword"] for i in d["items"]] == ["犬", "猫", "鳥"]
        first = d["items"][0]
        assert set(first) >= {"id", "headword", "reading", "fields", "has_sentence", "can_add", "reason",
                              "headword_match"}
        detail_call = next(p for a, p in fake.calls if a == "canAddNotesWithErrorDetail")
        assert detail_call["notes"][0]["options"] == {"allowDuplicate": False, "duplicateScope": "collection"}
        # the deck does not exist yet, so the check uses one that does
        assert detail_call["notes"][0]["deckName"] == "Default"

    def test_deck_exists(self, isolated_data_dir, monkeypatch):
        _seed()
        _use(monkeypatch, decks=("Default", "Studious"))
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["deck_exists"] is True and d["will_create_deck"] is False

    def test_note_type_missing(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch, models=("Basic",))
        r = client.post("/api/anki/push/preview", json=BODY)
        assert r.status_code == 409
        assert "Kaishi 1.5k" in r.json()["detail"]
        assert not WRITES & set(fake.actions)

    def test_field_missing(self, isolated_data_dir, monkeypatch):
        _seed()
        _use(monkeypatch, fields=[f for f in anki_push.KAISHI_FIELDS if f != "Sentence Furigana"])
        r = client.post("/api/anki/push/preview", json=BODY)
        assert r.status_code == 409
        assert "Sentence Furigana" in r.json()["detail"] and "Kaishi 1.5k" in r.json()["detail"]

    def test_duplicates_reported(self, isolated_data_dir, monkeypatch):
        _seed()
        _use(monkeypatch, duplicates=("猫",))
        d = client.post("/api/anki/push/preview", json=BODY).json()
        cat = d["items"][1]
        assert cat["can_add"] is False and "duplicate" in cat["reason"]
        assert d["counts"]["will_add"] == 2 and d["counts"]["skipped"] == 1

    def test_fallback_to_can_add_notes(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch, detail=False, duplicates=("猫",))
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert "canAddNotes" in fake.actions
        assert [i["can_add"] for i in d["items"]] == [True, False, True]
        assert d["items"][1]["reason"]

    def test_other_errors_are_not_swallowed_by_the_fallback(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch)

        def boom(action, params=None, *, timeout=0):
            if action == "canAddNotesWithErrorDetail":
                raise anki.AnkiUnavailable("AnkiConnect error on x: collection is not available")
            return fake(action, params)

        monkeypatch.setattr(anki, "_post", boom)
        assert client.post("/api/anki/push/preview", json=BODY).status_code == 503

    def test_unreachable_is_503(self, isolated_data_dir):
        _seed()
        r = client.post("/api/anki/push/preview", json=BODY)  # conftest guard raises AnkiUnavailable
        assert r.status_code == 503 and "AnkiConnect" in r.json()["detail"]

    def test_limit_and_validation(self, isolated_data_dir, monkeypatch):
        _seed()
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json={**BODY, "limit": 2}).json()
        assert [i["headword"] for i in d["items"]] == ["犬", "猫"]
        assert client.post("/api/anki/push/preview", json={**BODY, "limit": 0}).status_code == 422
        assert client.post("/api/anki/push/preview", json={**BODY, "limit": 501}).status_code == 422
        assert client.post("/api/anki/push/preview", json={"doc_id": DOC}).status_code == 422

    def test_source_restricts_and_is_validated(self, isolated_data_dir, monkeypatch):
        _seed()  # 犬 猫 鳥: breakdown sightings
        ids = _seed(("馬",))
        store.update_item("vocab", ids[0], sightings=[{
            "doc_id": DOC, "chapter_id": CH, "region_id": "v", "sentence_index": 0,
            "surface": "馬", "sentence_text": "", "source": "vocab_list"}])
        _use(monkeypatch)
        listed = client.post("/api/anki/push/preview", json={**BODY, "source": "vocab_list"}).json()
        assert [i["headword"] for i in listed["items"]] == ["馬"]
        assert [i["headword"] for i in anki_push.select_items(DOC, CH, 10, "vocab_list")] == ["馬"]
        everything = client.post("/api/anki/push/preview", json=BODY).json()
        assert len(everything["items"]) == 4
        assert len(anki_push.select_items(DOC, CH, 10)) == 4
        for path, extra in (("/preview", {}), ("", {"confirm": True})):
            r = client.post(f"/api/anki/push{path}", json={**BODY, "source": "bogus", **extra})
            assert r.status_code == 422

    def test_headword_match_flag(self, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        monkeypatch.setattr(anki, "lookup", lambda *a, **k: {"state": "mature", "deck": "K", "interval": 9,
                                                              "match": "headword"})
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["items"][0]["headword_match"] is True and d["items"][0]["can_add"] is True
        assert d["counts"]["headword_match"] == 1

    def test_in_batch_duplicate_spelling_flagged(self, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        item = store.create_item("vocab", headword="犬", reading="けん", meaning="dog (counter)")
        store.update_item("vocab", item["id"], jmdict_seq=9, pos=["n"],
                          sightings=[{"doc_id": DOC, "chapter_id": CH, "source": "vocab_list"}])
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert sorted(i["can_add"] for i in d["items"]) == [False, True]

    def test_sentence_counts(self, isolated_data_dir, monkeypatch):
        _seed(("犬", "猫"), with_sentence=True)
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["counts"]["without_sentence"] == 0
        assert all(i["has_sentence"] for i in d["items"])


# ---------- push ----------


class TestPush:
    def test_confirm_required(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch)
        for body in (BODY, {**BODY, "confirm": False}, {**BODY, "confirm": "true"}, {**BODY, "confirm": 1}):
            assert client.post("/api/anki/push", json=body).status_code == 400
        assert fake.calls == []

    def test_sends_in_shortlist_order_and_marks_active(self, isolated_data_dir, monkeypatch):
        ids = _seed(("犬", "猫", "鳥"), with_sentence=True)
        fake = _use(monkeypatch)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["created"] == 3 and d["skipped"] == [] and d["failed"] == []
        assert d["deck"] == "Studious" and d["deck_created"] is True and d["sync_ok"] is True
        add = next(p for a, p in fake.calls if a == "addNotes")
        assert [n["fields"]["Word"] for n in add["notes"]] == ["犬", "猫", "鳥"]
        for n in add["notes"]:
            assert n["deckName"] == "Studious" and n["modelName"] == "Kaishi 1.5k"
            assert n["tags"][0] == "studious"
            assert n["options"] == {"allowDuplicate": False, "duplicateScope": "collection"}
        assert fake.actions.index("createDeck") < fake.actions.index("addNotes")
        assert set(fake.actions) & WRITES == WRITES
        assert {a for a in fake.actions} <= WRITES | {
            "modelNames", "modelFieldNames", "deckNames", "canAddNotesWithErrorDetail",
            "version", "findCards", "cardsInfo"}
        assert [store.get_item("vocab", i)["status"] for i in ids] == ["active"] * 3

    def test_existing_deck_not_reported_created(self, isolated_data_dir, monkeypatch):
        _seed()
        _use(monkeypatch, decks=("Studious",))
        d = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert d["deck_created"] is False

    def test_skipped_duplicates_and_partial_failure(self, isolated_data_dir, monkeypatch):
        ids = _seed(("犬", "猫", "鳥", "馬"))
        _use(monkeypatch, duplicates=("猫",), add_results=[501, None, 503])
        d = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert d["created"] == 2
        assert [s["headword"] for s in d["skipped"]] == ["猫"]
        assert "duplicate" in d["skipped"][0]["reason"]
        assert [f["headword"] for f in d["failed"]] == ["鳥"]
        status = {hw: store.get_item("vocab", i)["status"] for hw, i in zip(("犬", "猫", "鳥", "馬"), ids, strict=True)}
        assert status == {"犬": "active", "猫": "unreviewed", "鳥": "unreviewed", "馬": "active"}

    def test_sync_failure_is_reported_not_fatal(self, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        fake = _use(monkeypatch)
        # sync() calls version first; make it fail only after the send.
        real = fake.__call__

        def flaky(action, params=None, *, timeout=0):
            if action == "version":
                raise anki.AnkiUnavailable("Anki went away")
            return real(action, params, timeout=timeout)

        monkeypatch.setattr(anki, "_post", flaky)
        r = client.post("/api/anki/push", json={**BODY, "confirm": True})
        assert r.status_code == 200
        d = r.json()
        assert d["created"] == 1 and d["sync_ok"] is False and "went away" in d["sync_error"]

    def test_sync_runs_after_send(self, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        fake = _use(monkeypatch)
        client.post("/api/anki/push", json={**BODY, "confirm": True})
        assert fake.actions.index("addNotes") < fake.actions.index("version")
        assert "findCards" in fake.actions

    def test_nothing_to_add_writes_nothing(self, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        fake = _use(monkeypatch, duplicates=("犬",))
        d = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert d["created"] == 0 and len(d["skipped"]) == 1
        assert not WRITES & set(fake.actions)

    def test_note_type_missing_blocks_push(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch, models=("Basic",))
        assert client.post("/api/anki/push", json={**BODY, "confirm": True}).status_code == 409
        assert not WRITES & set(fake.actions)

    def test_unreachable_is_503(self, isolated_data_dir):
        _seed()
        assert client.post("/api/anki/push", json={**BODY, "confirm": True}).status_code == 503

    def test_unexpected_add_response(self, isolated_data_dir, monkeypatch):
        ids = _seed()
        _use(monkeypatch, add_results=[1])
        r = client.post("/api/anki/push", json={**BODY, "confirm": True})
        assert r.status_code == 502
        assert store.get_item("vocab", ids[0])["status"] == "unreviewed"

    def test_concurrent_send_gets_409(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch)
        fake.hold = threading.Event()
        first: dict[str, Any] = {}

        def run():
            first["r"] = client.post("/api/anki/push", json={**BODY, "confirm": True})

        t = threading.Thread(target=run)
        t.start()
        assert fake.entered.wait(5)
        second = client.post("/api/anki/push", json={**BODY, "confirm": True})
        fake.hold.set()
        t.join(10)
        assert second.status_code == 409 and "already running" in second.json()["detail"]
        assert first["r"].status_code == 200 and first["r"].json()["created"] == 3
        assert [a for a in fake.actions if a == "addNotes"] == ["addNotes"]


# ---------- write allow-list ----------


class TestAllowList:
    @pytest.mark.parametrize(
        "action",
        ["updateNoteFields", "deleteNotes", "deleteDecks", "suspend", "setDeckConfigId", "changeDeck",
         "removeTags", "importPackage", "findCards", "addNote", "multi"],
    )
    def test_other_write_actions_refused(self, monkeypatch, action):
        fake = _use(monkeypatch)
        with pytest.raises(anki_push.AnkiWriteRefused):
            anki_push._write(action, {"x": 1})
        assert fake.calls == []

    def test_allowed_actions_pass_through(self, monkeypatch):
        fake = _use(monkeypatch)
        anki_push._write("createDeck", {"deck": "Studious"})
        assert fake.actions == ["createDeck"]

    def test_write_actions_constant(self):
        assert {"createDeck", "addNotes"} == anki_push.WRITE_ACTIONS

    def test_reads_refuse_writes(self, monkeypatch):
        fake = _use(monkeypatch)
        with pytest.raises(anki_push.AnkiWriteRefused):
            anki_push._read("addNotes", {})
        assert fake.calls == []

    def test_guard_still_blocks_real_anki(self):
        with pytest.raises(anki.AnkiUnavailable):
            anki_push._write("createDeck", {"deck": "x"})


class TestSettings:
    def test_env_overrides(self, isolated_data_dir, monkeypatch):
        from app import config

        monkeypatch.setenv("ANKI_PUSH_DECK", "Other")
        monkeypatch.setenv("ANKI_PUSH_NOTE_TYPE", "Core")
        config.get_settings.cache_clear()
        s = config.get_settings()
        assert (s.anki_push_deck, s.anki_push_note_type) == ("Other", "Core")
        config.get_settings.cache_clear()

    def test_defaults(self, isolated_data_dir):
        from app import config

        s = config.get_settings()
        assert (s.anki_push_deck, s.anki_push_note_type) == ("Studious", "Kaishi 1.5k")


# ---------- review follow-ups ----------


class TestMissingDeck:
    def test_preview_checks_with_an_existing_deck(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch, decks=("Default", "Other"))
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["will_create_deck"] is True and d["counts"]["will_add"] == 3
        checked = next(p for a, p in fake.calls if a == "canAddNotesWithErrorDetail")
        assert {n["deckName"] for n in checked["notes"]} == {"Default"}

    def test_first_existing_deck_when_no_default(self, isolated_data_dir, monkeypatch):
        _seed(("犬",))
        fake = _use(monkeypatch, decks=("Kaishi 1.5k",))
        assert client.post("/api/anki/push/preview", json=BODY).json()["counts"]["will_add"] == 1
        checked = next(p for a, p in fake.calls if a == "canAddNotesWithErrorDetail")
        assert checked["notes"][0]["deckName"] == "Kaishi 1.5k"

    def test_fallback_path_also_substitutes(self, isolated_data_dir, monkeypatch):
        _seed()
        _use(monkeypatch, detail=False)
        assert client.post("/api/anki/push/preview", json=BODY).json()["counts"]["will_add"] == 3

    def test_fake_reproduces_the_real_error_for_the_target_deck(self, isolated_data_dir, monkeypatch):
        fake = _use(monkeypatch)
        note = {"deckName": "Studious", "fields": {"Word": "x"}}
        assert fake("canAddNotesWithErrorDetail", {"notes": [note]}) == [
            {"canAdd": False, "error": "deck was not found: Studious"}
        ]

    def test_first_push_works_and_real_notes_use_target_deck(self, isolated_data_dir, monkeypatch):
        _seed()
        fake = _use(monkeypatch)
        d = client.post("/api/anki/push", json={**BODY, "confirm": True}).json()
        assert d["created"] == 3 and d["deck_created"] is True
        add = next(p for a, p in fake.calls if a == "addNotes")
        assert {n["deckName"] for n in add["notes"]} == {"Studious"}


class TestReadings:
    def test_first_alternative(self):
        assert anki_push.pick_reading("やめる", "やめる / とめる") == "やめる"
        assert anki_push.pick_reading("犬", "いぬ、ケン") == "いぬ"

    def test_prefers_alternative_that_aligns(self):
        assert anki_push.pick_reading("その他", "ほか・そのた") == "そのた"
        assert anki_push.furigana("その他", "そのた") == "その 他[た]"

    def test_no_alignment_uses_first(self):
        assert anki_push.pick_reading("他", "ほか・そのた") == "ほか"

    def test_katakana_headword_is_its_own_reading(self):
        assert anki_push.pick_reading("スキル", "すきる") == "スキル"
        assert anki_push.pick_reading("ア・ラ・カルト", "あらかると") == "ア・ラ・カルト"
        assert anki_push.pick_reading("コーヒー", "") == "コーヒー"

    def test_note_uses_picked_reading(self, textbook):
        doc, ch = textbook
        f = anki_push.build_note({"headword": "その他", "reading": "ほか・そのた"}, doc, ch)["fields"]
        assert f["Word Reading"] == "そのた" and f["Word Furigana"] == "その 他[た]"
        f = anki_push.build_note({"headword": "スキル", "reading": "すきる"}, doc, ch)["fields"]
        assert f["Word Reading"] == "スキル" and f["Word Furigana"] == "スキル"


class TestOmittedKana:
    def test_leading_kana_omitted_from_reading(self):
        assert anki_push.furigana("お笑い", "わらい") == "お 笑[わら]い"

    def test_honorific_prefix(self):
        assert anki_push.furigana("ご褒美", "ほうび") == "ご 褒美[ほうび]"
        assert anki_push.furigana("ご褒美", "ごほうび") == "ご 褒美[ほうび]"

    def test_trailing_kana_omitted(self):
        assert anki_push.furigana("笑い", "わら") == "笑[わら]い"

    def test_both_omitted(self):
        assert anki_push.furigana("お笑いさん", "わら") == "お 笑[わら]いさん"


class TestNotesAndCounts:
    def test_preview_rows_have_tags_and_counts(self, isolated_data_dir, monkeypatch):
        ids = _seed(("犬", "猫", "鳥"))
        for i, hw in enumerate(("犬", "猫")):
            store.update_item("vocab", ids[i], example={
                "source": "generated", "sentence": f"{hw}がいる。", "surface": hw,
                "furigana": f"{hw}がいる。", "gloss": "There is one." if i == 0 else ""})
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["counts"]["with_sentence"] == 2 and d["counts"]["with_gloss"] == 1
        assert d["counts"]["without_sentence"] == 1
        assert d["items"][0]["tags"] == ["studious", f"studious::{DOC}::{CH}"]
        assert [i["has_gloss"] for i in d["items"]] == [True, False, False]


# ---------- sentence selection: the stored generated example ----------

KAISHI = {
    "sentence": "彼に会えて嬉しかった。",
    "surface": "嬉しかった",
    "furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった。",
    "gloss": "I was glad to be able to meet him <b>.",
    "source": "generated",
    "model": "m",
    "created_at": "2026-01-01T00:00:00+00:00",
}


def _happy(sightings=(), example=None):
    return {"headword": "嬉しい", "reading": "うれしい", "meaning": "glad", "sightings": list(sightings),
            "example": example}


class TestSentenceSelection:



    def test_nothing_gives_empty(self):
        note = anki_push.build_note(_happy())
        assert note["sentence_source"] is None
        assert note["has_sentence"] is False
        assert note["fields"]["Sentence"] == note["fields"]["Sentence Furigana"] == ""
        assert note["fields"]["Sentence Meaning"] == ""

    def test_generated_example_fields(self):
        note = anki_push.build_note(_happy(example=KAISHI))
        f = note["fields"]
        assert f["Sentence"] == "彼に会えて<b>嬉しかった</b>。"
        assert f["Sentence Furigana"] == "彼[かれ]に 会[あ]えて<b>嬉[うれ]しかった</b>。"
        assert f["Sentence Meaning"] == "I was glad to be able to meet him &lt;b&gt;."
        assert note["has_sentence"] and note["has_gloss"]

    def test_generated_example_html_escaped(self):
        ex = {**KAISHI, "sentence": "A&B嬉しい。", "surface": "嬉しい", "furigana": "A&B 嬉[うれ]しい。"}
        f = anki_push.build_note(_happy(example=ex))["fields"]
        assert f["Sentence"] == "A&amp;B<b>嬉しい</b>。"
        assert f["Sentence Furigana"] == "A&amp;B<b>嬉[うれ]しい</b>。"

    def test_incomplete_example_ignored(self):
        assert anki_push.build_note(_happy(example={"sentence": "x。"}))["sentence_source"] is None


class TestPreviewNeedsExample:
    def test_counts_sources_and_ids(self, isolated_data_dir, monkeypatch):
        ids = _seed(("犬", "猫", "鳥"))
        store.update_item("vocab", ids[1], example=KAISHI)
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        by_id = {i["id"]: i for i in d["items"]}
        assert by_id[ids[0]]["sentence_source"] is None
        assert by_id[ids[1]]["sentence_source"] == "generated"
        assert d["counts"]["needs_example"] == 2
        assert sorted(d["counts"]["needs_example_ids"]) == sorted([ids[0], ids[2]])
        assert d["counts"]["with_sentence"] == 1

    def test_skipped_rows_do_not_need_examples(self, isolated_data_dir, monkeypatch):
        ids = _seed(("犬", "猫"))
        fake = _use(monkeypatch)
        orig = fake.__call__

        def dup_first(action, params=None, *, timeout=0):
            out = orig(action, params, timeout=timeout)
            if action == "canAddNotesWithErrorDetail":
                out[0] = {"canAdd": False, "error": "duplicate"}
            return out

        monkeypatch.setattr(anki, "_post", dup_first)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["counts"]["needs_example"] == 1
        assert d["counts"]["needs_example_ids"] == [ids[1]]


    def test_push_uses_stored_example_without_llm(self, isolated_data_dir, monkeypatch):
        ids = _seed(("犬",))
        store.update_item("vocab", ids[0], example=KAISHI)
        fake = _use(monkeypatch)
        from app.providers import registry

        monkeypatch.setattr(registry, "get_vlm", lambda name: (_ for _ in ()).throw(AssertionError("LLM called")))
        r = client.post("/api/anki/push", json={**BODY, "confirm": True})
        assert r.status_code == 200
        notes = next(p for a, p in fake.calls if a == "addNotes")["notes"]
        assert notes[0]["fields"]["Sentence"] == "彼に会えて<b>嬉しかった</b>。"


class TestTextbookSentencesNeverUsed:
    def _sighted(self, **extra):
        return {
            "headword": "嬉しい", "reading": "うれしい", "meaning": "glad",
            "sightings": [{"doc_id": DOC, "chapter_id": CH, "region_id": "r1", "sentence_index": 0,
                           "surface": "嬉しかった", "sentence_text": "彼に会えて嬉しかった。", "source": "breakdown"}],
            **extra,
        }

    def test_a_breakdown_sighting_gives_no_sentence(self):
        note = anki_push.build_note(self._sighted())
        assert note["sentence_source"] is None and note["has_sentence"] is False
        f = note["fields"]
        assert f["Sentence"] == f["Sentence Furigana"] == f["Sentence Meaning"] == ""

    def test_generated_example_wins_whatever_the_sightings(self):
        note = anki_push.build_note(self._sighted(example=KAISHI))
        assert note["sentence_source"] == "generated"
        assert note["fields"]["Sentence"] == "彼に会えて<b>嬉しかった</b>。"

    def test_a_stored_textbook_example_counts_as_no_example(self):
        old = {**KAISHI, "source": "textbook", "sighting": {"region_id": "r1", "sentence_index": 0}}
        note = anki_push.build_note(self._sighted(example=old))
        assert note["sentence_source"] is None and note["fields"]["Sentence"] == ""

    def test_preview_needs_example_for_every_row_without_a_generated_one(self, isolated_data_dir, monkeypatch):
        ids = _seed(("犬", "猫", "鳥"))  # all have breakdown sightings
        store.update_item("vocab", ids[0], example=KAISHI)
        store.update_item("vocab", ids[1], example={**KAISHI, "source": "textbook"})
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert [i["sentence_source"] for i in d["items"]] == ["generated", None, None]
        assert d["counts"]["needs_example"] == 2
        assert sorted(d["counts"]["needs_example_ids"]) == sorted(ids[1:])
        assert "needs_readings" not in d["counts"]
