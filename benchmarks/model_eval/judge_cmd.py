"""I/O orchestration for the `judge` subcommand.

Calls the Anthropic API directly (not the app's VLM provider) with a blind
rubric+ranking prompt, using structured outputs so the response parses as
JSON matching JUDGE_SCHEMA. Resumable: an item whose judgments/<item_id>.json
already exists and parses is skipped.
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import ensure_anthropic_api_key, git_sha
from .judging import (
    JUDGE_SCHEMA,
    RUBRIC_DESCRIPTIONS,
    invert_label_map,
    shuffle_candidates,
    validate_and_clamp_response,
)
from .pricing import estimate_cost

# Beta flag naming the server-side-fallback feature this eval assumes is
# available on the judge endpoint as of this project's synthetic "today"
# (2026-07-06). If the API rejects it, we retry once without betas/fallbacks.
FALLBACK_BETA = "server-side-fallback-2026-06-01"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _stop_details_dict(message: Any) -> dict[str, Any] | None:
    details = getattr(message, "stop_details", None)
    if details is None:
        return None
    return {
        "category": getattr(details, "category", None),
        "explanation": getattr(details, "explanation", None),
    }


def _existing_result_ok(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        json.loads(path.read_text("utf-8"))
        return True
    except (OSError, json.JSONDecodeError):
        return False


def _build_rubric_text() -> str:
    lines = ["For EACH candidate, score 0-10 (integers) on:"]
    for dim, desc in RUBRIC_DESCRIPTIONS.items():
        lines.append(f"- {dim}: {desc}")
    lines.append(
        "Also give a short, concrete `notes` string per candidate (specific errors observed),"
        " a top-level `ranking` (array of the candidate labels, best first, strict total order,"
        " every label appears exactly once), and a `rationale` explaining the ranking."
    )
    return "\n".join(lines)


def build_judge_content(
    image_b64: str, item_meta: dict[str, Any], label_to_markdown: dict[str, str]
) -> list[dict[str, Any]]:
    """Build the user message content blocks for one judge call.

    The judge sees the source image and the candidate transcriptions under
    their shuffled labels only — never the model names that produced them.
    """
    kind = item_meta.get("kind", "region")
    tag = item_meta.get("tag")
    source = item_meta.get("source", "textbook")
    intro = (
        "You are grading transcriptions of a scanned Japanese-textbook image "
        f"(source: {source} {kind}"
        + (f", region tag: {tag}" if tag else "")
        + "). The image below is the ground truth. Each candidate below is a "
        "markdown transcription of it produced by a different AI system — you "
        "are NOT told which system produced which candidate; judge blind."
    )
    candidates_text_parts = []
    for label in sorted(label_to_markdown.keys()):
        candidates_text_parts.append(f"--- Candidate {label} ---\n{label_to_markdown[label]}")
    candidates_text = "\n\n".join(candidates_text_parts)

    text = f"{intro}\n\n{_build_rubric_text()}\n\n{candidates_text}"

    return [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
        },
        {"type": "text", "text": text},
    ]


def _call_judge(client: Any, judge_model: str, fallback_model: str, content: list[dict[str, Any]]):
    """Call the judge endpoint, falling back to a plain (non-beta) call if the
    beta fallbacks parameter itself is rejected by the API."""
    try:
        return client.beta.messages.create(
            model=judge_model,
            max_tokens=8192,
            betas=[FALLBACK_BETA],
            fallbacks=[{"model": fallback_model}],
            output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:  # noqa: BLE001 - inspect then re-raise if unrelated
        msg = str(exc).lower()
        if "fallbacks" in msg or "beta" in msg:
            return client.messages.create(
                model=judge_model,
                max_tokens=8192,
                output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
                messages=[{"role": "user", "content": content}],
            )
        raise


def judge_run(
    run_dir: Path,
    dataset_dir: Path,
    judge_model: str,
    seed: int,
    fallback_model: str,
) -> dict[str, Any]:
    ensure_anthropic_api_key()
    import anthropic

    client = anthropic.Anthropic()

    dataset_dir = Path(dataset_dir)
    manifest_path = dataset_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    item_ids: list[str] = manifest.get("item_ids") or sorted(
        p.name for p in (dataset_dir / "items").iterdir() if p.is_dir()
    )

    run_dir = Path(run_dir)
    transcriptions_dir = run_dir / "transcriptions"
    judgments_dir = run_dir / "judgments"
    judgments_dir.mkdir(parents=True, exist_ok=True)

    totals = {"attempted": 0, "skipped": 0, "ok": 0, "refused": 0, "error": 0}
    started_at = _now_iso()

    for item_id in item_ids:
        out_path = judgments_dir / f"{item_id}.json"
        if _existing_result_ok(out_path):
            totals["skipped"] += 1
            print(f"  SKIP {item_id} (already judged)")
            continue

        item_dir = dataset_dir / "items" / item_id
        meta_path = item_dir / "meta.json"
        image_path = item_dir / "input.png"
        if not meta_path.exists() or not image_path.exists():
            print(f"  SKIP {item_id}: missing dataset item")
            continue
        item_meta = json.loads(meta_path.read_text("utf-8"))

        item_transcriptions_dir = transcriptions_dir / item_id
        successful: dict[str, str] = {}
        if item_transcriptions_dir.exists():
            for result_path in sorted(item_transcriptions_dir.glob("*.json")):
                try:
                    result = json.loads(result_path.read_text("utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if result.get("status") == "ok" and result.get("markdown"):
                    successful[result_path.stem] = result["markdown"]

        if len(successful) < 2:
            print(f"  SKIP {item_id}: only {len(successful)} successful transcription(s)")
            continue

        totals["attempted"] += 1
        model_names = sorted(successful.keys())
        label_to_model = shuffle_candidates(f"{seed}:{item_id}", model_names)
        label_to_markdown = {
            label: successful[model] for label, model in label_to_model.items()
        }
        image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
        content = build_judge_content(image_b64, item_meta, label_to_markdown)

        print(f"  JUDGE {item_id} ({len(successful)} candidates)...", end=" ", flush=True)
        t0 = time.monotonic()
        try:
            message = _call_judge(client, judge_model, fallback_model, content)
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            payload = {
                "status": "error",
                "error": str(exc),
                "judge_model": judge_model,
                "label_to_model": label_to_model,
                "duration_ms": duration_ms,
            }
            totals["error"] += 1
            print(f"ERROR: {exc}")
            _atomic_write_text(out_path, json.dumps(payload, indent=2, ensure_ascii=False))
            continue
        duration_ms = int((time.monotonic() - t0) * 1000)

        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "refusal":
            payload = {
                "status": "refused",
                "judge_model": judge_model,
                "label_to_model": label_to_model,
                "stop_details": _stop_details_dict(message),
                "duration_ms": duration_ms,
            }
            totals["refused"] += 1
            print("REFUSED")
            _atomic_write_text(out_path, json.dumps(payload, indent=2, ensure_ascii=False))
            continue

        text_blocks = [
            b.text for b in getattr(message, "content", []) if getattr(b, "type", None) == "text"
        ]
        if not text_blocks:
            payload = {
                "status": "error",
                "error": f"no text block in judge response (stop_reason={stop_reason!r})",
                "judge_model": judge_model,
                "label_to_model": label_to_model,
                "duration_ms": duration_ms,
            }
            totals["error"] += 1
            print("ERROR: no text block")
            _atomic_write_text(out_path, json.dumps(payload, indent=2, ensure_ascii=False))
            continue

        try:
            raw_json = json.loads(text_blocks[0])
            normalized = validate_and_clamp_response(raw_json, list(label_to_model.keys()))
        except (json.JSONDecodeError, ValueError) as exc:
            payload = {
                "status": "error",
                "error": f"could not parse/validate judge JSON: {exc}",
                "raw_text": text_blocks[0],
                "judge_model": judge_model,
                "label_to_model": label_to_model,
                "duration_ms": duration_ms,
            }
            totals["error"] += 1
            print(f"ERROR: {exc}")
            _atomic_write_text(out_path, json.dumps(payload, indent=2, ensure_ascii=False))
            continue

        usage = getattr(message, "usage", None)
        usage_dict = {}
        if usage is not None:
            usage_dict = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            }
        cost = estimate_cost(judge_model, usage_dict) if usage_dict else None

        ranking_models = [label_to_model.get(l) for l in normalized["ranking"]]
        payload = {
            "status": "ok",
            "judge_model": judge_model,
            "label_to_model": label_to_model,
            "model_to_label": invert_label_map(label_to_model),
            "candidates": normalized["candidates"],
            "ranking": normalized["ranking"],
            "ranking_models": ranking_models,
            "rationale": normalized["rationale"],
            "usage": usage_dict,
            "estimated_cost_usd": cost,
            "duration_ms": duration_ms,
        }
        totals["ok"] += 1
        print(f"ok ({duration_ms}ms)")
        _atomic_write_text(out_path, json.dumps(payload, indent=2, ensure_ascii=False))

    finished_at = _now_iso()
    summary = {
        "run_id": run_dir.name,
        "dataset_dir": str(dataset_dir.resolve()),
        "judge_model": judge_model,
        "fallback_model": fallback_model,
        "seed": seed,
        "git_sha": git_sha(),
        "started_at": started_at,
        "finished_at": finished_at,
        "totals": totals,
    }
    _atomic_write_text(
        run_dir / "judge_run.json", json.dumps(summary, indent=2, ensure_ascii=False)
    )
    return summary
