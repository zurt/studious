from __future__ import annotations

import logging

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from ..config import GRAMMAR_GUIDE_PROMPT, GRAMMAR_GUIDE_TOOL_SCHEMA, get_settings
from ..jobs import manager
from ..services import grammar_guide, storage

log = logging.getLogger("studious.api.chapters")

router = APIRouter(prefix="/api/documents/{doc_id}/chapters", tags=["chapters"])


class CreateChapter(BaseModel):
    title: str
    page_start: int
    page_end: int
    order: int = 0


class UpdateChapter(BaseModel):
    title: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    order: int | None = None


def _require_doc(doc_id: str) -> dict:
    doc = storage.load_document(doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return doc


@router.post("")
def create_chapter(doc_id: str, body: CreateChapter):
    doc = _require_doc(doc_id)
    if body.page_start < 1 or body.page_end < body.page_start:
        raise HTTPException(400, "invalid page range")
    if body.page_end > doc["page_count"]:
        raise HTTPException(400, f"page_end exceeds page count ({doc['page_count']})")
    chapter = storage.create_chapter(
        doc_id,
        title=body.title,
        page_start=body.page_start,
        page_end=body.page_end,
        order=body.order,
    )
    log.info("chapter_created", extra={"doc_id": doc_id, "chapter_id": chapter["id"]})
    return chapter


@router.get("")
def list_chapters(doc_id: str):
    _require_doc(doc_id)
    return storage.list_chapters(doc_id)


@router.get("/{chapter_id}")
def get_chapter(doc_id: str, chapter_id: str):
    _require_doc(doc_id)
    chapter = storage.load_chapter(doc_id, chapter_id)
    if chapter is None:
        raise HTTPException(404, "chapter not found")
    chapter = dict(chapter)
    chapter["regions"] = storage.list_regions(doc_id, chapter_id)
    chapter["has_grammar_guide"] = storage.load_grammar_guide(doc_id, chapter_id) is not None
    return chapter


@router.put("/{chapter_id}")
def update_chapter(doc_id: str, chapter_id: str, body: UpdateChapter):
    _require_doc(doc_id)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "no fields to update")
    updated = storage.update_chapter(doc_id, chapter_id, **changes)
    if updated is None:
        raise HTTPException(404, "chapter not found")
    log.info("chapter_updated", extra={"doc_id": doc_id, "chapter_id": chapter_id})
    return updated


@router.delete("/{chapter_id}")
def delete_chapter(doc_id: str, chapter_id: str):
    _require_doc(doc_id)
    if not storage.delete_chapter(doc_id, chapter_id):
        raise HTTPException(404, "chapter not found")
    log.info("chapter_deleted", extra={"doc_id": doc_id, "chapter_id": chapter_id})
    return {"ok": True}


class GrammarGuideRequest(BaseModel):
    overwrite: bool = False


def _annotate_guide_status(
    doc_id: str, chapter_id: str, guide: dict[str, Any]
) -> dict[str, Any]:
    current = grammar_guide.fingerprint(grammar_guide.grammar_regions(doc_id, chapter_id))
    stored = guide.get("source_fingerprint") or []
    out = dict(guide)
    out["is_stale"] = current != stored
    return out


@router.get("/{chapter_id}/grammar-guide")
def get_grammar_guide(doc_id: str, chapter_id: str):
    _require_doc(doc_id)
    if storage.load_chapter(doc_id, chapter_id) is None:
        raise HTTPException(404, "chapter not found")
    guide = storage.load_grammar_guide(doc_id, chapter_id)
    if guide is None:
        raise HTTPException(404, "grammar guide not found")
    return _annotate_guide_status(doc_id, chapter_id, guide)


@router.post("/{chapter_id}/grammar-guide")
def request_grammar_guide(
    doc_id: str,
    chapter_id: str,
    response: Response,
    body: GrammarGuideRequest = GrammarGuideRequest(),
):
    _require_doc(doc_id)
    if storage.load_chapter(doc_id, chapter_id) is None:
        raise HTTPException(404, "chapter not found")
    if (
        not body.overwrite
        and storage.load_grammar_guide(doc_id, chapter_id) is not None
    ):
        raise HTTPException(409, "grammar guide already exists; pass overwrite=true to regenerate")

    regions = grammar_guide.grammar_regions(doc_id, chapter_id)
    if not regions:
        raise HTTPException(400, "chapter has no grammar_points regions")
    untranscribed = [r["id"] for r in regions if not r.get("transcription_md")]
    if untranscribed:
        raise HTTPException(
            409,
            f"{len(untranscribed)} grammar region(s) are untranscribed",
        )

    settings = get_settings()
    payload: dict[str, Any] = {
        "job_type": "grammar_guide",
        "doc_id": doc_id,
        "chapter_id": chapter_id,
        "engine": "vlm",
        "provider": "anthropic",
        "config": {"model": settings.default_vlm_model, "max_tokens": 16000},
        "prompt": GRAMMAR_GUIDE_PROMPT,
        "tool_name": "record_grammar_guide",
        "tool_schema": GRAMMAR_GUIDE_TOOL_SCHEMA,
    }
    job = manager.submit(payload)
    response.status_code = 202
    return {"job_id": job["id"]}


@router.delete("/{chapter_id}/grammar-guide")
def delete_grammar_guide(doc_id: str, chapter_id: str):
    _require_doc(doc_id)
    if not storage.delete_grammar_guide(doc_id, chapter_id):
        raise HTTPException(404, "grammar guide not found")
    log.info("grammar_guide_deleted", extra={"doc_id": doc_id, "chapter_id": chapter_id})
    return {"ok": True}
