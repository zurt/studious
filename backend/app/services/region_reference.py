from __future__ import annotations

import logging
from typing import Any

from . import storage

log = logging.getLogger("studious.services.region_reference")


def resolve_references(doc_id: str, chapter_id: str, region_id: str) -> list[dict[str, Any]]:
    """Load the reading passages an exercises region cites, in stored order.

    Targets may live in other chapters or other documents. A target that no
    longer exists (deleted document/chapter/region, or moved to another
    chapter) is skipped rather than raising, as is one with no transcription
    yet — references are supplementary context, so a stale or partial list
    must not block exercise completion the way a missing `continues_to`
    tail would.
    """
    region = storage.load_region(doc_id, chapter_id, region_id)
    if region is None:
        return []
    out: list[dict[str, Any]] = []
    for ref in region.get("references") or []:
        ref_extra = {
            "doc_id": doc_id,
            "chapter_id": chapter_id,
            "region_id": region_id,
            "reference": ref,
        }
        try:
            ref_doc_id = ref["doc_id"]
            ref_chapter_id = ref["chapter_id"]
            doc = storage.load_document(ref_doc_id)
            chapter = storage.load_chapter(ref_doc_id, ref_chapter_id) if doc else None
            target = storage.load_region(ref_doc_id, ref_chapter_id, ref["region_id"]) if chapter else None
        except (KeyError, TypeError, storage.InvalidIdError):
            target = None
        if target is None:
            log.warning("reference_missing", extra=ref_extra)
            continue
        text = (target.get("transcription_md") or "").strip()
        if not text:
            log.warning("reference_untranscribed", extra=ref_extra)
            continue
        out.append(
            {
                "doc_id": ref_doc_id,
                "chapter_id": ref_chapter_id,
                "region_id": target["id"],
                "doc_name": doc.get("name") or ref_doc_id,
                "chapter_title": chapter.get("title") or "",
                "page": target.get("page"),
                "label": target.get("label") or "",
                "transcription_md": text,
            }
        )
    return out


def _source_line(group: list[dict[str, Any]]) -> str:
    head = group[0]
    pages = [r["page"] for r in group if isinstance(r.get("page"), int)]
    if not pages:
        where = ""
    elif min(pages) == max(pages):
        where = f", p.{pages[0]}"
    else:
        where = f", pp.{min(pages)}–{max(pages)}"
    label = f", {head['label']}" if head["label"] else ""
    return f"[Source: {head['doc_name']} — chapter \"{head['chapter_title']}\"{label}{where}]"


def combined_reference_text(resolved: list[dict[str, Any]]) -> str:
    """Render resolved references as labeled blocks for the completion prompt.

    Consecutive references from the same chapter (and with the same region
    label) are treated as one passage: a reading that spans several regions
    — often split mid-sentence at a page or column break — gets a single
    `[Source: …]` line, and its regions are joined with a blank line exactly
    like `region_chain.combined_transcription`. A new label starts wherever
    the chapter or label changes, so discrete cited passages stay separable
    for the model.
    """
    groups: list[list[dict[str, Any]]] = []
    for ref in resolved:
        key = (ref["doc_id"], ref["chapter_id"], ref["label"])
        if groups and (groups[-1][0]["doc_id"], groups[-1][0]["chapter_id"], groups[-1][0]["label"]) == key:
            groups[-1].append(ref)
        else:
            groups.append([ref])
    blocks = [
        _source_line(group) + "\n" + "\n\n".join(r["transcription_md"] for r in group)
        for group in groups
    ]
    return "\n\n".join(blocks)
