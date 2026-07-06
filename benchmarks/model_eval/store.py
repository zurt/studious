"""Read-only enumeration of the on-disk Studious store.

Only reads meta.json / region JSON files with plain json + pathlib — no
backend imports, no network — so it's safe to exercise directly in tests
against a fake store built under tmp_path.

On-disk layout (see backend/app/services/storage.py):
    <data_dir>/documents/<doc_id>/meta.json          {id, name, page_count, ...}
    <data_dir>/documents/<doc_id>/pages/NNNN.png      1-indexed, 4-digit zero pad
    <data_dir>/documents/<doc_id>/chapters/<chapter_id>/meta.json
    <data_dir>/documents/<doc_id>/chapters/<chapter_id>/regions/<region_id>.json

Note: document meta.json's display-name field is `name` (the originally
uploaded filename), not `filename` — `_classify_upload`/`create_document` in
backend/app/api/documents.py and backend/app/services/storage.py confirm
this. We read `name` and fall back to `filename` for forward compatibility.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .items import classify_source


@dataclass
class EnumeratedStore:
    documents: list[dict[str, Any]] = field(default_factory=list)
    region_candidates: list[dict[str, Any]] = field(default_factory=list)
    page_candidates: list[dict[str, Any]] = field(default_factory=list)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def enumerate_store(data_dir: Path) -> EnumeratedStore:
    """Walk `data_dir/documents/**` and return every document/chapter/region.

    Region and page candidate dicts carry an `id` field used purely as a
    stable, deterministic sort key by the sampler in sampling.py.
    """
    data_dir = Path(data_dir)
    docs_root = data_dir / "documents"
    out = EnumeratedStore()
    if not docs_root.exists():
        return out

    # First pass: collect every region across every document/chapter so we
    # can compute is_chained (referenced by another region's continues_to)
    # without a second disk walk.
    all_regions: list[dict[str, Any]] = []
    continuation_targets: set[str] = set()

    for doc_dir in sorted(p for p in docs_root.iterdir() if p.is_dir()):
        meta = _read_json(doc_dir / "meta.json")
        if meta is None:
            continue
        doc_id = meta.get("id", doc_dir.name)
        doc_filename = meta.get("name") or meta.get("filename") or ""
        source = classify_source(doc_filename)
        out.documents.append(meta)

        content_pages: set[int] = set()

        chapters_dir = doc_dir / "chapters"
        if chapters_dir.exists():
            for chapter_dir in sorted(p for p in chapters_dir.iterdir() if p.is_dir()):
                chapter_meta = _read_json(chapter_dir / "meta.json")
                if chapter_meta is None:
                    continue
                chapter_id = chapter_meta.get("id", chapter_dir.name)
                chapter_title = chapter_meta.get("title", "")

                regions_dir = chapter_dir / "regions"
                if not regions_dir.exists():
                    continue
                for region_file in sorted(regions_dir.glob("*.json")):
                    region = _read_json(region_file)
                    if region is None:
                        continue
                    region_id = region.get("id", region_file.stem)
                    page = region.get("page")
                    if isinstance(page, int):
                        content_pages.add(page)
                    continues_to = region.get("continues_to")
                    if continues_to:
                        continuation_targets.add(continues_to)
                    all_regions.append(
                        {
                            "kind": "region",
                            "id": region_id,
                            "doc_id": doc_id,
                            "doc_filename": doc_filename,
                            "source": source,
                            "chapter_id": chapter_id,
                            "chapter_title": chapter_title,
                            "page": page,
                            "tag": region.get("tag"),
                            "label": region.get("label", ""),
                            "bbox": region.get("bbox"),
                            "transcription_md": region.get("transcription_md"),
                            "transcribed_at": region.get("transcribed_at"),
                            "transcribed_model": region.get("transcribed_model"),
                            "continues_to": continues_to,
                        }
                    )

        for page in sorted(content_pages):
            transcription = _read_json(
                doc_dir / "transcriptions" / f"{page:04d}.json"
            )
            existing_model = None
            if transcription:
                existing_model = transcription.get("model") or (
                    transcription.get("meta") or {}
                ).get("model")
            out.page_candidates.append(
                {
                    "kind": "page",
                    "id": f"{doc_id}:{page:04d}",
                    "doc_id": doc_id,
                    "doc_filename": doc_filename,
                    "source": source,
                    "page": page,
                    "has_existing_transcription": transcription is not None,
                    "existing_transcribed_model": existing_model,
                }
            )

    for region in all_regions:
        region["is_chained"] = bool(region["continues_to"]) or region["id"] in continuation_targets
        out.region_candidates.append(region)

    return out
