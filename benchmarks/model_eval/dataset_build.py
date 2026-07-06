"""I/O orchestration for the `build-dataset` subcommand.

Enumerates the on-disk store (store.py), stratified-samples items
(sampling.py), then freezes the EXACT bytes the real transcription pipeline
would send to the VLM for each sampled item, plus per-item and per-dataset
metadata. No network calls — this only touches the local filesystem and
Pillow (via backend/app/services/pdf.py).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import sampling, store
from .common import ensure_backend_on_path, git_sha
from .items import dedupe_item_id, page_item_id, prompt_kind_for, region_item_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def build_dataset(
    data_dir: Path,
    out_dir: Path,
    name: str,
    seed: int,
    quotas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build dataset `name` under `out_dir/<name>/`. Returns the manifest dict.

    Requires backend/ importable (for pdf.crop_region / prepare_for_vlm /
    get_settings) — only called from the CLI, never from tests, so tests
    never need an API key or network access.
    """
    ensure_backend_on_path()
    from app.config import get_settings
    from app.services import pdf as pdf_service

    settings = get_settings()
    quotas = quotas if quotas is not None else sampling.DEFAULT_QUOTAS

    enumerated = store.enumerate_store(data_dir)
    selection = sampling.select_dataset(
        enumerated.region_candidates, enumerated.page_candidates, seed, quotas
    )

    dataset_dir = out_dir / name
    items_dir = dataset_dir / "items"
    if items_dir.exists():
        # Rebuilding a dataset with the same name should be idempotent, not
        # append stale leftovers from a prior (differently-sized) run.
        import shutil

        shutil.rmtree(items_dir)
    items_dir.mkdir(parents=True, exist_ok=True)

    sampled_at = _now_iso()
    item_ids: list[str] = []
    used_ids: set[str] = set()

    def write_item(item_id: str, image_bytes: bytes, meta: dict[str, Any]) -> None:
        item_dir = items_dir / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "input.png").write_bytes(image_bytes)
        _atomic_write_text(
            item_dir / "meta.json", json.dumps(meta, indent=2, ensure_ascii=False)
        )

    def image_dims(image_bytes: bytes) -> tuple[int, int]:
        from PIL import Image
        import io

        with Image.open(io.BytesIO(image_bytes)) as im:
            return im.size

    for region in selection.selected_regions:
        base_id = region_item_id(region["source"], region["tag"], region["id"])
        item_id = dedupe_item_id(base_id, region["doc_id"], used_ids)
        used_ids.add(item_id)
        item_ids.append(item_id)

        page_image_path = (
            Path(data_dir) / "documents" / region["doc_id"] / "pages" / f"{region['page']:04d}.png"
        )
        image_bytes = pdf_service.crop_region(
            page_image_path, region["bbox"], settings.vlm_max_edge
        )
        width, height = image_dims(image_bytes)
        prompt_kind = prompt_kind_for("region", region["tag"])

        meta = {
            "item_id": item_id,
            "kind": "region",
            "source": region["source"],
            "doc_id": region["doc_id"],
            "doc_filename": region["doc_filename"],
            "chapter_id": region["chapter_id"],
            "chapter_title": region["chapter_title"],
            "page": region["page"],
            "tag": region["tag"],
            "label": region.get("label", ""),
            "bbox": region["bbox"],
            "prompt_kind": prompt_kind,
            "image_width": width,
            "image_height": height,
            "image_bytes": len(image_bytes),
            "has_existing_transcription": bool(region.get("transcription_md")),
            "existing_transcribed_model": region.get("transcribed_model"),
            "is_chained": bool(region.get("is_chained")),
            "sampled_at": sampled_at,
        }
        write_item(item_id, image_bytes, meta)

    for page in selection.selected_pages:
        base_id = page_item_id(page["source"], page["page"])
        item_id = dedupe_item_id(base_id, page["doc_id"], used_ids)
        used_ids.add(item_id)
        item_ids.append(item_id)

        page_image_path = (
            Path(data_dir) / "documents" / page["doc_id"] / "pages" / f"{page['page']:04d}.png"
        )
        image_bytes = pdf_service.prepare_for_vlm(page_image_path, settings.vlm_max_edge)
        width, height = image_dims(image_bytes)
        prompt_kind = prompt_kind_for("page", None)

        meta = {
            "item_id": item_id,
            "kind": "page",
            "source": page["source"],
            "doc_id": page["doc_id"],
            "doc_filename": page["doc_filename"],
            "chapter_id": None,
            "chapter_title": None,
            "page": page["page"],
            "tag": None,
            "label": None,
            "bbox": None,
            "prompt_kind": prompt_kind,
            "image_width": width,
            "image_height": height,
            "image_bytes": len(image_bytes),
            "has_existing_transcription": bool(page.get("has_existing_transcription")),
            "existing_transcribed_model": page.get("existing_transcribed_model"),
            "is_chained": False,
            "sampled_at": sampled_at,
        }
        write_item(item_id, image_bytes, meta)

    manifest = {
        "name": name,
        "seed": seed,
        "data_dir": str(Path(data_dir).resolve()),
        "quotas": quotas,
        "strata": [s.to_dict() for s in selection.stratum_stats],
        "shortfalls": [s.to_dict() for s in selection.stratum_stats if s.shortfall > 0],
        "item_ids": sorted(item_ids),
        "item_count": len(item_ids),
        "git_sha": git_sha(),
        "created_at": sampled_at,
    }
    _atomic_write_text(
        dataset_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False)
    )
    return manifest
