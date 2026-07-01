"""API for the central vocab/grammar store (docs/vocab-store-plan.md).

/api/vocab and /api/grammar expose the same list/create/update/delete
surface over the two store kinds; /api/store carries cross-kind
operations (stats, backfill).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import harvest, store

log = logging.getLogger("studious.api.store")

router = APIRouter(prefix="/api", tags=["store"])

_SORTS = ("recent", "updated", "alpha")


class CreateVocab(BaseModel):
    headword: str
    reading: str = ""
    meaning: str = ""
    notes: str = ""
    status: str = "active"


class UpdateVocab(BaseModel):
    headword: str | None = None
    reading: str | None = None
    meaning: str | None = None
    notes: str | None = None
    status: str | None = None


class CreateGrammar(BaseModel):
    pattern: str
    explanation: str = ""
    notes: str = ""
    status: str = "active"


class UpdateGrammar(BaseModel):
    pattern: str | None = None
    explanation: str | None = None
    notes: str | None = None
    status: str | None = None


def _check_status(status: str | None) -> None:
    if status is not None and status not in store.STATUSES:
        raise HTTPException(400, f"invalid status: {status!r}")


def _search_text(kind: str, item: dict[str, Any]) -> str:
    if kind == "vocab":
        fields = (item.get("headword"), item.get("reading"), item.get("meaning"))
    else:
        fields = (item.get("pattern"), item.get("pattern_normalized"), item.get("explanation"))
    return " ".join(f for f in fields if f).casefold()


def _list_items(
    kind: str,
    *,
    status: str | None,
    q: str | None,
    doc_id: str | None,
    chapter_id: str | None,
    source: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    _check_status(status)
    if sort not in _SORTS:
        raise HTTPException(400, f"invalid sort: {sort!r}")
    if source is not None and source not in store.SOURCES:
        raise HTTPException(400, f"invalid source: {source!r}")
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    items = store.list_items(kind)
    if status:
        items = [i for i in items if (i.get("status") or "unreviewed") == status]
    if q:
        needle = q.casefold()
        items = [i for i in items if needle in _search_text(kind, i)]
    if doc_id:
        items = [
            i for i in items if any(s.get("doc_id") == doc_id for s in i.get("sightings", []))
        ]
    if chapter_id:
        items = [
            i
            for i in items
            if any(s.get("chapter_id") == chapter_id for s in i.get("sightings", []))
        ]
    if source:
        items = [
            i for i in items if any(s.get("source") == source for s in i.get("sightings", []))
        ]

    if sort == "updated":
        items.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
    elif sort == "alpha":
        if kind == "vocab":
            items.sort(key=lambda i: (i.get("reading") or "", i.get("headword") or ""))
        else:
            items.sort(key=lambda i: i.get("pattern_normalized") or "")
    # "recent" is list_items' natural order (created_at desc).

    total = len(items)
    return {"items": items[offset : offset + limit], "total": total}


def _create_item(kind: str, body: CreateVocab | CreateGrammar) -> dict[str, Any]:
    _check_status(body.status)
    fields = body.model_dump()
    key_field = "headword" if kind == "vocab" else "pattern"
    fields[key_field] = fields[key_field].strip()
    if not fields[key_field]:
        raise HTTPException(400, f"{key_field} must not be empty")
    if kind == "vocab":
        key = store.vocab_key(fields["headword"], fields["reading"])
        fields["reading"] = store.normalize_reading(fields["reading"], fields["headword"])
    else:
        key = (store.normalize_pattern(fields["pattern"]),)
    existing_id = store.build_index(kind).get(key)
    if existing_id is not None:
        raise HTTPException(
            409, {"detail": f"{kind} item already exists", "id": existing_id}
        )
    item = store.create_item(kind, **fields)
    log.info(f"{kind}_item_created", extra={"item_id": item["id"]})
    return item


def _update_item(kind: str, item_id: str, body: UpdateVocab | UpdateGrammar) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(400, "no fields to update")
    _check_status(changes.get("status"))
    for key_field in ("headword", "pattern"):
        if key_field in changes and not (changes[key_field] or "").strip():
            raise HTTPException(400, f"{key_field} must not be empty")
    updated = store.update_item(kind, item_id, **changes)
    if updated is None:
        raise HTTPException(404, f"{kind} item not found")
    log.info(f"{kind}_item_updated", extra={"item_id": item_id, "fields": sorted(changes)})
    return updated


def _delete_item(kind: str, item_id: str) -> dict[str, Any]:
    if not store.delete_item(kind, item_id):
        raise HTTPException(404, f"{kind} item not found")
    log.info(f"{kind}_item_deleted", extra={"item_id": item_id})
    return {"ok": True}


@router.get("/vocab")
def list_vocab(
    status: str | None = None,
    q: str | None = None,
    doc_id: str | None = None,
    chapter_id: str | None = None,
    source: str | None = None,
    sort: str = "recent",
    limit: int = 100,
    offset: int = 0,
):
    return _list_items(
        "vocab",
        status=status,
        q=q,
        doc_id=doc_id,
        chapter_id=chapter_id,
        source=source,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.post("/vocab", status_code=201)
def create_vocab(body: CreateVocab):
    return _create_item("vocab", body)


@router.patch("/vocab/{item_id}")
def update_vocab(item_id: str, body: UpdateVocab):
    return _update_item("vocab", item_id, body)


@router.delete("/vocab/{item_id}")
def delete_vocab(item_id: str):
    return _delete_item("vocab", item_id)


@router.get("/grammar")
def list_grammar(
    status: str | None = None,
    q: str | None = None,
    doc_id: str | None = None,
    chapter_id: str | None = None,
    source: str | None = None,
    sort: str = "recent",
    limit: int = 100,
    offset: int = 0,
):
    return _list_items(
        "grammar",
        status=status,
        q=q,
        doc_id=doc_id,
        chapter_id=chapter_id,
        source=source,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.post("/grammar", status_code=201)
def create_grammar(body: CreateGrammar):
    return _create_item("grammar", body)


@router.patch("/grammar/{item_id}")
def update_grammar(item_id: str, body: UpdateGrammar):
    return _update_item("grammar", item_id, body)


@router.delete("/grammar/{item_id}")
def delete_grammar(item_id: str):
    return _delete_item("grammar", item_id)


@router.get("/store/stats")
def store_stats():
    return {"vocab": store.stats("vocab"), "grammar": store.stats("grammar")}


@router.post("/store/backfill")
async def run_backfill():
    """Re-harvest all vocab_list transcriptions and breakdowns on disk.

    Pure-local work (no LLM calls), so it runs inline in a thread rather
    than through the job queue.
    """
    totals = await asyncio.to_thread(harvest.backfill)
    return totals
