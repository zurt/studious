from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers import registry
from app.services import examples, llm_audit, preferences, store

client = TestClient(app)

KAISHI: dict[str, str] = {
    "sentence": "彼に会えて嬉しかった。",
    "surface": "嬉しかった",
    "furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった。",
    "gloss": "I was glad to be able to meet him.",
}


def ok_entry(**over: str) -> dict[str, str]:
    return {**KAISHI, **over}


# ---------- validation ----------


class TestValidateEntry:
    def test_accepts_kaishi_example(self):
        assert examples.validate_entry(KAISHI, "嬉しい") is None

    @pytest.mark.parametrize(
        "over,needle",
        [
            ({"sentence": "嬉しい。"}, "6 to 40"),
            ({"sentence": "嬉" * 41 + "。"}, "6 to 40"),
            ({"sentence": "彼に会えて嬉しかった"}, "end with"),
            ({"sentence": "彼に会えて嬉しかった(笑)。"}, "brackets"),
            ({"sentence": "彼に会えて「嬉しかった」。"}, "brackets"),
            ({"sentence": "彼に会えて<b>嬉しかった</b>。"}, "brackets"),
            ({"sentence": "彼に会えて＿＿嬉しかった。"}, "blank"),
            ({"sentence": "彼に会えて嬉しかった_。"}, "blank"),
            ({"sentence": "彼に会えて\n嬉しかった。"}, "whitespace"),
            ({"sentence": "彼に会えて嬉しかった ok。"}, "whitespace"),
            ({"sentence": "彼にOKして嬉しかった。"}, "Latin"),
            ({"surface": ""}, "surface is empty"),
            ({"surface": "嬉しくない"}, "does not occur"),
            ({"surface": "彼に"}, "stem"),
            ({"furigana": "彼[かれ]に 会[あ]えて 嬉[うれ]しかった"}, "reduce"),
            ({"furigana": "彼[かれ]に 会えて 嬉[うれ]しかった。"}, "no reading"),
            ({"furigana": "彼に 会[あ]えて 嬉[うれ]しかった。"}, "no reading"),
            ({"furigana": "彼[かれ]に[に] 会[あ]えて 嬉[うれ]しかった。"}, "not a kanji run"),
            ({"furigana": "彼[かれ]に 会[あ]えて 嬉[ureshi]しかった。"}, "hiragana"),
            ({"furigana": "彼[かれ]に 会[あ]えて 嬉[]しかった。"}, "hiragana"),
            ({"furigana": ""}, "empty"),
            ({"gloss": ""}, "gloss is empty"),
            ({"gloss": "  "}, "gloss is empty"),
            ({"gloss": "x" * 200}, "under 200"),
            ({"gloss": "I was 嬉しい."}, "Japanese"),
            ({"gloss": "I was glad。"}, "Japanese"),
        ],
    )
    def test_rejects(self, over, needle):
        reason = examples.validate_entry(ok_entry(**over), "嬉しい")
        assert reason is not None and needle in reason

    def test_non_string_fields_and_non_dict(self):
        assert examples.validate_entry({**KAISHI, "gloss": None}, "嬉しい")
        assert examples.validate_entry("nope", "嬉しい")

    def test_length_bounds_inclusive(self):
        assert examples.validate_entry(ok_entry(sentence="嬉しかった。", furigana="嬉[うれ]しかった。"), "嬉しい") is None
        sentence = "あ" * 39 + "。"
        entry = {**KAISHI, "sentence": sentence, "surface": "あああ", "furigana": sentence}
        assert examples.validate_entry(entry, "あああ") is None

    def test_exclamation_and_question_endings(self):
        for end in "！？":
            e = ok_entry(sentence=f"彼に会えて嬉しかった{end}", furigana=f"彼[かれ]に 会[あ]えて 嬉[うれ]しかった{end}")
            assert examples.validate_entry(e, "嬉しい") is None

    def test_suru_headword_uses_stem(self):
        e = {
            "sentence": "友達と旅行を企画した。",
            "surface": "企画した",
            "furigana": "友達[ともだち]と 旅行[りょこう]を 企画[きかく]した。",
            "gloss": "I planned a trip with friends.",
        }
        for hw in ("企画する", "企画(する)", "企画（する）", "企画"):
            assert examples.validate_entry(e, hw) is None
        assert examples.validate_entry({**e, "surface": "した"}, "企画する")

    def test_na_headword_uses_stem(self):
        e = {
            "sentence": "これは重要な問題です。",
            "surface": "重要な",
            "furigana": "これは 重要[じゅうよう]な 問題[もんだい]です。",
            "gloss": "This is an important problem.",
        }
        assert examples.validate_entry(e, "重要な") is None
        assert examples.validate_entry({**e, "surface": "問題"}, "重要な")

    def test_kana_headword_uses_first_two_chars(self):
        e = {
            "sentence": "もう少しゆっくり話してください。",
            "surface": "ゆっくり",
            "furigana": "もう 少[すこ]しゆっくり 話[はな]してください。",
            "gloss": "Please speak a little more slowly.",
        }
        assert examples.validate_entry(e, "ゆっくり") is None
        assert examples.validate_entry({**e, "surface": "話して"}, "ゆっくり")

    def test_katakana_headword_may_be_hiragana_free(self):
        e = {
            "sentence": "毎朝コーヒーを飲みます。",
            "surface": "コーヒー",
            "furigana": "毎朝[まいあさ]コーヒーを 飲[の]みます。",
            "gloss": "I drink coffee every morning.",
        }
        assert examples.validate_entry(e, "コーヒー") is None
        assert examples.validate_entry({**e, "surface": "を"}, "コーヒー")

    def test_latin_allowed_when_headword_has_latin(self):
        e = {
            "sentence": "このTシャツは大きいです。",
            "surface": "Tシャツ",
            "furigana": "このTシャツは 大[おお]きいです。",
            "gloss": "This T-shirt is big.",
        }
        assert examples.validate_entry(e, "Tシャツ") is None
        assert examples.validate_entry(e, "シャツ") is not None  # stem シャ is in surface but T is not allowed

    def test_stem_helper(self):
        assert examples.headword_stem("企画する") == "企画"
        assert examples.headword_stem("料理(する)") == "料理"
        assert examples.headword_stem("重要な") == "重要"
        assert examples.headword_stem("食べ物") == "食"
        assert examples.headword_stem("お願いする") == "願"
        assert examples.headword_stem("する") == "する"
        assert examples.headword_stem("ね") == "ね"
        assert examples.headword_stem("コーヒー") == "コー"


