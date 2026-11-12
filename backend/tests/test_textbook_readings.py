# ruff: noqa: F811
"""Readings for textbook example sentences (source "textbook")."""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers import registry
from app.services import anki_push, examples, llm_audit, preferences, store
from tests.test_anki_push import BODY, CH, DOC, _breakdown, _sighting, _use, textbook  # noqa: F401

client = TestClient(app)

SENT = "店員：「どうして、遅れたの？」"
FURI = "店員[てんいん]：「どうして、 遅[おく]れたの？」"


class FakeVlm:
    """Answers record_sentence_readings (and record_examples) from a script."""

    name = "anthropic"

    def __init__(self, script: dict[int, Any] | None = None):
        self.script = script or {}
        self.calls: list[dict[str, Any]] = []

    def call_tool(self, prompt, tool_name, tool_schema, config):
        text = registry.prompt_text(prompt)
        tag = "sentences" if tool_name == "record_sentence_readings" else "words"
        words = json.loads(text.rsplit(f"<{tag}>", 1)[1].split(f"</{tag}>")[0])
        self.calls.append({"tool": tool_name, "words": words, "prompt": prompt, "config": config})
        scripted = self.script.get(len(self.calls))
        if isinstance(scripted, Exception):
            raise scripted
        if scripted is None:
            if tool_name == "record_sentence_readings":
                scripted = [{"id": w["id"], "furigana": FURI, "gloss": "Clerk: Why were you late?"} for w in words]
            else:
                scripted = [
                    {
                        "id": w["id"],
                        "sentence": "彼に会えて嬉しかった。",
                        "surface": "嬉しかった",
                        "furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった。",
                        "gloss": "Glad.",
                    }
                    for w in words
                ]
        key = "readings" if tool_name == "record_sentence_readings" else "examples"
        return registry.ToolCallResult(
            tool_input={key: scripted},
            meta={"model": "fake-model", "usage": {"input_tokens": 100, "output_tokens": 50}},
        )


@pytest.fixture
def fake(monkeypatch, isolated_data_dir):
    vlm = FakeVlm()
    monkeypatch.setattr(registry, "get_vlm", lambda name: vlm)
    return vlm


def _item(doc, ch, text=SENT, surface="遅れた", headword="遅れる", **kw):
    item = store.create_item("vocab", headword=headword, reading="おくれる", meaning="be late")
    store.update_item("vocab", item["id"], sightings=[_sighting(text, doc=doc, chapter=ch, surface=surface)], **kw)
    return item["id"]


# ---------- validation ----------


class TestValidateReadings:
    def test_accepts_speaker_label_and_quotes(self):
        e = {"furigana": FURI, "gloss": "Clerk: Why were you late?"}
        assert examples.validate_reading_entry(e, SENT) is None

    def test_generation_only_rules_do_not_apply(self):
        sentence = "A：「テストは100点でした」ね"
        furi = "A：「テストは100 点[てん]でした」ね"
        assert len(sentence) < 60
        assert examples.validate_reading_entry({"furigana": furi, "gloss": "A: The test was 100."}, sentence) is None
        assert examples.validate_entry({"sentence": sentence, "surface": "テスト", "furigana": furi,
                                        "gloss": "x"}, "テスト")  # the generated rules would reject it

    @pytest.mark.parametrize(
        "furi,needle",
        [
            ("店員[てんいん]：「どうして、 遅[おく]れたの？」。", "reduce"),
            ("店員：「どうして、 遅[おく]れたの？」", "no reading"),
            ("店員[てんいん]：「どうして、 遅れたの？」", "no reading"),
            ("店員[てんいん]：「どうして、[x] 遅[おく]れたの？」", "not a kanji run"),
            ("店員[てんいん]：「どうして、 遅[oku]れたの？」", "hiragana"),
            ("", "empty"),
        ],
    )
    def test_furigana_failures(self, furi, needle):
        reason = examples.validate_reading_entry({"furigana": furi, "gloss": "ok"}, SENT)
        assert reason and needle in reason

    def test_gloss_rules(self):
        base = {"furigana": FURI}
        assert "empty" in examples.validate_reading_entry({**base, "gloss": ""}, SENT)
        assert "Japanese" in examples.validate_reading_entry({**base, "gloss": "店員 said"}, SENT)

    def test_entries_split_and_missing(self):
        ok, bad = examples.validate_readings(
            [{"id": "a", "furigana": FURI, "gloss": " g "}, {"id": "a", "furigana": FURI, "gloss": "g"},
             {"id": "b", "furigana": FURI, "gloss": " g "}, {"id": "zzz", "furigana": FURI, "gloss": "g"}],
            {"a": SENT, "b": SENT, "c": SENT},
        )
        assert ok == {"b": {"furigana": FURI, "gloss": "g"}}
        assert "more than once" in bad["a"] and "no entry" in bad["c"]

    def test_furigana_reading(self):
        assert examples.furigana_reading("彼[かれ]に 会[あ]えて 嬉[うれ]しかった。") == "かれにあえてうれしかった。"


