"""Pure aggregation logic for the `analyze` subcommand.

Every function here takes already-loaded dicts (judgments, transcription
results, item metadata) and returns plain dicts/numbers — no file I/O, no
network — so test_model_eval.py can feed synthetic fixtures directly.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any

from .judging import RUBRIC_DIMENSIONS


def aggregate_judgments(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a list of successful (`status == "ok"`) judgment payloads.

    Each judgment is expected to have: `label_to_model`, `candidates` (list of
    {label, character_accuracy, completeness, formatting,
    hallucination_control, overall, notes}), and `ranking_models` (labels
    resolved to model names, best first).

    Returns per-model means/ranks and a pairwise win matrix, where
    win_matrix[a][b] = number of items in which model a ranked ahead of b.
    """
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: dict[str, int] = defaultdict(int)
    ranks: dict[str, list[int]] = defaultdict(list)
    win_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for j in judgments:
        if j.get("status") not in (None, "ok"):
            continue
        label_to_model = j.get("label_to_model") or {}
        for c in j.get("candidates") or []:
            model = label_to_model.get(c.get("label"))
            if not model:
                continue
            counts[model] += 1
            for dim in RUBRIC_DIMENSIONS:
                sums[model][dim] += float(c.get(dim) or 0)

        ranking_models = j.get("ranking_models")
        if not ranking_models:
            ranking_models = [label_to_model.get(l) for l in (j.get("ranking") or [])]
        ranking_models = [m for m in ranking_models if m]

        for idx, model in enumerate(ranking_models):
            ranks[model].append(idx + 1)
        for i in range(len(ranking_models)):
            for k in range(i + 1, len(ranking_models)):
                win_matrix[ranking_models[i]][ranking_models[k]] += 1

    per_model: dict[str, Any] = {}
    all_models = set(counts) | set(ranks)
    for model in all_models:
        n = counts.get(model, 0)
        mean_dims = {
            dim: (sums[model][dim] / n if n else None) for dim in RUBRIC_DIMENSIONS
        }
        model_ranks = ranks.get(model, [])
        per_model[model] = {
            "n_scored": n,
            "mean_dims": mean_dims,
            "mean_rank": (sum(model_ranks) / len(model_ranks)) if model_ranks else None,
            "rank1_count": sum(1 for r in model_ranks if r == 1),
            "n_ranked": len(model_ranks),
        }

    return {
        "per_model": per_model,
        "win_matrix": {a: dict(b) for a, b in win_matrix.items()},
        "n_judgments": sum(1 for j in judgments if j.get("status") in (None, "ok")),
    }


def binomial_sign_test(k: int, n: int) -> float:
    """Two-sided exact binomial sign-test p-value for `k` successes of `n`
    trials under p=0.5 (no ties). Uses math.comb — no scipy dependency."""
    if n == 0:
        return 1.0
    k = max(0, min(n, k))
    larger = max(k, n - k)
    tail = sum(math.comb(n, i) for i in range(larger, n + 1)) / (2**n)
    return min(1.0, 2 * tail)


def pairwise_sign_tests(win_matrix: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    """For every unordered model pair with >=1 head-to-head comparison, run a
    sign test on ranking-implied preference. Returns a list of result dicts
    sorted by (model_a, model_b)."""
    models = sorted(set(win_matrix.keys()) | {m for d in win_matrix.values() for m in d.keys()})
    out = []
    for i, a in enumerate(models):
        for b in models[i + 1 :]:
            wins_a = win_matrix.get(a, {}).get(b, 0)
            wins_b = win_matrix.get(b, {}).get(a, 0)
            n = wins_a + wins_b
            if n == 0:
                continue
            k = max(wins_a, wins_b)
            p_value = binomial_sign_test(k, n)
            preferred = a if wins_a >= wins_b else b
            out.append(
                {
                    "model_a": a,
                    "model_b": b,
                    "wins_a": wins_a,
                    "wins_b": wins_b,
                    "n": n,
                    "preferred": preferred,
                    "p_value": p_value,
                }
            )
    return out


def _duration_and_cost(results: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [r["duration_ms"] for r in results if isinstance(r.get("duration_ms"), (int, float))]
    costs = [r["estimated_cost_usd"] for r in results if isinstance(r.get("estimated_cost_usd"), (int, float))]
    lengths = [len(r["markdown"]) for r in results if isinstance(r.get("markdown"), str)]
    out: dict[str, Any] = {
        "n": len(results),
        "avg_duration_ms": (sum(durations) / len(durations)) if durations else None,
        "avg_cost_usd": (sum(costs) / len(costs)) if costs else None,
        "total_cost_usd": sum(costs) if costs else 0.0,
    }
    if lengths:
        out["output_chars"] = {
            "mean": sum(lengths) / len(lengths),
            "median": statistics.median(lengths),
            "min": min(lengths),
            "max": max(lengths),
        }
    else:
        out["output_chars"] = None
    return out


def aggregate_transcriptions(transcriptions: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate successful transcription result payloads by model.

    Each item is expected to carry a `model` key alongside `duration_ms`,
    `estimated_cost_usd`, and `markdown` (only present when `status == "ok"`).
    """
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in transcriptions:
        if r.get("status") not in (None, "ok"):
            continue
        model = r.get("model")
        if not model:
            continue
        by_model[model].append(r)
    return {model: _duration_and_cost(results) for model, results in by_model.items()}


def group_by(items: list[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    out: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        out[item.get(key)].append(item)
    return dict(out)
