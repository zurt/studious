"""Tests for benchmarks/model_eval — pure logic only, no network calls.

Imports the model_eval package by inserting the repo root onto sys.path (it
lives outside backend/, alongside the app itself), matching the pattern
benchmarks/run_benchmark.py uses in reverse for backend/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.model_eval import analysis, items, judging, pricing, sampling, store  # noqa: E402


# ---------------------------------------------------------------------------
# Fake store helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_document(
    tmp_path: Path,
    doc_id: str,
    name: str,
    chapters: dict[str, list[dict]],
) -> Path:
    """Build `<tmp_path>/documents/<doc_id>/...` with the real on-disk layout.

    `chapters` maps chapter_id -> list of region dicts (page, tag, and
    optionally continues_to/transcription_md/transcribed_model).
    """
    doc_dir = tmp_path / "documents" / doc_id
    _write_json(doc_dir / "meta.json", {"id": doc_id, "name": name, "page_count": 50})
    for chapter_id, regions in chapters.items():
        chapter_dir = doc_dir / "chapters" / chapter_id
        _write_json(chapter_dir / "meta.json", {"id": chapter_id, "title": chapter_id})
        for i, region in enumerate(regions):
            region_id = region.get("id", f"{chapter_id}-r{i:03d}")
            payload = {
                "id": region_id,
                "chapter_id": chapter_id,
                "page": region["page"],
                "bbox": region.get("bbox", [0.0, 0.0, 1.0, 1.0]),
                "tag": region["tag"],
                "label": region.get("label", ""),
                "transcription_md": region.get("transcription_md"),
                "transcribed_at": region.get("transcribed_at"),
                "transcribed_model": region.get("transcribed_model"),
                "continues_to": region.get("continues_to"),
            }
            _write_json(chapter_dir / "regions" / f"{region_id}.json", payload)
    return doc_dir


# ---------------------------------------------------------------------------
# items.py
# ---------------------------------------------------------------------------


def test_classify_source_case_insensitive():
    assert items.classify_source("Workbook - Chapter 3.pdf") == "workbook"
    assert items.classify_source("WORKBOOK.pdf") == "workbook"
    assert items.classify_source("Authentic Japanese.pdf") == "textbook"
    assert items.classify_source(None) == "textbook"


def test_item_id_builders():
    assert items.region_item_id("textbook", "vocab_list", "abcdef0123456789") == (
        "tb-r-vocab_list-abcdef01"
    )
    assert items.page_item_id("workbook", 7) == "wb-p-0007"


def test_prompt_kind_mapping():
    assert items.prompt_kind_for("page", None) == "page"
    assert items.prompt_kind_for("region", "vocab_list") == "vocab_list"
    for tag in ("exercises", "grammar_points", "reading_passage", "instructions", "other"):
        assert items.prompt_kind_for("region", tag) == "region"


def test_dedupe_item_id():
    used = {"tb-p-0001"}
    assert items.dedupe_item_id("tb-p-0001", "doc123456", used) == "tb-p-0001-doc123"
    assert items.dedupe_item_id("tb-p-0002", "doc123456", used) == "tb-p-0002"


# ---------------------------------------------------------------------------
# store.py enumeration against a fake on-disk store
# ---------------------------------------------------------------------------


def test_enumerate_store_reads_layout_and_classifies_source(tmp_path: Path):
    _make_document(
        tmp_path,
        "doc-tb",
        "Authentic Japanese.pdf",
        {
            "ch1": [
                {"page": 1, "tag": "reading_passage"},
                {"page": 1, "tag": "vocab_list"},
                {"page": 2, "tag": "exercises"},
            ]
        },
    )
    _make_document(
        tmp_path,
        "doc-wb",
        "Workbook.pdf",
        {"ch1": [{"page": 1, "tag": "exercises"}]},
    )

    enumerated = store.enumerate_store(tmp_path)
    sources = {r["doc_id"]: r["source"] for r in enumerated.region_candidates}
    assert sources["doc-tb"] == "textbook"
    assert sources["doc-wb"] == "workbook"
    # Page candidates are content pages (>=1 region), deduped per (doc, page).
    tb_pages = {p["page"] for p in enumerated.page_candidates if p["doc_id"] == "doc-tb"}
    assert tb_pages == {1, 2}


def test_enumerate_store_is_chained_detects_continuation(tmp_path: Path):
    _make_document(
        tmp_path,
        "doc-tb",
        "Textbook.pdf",
        {
            "ch1": [
                {"id": "head", "page": 1, "tag": "reading_passage", "continues_to": "tail"},
                {"id": "tail", "page": 2, "tag": "reading_passage"},
                {"id": "solo", "page": 3, "tag": "exercises"},
            ]
        },
    )
    enumerated = store.enumerate_store(tmp_path)
    by_id = {r["id"]: r for r in enumerated.region_candidates}
    assert by_id["head"]["is_chained"] is True
    assert by_id["tail"]["is_chained"] is True
    assert by_id["solo"]["is_chained"] is False


# ---------------------------------------------------------------------------
# sampling.py: determinism, difference across seeds, shortfall handling
# ---------------------------------------------------------------------------


def _region_candidates(source: str, tag: str, n: int) -> list[dict]:
    return [
        {"id": f"{source}-{tag}-{i:03d}", "source": source, "tag": tag, "doc_id": "doc", "page": i}
        for i in range(n)
    ]


def test_sample_stratum_determinism_same_seed():
    import random

    candidates = _region_candidates("textbook", "exercises", 20)
    out1 = sampling.sample_stratum(random.Random(20260706), candidates, 5)
    out2 = sampling.sample_stratum(random.Random(20260706), candidates, 5)
    assert [c["id"] for c in out1.selected] == [c["id"] for c in out2.selected]
    assert out1.shortfall == 0


def test_sample_stratum_different_seed_differs():
    import random

    candidates = _region_candidates("textbook", "exercises", 20)
    out1 = sampling.sample_stratum(random.Random(1), candidates, 5)
    out2 = sampling.sample_stratum(random.Random(2), candidates, 5)
    assert [c["id"] for c in out1.selected] != [c["id"] for c in out2.selected]


def test_sample_stratum_shortfall_takes_all_candidates():
    import random

    candidates = _region_candidates("workbook", "exercises", 3)
    out = sampling.sample_stratum(random.Random(1), candidates, 7)
    assert out.shortfall == 4
    assert len(out.selected) == 3
    assert {c["id"] for c in out.selected} == {c["id"] for c in candidates}


def test_sample_pages_avoiding_used_soft_constraint():
    import random

    pages = [{"id": f"doc:{i:04d}", "doc_id": "doc", "page": i} for i in range(1, 6)]
    used = {("doc", 1), ("doc", 2), ("doc", 3), ("doc", 4)}
    out = sampling.sample_pages_avoiding_used(
        random.Random(2), pages, 2, used, key=lambda c: (c["doc_id"], c["page"])
    )
    selected_pages = {c["page"] for c in out.selected}
    assert 5 in selected_pages  # the unused page is always taken first
    assert out.shortfall == 0
    assert len(out.selected) == 2


def test_select_dataset_end_to_end_determinism_and_shortfall(tmp_path: Path):
    _make_document(
        tmp_path,
        "doc-tb",
        "Textbook.pdf",
        {
            "ch1": [{"page": i, "tag": "exercises"} for i in range(1, 9)]
            + [{"page": 20 + i, "tag": "vocab_list"} for i in range(2)]
        },
    )
    enumerated = store.enumerate_store(tmp_path)
    quotas = {"textbook": {"region": {"exercises": 5, "vocab_list": 4}, "page": 2}}

    sel_a = sampling.select_dataset(
        enumerated.region_candidates, enumerated.page_candidates, seed=20260706, quotas=quotas
    )
    sel_b = sampling.select_dataset(
        enumerated.region_candidates, enumerated.page_candidates, seed=20260706, quotas=quotas
    )
    sel_c = sampling.select_dataset(
        enumerated.region_candidates, enumerated.page_candidates, seed=1, quotas=quotas
    )

    ids_a = sorted(r["id"] for r in sel_a.selected_regions)
    ids_b = sorted(r["id"] for r in sel_b.selected_regions)
    ids_c = sorted(r["id"] for r in sel_c.selected_regions)
    assert ids_a == ids_b
    assert ids_a != ids_c

    vocab_stats = next(s for s in sel_a.stratum_stats if s.stratum == "textbook/region/vocab_list")
    assert vocab_stats.candidate_count == 2
    assert vocab_stats.quota == 4
    assert vocab_stats.shortfall == 2
    assert vocab_stats.selected_count == 2


# ---------------------------------------------------------------------------
# pricing.py
# ---------------------------------------------------------------------------


def test_estimate_cost_basic_input_output():
    cost = pricing.estimate_cost(
        "claude-sonnet-5", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    )
    assert cost == pytest.approx(2.00 + 10.00)


def test_estimate_cost_with_cache_tokens():
    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_input_tokens": 2000,
        "cache_creation_input_tokens": 3000,
    }
    cost = pricing.estimate_cost("claude-haiku-4-5", usage)
    expected = (
        1000 * 1.00 + 500 * 5.00 + 2000 * (1.00 * 0.1) + 3000 * (1.00 * 1.25)
    ) / 1_000_000
    assert cost == pytest.approx(expected)


def test_estimate_cost_unknown_model_returns_none():
    assert pricing.estimate_cost("some-unreleased-model", {"input_tokens": 1}) is None


def test_estimate_cost_dated_suffix_alias_resolves():
    cost = pricing.estimate_cost(
        "claude-haiku-4-5-20251001", {"input_tokens": 1_000_000, "output_tokens": 0}
    )
    assert cost == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# judging.py: label shuffling determinism + round trip
# ---------------------------------------------------------------------------


def test_shuffle_candidates_deterministic_for_same_key():
    models = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8"]
    map1 = judging.shuffle_candidates("20260706:tb-r-vocab_list-abc12345", models)
    map2 = judging.shuffle_candidates("20260706:tb-r-vocab_list-abc12345", models)
    assert map1 == map2
    assert set(map1.values()) == set(models)


def test_shuffle_candidates_differs_per_item():
    models = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8"]
    map1 = judging.shuffle_candidates("20260706:item-a", models)
    map2 = judging.shuffle_candidates("20260706:item-b", models)
    # Not guaranteed different by pigeonhole for 3 items, but with a real RNG
    # over many item ids at least the mapping keys round-trip correctly.
    assert judging.invert_label_map(map1)[map1["A"]] == "A"
    assert map1 != {} and map2 != {}


def test_label_to_model_round_trip():
    models = ["a", "b", "c"]
    label_to_model = judging.shuffle_candidates("seed:item", models)
    model_to_label = judging.invert_label_map(label_to_model)
    for label, model in label_to_model.items():
        assert model_to_label[model] == label


def test_clamp_score_bounds():
    assert judging.clamp_score(-5) == 0
    assert judging.clamp_score(15) == 10
    assert judging.clamp_score(7.6) == 8
    assert judging.clamp_score("not a number") == 0


def test_validate_and_clamp_response_normalizes_and_fills_ranking():
    raw = {
        "candidates": [
            {
                "label": "A",
                "character_accuracy": 11,
                "completeness": 8,
                "formatting": 8,
                "hallucination_control": 8,
                "overall": 8,
                "notes": "good",
            },
            {
                "label": "B",
                "character_accuracy": -2,
                "completeness": 5,
                "formatting": 5,
                "hallucination_control": 5,
                "overall": 5,
                "notes": "worse",
            },
        ],
        "ranking": ["A"],  # missing B — should be appended
        "rationale": "A is more accurate.",
    }
    normalized = judging.validate_and_clamp_response(raw, ["A", "B"])
    assert normalized["candidates"][0]["character_accuracy"] == 10
    assert normalized["candidates"][1]["character_accuracy"] == 0
    assert normalized["ranking"] == ["A", "B"]


def test_validate_and_clamp_response_rejects_empty_candidates():
    with pytest.raises(ValueError):
        judging.validate_and_clamp_response({"candidates": [], "ranking": [], "rationale": ""}, ["A"])


# ---------------------------------------------------------------------------
# analysis.py: aggregation, win matrix, sign test
# ---------------------------------------------------------------------------


def _synthetic_judgment(winner: str, loser: str, winner_score=8, loser_score=5) -> dict:
    return {
        "status": "ok",
        "label_to_model": {"A": winner, "B": loser},
        "candidates": [
            {
                "label": "A",
                "character_accuracy": winner_score,
                "completeness": winner_score,
                "formatting": winner_score,
                "hallucination_control": winner_score,
                "overall": winner_score,
                "notes": "",
            },
            {
                "label": "B",
                "character_accuracy": loser_score,
                "completeness": loser_score,
                "formatting": loser_score,
                "hallucination_control": loser_score,
                "overall": loser_score,
                "notes": "",
            },
        ],
        "ranking_models": [winner, loser],
    }


def test_aggregate_judgments_mean_rank_and_win_matrix():
    judgments = [_synthetic_judgment("sonnet", "haiku") for _ in range(4)]
    agg = analysis.aggregate_judgments(judgments)
    assert agg["per_model"]["sonnet"]["mean_rank"] == 1.0
    assert agg["per_model"]["haiku"]["mean_rank"] == 2.0
    assert agg["per_model"]["sonnet"]["rank1_count"] == 4
    assert agg["per_model"]["sonnet"]["mean_dims"]["overall"] == 8.0
    assert agg["win_matrix"]["sonnet"]["haiku"] == 4


def test_pairwise_sign_test_known_case():
    # sonnet beats haiku all 4 times -> two-sided sign test p-value = 0.125.
    judgments = [_synthetic_judgment("sonnet", "haiku") for _ in range(4)]
    agg = analysis.aggregate_judgments(judgments)
    tests = analysis.pairwise_sign_tests(agg["win_matrix"])
    assert len(tests) == 1
    t = tests[0]
    assert {t["model_a"], t["model_b"]} == {"sonnet", "haiku"}
    assert t["preferred"] == "sonnet"
    assert t["p_value"] == pytest.approx(0.125)


def test_binomial_sign_test_even_split_is_not_significant():
    # 2 wins out of 4 -> maximally uncertain, p-value 1.0.
    assert analysis.binomial_sign_test(2, 4) == pytest.approx(1.0)


def test_aggregate_transcriptions_cost_and_duration():
    transcriptions = [
        {"status": "ok", "model": "sonnet", "duration_ms": 1000, "estimated_cost_usd": 0.01, "markdown": "abc"},
        {"status": "ok", "model": "sonnet", "duration_ms": 2000, "estimated_cost_usd": 0.02, "markdown": "abcdef"},
        {"status": "error", "model": "sonnet", "duration_ms": 500},
    ]
    agg = analysis.aggregate_transcriptions(transcriptions)
    assert agg["sonnet"]["n"] == 2
    assert agg["sonnet"]["avg_duration_ms"] == pytest.approx(1500)
    assert agg["sonnet"]["avg_cost_usd"] == pytest.approx(0.015)
    assert agg["sonnet"]["output_chars"]["mean"] == pytest.approx((3 + 6) / 2)
