"""API for the central vocab/grammar store (docs/design/vocab-store-plan.md).

/api/vocab and /api/grammar expose the same list/create/update/delete
surface over the two store kinds; /api/store carries cross-kind
operations (stats, backfill).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services import anki as anki_service
from ..services import (
    anki_push,
    enrich,
    examples,
    harvest,
    jmdict,
    store,
    tts,
    voicevox,
    wanikani,
)
from ..services import shortlist as shortlist_service

log = logging.getLogger("studious.api.store")

router = APIRouter(prefix="/api", tags=["store"])

_SORTS = ("recent", "updated", "alpha", "priority", "frequency")
_ANKI_FILTERS = ("any", "none", *anki_service.STATES)


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


class ExamplesBody(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=40)
    force: bool = False


class MergeBody(BaseModel):
    source_id: str


class LookupEntry(BaseModel):
    headword: str
    reading: str = ""


class LookupBody(BaseModel):
    entries: list[LookupEntry]


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
        fields = (
            item.get("headword"),
            item.get("reading"),
            item.get("meaning"),
            *(item.get("surface_variants") or []),
        )
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
    anki_filter: str | None = None,
    shortlist: bool = False,
    excluded: str | None = None,
) -> dict[str, Any]:
    _check_status(status)
    if excluded is not None and excluded not in shortlist_service.REASONS:
        raise HTTPException(400, f"invalid excluded reason: {excluded!r}")
    if excluded is not None and shortlist:
        raise HTTPException(400, "excluded and shortlist cannot be combined")
    if anki_filter is not None and anki_filter not in _ANKI_FILTERS:
        raise HTTPException(400, f"invalid anki filter: {anki_filter!r}")
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
    elif sort == "priority":
        # Unenriched items (priority_group null) sort last within their bucket.
        items.sort(key=lambda i: (i.get("priority_group") or 9, i.get("reading") or ""))
    elif sort == "frequency":
        if kind != "vocab":
            raise HTTPException(400, "sort=frequency applies to vocab only")
        # Rank ascending; unranked last. list.sort is stable, so ties and the
        # unranked tail keep the newest-first order.
        items.sort(key=lambda i: (i.get("classifications") or {}).get("freq_rank") or float("inf"))
    # "recent" is list_items' natural order (created_at desc).

    if kind == "vocab":
        # Anki state is joined at read time from the snapshot (never stored).
        # Filter before paging so `total` matches what the filter returns.
        index = anki_service.get_index()
        items = [
            {**i, "anki": anki_service.lookup(i.get("headword", ""), i.get("reading"), i.get("jmdict_seq"), index)}
            for i in items
        ]
        if anki_filter == "any":
            items = [i for i in items if i["anki"]]
        elif anki_filter == "none":
            items = [i for i in items if not i["anki"]]
        elif anki_filter:
            items = [i for i in items if i["anki"] and i["anki"]["state"] == anki_filter]

        # Shortlist assessment and the WaniKani burned flag are read-time joins too.
        burned = wanikani.burned_index()
        for i in items:
            i["wk_burned"] = burned.get(i.get("headword", ""), False)
            i["shortlist_excluded"] = shortlist_service.assess(i, i["anki"], i["wk_burned"])
        if excluded:
            items = [i for i in items if i["shortlist_excluded"] == excluded]
        elif shortlist:
            counts = dict.fromkeys(shortlist_service.REASONS, 0)
            for i in items:
                if i["shortlist_excluded"]:
                    counts[i["shortlist_excluded"]] += 1
            items = [i for i in items if not i["shortlist_excluded"]]
            items.sort(key=lambda i: shortlist_service.order_key(i, chapter_id))
            return {
                "items": items[offset : offset + limit],
                "total": len(items),
                "shortlist": {
                    "excluded": counts,
                    "wk_burned": sum(1 for i in items if i["wk_burned"]),
                },
            }

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
    if kind == "vocab" and "meaning" in changes:
        # A hand-edited meaning must survive future enrichment passes.
        changes["meaning_source"] = "user"
        changes["meaning_context"] = (changes["meaning"] or "").strip()
    updated = store.update_item(kind, item_id, **changes)
    if updated is None:
        raise HTTPException(404, f"{kind} item not found")
    log.info(f"{kind}_item_updated", extra={"item_id": item_id, "fields": sorted(changes)})
    return updated


def _merge_items(kind: str, item_id: str, body: MergeBody) -> dict[str, Any]:
    try:
        merged = store.merge_items(kind, item_id, body.source_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if merged is None:
        raise HTTPException(404, f"{kind} item not found")
    log.info(
        f"{kind}_items_merged",
        extra={"target_id": item_id, "source_id": body.source_id},
    )
    return merged


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
    anki: str | None = None,
    shortlist: bool = False,
    excluded: str | None = None,
):
    return _list_items(
        "vocab",
        anki_filter=anki,
        shortlist=shortlist,
        excluded=excluded,
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


@router.post("/vocab/examples")
def generate_vocab_examples(body: ExamplesBody):
    """Generate (and store) an example sentence for each item, in the Kaishi
    style. Items that already have one are reported as `kept` unless `force`."""
    try:
        return examples.generate_examples(body.item_ids, force=body.force)
    except examples.ExamplesError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.delete("/vocab/{item_id}/example")
def delete_vocab_example(item_id: str):
    if not examples.remove_example(item_id):
        raise HTTPException(404, "vocab item not found")
    return {"ok": True}


@router.get("/tts/status")
def tts_status():
    return tts.status()


@router.get("/tts/speakers")
def tts_speakers():
    """Speakers of the VOICEVOX-compatible engine at the configured URL."""
    if tts.engine() != "voicevox":
        raise HTTPException(400, "Speakers are listed for the VOICEVOX engine only.")
    try:
        return {"url": tts.url(), "speaker": tts.speaker(), "speakers": voicevox.speakers(tts.url())}
    except voicevox.EngineError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/tts/test")
def tts_test():
    """A fixed sentence through the selected engine and speaker."""
    try:
        path = tts.synthesize(tts.TEST_SENTENCE)
    except tts.TtsError as exc:
        raise HTTPException(503, str(exc)) from exc
    return FileResponse(path, media_type=tts.media_type(path))


@router.get("/vocab/{item_id}/audio")
def vocab_audio(item_id: str, part: str = "word"):
    """The clip for the item's word or sentence, as it would go on the card."""
    if part not in ("word", "sentence"):
        raise HTTPException(400, "part must be 'word' or 'sentence'")
    item = store.get_item("vocab", item_id)
    if item is None or item.get("deleted"):
        raise HTTPException(404, "vocab item not found")
    note = anki_push.build_note(item)
    text = note["word_text"] if part == "word" else note["sentence_text"]
    if not text:
        raise HTTPException(404, f"this item has no {part} to speak")
    if not tts.is_available():
        raise HTTPException(503, tts.unavailable_reason())
    reading = note["word_reading"] if part == "word" else note["sentence_reading"]
    try:
        path = tts.synthesize(text, anki_push.expected_reading(reading))
    except tts.TtsError as exc:
        raise HTTPException(503, str(exc)) from exc
    return FileResponse(path, media_type=tts.media_type(path))


