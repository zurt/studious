"""Shared region-selection rules for chapter bulk operations.

Per docs/bulk-operations-plan.md, "Prepare chapter" must never do anything
the single-region transcribe/breakdown buttons couldn't. Both the
`POST .../bulk` endpoint (for the dry-run plan preview) and the
`bulk_chapter` job runner (for the actual per-phase work lists) call these
functions so the selection logic lives in exactly one place.
"""
from __future__ import annotations

from typing import Any

from . import region_chain, storage


def select_transcribe_targets(
    doc_id: str, chapter_id: str, *, overwrite: bool = False
) -> list[dict[str, Any]]:
    """Regions eligible for the bulk transcribe phase, in `list_regions` order.

    Mirrors the single-region transcribe endpoint: every region (any tag)
    without a transcription. `overwrite` widens this to every region in the
    chapter, matching re-transcribe semantics.
    """
    regions = storage.list_regions(doc_id, chapter_id)
    if overwrite:
        return regions
    return [r for r in regions if not r.get("transcription_md")]


def select_breakdown_targets(
    doc_id: str, chapter_id: str, *, overwrite: bool = False
) -> list[dict[str, Any]]:
    """Regions eligible for the bulk breakdown phase, in `list_regions` order.

    Mirrors the single-region breakdown endpoint: tag != vocab_list, a
    transcription exists (including one the transcribe phase just
    produced), the region is not a continuation target (chain heads only —
    the chain's combined transcription is used), and no breakdown exists
    unless `overwrite`.
    """
    out: list[dict[str, Any]] = []
    for region in storage.list_regions(doc_id, chapter_id):
        if region.get("tag") == "vocab_list":
            continue
        if not region.get("transcription_md"):
            continue
        if region_chain.find_inbound_source(doc_id, chapter_id, region["id"]) is not None:
            continue
        if not overwrite and storage.load_breakdown(doc_id, chapter_id, region["id"]) is not None:
            continue
        out.append(region)
    return out
