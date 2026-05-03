from __future__ import annotations

from fastapi import APIRouter, Query

from ..services import costs

router = APIRouter(prefix="/api/costs", tags=["costs"])


@router.get("/summary")
def get_summary():
    return costs.summary()


@router.get("/audit")
def get_audit(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    return costs.paginated_audit(limit=limit, offset=offset)


@router.get("/pricing")
def get_pricing():
    from ..config import MODEL_PRICING

    return {"models": MODEL_PRICING, "unit": "USD per 1M tokens"}
