"""I/O orchestration for the `analyze` subcommand.

Reads a run's judgments/ and transcriptions/ plus the dataset's item
meta.json files, aggregates with analysis.py, and writes analysis.json (for
machine consumption) and report.md (for humans).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import analysis
from .common import git_sha

WORST_ITEMS_COUNT = 5


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_run_data(run_dir: Path) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Return (judgments_by_item_id, transcriptions_by_item_id)."""
    judgments: dict[str, dict] = {}
    judgments_dir = run_dir / "judgments"
    if judgments_dir.exists():
        for f in sorted(judgments_dir.glob("*.json")):
            data = _load_json(f)
            if data is not None:
                judgments[f.stem] = data

    transcriptions: dict[str, list[dict]] = {}
    transcriptions_dir = run_dir / "transcriptions"
    if transcriptions_dir.exists():
        for item_dir in sorted(p for p in transcriptions_dir.iterdir() if p.is_dir()):
            results = []
            for f in sorted(item_dir.glob("*.json")):
                data = _load_json(f)
                if data is not None:
                    data = {**data, "model": data.get("model") or f.stem}
                    results.append(data)
            transcriptions[item_dir.name] = results

    return judgments, transcriptions


def _load_item_metas(dataset_dir: Path, item_ids: set[str]) -> dict[str, dict]:
    out = {}
    items_dir = dataset_dir / "items"
    for item_id in item_ids:
        meta = _load_json(items_dir / item_id / "meta.json")
        if meta is not None:
            out[item_id] = meta
    return out


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _league_table_md(per_model: dict[str, Any], win_matrix: dict[str, dict[str, int]]) -> str:
    models = sorted(per_model.keys(), key=lambda m: (per_model[m]["mean_rank"] or 999))
    header = (
        "| Model | n | mean overall | mean rank | #1 count | char_acc | complete | "
        "format | halluc_ctrl |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for m in models:
        s = per_model[m]
        dims = s["mean_dims"]
        rows.append(
            f"| {m} | {s['n_scored']} | {_fmt(dims.get('overall'))} | {_fmt(s['mean_rank'])} | "
            f"{s['rank1_count']} | {_fmt(dims.get('character_accuracy'))} | "
            f"{_fmt(dims.get('completeness'))} | {_fmt(dims.get('formatting'))} | "
            f"{_fmt(dims.get('hallucination_control'))} |"
        )
    return header + "\n".join(rows)


def _group_table_md(groups: dict[Any, dict[str, Any]], group_label: str) -> str:
    header = f"| {group_label} | Model | n | mean overall | mean rank |\n|---|---|---|---|---|\n"
    rows = []
    for key in sorted(groups.keys(), key=lambda k: str(k)):
        agg = groups[key]
        per_model = agg["per_model"]
        for m in sorted(per_model.keys(), key=lambda mm: (per_model[mm]["mean_rank"] or 999)):
            s = per_model[m]
            rows.append(
                f"| {key} | {m} | {s['n_scored']} | {_fmt(s['mean_dims'].get('overall'))} | "
                f"{_fmt(s['mean_rank'])} |"
            )
    return header + "\n".join(rows)


def _cost_latency_table_md(by_model: dict[str, Any]) -> str:
    header = (
        "| Model | n | avg duration (ms) | avg cost (USD) | total cost (USD) | "
        "avg output chars |\n|---|---|---|---|---|---|\n"
    )
    rows = []
    for m in sorted(by_model.keys()):
        s = by_model[m]
        avg_chars = s["output_chars"]["mean"] if s.get("output_chars") else None
        rows.append(
            f"| {m} | {s['n']} | {_fmt(s['avg_duration_ms'], 0)} | "
            f"{_fmt(s['avg_cost_usd'], 4)} | {_fmt(s['total_cost_usd'], 4)} | "
            f"{_fmt(avg_chars, 0)} |"
        )
    return header + "\n".join(rows)


def analyze_run(run_dir: Path, dataset_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    dataset_dir = Path(dataset_dir)

    judgments_by_item, transcriptions_by_item = _load_run_data(run_dir)
    item_metas = _load_item_metas(dataset_dir, set(judgments_by_item) | set(transcriptions_by_item))

    ok_judgments = [j for j in judgments_by_item.values() if j.get("status") in (None, "ok")]
    overall = analysis.aggregate_judgments(ok_judgments)
    sign_tests = analysis.pairwise_sign_tests(overall["win_matrix"])

    all_transcriptions = [r for results in transcriptions_by_item.values() for r in results]
    cost_latency = analysis.aggregate_transcriptions(all_transcriptions)

    def judgments_grouped_by(field: str) -> dict[Any, dict[str, Any]]:
        buckets: dict[Any, list[dict]] = {}
        for item_id, j in judgments_by_item.items():
            if j.get("status") not in (None, "ok"):
                continue
            meta = item_metas.get(item_id, {})
            key = meta.get(field)
            buckets.setdefault(key, []).append(j)
        return {key: analysis.aggregate_judgments(js) for key, js in buckets.items()}

    by_source = judgments_grouped_by("source")
    by_tag = judgments_grouped_by("tag")
    by_kind = judgments_grouped_by("kind")
    by_prompt_kind = judgments_grouped_by("prompt_kind")

    # Worst items: lowest mean "overall" across candidates, with the
    # lowest-scoring candidate's notes as a quote.
    worst_items = []
    for item_id, j in judgments_by_item.items():
        if j.get("status") not in (None, "ok"):
            continue
        candidates = j.get("candidates") or []
        if not candidates:
            continue
        mean_overall = sum(c.get("overall", 0) for c in candidates) / len(candidates)
        worst_candidate = min(candidates, key=lambda c: c.get("overall", 0))
        label_to_model = j.get("label_to_model") or {}
        worst_items.append(
            {
                "item_id": item_id,
                "mean_overall": mean_overall,
                "worst_model": label_to_model.get(worst_candidate.get("label")),
                "worst_overall": worst_candidate.get("overall"),
                "notes": worst_candidate.get("notes", ""),
            }
        )
    worst_items.sort(key=lambda w: w["mean_overall"])
    worst_items = worst_items[:WORST_ITEMS_COUNT]

    analysis_out = {
        "run_id": run_dir.name,
        "dataset_dir": str(dataset_dir.resolve()),
        "git_sha": git_sha(),
        "created_at": _now_iso(),
        "overall": overall,
        "sign_tests": sign_tests,
        "cost_latency": cost_latency,
        "by_source": by_source,
        "by_tag": by_tag,
        "by_kind": by_kind,
        "by_prompt_kind": by_prompt_kind,
        "worst_items": worst_items,
        "n_items_judged": len(ok_judgments),
    }
    _atomic_write_text(
        run_dir / "analysis.json", json.dumps(analysis_out, indent=2, ensure_ascii=False)
    )

    report_lines = [
        f"# Model eval report — run `{run_dir.name}`",
        "",
        f"- git sha: `{analysis_out['git_sha']}`",
        f"- dataset: `{analysis_out['dataset_dir']}`",
        f"- items judged: {analysis_out['n_items_judged']}",
        "",
        "## Overall league table",
        "",
        _league_table_md(overall["per_model"], overall["win_matrix"]),
        "",
        "## Pairwise sign tests (ranking-implied preference)",
        "",
        "| Model A | Model B | A wins | B wins | n | preferred | p-value |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in sign_tests:
        report_lines.append(
            f"| {t['model_a']} | {t['model_b']} | {t['wins_a']} | {t['wins_b']} | {t['n']} | "
            f"{t['preferred']} | {_fmt(t['p_value'], 4)} |"
        )
    report_lines += [
        "",
        "## By source",
        "",
        _group_table_md(by_source, "Source"),
        "",
        "## By tag",
        "",
        _group_table_md(by_tag, "Tag"),
        "",
        "## Cost / latency",
        "",
        _cost_latency_table_md(cost_latency),
        "",
        "## Notable judge quotes (worst items)",
        "",
    ]
    if not worst_items:
        report_lines.append("(no judged items)")
    for w in worst_items:
        report_lines.append(
            f"- **{w['item_id']}** (mean overall {w['mean_overall']:.1f}) — "
            f"worst: `{w['worst_model']}` scored {w['worst_overall']}: {w['notes']}"
        )
    report_lines.append("")

    _atomic_write_text(run_dir / "report.md", "\n".join(report_lines))
    return analysis_out
