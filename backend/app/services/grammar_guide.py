"""Helpers for assembling a chapter grammar guide from its regions."""
from __future__ import annotations

from typing import Any

from . import storage


GRAMMAR_TAG = "grammar_points"


class NoGrammarRegionsError(Exception):
    pass


class UntranscribedRegionsError(Exception):
    def __init__(self, region_ids: list[str]) -> None:
        super().__init__(f"{len(region_ids)} grammar region(s) untranscribed")
        self.region_ids = region_ids


def grammar_regions(doc_id: str, chapter_id: str) -> list[dict[str, Any]]:
    return [
        r
        for r in storage.list_regions(doc_id, chapter_id)
        if r.get("tag") == GRAMMAR_TAG
    ]


def fingerprint(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-region transcription fingerprint used to detect source changes."""
    return [
        {
            "region_id": r["id"],
            "transcribed_at": r.get("transcribed_at"),
        }
        for r in regions
    ]


def assemble_source(regions: list[dict[str, Any]]) -> str:
    """Concatenate transcribed grammar regions in page order with separators."""
    parts: list[str] = []
    for r in regions:
        label = r.get("label") or f"page {r['page']}"
        body = (r.get("transcription_md") or "").strip()
        parts.append(f"<region label=\"{label}\">\n{body}\n</region>")
    return "\n\n---\n\n".join(parts)


def prepare_source(doc_id: str, chapter_id: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (source_markdown, regions) or raise."""
    regions = grammar_regions(doc_id, chapter_id)
    if not regions:
        raise NoGrammarRegionsError("chapter has no grammar_points regions")
    missing = [r["id"] for r in regions if not r.get("transcription_md")]
    if missing:
        raise UntranscribedRegionsError(missing)
    return assemble_source(regions), regions