class TestValidateEntries:
    HW = {"a": "嬉しい", "b": "嬉しい"}

    def test_splits_ok_and_bad(self):
        ok, bad = examples.validate_entries(
            [{"id": "a", **KAISHI}, {"id": "b", **KAISHI, "gloss": ""}], self.HW
        )
        assert list(ok) == ["a"] and ok["a"] == KAISHI
        assert "gloss" in bad["b"]

    def test_unknown_id_ignored_missing_id_fails(self):
        ok, bad = examples.validate_entries([{"id": "zzz", **KAISHI}, {"id": "a", **KAISHI}], self.HW)
        assert list(ok) == ["a"]
        assert "no entry" in bad["b"] and "zzz" not in bad

    def test_duplicate_id_fails_both_copies(self):
        ok, bad = examples.validate_entries([{"id": "a", **KAISHI}, {"id": "a", **KAISHI}], self.HW)
        assert "a" not in ok and "more than once" in bad["a"]

    def test_garbage_response(self):
        ok, bad = examples.validate_entries("nope", self.HW)
        assert ok == {} and set(bad) == {"a", "b"}
        ok, bad = examples.validate_entries([None, 3, {"sentence": "x"}], self.HW)
        assert ok == {} and set(bad) == {"a", "b"}


# ---------- bold wrap ----------


