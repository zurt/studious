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
    assert call["fallbacks"] == [{"model": "claude-opus-4-8"}]


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
