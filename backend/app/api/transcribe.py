from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..jobs import manager
from ..services import storage
from ..services.range_parser import parse_pages

router = APIRouter(prefix="/api/documents", tags=["transcribe"])


class TranscribeRequest(BaseModel):
    engine: Literal["ocr", "vlm"]
    provider: str
    pages: str = Field("all", description='Range like "1-5, 8, 12-14" or "all".')
    config: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None
    overwrite: bool = False


@router.post("/{doc_id}/transcribe")
def submit_transcription(doc_id: str, req: TranscribeRequest):
    meta = storage.load_document(doc_id)
    if meta is None:
        raise HTTPException(404, "document not found")
    try:
        pages = parse_pages(req.pages, meta["page_count"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    prompt = req.prompt
    if req.engine == "vlm" and not prompt:
        prompt = get_settings().default_vlm_prompt

    payload = {
        "doc_id": doc_id,
        "engine": req.engine,
        "provider": req.provider,
        "pages": pages,
        "config": req.config,
        "prompt": prompt,
        "overwrite": req.overwrite,
        "current_page": None,
    }
    job = manager.submit(payload)
    return {"job_id": job["id"], "pages": pages}
