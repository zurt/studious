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


# ---------- sentences ----------


def _sighting(text, *, source="breakdown", chapter=CH, surface="嬉しかった", region="r1", index=0, doc=DOC):
    return {
        "doc_id": doc,
        "chapter_id": chapter,
        "region_id": region,
        "sentence_index": index,
        "surface": surface,
        "sentence_text": text,
        "source": source,
    }


class TestPlainSentence:
    def test_strips_markdown_and_furigana(self):
        assert anki_push.plain_sentence("- **彼(かれ)**に 会(あ)えて`嬉しかった`。") == "彼に会えて嬉しかった。"

    def test_collapses_whitespace_and_links(self):
        assert anki_push.plain_sentence("# 見て  [ここ](http://x)\n  ください") == "見てここください"

    def test_katakana_parens_are_not_furigana(self):
        assert anki_push.plain_sentence("文(ア)です") == "文(ア)です"


class TestChooseSentence:
    def test_prefers_chapter_then_any_breakdown(self):
        item = {"sightings": [_sighting("別の章。", chapter="other"), _sighting("この章。")]}
        assert anki_push.choose_sentence(item, CH)[1] == "この章。"
        assert anki_push.choose_sentence(item, "zzz")[1] == "別の章。"

    def test_vocab_list_sighting_never_used(self):
        item = {"sightings": [_sighting("嬉しい（うれしい）glad", source="vocab_list")]}
        assert anki_push.choose_sentence(item, CH) is None

    def test_long_and_blank_sentences_dropped(self):
        item = {
            "sightings": [
                _sighting("あ" * 120 + "。"),
                _sighting("これは＿＿＿です。"),
                _sighting("これは_____です。"),
                _sighting("短い。"),
            ]
        }
        assert anki_push.choose_sentence(item, CH)[1] == "短い。"
        item["sightings"] = item["sightings"][:3]
        assert anki_push.choose_sentence(item, CH) is None

    def test_exactly_120_allowed(self):
        assert anki_push.choose_sentence({"sightings": [_sighting("あ" * 119 + "。")]}, CH) is not None

    def test_no_sightings(self):
        assert anki_push.choose_sentence({}, CH) is None


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


def _breakdown(doc, ch, sentences, region="r1"):
    storage.save_breakdown(doc, ch, region, {"sentences": sentences})


class TestBuildNote:
    def test_field_completeness_and_values(self, textbook):
        doc, ch = textbook
        text = "彼に会えて嬉しかった。"
        _breakdown(doc, ch, [{"text": text, "gloss": "I was glad to meet him."}])
        item = {
            "headword": "嬉しい",
            "reading": "うれしい",
            "meaning": "happy, glad",
            "notes": "line1\nline2",
            "classifications": {"freq_rank": 355},
            "sightings": [_sighting(text, doc=doc, chapter=ch)],
        }
        note = anki_push.build_note(item, doc, ch)
        f = note["fields"]
        assert tuple(f) == anki_push.KAISHI_FIELDS
        assert f["Word"] == "嬉しい" and f["Word Reading"] == "うれしい"
        assert f["Word Meaning"] == "happy, glad"
        assert f["Word Furigana"] == "嬉[うれ]しい"
        assert f["Sentence"] == "彼に会えて<b>嬉しかった</b>。"
        assert f["Sentence Furigana"] == f["Sentence"]
        assert f["Sentence Meaning"] == "I was glad to meet him."
        assert f["Notes"] == "line1<br>line2"
        assert f["Frequency"] == "355"
        for empty in ("Word Audio", "Sentence Audio", "Pitch Accent", "Pitch Accent Notes", "Picture"):
            assert f[empty] == ""
        assert note["tags"] == ["studious", f"studious::{doc}::{ch}"]
        assert note["has_sentence"] is True

    def test_gloss_rejected_when_sentence_shifted(self, textbook):
        doc, ch = textbook
        _breakdown(doc, ch, [{"text": "別の文。", "gloss": "Other."}])
        item = {"headword": "嬉しい", "reading": "うれしい", "sightings": [_sighting("彼は嬉しかった。", doc=doc, chapter=ch)]}
        assert anki_push.build_note(item, doc, ch)["fields"]["Sentence Meaning"] == ""

    def test_gloss_missing_breakdown_or_index(self, textbook):
        doc, ch = textbook
        s = _sighting("彼は嬉しかった。", doc=doc, chapter=ch, index=5)
        assert anki_push.sentence_gloss(s) == ""
        _breakdown(doc, ch, [{"text": "彼は嬉しかった。", "gloss": "g"}])
        assert anki_push.sentence_gloss(s) == ""
        assert anki_push.sentence_gloss({}) == ""

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
                      "surface": hw, "sentence_text": f"{hw}がいる。",
                      "source": "breakdown" if with_sentence else "vocab_list"}]
        store.update_item("vocab", item["id"], jmdict_seq=rank, pos=["n"], sightings=sightings,
                          classifications={"freq_rank": rank * 100})
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
                               "headword_match": 0, "with_sentence": 0, "with_gloss": 0}
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


