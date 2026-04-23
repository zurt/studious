from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from ..jobs import manager
from ..services import storage

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get_job(job_id: str):
    job = storage.load_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@router.get("/{job_id}/events")
async def job_events(job_id: str, request: Request):
    job = storage.load_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")

    queue = manager.subscribe(job_id)

    async def event_stream():
        try:
            # Replay current status as the first event so late subscribers
            # see something meaningful.
            current = storage.load_job(job_id) or {}
            yield {"event": "snapshot", "data": json.dumps(current, ensure_ascii=False)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": item["event"], "data": json.dumps(item["data"], ensure_ascii=False)}
                if item["event"] in {"job-done", "job-failed"}:
                    break
        finally:
            manager.unsubscribe(job_id, queue)

    return EventSourceResponse(event_stream())
