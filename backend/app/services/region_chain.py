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
    """Concatenate each region's transcription_md as one continuous text.

    Used to feed the LLM (breakdown, exercise completion). No page-break
    markers are inserted — the page boundary is a rendering concern handled
    by the frontend, and any inline marker leaks into prompts and tool
    output as if it were content. Regions are joined with a blank line so
    the model still sees a paragraph break between them.
    """
    parts = [
        (region.get("transcription_md") or "").strip()
        for region in chain
    ]
    return "\n\n".join(p for p in parts if p)