class TestUsableSentence:
    @pytest.mark.parametrize(
        "raw",
        [
            "| | | |---|---| | 手に入れる | 耐える |。",
            "□たまたまあくまで要はどんどんやっぱり例えば□",
            "⑥彼女は就職活動をして、世の中はまだまだ男性社会であること（　　）実感した。",
            "彼女は（）実感した。",
            "彼女は( )実感した。",
            "彼女は［　］実感した。",
            "これは＿＿＿です。",
            "これは______です。",
            "これは\\_\\_\\_です。",
            "これは__です。",
            "これは本です",
            "犬と猫",
            "あ" * 120 + "。",
            "",
        ],
    )
    def test_rejected(self, raw):
        assert anki_push.usable_sentence(raw) is None

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("3 次の図は、グラフです。", "次の図は、グラフです。"),
            ("⑨休暇は大切です。", "休暇は大切です。"),
            ("1. 本を読む。", "本を読む。"),
            ("１．本を読む。", "本を読む。"),
            ("(2) 本を読む。", "本を読む。"),
            ("- 本を読む。", "本を読む。"),
            ("「行こう！」", "「行こう！」"),
            ("本当ですか？", "本当ですか？"),
            ("彼(かれ)は行く。", "彼は行く。"),
        ],
    )
    def test_accepted_and_cleaned(self, raw, expected):
        assert anki_push.usable_sentence(raw) == expected

    def test_split_marker_numbers(self):
        assert anki_push.split_marker("⑥あ") == ("あ", 6)
        assert anki_push.split_marker("12) あ") == ("あ", 12)
        assert anki_push.split_marker("あ") == ("あ", None)


class TestRanking:
    def test_reading_passage_region_wins(self, textbook):
        doc, ch = textbook
        passage = storage.create_region(doc, ch, page=1, bbox=[0, 0, 1, 1], tag="reading_passage")
        other = storage.create_region(doc, ch, page=1, bbox=[0, 0, 1, 1], tag="exercises")
        item = {"sightings": [
            _sighting("短い。", doc=doc, chapter=ch, region=other["id"]),
            _sighting("これは長めの文章です。", doc=doc, chapter=ch, region=passage["id"]),
        ]}
        assert anki_push.choose_sentence(item, ch)[1] == "これは長めの文章です。"

    def test_chapter_then_shorter(self, textbook):
        item = {"sightings": [
            _sighting("別章の短文。", chapter="x"),
            _sighting("この章の少し長い文です。"),
            _sighting("この章の文。"),
        ]}
        assert anki_push.choose_sentence(item, CH)[1] == "この章の文。"

    def test_unusable_sentences_give_none(self):
        item = {"sightings": [_sighting("| a | b |"), _sighting("□あ□")]}
        assert anki_push.choose_sentence(item, CH) is None

    def test_region_lookups_cached_per_request(self, textbook, monkeypatch):
        doc, ch = textbook
        calls = []
        real = storage.load_region
        monkeypatch.setattr(storage, "load_region", lambda *a: calls.append(a) or real(*a))
        cache: dict = {}
        item = {"sightings": [_sighting("文一。", doc=doc, chapter=ch), _sighting("文二。", doc=doc, chapter=ch)]}
        anki_push.choose_sentence(item, ch, cache)
        anki_push.choose_sentence(item, ch, cache)
        assert len(calls) == 1

    def test_gloss_number_stripped_when_matching(self, textbook):
        doc, ch = textbook
        _breakdown(doc, ch, [{"text": "3 次の図は、グラフです。", "gloss": "3 The next figure is a graph."}])
        s = _sighting("3 次の図は、グラフです。", doc=doc, chapter=ch)
        assert anki_push.sentence_gloss(s) == "The next figure is a graph."
        _breakdown(doc, ch, [{"text": "3 次の図は、グラフです。", "gloss": "4 students came."}])
        assert anki_push.sentence_gloss(s) == "4 students came."


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
    def test_preview_rows_have_tags_and_counts(self, textbook, monkeypatch):
        doc, ch = textbook
        _breakdown(doc, ch, [{"text": "犬がいる。", "gloss": "There is a dog."},
                             {"text": "猫がいる。", "gloss": ""}], region="r")
        for i, hw in enumerate(("犬", "猫", "鳥")):
            it = store.create_item("vocab", headword=hw, reading=hw, meaning="m")
            if i < 2:
                sight = [{"doc_id": doc, "chapter_id": ch, "region_id": "r", "sentence_index": i,
                          "surface": hw, "sentence_text": f"{hw}がいる。", "source": "breakdown"}]
            else:
                sight = [{"doc_id": doc, "chapter_id": ch, "source": "vocab_list"}]
            store.update_item("vocab", it["id"], jmdict_seq=i + 1, pos=["n"], sightings=sight,
                              classifications={"freq_rank": i + 1})
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json={"doc_id": doc, "chapter_id": ch}).json()
        assert d["counts"]["with_sentence"] == 2 and d["counts"]["with_gloss"] == 1
        assert d["counts"]["without_sentence"] == 1
        assert d["items"][0]["tags"] == ["studious", f"studious::{doc}::{ch}"]
        assert [i["has_gloss"] for i in d["items"]] == [True, False, False]