# ---------- note building ----------


def _stored(text=SENT, **over):
    return {"source": "textbook", "sentence": text, "surface": "遅れた", "furigana": FURI,
            "gloss": "Stored gloss", "model": "m", "created_at": "t", **over}


class TestNote:
    def test_textbook_sentence_with_readings(self, textbook):
        doc, ch = textbook
        _breakdown(doc, ch, [{"text": SENT, "gloss": "Breakdown gloss"}])
        item = {"headword": "遅れる", "reading": "おくれる", "example": _stored(),
                "sightings": [_sighting(SENT, doc=doc, chapter=ch, surface="遅れた")]}
        note = anki_push.build_note(item, doc, ch)
        f = note["fields"]
        assert f["Sentence"] == "店員：「どうして、<b>遅れた</b>の？」"
        assert f["Sentence Furigana"] == "店員[てんいん]：「どうして、<b>遅[おく]れた</b>の？」"
        assert note["sentence_source"] == "textbook" and note["needs_readings"] is False
        assert note["sentence_reading"] == "てんいん：「どうして、おくれたの？」"

    def test_breakdown_gloss_beats_stored_gloss(self, textbook):
        doc, ch = textbook
        _breakdown(doc, ch, [{"text": SENT, "gloss": "Breakdown gloss"}])
        item = {"headword": "遅れる", "reading": "おくれる", "example": _stored(),
                "sightings": [_sighting(SENT, doc=doc, chapter=ch, surface="遅れた")]}
        assert anki_push.build_note(item, doc, ch)["fields"]["Sentence Meaning"] == "Breakdown gloss"

    def test_stored_gloss_used_when_no_breakdown_gloss(self, textbook):
        doc, ch = textbook
        item = {"headword": "遅れる", "reading": "おくれる", "example": _stored(),
                "sightings": [_sighting(SENT, doc=doc, chapter=ch, surface="遅れた")]}
        assert anki_push.build_note(item, doc, ch)["fields"]["Sentence Meaning"] == "Stored gloss"

    def test_stale_stored_textbook_example_is_ignored_not_used_as_generated(self, textbook):
        doc, ch = textbook
        item = {"headword": "遅れる", "reading": "おくれる", "example": _stored(text="古い文。"),
                "sightings": [_sighting(SENT, doc=doc, chapter=ch, surface="遅れた")]}
        note = anki_push.build_note(item, doc, ch)
        assert note["fields"]["Sentence Furigana"] == note["fields"]["Sentence"]  # no readings
        assert note["needs_readings"] is True and note["sentence_source"] == "textbook"
        assert item["example"]["sentence"] == "古い文。"  # untouched

    def test_stale_textbook_example_without_a_sighting_gives_no_sentence(self):
        note = anki_push.build_note({"headword": "遅れる", "reading": "おくれる", "example": _stored()})
        assert note["sentence_source"] is None and note["fields"]["Sentence"] == ""

    def test_html_escaping_in_furigana(self):
        text = "A&B：<遅れた>"
        furi = "A&B：<遅[おく]れた>"
        item = {"headword": "遅れる", "reading": "おくれる",
                "example": _stored(text=text, furigana=furi, surface="遅れた"),
                "sightings": [_sighting(text, surface="遅れた")]}
        # usable_sentence needs a terminator
        item["sightings"][0]["sentence_text"] = text + "。"
        item["example"]["sentence"] = text + "。"
        item["example"]["furigana"] = furi + "。"
        f = anki_push.build_note(item)["fields"]
        assert f["Sentence Furigana"] == "A&amp;B：&lt;<b>遅[おく]れた</b>&gt;。"

    def test_generated_example_still_used_without_a_textbook_sentence(self):
        gen = {"source": "generated", "sentence": "彼に会えて嬉しかった。", "surface": "嬉しかった",
               "furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった。", "gloss": "Glad."}
        note = anki_push.build_note({"headword": "嬉しい", "reading": "うれしい", "example": gen})
        assert note["sentence_source"] == "generated" and note["needs_readings"] is False


