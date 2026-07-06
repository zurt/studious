"""Pure helpers for classifying documents and naming dataset items.

No file I/O and no backend imports here — these are simple string/id
transforms shared by the store enumerator, the dataset builder, and tests.
"""
from __future__ import annotations

SOURCE_TEXTBOOK = "textbook"
SOURCE_WORKBOOK = "workbook"


def classify_source(doc_filename: str | None) -> str:
    """`workbook` if the document filename contains "workbook" (any case), else `textbook`."""
    if doc_filename and "workbook" in doc_filename.lower():
        return SOURCE_WORKBOOK
    return SOURCE_TEXTBOOK


def source_prefix(source: str) -> str:
    return "wb" if source == SOURCE_WORKBOOK else "tb"


def prompt_kind_for(kind: str, tag: str | None) -> str:
    """Mirrors backend/app/api/regions.py: vocab_list tag -> vocab_list prompt,
    every other region tag -> region prompt, pages -> page prompt."""
    if kind == "page":
        return "page"
    if tag == "vocab_list":
        return "vocab_list"
    return "region"


def region_item_id(source: str, tag: str, region_id: str) -> str:
    return f"{source_prefix(source)}-r-{tag}-{region_id[:8]}"


def page_item_id(source: str, page: int) -> str:
    return f"{source_prefix(source)}-p-{page:04d}"


def dedupe_item_id(base_id: str, doc_id: str, used: set[str]) -> str:
    """Disambiguate an item id if it collides with one already assigned.

    Collisions are only possible if two documents share a source
    classification (e.g. two workbooks) and land on the same tag/page/short
    region-id-prefix. Falls back to appending a slice of the doc id.
    """
    if base_id not in used:
        return base_id
    candidate = f"{base_id}-{doc_id[:6]}"
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{base_id}-{doc_id[:6]}-{suffix}"
    return candidate