@router.post("/vocab/{item_id}/merge")
def merge_vocab(item_id: str, body: MergeBody):
    return _merge_items("vocab", item_id, body)


@router.post("/vocab/lookup")
def lookup_vocab(body: LookupBody):
    """Batch-resolve headword+reading pairs to store items.

    Used by the breakdown pane to mark words already in the store and
    de-emphasize known ones. Each entry resolves to ``{id, status}`` or
    ``null``; surface variants recorded by merges match too.
    """
    index = store.build_index("vocab")
    variant_ids: dict[str, str] = {}
    for item in store.list_items("vocab"):
        for variant in item.get("surface_variants") or []:
            variant_ids[variant] = item["id"]
    matches: list[dict[str, Any] | None] = []
    for entry in body.entries:
        item_id = index.get(store.vocab_key(entry.headword, entry.reading))
        if item_id is None:
            item_id = variant_ids.get(entry.headword.strip())
        item = store.get_item("vocab", item_id) if item_id else None
        if item is None or item.get("deleted"):
            matches.append(None)
        else:
            matches.append(
                {"id": item["id"], "status": item.get("status") or "unreviewed"}
            )
    return {"matches": matches}


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


@router.post("/grammar/{item_id}/merge")
def merge_grammar(item_id: str, body: MergeBody):
    return _merge_items("grammar", item_id, body)


