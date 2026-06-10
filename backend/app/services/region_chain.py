from __future__ import annotations

from typing import Any

from . import storage


def resolve_chain(doc_id: str, chapter_id: str, region_id: str) -> list[dict[str, Any]]:
    """Walk continues_to pointers forward. Returns [head, ..., tail].

    Stops at the first missing target or repeated id (cycle guard).
    """
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current_id: str | None = region_id
    while current_id and current_id not in seen:
        region = storage.load_region(doc_id, chapter_id, current_id)
        if region is None:
            break
        seen.add(current_id)
        chain.append(region)
        nxt = region.get("continues_to")
        current_id = nxt if isinstance(nxt, str) else None
    return chain


def combined_transcription(chain: list[dict[str, Any]]) -> str:
    """Concatenate each region's transcription_md with a page-aware separator."""
    parts: list[str] = []
    for idx, region in enumerate(chain):
        text = region.get("transcription_md") or ""
        if not text:
            continue
        if idx == 0:
            parts.append(text)
        else:
            page = region.get("page")
            parts.append(f"\n\n---\n(continues on page {page})\n\n{text}")
    return "".join(parts)
