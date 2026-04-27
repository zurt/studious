from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import REGION_TRANSCRIBE_PROMPT, get_settings
from ..jobs import manager
from ..services import storage

log = logging.getLogger("studious.api.regions")

VALID_TAGS = {"vocab_list", "grammar_points", "reading_passage", "exercises", "instructions", "other"}

router = APIRouter(
    prefix="/api/documents/{doc_id}/chapters/{chapter_id}/regions",
    tags=["regions"],
)


class CreateRegion(BaseModel):
    page: int
    bbox: list[float] = Field(..., min_length=4, max_length=4)
    tag: str
    label: str = ""


class UpdateRegion(BaseModel):
    bbox: list[float] | None = Field(None, min_length=4, max_length=4)
    tag: str | None = None
    label: str | None = None


def _require_chapter(doc_id: str, chapter_id: str) -> dict:
    doc = storage.load_document(doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    chapter = storage.load_chapter(doc_id, chapter_id)
    if chapter is None:
        raise HTTPException(404, "chapter not found")
    return chapter


def _validate_bbox(bbox: list[float]) -> None:
    x1, y1, x2, y2 = bbox
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise HTTPException(400, "bbox values must be in [0,1] with x1<x2 and y1<y2")


@router.post("")
def create_region(doc_id: str, chapter_id: str, body: CreateRegion):
    chapter = _require_chapter(doc_id, chapter_id)
    if body.tag not in VALID_TAGS:
        raise HTTPException(400, f"tag must be one of {sorted(VALID_TAGS)}")
    if body.page < chapter["page_start"] or body.page > chapter["page_end"]:
        raise HTTPException(400, f"page must be within chapter range ({chapter['page_start']}-{chapter['page_end']})")
    _validate_bbox(body.bbox)
    region = storage.create_region(
        doc_id,
        chapter_id,
        page=body.page,
        bbox=body.bbox,
        tag=body.tag,
        label=body.label,
    )
    log.info("region_created", extra={"doc_id": doc_id, "chapter_id": chapter_id, "region_id": region["id"]})
    return region


@router.get("")
def list_regions(doc_id: str, chapter_id: str):
    _require_chapter(doc_id, chapter_id)
    return storage.list_regions(doc_id, chapter_id)


@router.put("/{region_id}")
def update_region(doc_id: str, chapter_id: str, region_id: str, body: UpdateRegion):
    _require_chapter(doc_id, chapter_id)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "no fields to update")
    if "bbox" in changes:
        _validate_bbox(changes["bbox"])
    if "tag" in changes and changes["tag"] not in VALID_TAGS:
        raise HTTPException(400, f"tag must be one of {sorted(VALID_TAGS)}")
    updated = storage.update_region(doc_id, chapter_id, region_id, **changes)
    if updated is None:
        raise HTTPException(404, "region not found")
    log.info("region_updated", extra={"doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id})
    return updated


@router.delete("/{region_id}")
def delete_region(doc_id: str, chapter_id: str, region_id: str):
    _require_chapter(doc_id, chapter_id)
    if not storage.delete_region(doc_id, chapter_id, region_id):
        raise HTTPException(404, "region not found")
    log.info("region_deleted", extra={"doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id})
    return {"ok": True}


@router.post("/{region_id}/transcribe")
def transcribe_region(doc_id: str, chapter_id: str, region_id: str):
    _require_chapter(doc_id, chapter_id)
    region = storage.load_region(doc_id, chapter_id, region_id)
    if region is None:
        raise HTTPException(404, "region not found")

    page_img = storage.page_image_path(doc_id, region["page"])
    if not page_img.exists():
        raise HTTPException(404, "page image not found")

    settings = get_settings()
    payload: dict[str, Any] = {
        "job_type": "transcribe_region",
        "doc_id": doc_id,
        "chapter_id": chapter_id,
        "region_id": region_id,
        "page": region["page"],
        "bbox": region["bbox"],
        "engine": "vlm",
        "provider": "anthropic",
        "config": {"model": settings.default_vlm_model},
        "prompt": REGION_TRANSCRIBE_PROMPT,
    }
    job = manager.submit(payload)
    return {"job_id": job["id"]}
