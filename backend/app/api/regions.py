from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from ..config import (
    BREAKDOWN_TOOL_SCHEMA,
    EXERCISE_COMPLETION_PROMPT,
    EXERCISE_COMPLETION_TOOL_SCHEMA,
    REGION_TRANSCRIBE_PROMPT,
    SENTENCE_BREAKDOWN_PROMPT,
    VOCAB_LIST_TRANSCRIBE_PROMPT,
)
from ..jobs import manager
from ..services import breakdown_links, storage
from ..services.preferences import get_active_vlm_model

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


class MoveRegion(BaseModel):
    dst_chapter_id: str


@router.post("/{region_id}/move")
def move_region(doc_id: str, chapter_id: str, region_id: str, body: MoveRegion):
    _require_chapter(doc_id, chapter_id)
    dst_chapter = storage.load_chapter(doc_id, body.dst_chapter_id)
    if dst_chapter is None:
        raise HTTPException(404, "destination chapter not found")
    region = storage.load_region(doc_id, chapter_id, region_id)
    if region is None:
        raise HTTPException(404, "region not found")
    if region["page"] < dst_chapter["page_start"] or region["page"] > dst_chapter["page_end"]:
        raise HTTPException(
            400,
            f"region page {region['page']} is outside destination chapter range "
            f"({dst_chapter['page_start']}-{dst_chapter['page_end']})",
        )
    moved = storage.move_region(doc_id, chapter_id, region_id, body.dst_chapter_id)
    log.info(
        "region_moved",
        extra={
            "doc_id": doc_id,
            "src_chapter_id": chapter_id,
            "dst_chapter_id": body.dst_chapter_id,
            "region_id": region_id,
        },
    )
    return moved


class LinkRegion(BaseModel):
    continues_to: str | None = None


