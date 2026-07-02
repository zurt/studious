"""Study (built-in SRS) API — milestone 3.4 of docs/vocab-store-plan.md.

The queue is derived on demand from the store plus the append-only
review log; submitting a review appends one event and returns the
card's new state (including its next due date) so the frontend can
decide whether to re-show a failed card within the session.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import srs, store

log = logging.getLogger("studious.api.study")

router = APIRouter(prefix="/api/study", tags=["study"])


class ReviewBody(BaseModel):
    kind: str
    item_id: str
    card_type: str
    grade: int
    elapsed_ms: int | None = None


@router.get("/queue")
def study_queue(limit: int = 20, new_limit: int = 10):
    return srs.build_queue(limit=limit, new_limit=new_limit)


@router.post("/reviews", status_code=201)
def submit_review(body: ReviewBody):
    item = store.get_item(body.kind, body.item_id) if body.kind in store.KINDS else None
    if item is None or item.get("deleted"):
        raise HTTPException(404, f"{body.kind} item not found")
    try:
        state = srs.record_review(
            kind=body.kind,
            item_id=body.item_id,
            card_type=body.card_type,
            grade=body.grade,
            elapsed_ms=body.elapsed_ms,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log.info(
        "review_recorded",
        extra={
            "kind": body.kind,
            "item_id": body.item_id,
            "card_type": body.card_type,
            "grade": body.grade,
        },
    )
    return {"state": state.as_dict()}
