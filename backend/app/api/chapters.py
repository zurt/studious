from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import storage

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