class TestWrapSurface:
    def test_kaishi_end_of_sentence(self):
        assert (
            examples.wrap_surface(KAISHI["furigana"], KAISHI["surface"])
            == "彼[かれ]に 会[あ]えて<b>嬉[うれ]しかった</b>。"
        )

    def test_start(self):
        out = examples.wrap_surface("嬉[うれ]しい人[ひと]が 来[き]た。", "嬉しい")
        assert out == "<b>嬉[うれ]しい</b>人[ひと]が 来[き]た。"

    def test_start_of_sentence_kanji_has_no_space(self):
        assert examples.wrap_surface("友達[ともだち]と 行[い]く。", "友達") == "<b>友達[ともだち]</b>と 行[い]く。"

    def test_middle_and_following_kanji_space_dropped(self):
        out = examples.wrap_surface("私[わたし]は 毎日[まいにち] 勉強[べんきょう]する。", "毎日")
        assert out == "私[わたし]は<b>毎日[まいにち]</b>勉強[べんきょう]する。"

    def test_surface_spanning_several_units(self):
        out = examples.wrap_surface("友達[ともだち]と 旅行[りょこう]を 企画[きかく]した。", "旅行を企画した")
        assert out == "友達[ともだち]と<b>旅行[りょこう]を 企画[きかく]した</b>。"

    def test_kana_only_surface(self):
        out = examples.wrap_surface("もう 少[すこ]しゆっくり 話[はな]してください。", "ゆっくり")
        assert out == "もう 少[すこ]し<b>ゆっくり</b>話[はな]してください。"

    def test_surface_cutting_a_kanji_run_widens_to_the_unit(self):
        assert examples.wrap_surface("旅行[りょこう]に 行[い]く。", "旅") == "<b>旅行[りょこう]</b>に 行[い]く。"

    def test_not_found_means_no_wrap(self):
        assert examples.wrap_surface(KAISHI["furigana"], "存在しない") == KAISHI["furigana"]
        assert examples.wrap_surface(KAISHI["furigana"], "") == KAISHI["furigana"]

    def test_escapes_html(self):
        assert examples.wrap_surface("A&B 嬉[うれ]しい<。", "嬉しい") == "A&amp;B<b>嬉[うれ]しい</b>&lt;。"

    def test_first_occurrence_only(self):
        assert examples.wrap_surface("あああ", "あ") == "<b>あ</b>ああ"


# ---------- generation ----------


class FakeVlm:
    """Answers record_examples. `script` maps call number -> response or Exception;
    by default every requested word gets the Kaishi example."""

    name = "anthropic"

    def __init__(self, script: dict[int, Any] | None = None, model: str = "fake-model"):
        self.script = script or {}
        self.model = model
        self.calls: list[dict[str, Any]] = []

    def call_tool(self, prompt, tool_name, tool_schema, config):
        words = json.loads(registry.prompt_text(prompt).rsplit("<words>", 1)[1].split("</words>")[0])
        self.calls.append({"prompt": prompt, "tool": tool_name, "schema": tool_schema, "config": config, "words": words})
        scripted = self.script.get(len(self.calls))
        if isinstance(scripted, Exception):
            raise scripted
        if scripted is None:
            scripted = [{"id": w["id"], **KAISHI} for w in words]
        return registry.ToolCallResult(
            tool_input={"examples": scripted},
            meta={"model": self.model, "usage": {"input_tokens": 1000, "output_tokens": 200}},
        )


@pytest.fixture
def fake(monkeypatch, isolated_data_dir):
    vlm = FakeVlm()
    monkeypatch.setattr(registry, "get_vlm", lambda name: vlm)
    return vlm


def _items(n: int, headword: str = "嬉しい") -> list[str]:
    return [
        store.create_item("vocab", headword=f"{headword}{i}" if i else headword, reading="うれしい", meaning="glad")["id"]
        for i in range(n)
    ]


