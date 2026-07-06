"""I/O orchestration for the `run` subcommand.

Sends each frozen dataset item to each requested model via the app's own
`anthropic` VLM provider (same code path production uses), and writes one
result file per (item, model) pair. Resumable: a (item, model) pair whose
output file already exists and parses as JSON is skipped.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import ensure_backend_on_path, git_sha
from .pricing import estimate_cost


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _manifest_hash(manifest_path: Path) -> str | None:
    if not manifest_path.exists():
        return None
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:16]


def _existing_result_ok(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        json.loads(path.read_text("utf-8"))
        return True
    except (OSError, json.JSONDecodeError):
        return False


def run_dataset(
    dataset_dir: Path,
    runs_dir: Path,
    models: list[str],
    run_id: str,
    max_tokens: int = 8192,
) -> dict[str, Any]:
    ensure_backend_on_path()
    from app.config import (
        REGION_TRANSCRIBE_PROMPT,
        VOCAB_LIST_TRANSCRIBE_PROMPT,
        get_settings,
    )
    from app.providers import registry

    registry.bootstrap_default_providers()
    settings = get_settings()
    prompts = {
        "page": settings.default_vlm_prompt,
        "region": REGION_TRANSCRIBE_PROMPT,
        "vocab_list": VOCAB_LIST_TRANSCRIBE_PROMPT,
    }
    provider = registry.get_vlm("anthropic")

    dataset_dir = Path(dataset_dir)
    manifest_path = dataset_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    item_ids: list[str] = manifest.get("item_ids") or sorted(
        p.name for p in (dataset_dir / "items").iterdir() if p.is_dir()
    )

    run_dir = Path(runs_dir) / run_id
    transcriptions_dir = run_dir / "transcriptions"
    transcriptions_dir.mkdir(parents=True, exist_ok=True)

    started_at = _now_iso()
    totals = {"attempted": 0, "skipped": 0, "ok": 0, "error": 0}

    for item_id in item_ids:
        item_dir = dataset_dir / "items" / item_id
        meta_path = item_dir / "meta.json"
        image_path = item_dir / "input.png"
        if not meta_path.exists() or not image_path.exists():
            print(f"  SKIP {item_id}: missing input.png/meta.json")
            continue
        item_meta = json.loads(meta_path.read_text("utf-8"))
        prompt_kind = item_meta.get("prompt_kind", "page")
        prompt = prompts.get(prompt_kind)
        if prompt is None:
            print(f"  SKIP {item_id}: unknown prompt_kind {prompt_kind!r}")
            continue
        image_bytes = image_path.read_bytes()

        out_item_dir = transcriptions_dir / item_id
        for model in models:
            out_path = out_item_dir / f"{model}.json"
            totals["attempted"] += 1
            if _existing_result_ok(out_path):
                totals["skipped"] += 1
                print(f"  SKIP {item_id}/{model} (already done)")
                continue

            print(f"  RUN  {item_id}/{model}...", end=" ", flush=True)
            t0 = time.monotonic()
            try:
                result = provider.transcribe(
                    image_bytes, prompt, {"model": model, "max_tokens": max_tokens}
                )
                duration_ms = int((time.monotonic() - t0) * 1000)
                cost = estimate_cost(model, result.meta.get("usage"))
                payload = {
                    "status": "ok",
                    "model": model,
                    "markdown": result.markdown,
                    "meta": result.meta,
                    "duration_ms": duration_ms,
                    "estimated_cost_usd": cost,
                }
                totals["ok"] += 1
                print(f"ok ({duration_ms}ms)")
            except Exception as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                payload = {
                    "status": "error",
                    "model": model,
                    "error": str(exc),
                    "duration_ms": duration_ms,
                }
                totals["error"] += 1
                print(f"ERROR: {exc}")

            _atomic_write_text(out_path, json.dumps(payload, indent=2, ensure_ascii=False))

    finished_at = _now_iso()
    run_meta = {
        "run_id": run_id,
        "dataset_dir": str(dataset_dir.resolve()),
        "dataset_manifest_hash": _manifest_hash(manifest_path),
        "models": models,
        "max_tokens": max_tokens,
        "git_sha": git_sha(),
        "started_at": started_at,
        "finished_at": finished_at,
        "totals": totals,
        "item_count": len(item_ids),
    }
    _atomic_write_text(run_dir / "run.json", json.dumps(run_meta, indent=2, ensure_ascii=False))
    return run_meta
