"""Tests for the regression benchmark (benchmarks/run_benchmark.py,
benchmarks/compare.py, benchmarks/model_eval/reference_judge.py) — pure
logic and a fake judge client only, no network calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks import compare, run_benchmark  # noqa: E402
from benchmarks.model_eval import pricing, reference_judge  # noqa: E402
from benchmarks.model_eval.judge_cmd import VOCAB_GLOSS_POLICY  # noqa: E402
from benchmarks.model_eval.judging import RUBRIC_DIMENSIONS as _DIMS  # noqa: E402

# ---------------------------------------------------------------------------
# String metrics
# ---------------------------------------------------------------------------


def test_cer_is_zero_for_identical_text_ignoring_outer_whitespace():
    assert run_benchmark.character_error_rate("日本語\n", "  日本語") == 0.0


def test_cer_counts_one_wrong_character():
    # The weakness the judge exists to cover: a wrong furigana reading is a
    # single-character error however much it matters to a learner.
    assert run_benchmark.character_error_rate("慰める（なぐさめる）", "慰める（なぐめめる）") == pytest.approx(0.1)


def test_cer_with_empty_reference():
    assert run_benchmark.character_error_rate("", "") == 0.0
    assert run_benchmark.character_error_rate("", "x") == 1.0


def test_line_accuracy_counts_exact_reference_lines():
    assert run_benchmark.line_accuracy("a\nb\n\nc", "a\nx\nc") == pytest.approx(2 / 3)
    assert run_benchmark.line_accuracy("", "anything") == 1.0


def test_evaluate_breakdown_reports_count_and_missing_vocab():
    tool_input = {
        "sentences": [
            {"text": "父は料理が好きだ。", "gloss": "g", "vocab": [{"word": "料理"}]},
            {"text": "母は違う。", "gloss": "g"},
        ]
    }
    result = run_benchmark.evaluate_breakdown(
        tool_input, {"expected_sentence_count": 2, "expected_vocab": ["料理", "父", "健康"]}
    )
    assert result["sentence_count_match"] is True
    assert result["vocab_found"] == ["料理", "父"]  # 父 found in sentence text
    assert result["vocab_missing"] == ["健康"]
    assert result["vocab_recall"] == pytest.approx(0.6667)


# ---------------------------------------------------------------------------
# Reference judge
# ---------------------------------------------------------------------------


def _judge_message(payload: dict, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(
            input_tokens=1_000_000,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


_GOOD_PAYLOAD = {
    "candidates": [
        {
            "label": "A",
            "character_accuracy": 9,
            "completeness": 10,
            "formatting": 8,
            "hallucination_control": 10,
            "overall": 9,
            "notes": "one furigana slip",
        }
    ],
    "ranking": ["A"],
    "rationale": "close to the reference",
}


class _FakeBetaMessages:
    def __init__(self, message):
        self.message = message
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.message


def _fake_client(message):
    beta_messages = _FakeBetaMessages(message)
    return SimpleNamespace(beta=SimpleNamespace(messages=beta_messages)), beta_messages


def test_reference_judge_content_shows_image_reference_and_candidate():
    content = reference_judge.build_reference_judge_content(
        "QUJD", "region", "REFERENCE TEXT", "CANDIDATE TEXT"
    )
    assert content[0]["type"] == "image"
    assert content[0]["source"] == {"type": "base64", "media_type": "image/png", "data": "QUJD"}
    text = content[1]["text"]
    assert "trust the image" in text
    assert text.index("REFERENCE TEXT") < text.index("CANDIDATE TEXT")
    assert VOCAB_GLOSS_POLICY not in text


def test_reference_judge_content_explains_gloss_policy_for_vocab_lists():
    content = reference_judge.build_reference_judge_content("QUJD", "vocab_list", "r", "c")
    assert VOCAB_GLOSS_POLICY in content[1]["text"]


def test_judge_against_reference_returns_scores_and_cost():
    client, beta_messages = _fake_client(_judge_message(_GOOD_PAYLOAD))
    result = reference_judge.judge_against_reference(
        client, b"png-bytes", "region", "ref", "cand", "claude-fable-5", "claude-opus-4-8"
    )
    assert result["status"] == "ok"
    assert result["overall"] == 9
    assert result["character_accuracy"] == 9
    assert result["notes"] == "one furigana slip"
    assert result["judge_model"] == "claude-fable-5"
    assert result["estimated_cost_usd"] == pytest.approx(10.00)
    assert "label" not in result
    call = beta_messages.calls[0]
    assert call["model"] == "claude-fable-5"
    # The pinned SDK has no typed `fallbacks` parameter, so it rides in extra_body.
    assert call["extra_body"] == {"fallbacks": [{"model": "claude-opus-4-8"}]}
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "fallbacks" not in call


def test_judge_uses_category_routed_fallback_by_default_and_records_who_answered():
    message = _judge_message(_GOOD_PAYLOAD)
    message.model = "claude-opus-4-8"  # the fallback answered
    client, beta_messages = _fake_client(message)
    result = reference_judge.judge_against_reference(
        client, b"x", "page", "r", "c", "claude-fable-5-2", "default"
    )
    assert beta_messages.calls[0]["extra_body"] == {"fallbacks": "default"}
    assert result["judge_model"] == "claude-fable-5-2"
    assert result["served_by_model"] == "claude-opus-4-8"


def test_judge_retries_without_fallback_when_the_api_rejects_it():
    import anthropic
    import httpx2

    from benchmarks.model_eval import judge_cmd

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    rejection = anthropic.BadRequestError(
        "fallbacks: this model does not support server-side fallback",
        response=httpx2.Response(400, request=request),
        body=None,
    )

    class _Rejecting:
        def create(self, **kwargs):
            raise rejection

    plain = _FakeBetaMessages(_judge_message(_GOOD_PAYLOAD))
    client = SimpleNamespace(beta=SimpleNamespace(messages=_Rejecting()), messages=plain)
    message = judge_cmd.call_judge(client, "claude-haiku-5-5", "default", [])
    assert message.stop_reason == "end_turn"
    assert "extra_body" not in plain.calls[0] and "betas" not in plain.calls[0]

    # An unrelated 400 is not swallowed.
    other = anthropic.BadRequestError(
        "image too large", response=httpx2.Response(400, request=request), body=None
    )

    class _Other:
        def create(self, **kwargs):
            raise other

    client = SimpleNamespace(beta=SimpleNamespace(messages=_Other()), messages=plain)
    with pytest.raises(anthropic.BadRequestError):
        judge_cmd.call_judge(client, "claude-fable-5-2", "default", [])


def test_judge_against_reference_clamps_out_of_range_scores():
    payload = json.loads(json.dumps(_GOOD_PAYLOAD))
    payload["candidates"][0]["overall"] = 14
    client, _ = _fake_client(_judge_message(payload))
    result = reference_judge.judge_against_reference(client, b"x", "page", "r", "c", "j", "f")
    assert result["overall"] == 10


def test_judge_against_reference_records_refusal_and_bad_json_without_raising():
    client, _ = _fake_client(_judge_message(_GOOD_PAYLOAD, stop_reason="refusal"))
    assert reference_judge.judge_against_reference(client, b"x", "page", "r", "c", "j", "f")[
        "status"
    ] == "refused"

    bad = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text="not json")], usage=None
    )
    client, _ = _fake_client(bad)
    result = reference_judge.judge_against_reference(client, b"x", "page", "r", "c", "j", "f")
    assert result["status"] == "error"
    assert "parse" in result["error"]


def test_judge_against_reference_records_api_errors_without_raising():
    class _Boom:
        def create(self, **kwargs):
            raise RuntimeError("overloaded")

    client = SimpleNamespace(beta=SimpleNamespace(messages=_Boom()))
    result = reference_judge.judge_against_reference(client, b"x", "page", "r", "c", "j", "f")
    assert result == {"status": "error", "error": "overloaded", "judge_model": "j"}


# ---------------------------------------------------------------------------
# Summary + comparison
# ---------------------------------------------------------------------------


def _fixture(name: str, overall: int | None = None, cer: float | None = None, status="ok"):
    entry: dict = {"fixture": name, "status": "ok"}
    if cer is not None:
        entry["cer"] = cer
    if overall is not None or status != "ok":
        entry["judge"] = {
            "status": status,
            "character_accuracy": overall, "completeness": overall, "formatting": overall,
            "hallucination_control": overall, "overall": overall,
            "estimated_cost_usd": 0.01,
        }
    return entry


def test_summarize_judgments_averages_scored_fixtures_and_counts_failures():
    results = [_fixture("a", 9), _fixture("b", 6), _fixture("c", status="error"), _fixture("d")]
    summary = run_benchmark.summarize_judgments(results)
    assert summary["judged"] == 2
    assert summary["judge_failures"] == 1
    assert summary["avg_judge_overall"] == 7.5
    assert summary["min_judge_overall"] == 6
    assert summary["judge_cost_usd"] == 0.02


def test_summarize_judgments_is_empty_when_judge_was_off():
    assert run_benchmark.summarize_judgments([_fixture("a", cer=0.1)]) == {}


def test_classify_prefers_judge_score_over_cer():
    # CER got worse but the judge says quality held: not a regression.
    assert compare.classify(_fixture("a", 9, cer=0.02), _fixture("a", 9, cer=0.10)) == ""
    # CER unchanged but the judge dropped a point: regression.
    assert compare.classify(_fixture("a", 9, cer=0.02), _fixture("a", 8, cer=0.02)) == "regression"
    assert compare.classify(_fixture("a", 7), _fixture("a", 9)) == "improved"


def test_classify_falls_back_to_cer_without_judge_scores():
    assert compare.classify(_fixture("a", cer=0.02), _fixture("a", cer=0.05)) == "regression"
    assert compare.classify(_fixture("a", cer=0.05), _fixture("a", cer=0.02)) == "improved"
    assert compare.classify(_fixture("a", cer=0.02), _fixture("a", cer=0.025)) == ""
    # One side judged, the other not: only CER is comparable.
    assert compare.classify(_fixture("a", 9, cer=0.02), _fixture("a", cer=0.05)) == "regression"


def test_compare_returns_regression_count_and_warns_on_judge_change(tmp_path, capsys):
    base = {"judge_model": "j1", "fixtures": [_fixture("a", 9), _fixture("b", 8)]}
    curr = {"judge_model": "j2", "fixtures": [_fixture("a", 7), _fixture("b", 8)]}
    (tmp_path / "base.json").write_text(json.dumps(base))
    (tmp_path / "curr.json").write_text(json.dumps(curr))
    assert compare.compare(tmp_path / "base.json", tmp_path / "curr.json") == 1
    out = capsys.readouterr().out
    assert "REGRESSION" in out
    assert "not directly comparable" in out


# ---------------------------------------------------------------------------
# One pricing table
# ---------------------------------------------------------------------------


def test_eval_pricing_uses_the_apps_table():
    from app.config import MODEL_PRICING

    table = pricing.pricing_table()
    for model, row in MODEL_PRICING.items():
        assert table[model] == row
    assert "claude-fable-5" in table  # eval-only judge model


def test_eval_pricing_honours_app_cache_rate_overrides():
    from app.config import MODEL_PRICING

    row = MODEL_PRICING["claude-opus-5-5"]
    cost = pricing.estimate_cost(
        "claude-opus-5-5",
        {"cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000},
    )
    assert cost == pytest.approx(row["cache_read"] + row["cache_write"])


def test_dated_alias_resolves_to_the_longest_matching_model():
    # "claude-sonnet-5-5-<date>" must not be priced as "claude-sonnet-5".
    from app.config import MODEL_PRICING

    cost = pricing.estimate_cost(
        "claude-opus-5-5-20260901", {"input_tokens": 1_000_000, "output_tokens": 0}
    )
    assert cost == pytest.approx(MODEL_PRICING["claude-opus-5-5"]["input"])
    assert pricing.estimate_cost("claude-sonnet-50", {"input_tokens": 1}) is None


# ---------------------------------------------------------------------------
# Whole run over the committed fixtures, model and judge stubbed
# ---------------------------------------------------------------------------


def test_run_benchmark_judges_every_fixture_that_has_a_reference(monkeypatch):
    seen: list[tuple[str, str]] = []

    def fake_transcription(image_path, engine, provider, prompt_kind="page"):
        reference = run_benchmark.GROUND_TRUTH_DIR / f"{image_path.parent.name}.md"
        return {
            "markdown": reference.read_text("utf-8"),
            "meta": {},
            "duration_ms": 5,
            "model": "stub-model",
        }

    def fake_breakdown(text, provider):
        return {"tool_input": {"sentences": []}, "meta": {}, "duration_ms": 5}

    def fake_judge(image_path, prompt_kind, reference_md, candidate_md):
        assert reference_md == candidate_md
        seen.append((image_path.parent.name, prompt_kind))
        return {"status": "ok", **{d: 10 for d in _DIMS}, "estimated_cost_usd": 0.0}

    monkeypatch.setattr(run_benchmark, "run_transcription", fake_transcription)
    monkeypatch.setattr(run_benchmark, "run_breakdown", fake_breakdown)

    result = run_benchmark.run_benchmark("vlm", "anthropic", judge=fake_judge)

    with_reference = [
        r for r in result["fixtures"] if r.get("kind") != "breakdown" and "cer" in r
    ]
    assert with_reference, "expected committed fixtures with ground truth"
    assert len(seen) == len(with_reference)
    assert all(r["cer"] == 0.0 and r["model"] == "stub-model" for r in with_reference)
    assert ("vocab-young-japanese-1", "vocab_list") in seen
    assert result["summary"]["judged"] == len(with_reference)
    assert result["summary"]["avg_judge_overall"] == 10
    assert result["summary"]["errors"] == 0


def test_run_benchmark_without_judge_reports_string_metrics_only(monkeypatch):
    monkeypatch.setattr(
        run_benchmark,
        "run_transcription",
        lambda *a, **k: {"markdown": "x", "meta": {}, "duration_ms": 1, "model": "m"},
    )
    monkeypatch.setattr(
        run_benchmark,
        "run_breakdown",
        lambda *a, **k: {"tool_input": {"sentences": []}, "meta": {}, "duration_ms": 1},
    )
    result = run_benchmark.run_benchmark("vlm", "anthropic")
    assert all("judge" not in r for r in result["fixtures"])
    assert "avg_cer" in result["summary"]
    assert "judged" not in result["summary"]


# ---------------------------------------------------------------------------
# New-models run: prices, dataset v2, spend cap
# ---------------------------------------------------------------------------


def test_new_candidate_and_judge_models_are_priced():
    assert pricing.estimate_cost(
        "claude-fable-5-2", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    ) == pytest.approx(48.00)
    assert pricing.estimate_cost(
        "claude-haiku-5-5", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    ) == pytest.approx(0.60)
    for model in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-5", "claude-opus-4-8"):
        assert pricing.estimate_cost(model, {"input_tokens": 1}) is not None


def _quota_total(quotas: dict) -> int:
    return sum(sum(q["region"].values()) + q["page"] for q in quotas.values())


def test_v2_quotas_grow_the_dataset_and_favour_full_pages():
    from benchmarks.model_eval import sampling

    assert _quota_total(sampling.QUOTAS_V1) == 31
    assert _quota_total(sampling.QUOTAS_V2) == 48
    assert sampling.DEFAULT_QUOTAS is sampling.QUOTAS_V2
    pages = lambda q: sum(src["page"] for src in q.values())  # noqa: E731
    assert pages(sampling.QUOTAS_V2) == 14 and pages(sampling.QUOTAS_V1) == 6


def test_exclude_documents_matches_filename_substrings_case_insensitively():
    from benchmarks.model_eval import sampling

    candidates = [
        {"id": "a", "doc_filename": "Tobira Textbook.pdf"},
        {"id": "b", "doc_filename": "魔女の宅急便.pdf"},
        {"id": "c", "doc_filename": "tobira WORKBOOK.pdf"},
        {"id": "d"},
    ]
    kept = sampling.exclude_documents(candidates, ["魔女", "workbook"])
    assert [c["id"] for c in kept] == ["a", "d"]
    assert sampling.exclude_documents(candidates, []) == candidates


def test_budget_guard_stops_before_an_item_it_cannot_afford():
    from benchmarks.model_eval.run_cmd import BudgetGuard

    guard = BudgetGuard(1.00)
    assert guard.can_start_item()  # nothing spent; first-item allowance fits
    guard.begin_item()
    guard.add(0.30)
    guard.add(0.10)  # item one cost 0.40
    guard.begin_item()
    guard.add(0.15)  # item two cost 0.15; spent 0.55
    assert guard.can_start_item()  # 0.55 + 0.40 reserve <= 1.00
    guard.begin_item()
    guard.add(0.10)  # spent 0.65
    assert not guard.can_start_item()  # 0.65 + 0.40 > 1.00
    assert guard.spent == pytest.approx(0.65)


def test_budget_guard_counts_results_from_an_interrupted_run(tmp_path):
    from benchmarks.model_eval.run_cmd import BudgetGuard

    (tmp_path / "m1.json").write_text(json.dumps({"estimated_cost_usd": 0.5}))
    (tmp_path / "m2.json").write_text(json.dumps({"status": "error"}))
    guard = BudgetGuard(0.6)
    guard.add_existing(tmp_path, ["m1", "m2", "missing"])
    assert guard.spent == pytest.approx(0.5)
    assert not guard.can_start_item()


def test_budget_guard_without_a_budget_never_stops():
    from benchmarks.model_eval.run_cmd import BudgetGuard

    guard = BudgetGuard(None)
    guard.add(1000.0)
    assert guard.can_start_item()


def test_run_dataset_stops_at_the_budget_between_items_and_resumes(tmp_path, monkeypatch):
    from app.providers import registry
    from app.providers.registry import TranscriptionResult
    from benchmarks.model_eval import run_cmd

    dataset = tmp_path / "dataset"
    item_ids = ["item-1", "item-2", "item-3"]
    for item_id in item_ids:
        item_dir = dataset / "items" / item_id
        item_dir.mkdir(parents=True)
        (item_dir / "input.png").write_bytes(b"png")
        (item_dir / "meta.json").write_text(json.dumps({"prompt_kind": "region"}))
    (dataset / "manifest.json").write_text(json.dumps({"item_ids": item_ids}))

    class _Provider:
        calls = 0

        def transcribe(self, image_bytes, prompt, config):
            _Provider.calls += 1
            # 100K input tokens of Sonnet 5 = $0.20 per call.
            return TranscriptionResult(
                markdown="text", raw="text",
                meta={"usage": {"input_tokens": 100_000, "output_tokens": 0}},
            )

    monkeypatch.setattr(registry, "bootstrap_default_providers", lambda: None)
    monkeypatch.setattr(registry, "get_vlm", lambda name: _Provider())

    models = ["claude-sonnet-5", "claude-opus-4-8"]  # $0.20 + $0.50 = $0.70 an item
    meta = run_cmd.run_dataset(dataset, tmp_path / "runs", models, "r1", budget_usd=1.00)

    # Item 1 runs ($0.70); item 2 would need another $0.70 and is not started.
    assert meta["budget_stopped_before"] == "item-2"
    assert meta["estimated_cost_usd"] == pytest.approx(0.70)
    assert _Provider.calls == 2
    done = sorted(p.name for p in (tmp_path / "runs" / "r1" / "transcriptions").iterdir())
    assert done == ["item-1"]

    # Same run id, bigger budget: picks up where it stopped, counting item 1.
    meta = run_cmd.run_dataset(dataset, tmp_path / "runs", models, "r1", budget_usd=1.50)
    assert meta["budget_stopped_before"] == "item-3"
    assert meta["estimated_cost_usd"] == pytest.approx(1.40)
    assert meta["totals"]["skipped"] == 2 and _Provider.calls == 4

    # No budget: finishes.
    meta = run_cmd.run_dataset(dataset, tmp_path / "runs", models, "r1")
    assert meta["budget_stopped_before"] is None and _Provider.calls == 6