class TestGenerate:
    def test_generates_stores_and_records_model(self, fake):
        (item_id,) = _items(1)
        out = examples.generate_examples([item_id])
        (r,) = out["items"]
        assert r["status"] == "generated" and r["example"]["sentence"] == KAISHI["sentence"]
        stored = store.get_item("vocab", item_id)["example"]
        assert stored == r["example"]
        assert stored["source"] == "generated" and stored["model"] == preferences.get_active_vlm_model()
        assert stored["created_at"]
        assert {k: stored[k] for k in KAISHI} == KAISHI

    def test_call_shape_cache_effort_and_inputs(self, fake):
        (item_id,) = _items(1)
        store.update_item("vocab", item_id, pos=["adj-i"])
        examples.generate_examples([item_id])
        (call,) = fake.calls
        assert call["tool"] == "record_examples"
        assert call["prompt"][0]["cache"] is True and "cache" not in call["prompt"][1]
        assert call["config"]["effort"] == "medium" and call["config"]["model"] == preferences.get_active_vlm_model()
        assert call["words"] == [
            {"id": item_id, "headword": "嬉しい", "reading": "うれしい", "meaning": "glad", "pos": ["adj-i"]}
        ]

    def test_batches_of_20(self, fake):
        ids = _items(45)
        out = examples.generate_examples(ids)
        assert examples.BATCH_SIZE == 20
        assert [len(c["words"]) for c in fake.calls] == [20, 20, 5]
        assert all(r["status"] == "generated" for r in out["items"])
        assert [r["id"] for r in out["items"]] == ids

    def test_failures_retried_once_with_reasons(self, fake):
        a, b = _items(2)
        bad = {"id": b, **KAISHI, "gloss": "私は嬉しい"}
        fake.script = {1: [{"id": a, **KAISHI}, bad]}
        out = examples.generate_examples([a, b])
        assert [r["status"] for r in out["items"]] == ["generated", "generated"]
        assert len(fake.calls) == 2
        retry = fake.calls[1]["words"]
        assert [w["id"] for w in retry] == [b]
        assert "Japanese" in retry[0]["problem"]
        assert "problem" not in fake.calls[0]["words"][0]

    def test_dropped_when_it_fails_twice(self, fake):
        a, b = _items(2)
        bad = {"id": b, **KAISHI, "sentence": "短い。"}
        fake.script = {1: [{"id": a, **KAISHI}, bad], 2: [bad]}
        out = examples.generate_examples([a, b])
        assert [r["status"] for r in out["items"]] == ["generated", "failed"]
        assert "6 to 40" in out["items"][1]["reason"]
        assert len(fake.calls) == 2  # exactly one retry
        assert "example" not in store.get_item("vocab", b)

    def test_missing_entry_is_retried(self, fake):
        a, b = _items(2)
        fake.script = {1: [{"id": a, **KAISHI}]}
        out = examples.generate_examples([a, b])
        assert out["items"][1]["status"] == "generated"
        assert "no entry" in fake.calls[1]["words"][0]["problem"]

    def test_retry_call_error_keeps_first_pass(self, fake):
        a, b = _items(2)
        fake.script = {1: [{"id": a, **KAISHI}], 2: RuntimeError("boom")}
        out = examples.generate_examples([a, b])
        assert [r["status"] for r in out["items"]] == ["generated", "failed"]
        assert "retry call failed" in out["items"][1]["reason"]

    def test_kept_unless_force(self, fake):
        (item_id,) = _items(1)
        old = {**KAISHI, "gloss": "old", "source": "generated", "model": "x", "created_at": "t"}
        store.update_item("vocab", item_id, example=old)
        out = examples.generate_examples([item_id])
        assert out["items"][0] == {"id": item_id, "status": "kept", "example": old}
        assert fake.calls == []
        out = examples.generate_examples([item_id], force=True)
        assert out["items"][0]["status"] == "generated"
        assert store.get_item("vocab", item_id)["example"]["gloss"] == KAISHI["gloss"]

    def test_unknown_and_deleted_items_fail_without_a_call(self, fake):
        (item_id,) = _items(1)
        store.delete_item("vocab", item_id)
        out = examples.generate_examples(["nope", item_id])
        assert [r["status"] for r in out["items"]] == ["failed", "failed"]
        assert fake.calls == []

    def test_duplicate_ids_in_request_collapse(self, fake):
        (item_id,) = _items(1)
        out = examples.generate_examples([item_id, item_id])
        assert len(out["items"]) == 1 and len(fake.calls[0]["words"]) == 1

    def test_audit_and_cost_entries(self, fake):
        a, b = _items(2)
        fake.script = {1: [{"id": a, **KAISHI}]}
        out = examples.generate_examples([a, b])
        entries = [e for e in llm_audit.read_all() if e["job_type"] == "example_sentences"]
        assert len(entries) == 2  # first call plus the retry
        assert all(e["status"] == "success" and e["model"] == "fake-model" for e in entries)
        assert entries[0]["input_tokens"] == 1000 and entries[0]["output_tokens"] == 200
        usage = out["usage"]
        assert usage["calls"] == 2 and usage["input_tokens"] == 2000 and usage["output_tokens"] == 400

    def test_cost_in_usage_for_priced_model(self, fake):
        fake.model = "claude-sonnet-5-5"
        (item_id,) = _items(1)
        usage = examples.generate_examples([item_id])["usage"]
        assert usage["estimated_cost_usd"] == pytest.approx((1000 * 2.0 + 200 * 10.0) / 1_000_000)

    def test_call_error_is_audited_and_raised_when_nothing_worked(self, fake):
        (item_id,) = _items(1)
        fake.script = {1: RuntimeError("overloaded")}
        with pytest.raises(examples.ExamplesError) as exc:
            examples.generate_examples([item_id])
        assert exc.value.status == 502 and "overloaded" in exc.value.message
        (entry,) = [e for e in llm_audit.read_all() if e["job_type"] == "example_sentences"]
        assert entry["status"] == "error" and "overloaded" in entry["error"]

    def test_one_failed_batch_does_not_lose_the_other(self, fake):
        ids = _items(25)
        fake.script = {2: RuntimeError("overloaded")}
        out = examples.generate_examples(ids)
        statuses = [r["status"] for r in out["items"]]
        assert statuses == ["generated"] * 20 + ["failed"] * 5
        assert store.get_item("vocab", ids[0])["example"]

    def test_provider_not_configured(self, isolated_data_dir, monkeypatch):
        def boom(name):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        monkeypatch.setattr(registry, "get_vlm", boom)
        (item_id,) = _items(1)
        with pytest.raises(examples.ExamplesError) as exc:
            examples.generate_examples([item_id])
        assert exc.value.status == 503 and "ANTHROPIC_API_KEY" in exc.value.message

    def test_nothing_to_do_does_not_need_provider(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(registry, "get_vlm", lambda n: (_ for _ in ()).throw(AssertionError("called")))
        assert examples.generate_examples(["nope"])["items"][0]["status"] == "failed"

    def test_remove_example(self, fake):
        (item_id,) = _items(1)
        examples.generate_examples([item_id])
        assert examples.remove_example(item_id) is True
        assert store.get_item("vocab", item_id)["example"] is None
        assert examples.remove_example("nope") is False


# ---------- API ----------


class TestApi:
    def test_generate_endpoint(self, fake):
        a, b = _items(2)
        r = client.post("/api/vocab/examples", json={"item_ids": [a, b]})
        assert r.status_code == 200
        d = r.json()
        assert [i["status"] for i in d["items"]] == ["generated", "generated"]
        assert d["usage"]["calls"] == 1
        listed = client.get("/api/vocab").json()["items"]
        assert all(i["example"]["sentence"] == KAISHI["sentence"] for i in listed)

    def test_kept_and_force(self, fake):
        (a,) = _items(1)
        client.post("/api/vocab/examples", json={"item_ids": [a]})
        r = client.post("/api/vocab/examples", json={"item_ids": [a]}).json()
        assert r["items"][0]["status"] == "kept" and len(fake.calls) == 1
        r = client.post("/api/vocab/examples", json={"item_ids": [a], "force": True}).json()
        assert r["items"][0]["status"] == "generated" and len(fake.calls) == 2

    def test_id_count_limits(self, fake):
        assert client.post("/api/vocab/examples", json={"item_ids": []}).status_code == 422
        assert client.post("/api/vocab/examples", json={"item_ids": [f"x{i}" for i in range(41)]}).status_code == 422
        assert client.post("/api/vocab/examples", json={}).status_code == 422
        ok = client.post("/api/vocab/examples", json={"item_ids": [f"x{i}" for i in range(40)]})
        assert ok.status_code == 200 and len(ok.json()["items"]) == 40

    def test_provider_not_configured_is_503(self, isolated_data_dir, monkeypatch):
        def boom(name):
            raise RuntimeError("ANTHROPIC_API_KEY is not set; configure it in .env")

        monkeypatch.setattr(registry, "get_vlm", boom)
        (a,) = _items(1)
        r = client.post("/api/vocab/examples", json={"item_ids": [a]})
        assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]

    def test_llm_failure_is_502(self, fake):
        (a,) = _items(1)
        fake.script = {1: RuntimeError("down")}
        r = client.post("/api/vocab/examples", json={"item_ids": [a]})
        assert r.status_code == 502

    def test_delete_example(self, fake):
        (a,) = _items(1)
        client.post("/api/vocab/examples", json={"item_ids": [a]})
        assert client.delete(f"/api/vocab/{a}/example").status_code == 200
        item = client.get("/api/vocab").json()["items"][0]
        assert item["example"] is None
        assert client.delete("/api/vocab/nope/example").status_code == 404
        # the item itself is still there
        assert client.get("/api/vocab").json()["total"] == 1
