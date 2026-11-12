"""Send a chapter's shortlist words to Anki (see services/anki_push.py)."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import anki_push

router = APIRouter(prefix="/api/anki", tags=["anki"])


class PushPreview(BaseModel):
    doc_id: str
    chapter_id: str
    limit: int = Field(default=125, ge=1, le=500)


class PushSend(PushPreview):
    confirm: Any = None
    audio: bool | None = None  # default: the ANKI_PUSH_AUDIO setting


async def _run(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except anki_push.AnkiPushError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.post("/push/preview")
async def push_preview(body: PushPreview):
    return await _run(anki_push.preview, body.doc_id, body.chapter_id, body.limit)


@router.post("/push")
async def push(body: PushSend):
    if body.confirm is not True:
        raise HTTPException(400, "confirm must be true to send words to Anki")
    return await _run(anki_push.push, body.doc_id, body.chapter_id, body.limit, body.audio)