class TestPreview:
    def test_needs_readings_counts_and_ids(self, isolated_data_dir, monkeypatch):
        from tests.test_anki_push import _seed

        ids = _seed(("犬", "猫", "鳥"), with_sentence=True)
        store.update_item("vocab", ids[0], example={
            "source": "textbook", "sentence": "犬がいる。", "surface": "犬",
            "furigana": "犬[いぬ]がいる。", "gloss": "A dog.", "model": "m", "created_at": "t"})
        _use(monkeypatch)
        d = client.post("/api/anki/push/preview", json=BODY).json()
        assert d["counts"]["needs_readings"] == 2
        assert sorted(d["counts"]["needs_readings_ids"]) == sorted(ids[1:])
        assert d["counts"]["needs_example"] == 0
        assert d["items"][0]["needs_readings"] is False
        assert d["items"][0]["fields"]["Sentence Furigana"] == "<b>犬[いぬ]</b>がいる。"


# ---------- generation ----------


class TestGenerate:
    def test_readings_job_stores_a_textbook_example(self, fake, textbook):
        doc, ch = textbook
        _breakdown(doc, ch, [{"text": SENT, "gloss": "Breakdown gloss"}])
        item_id = _item(doc, ch)
        out = examples.generate_examples([item_id], doc_id=doc, chapter_id=ch)
        (r,) = out["items"]
        assert r["status"] == "readings"
        ex = store.get_item("vocab", item_id)["example"]
        assert ex["source"] == "textbook" and ex["sentence"] == SENT and ex["furigana"] == FURI
        assert ex["gloss"] == "Breakdown gloss"  # the breakdown's translation is kept
        assert ex["model"] == preferences.get_active_vlm_model() and ex["created_at"]
        assert ex["sighting"] == {"region_id": "r1", "sentence_index": 0}
        (call,) = fake.calls
        assert call["tool"] == "record_sentence_readings"
        assert call["words"] == [{"id": item_id, "sentence": SENT, "surface": "遅れた"}]
        assert call["prompt"][0]["cache"] is True

    def test_model_gloss_used_when_the_breakdown_has_none(self, fake, textbook):
        doc, ch = textbook
        item_id = _item(doc, ch)
        examples.generate_examples([item_id], doc_id=doc, chapter_id=ch)
        assert store.get_item("vocab", item_id)["example"]["gloss"] == "Clerk: Why were you late?"

    def test_items_without_a_textbook_sentence_are_generated(self, fake, textbook):
        doc, ch = textbook
        a = _item(doc, ch)
        b = store.create_item("vocab", headword="嬉しい", reading="うれしい", meaning="glad")["id"]
        out = examples.generate_examples([a, b], doc_id=doc, chapter_id=ch)
        assert [r["status"] for r in out["items"]] == ["readings", "generated"]
        assert {c["tool"] for c in fake.calls} == {"record_sentence_readings", "record_examples"}
        assert store.get_item("vocab", b)["example"]["source"] == "generated"

    def test_kept_unless_force_and_stale_is_redone(self, fake, textbook):
        doc, ch = textbook
        item_id = _item(doc, ch)
        examples.generate_examples([item_id], doc_id=doc, chapter_id=ch)
        out = examples.generate_examples([item_id], doc_id=doc, chapter_id=ch)
        assert out["items"][0]["status"] == "kept" and len(fake.calls) == 1
        assert examples.generate_examples([item_id], force=True, doc_id=doc, chapter_id=ch)["items"][0]["status"] == "readings"
        store.update_item("vocab", item_id, example=_stored(text="古い文。"))
        assert examples.generate_examples([item_id], doc_id=doc, chapter_id=ch)["items"][0]["status"] == "readings"

    def test_stale_textbook_example_without_sighting_is_regenerated_as_a_sentence(self, fake):
        item_id = store.create_item("vocab", headword="嬉しい", reading="うれしい", meaning="glad")["id"]
        store.update_item("vocab", item_id, example=_stored(text="古い文。"))
        assert examples.generate_examples([item_id])["items"][0]["status"] == "generated"

    def test_retry_with_reasons_then_give_up(self, fake, textbook):
        doc, ch = textbook
        a, b = _item(doc, ch), _item(doc, ch, headword="遅れる2")
        bad = {"id": b, "furigana": "店員：「どうして、 遅れたの？」", "gloss": "x"}
        fake.script = {1: [{"id": a, "furigana": FURI, "gloss": "g"}, bad], 2: [bad]}
        out = examples.generate_examples([a, b], doc_id=doc, chapter_id=ch)
        assert [r["status"] for r in out["items"]] == ["readings", "failed"]
        assert "no reading" in out["items"][1]["reason"]
        assert len(fake.calls) == 2 and "no reading" in fake.calls[1]["words"][0]["problem"]
        assert "example" not in store.get_item("vocab", b) or not store.get_item("vocab", b).get("example")

    def test_batches_of_20_and_audit_job_type(self, fake, textbook):
        doc, ch = textbook
        ids = [_item(doc, ch, headword=f"遅れる{i}") for i in range(25)]
        out = examples.generate_examples(ids, doc_id=doc, chapter_id=ch)
        assert [len(c["words"]) for c in fake.calls] == [20, 5]
        assert all(r["status"] == "readings" for r in out["items"])
        entries = [e for e in llm_audit.read_all() if e["job_type"] == "sentence_readings"]
        assert len(entries) == 2 and out["usage"]["calls"] == 2

    def test_chapter_context_picks_the_same_sentence_as_the_preview(self, fake, textbook):
        doc, ch = textbook
        item = store.create_item("vocab", headword="遅れる", reading="おくれる", meaning="late")
        store.update_item("vocab", item["id"], sightings=[
            _sighting("別の章の文。", chapter="other", surface="遅れた", doc=doc),
            _sighting("この章の文。", chapter=ch, surface="遅れた", doc=doc),
        ])
        examples.generate_examples([item["id"]], doc_id=doc, chapter_id=ch)
        assert fake.calls[0]["words"][0]["sentence"] == "この章の文。"

    def test_provider_not_configured_is_503(self, isolated_data_dir, textbook, monkeypatch):
        doc, ch = textbook
        item_id = _item(doc, ch)

        def boom(name):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        monkeypatch.setattr(registry, "get_vlm", boom)
        r = client.post("/api/vocab/examples", json={"item_ids": [item_id], "doc_id": doc, "chapter_id": ch})
        assert r.status_code == 503

    def test_endpoint_reports_readings(self, fake, textbook):
        doc, ch = textbook
        item_id = _item(doc, ch)
        r = client.post("/api/vocab/examples", json={"item_ids": [item_id], "doc_id": doc, "chapter_id": ch})
        assert r.status_code == 200 and r.json()["items"][0]["status"] == "readings"

    def test_prompt_states_the_rules(self):
        from app.config import SENTENCE_READINGS_PROMPT as p

        assert "Do not change the sentence" in p and "店員：" in p and "translation" in p