@router.post("/{region_id}/link")
def link_region(doc_id: str, chapter_id: str, region_id: str, body: LinkRegion):
    _require_chapter(doc_id, chapter_id)
    region = storage.load_region(doc_id, chapter_id, region_id)
    if region is None:
        raise HTTPException(404, "region not found")

    if body.continues_to is None:
        updated = storage.update_region(doc_id, chapter_id, region_id, continues_to=None)
        return updated

    if body.continues_to == region_id:
        raise HTTPException(400, "region cannot link to itself")

    target = storage.load_region(doc_id, chapter_id, body.continues_to)
    if target is None:
        raise HTTPException(404, "target region not found in this chapter")
    if target["page"] <= region["page"]:
        raise HTTPException(400, "target region must be on a later page than the source")

    # cycle detection: follow the target's chain forward; we must not reach source.
    seen: set[str] = {region_id}
    cur = target
    while cur is not None:
        if cur["id"] in seen:
            raise HTTPException(400, "linking would create a cycle")
        seen.add(cur["id"])
        nxt_id = cur.get("continues_to")
        if not nxt_id:
            break
        cur = storage.load_region(doc_id, chapter_id, nxt_id)

    updated = storage.update_region(doc_id, chapter_id, region_id, continues_to=body.continues_to)
    log.info(
        "region_linked",
        extra={"doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id, "continues_to": body.continues_to},
    )
    return updated


@router.post("/{region_id}/transcribe")
def transcribe_region(doc_id: str, chapter_id: str, region_id: str):
    _require_chapter(doc_id, chapter_id)
    region = storage.load_region(doc_id, chapter_id, region_id)
    if region is None:
        raise HTTPException(404, "region not found")

    page_img = storage.page_image_path(doc_id, region["page"])
    if not page_img.exists():
        raise HTTPException(404, "page image not found")

    prompt = (
        VOCAB_LIST_TRANSCRIBE_PROMPT
        if region.get("tag") == "vocab_list"
        else REGION_TRANSCRIBE_PROMPT
    )
    payload: dict[str, Any] = {
        "job_type": "transcribe_region",
        "doc_id": doc_id,
        "chapter_id": chapter_id,
        "region_id": region_id,
        "page": region["page"],
        "bbox": region["bbox"],
        "engine": "vlm",
        "provider": "anthropic",
        "config": {"model": get_active_vlm_model()},
        "prompt": prompt,
    }
    job = manager.submit(payload)
    return {"job_id": job["id"]}


class BreakdownRequest(BaseModel):
    overwrite: bool = False


@router.get("/{region_id}/breakdown")
def get_region_breakdown(doc_id: str, chapter_id: str, region_id: str):
    _require_chapter(doc_id, chapter_id)
    breakdown = storage.load_breakdown(doc_id, chapter_id, region_id)
    if breakdown is None:
        raise HTTPException(404, "breakdown not found")
    if breakdown_links.needs_links(breakdown):
        breakdown_links.annotate(breakdown)
        breakdown = storage.save_breakdown(doc_id, chapter_id, region_id, breakdown)
    return breakdown


@router.post("/{region_id}/breakdown")
def request_region_breakdown(
    doc_id: str,
    chapter_id: str,
    region_id: str,
    response: Response,
    body: BreakdownRequest = BreakdownRequest(),
):
    _require_chapter(doc_id, chapter_id)
    region = storage.load_region(doc_id, chapter_id, region_id)
    if region is None:
        raise HTTPException(404, "region not found")
    if region.get("tag") == "vocab_list":
        raise HTTPException(400, "breakdowns are not available on vocab_list regions")
    if not region.get("transcription_md"):
        raise HTTPException(409, "region has no transcription")
    if (
        not body.overwrite
        and storage.load_breakdown(doc_id, chapter_id, region_id) is not None
    ):
        raise HTTPException(409, "breakdown already exists; pass overwrite=true to regenerate")

    payload: dict[str, Any] = {
        "job_type": "breakdown_region",
        "doc_id": doc_id,
        "chapter_id": chapter_id,
        "region_id": region_id,
        "page": region["page"],
        "engine": "vlm",
        "provider": "anthropic",
        "config": {"model": get_active_vlm_model(), "max_tokens": 8192},
        "prompt": SENTENCE_BREAKDOWN_PROMPT,
        "tool_name": "record_breakdown",
        "tool_schema": BREAKDOWN_TOOL_SCHEMA,
    }
    job = manager.submit(payload)
    response.status_code = 202
    return {"job_id": job["id"]}


class ExerciseCompletionRequest(BaseModel):
    sentence_index: int = Field(..., ge=0)
    overwrite: bool = False


@router.get("/{region_id}/exercise-completion")
def get_region_exercise_completion(doc_id: str, chapter_id: str, region_id: str):
    _require_chapter(doc_id, chapter_id)
    record = storage.load_exercise_completion(doc_id, chapter_id, region_id)
    if record is None:
        raise HTTPException(404, "exercise completion not found")
    return record


@router.post("/{region_id}/exercise-completion")
def request_region_exercise_completion(
    doc_id: str,
    chapter_id: str,
    region_id: str,
    response: Response,
    body: ExerciseCompletionRequest,
):
    _require_chapter(doc_id, chapter_id)
    region = storage.load_region(doc_id, chapter_id, region_id)
    if region is None:
        raise HTTPException(404, "region not found")
    if region.get("tag") != "exercises":
        raise HTTPException(400, "exercise completions are only available on exercises regions")

    breakdown = storage.load_breakdown(doc_id, chapter_id, region_id)
    if breakdown is None:
        raise HTTPException(409, "breakdown must be generated before requesting an exercise completion")
    sentences = breakdown.get("sentences") or []
    if body.sentence_index >= len(sentences):
        raise HTTPException(400, f"sentence_index {body.sentence_index} out of range")
    sentence = sentences[body.sentence_index]
    sentence_text = sentence.get("text") if isinstance(sentence, dict) else None
    if not sentence_text:
        raise HTTPException(400, "sentence has no text")

    existing = storage.load_exercise_completion(doc_id, chapter_id, region_id)
    if (
        not body.overwrite
        and existing
        and str(body.sentence_index) in (existing.get("completions") or {})
    ):
        raise HTTPException(409, "exercise completion already exists; pass overwrite=true to regenerate")

    payload: dict[str, Any] = {
        "job_type": "exercise_completion",
        "doc_id": doc_id,
        "chapter_id": chapter_id,
        "region_id": region_id,
        "sentence_index": body.sentence_index,
        "sentence_text": sentence_text,
        "region_transcription": region.get("transcription_md") or "",
        "engine": "vlm",
        "provider": "anthropic",
        "config": {"model": get_active_vlm_model(), "max_tokens": 2048},
        "prompt": EXERCISE_COMPLETION_PROMPT,
        "tool_name": "record_exercise_completion",
        "tool_schema": EXERCISE_COMPLETION_TOOL_SCHEMA,
    }
    job = manager.submit(payload)
    response.status_code = 202
    return {"job_id": job["id"]}