@router.get("/store/coverage")
def store_coverage(chapter_id: str):
    """Chapter coverage: per-kind status counts over items sighted in
    the chapter ("N of M chapter vocab known")."""
    out: dict[str, dict[str, int]] = {}
    for kind in store.KINDS:
        counts = {status: 0 for status in store.STATUSES}
        total = 0
        for item in store.list_items(kind):
            if any(
                s.get("chapter_id") == chapter_id for s in item.get("sightings", [])
            ):
                total += 1
                status = item.get("status") or "unreviewed"
                counts[status] = counts.get(status, 0) + 1
        out[kind] = {"total": total, **counts}
    return out


@router.get("/store/stats")
def store_stats():
    return {
        "vocab": store.stats("vocab"),
        "grammar": store.stats("grammar"),
        "jmdict": {"available": jmdict.is_available(), **jmdict.meta()},
    }


@router.post("/store/enrich")
async def run_enrich(force: bool = False):
    """(Re-)link store items against the local JMdict/JLPT index.

    With force=true every item is re-enriched (after rebuilding the
    index); otherwise only never-attempted items are touched. 409 when
    the index hasn't been built (`make refs`).
    """
    if not jmdict.is_available():
        raise HTTPException(409, "JMdict index not built — run `make refs` first")
    return await asyncio.to_thread(enrich.enrich_pending, force=force)


@router.get("/refs/wanikani/status")
def wanikani_status():
    return wanikani.status()


@router.get("/refs/anki/status")
def anki_status():
    return anki_service.status()


@router.post("/refs/anki/sync")
async def anki_sync():
    """Read-only import of Anki card state via AnkiConnect (Anki must be
    open). 503 with an actionable message when Anki is unreachable."""
    try:
        result = await asyncio.to_thread(anki_service.sync)
    except anki_service.AnkiUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    index = anki_service.get_index()
    matched = sum(
        1
        for i in store.list_items("vocab")
        if anki_service.lookup(i.get("headword", ""), i.get("reading"), i.get("jmdict_seq"), index)
    )
    return {**result, "matched": matched}


@router.post("/refs/wanikani/sync")
async def wanikani_sync(full: bool = False):
    """Incrementally sync WaniKani subjects, study materials, and
    assignments into the local cache, then re-enrich store items so
    WK levels and links land in classifications."""
    if not wanikani.is_configured():
        raise HTTPException(
            409,
            "WANIKANI_API_TOKEN is not set — store your token in the Keychain "
            "and export it like ANTHROPIC_API_KEY (see README)",
        )
    try:
        result = await asyncio.to_thread(wanikani.sync, full=full)
    except Exception as exc:
        log.error("wanikani_sync_failed", extra={"error": str(exc)})
        raise HTTPException(502, f"WaniKani sync failed: {exc}") from exc
    enriched = await asyncio.to_thread(enrich.enrich_pending, force=True)
    return {**result, "enriched": enriched}


@router.get("/vocab/{item_id}/wanikani")
def vocab_wanikani(item_id: str):
    """Vocab → kanji → radical drill-down with WK mnemonics, the user's
    own WK notes, and SRS history (display only)."""
    item = store.get_item("vocab", item_id)
    if item is None or item.get("deleted"):
        raise HTTPException(404, "vocab item not found")
    if not wanikani.has_subjects():
        raise HTTPException(409, "WaniKani cache is empty — run a sync first")
    payload = wanikani.drilldown(item.get("headword") or "")
    if payload is None:
        raise HTTPException(404, "no WaniKani subject for this word")
    return payload


@router.post("/store/backfill")
async def run_backfill():
    """Re-harvest all vocab_list transcriptions and breakdowns on disk.

    Pure-local work (no LLM calls), so it runs inline in a thread rather
    than through the job queue.
    """
    totals = await asyncio.to_thread(harvest.backfill)
    return totals
