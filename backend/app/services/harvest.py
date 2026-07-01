"""Harvest vocab/grammar from transcriptions and breakdowns into the store.

Two sources feed the central store (docs/vocab-store-plan.md):

- ``vocab_list`` region transcriptions — the structured
  ``term（reading）gloss`` / ``term　gloss`` markdown emitted by
  VOCAB_LIST_TRANSCRIBE_PROMPT. Textbook-curated, higher trust.
- Sentence breakdowns — per-sentence ``vocab`` and ``grammar`` entries.

Both run through ``store.replace_region_sightings`` so re-transcribing
or regenerating a region converges instead of duplicating.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import storage, store

log = logging.getLogger("studious.harvest")

# Leading item index tying an entry to the passage: `1`, `12.`, `(4)`,
# `（前文）`. Only stripped when what remains still parses as an entry.
_INDEX_RE = re.compile(r"^(?:\d{1,3}[．.]?|[（(][^（）()]{1,8}[）)])\s*")

# `term（reading）gloss` — the reading must be pure kana (plus the
# prolonged-sound and middle-dot marks), which is what separates a real
# reading from parenthesized page references like `（p. 28）` in section
# headers. Half-width parens accepted for robustness.
_READING_ENTRY_RE = re.compile(
    r"^(?P<term>[^（）()\s][^（）()]*)[（(]"
    r"(?P<reading>[ぁ-ゖァ-ヺーゝゞヽヾ・]+)[）)]\s*"
    r"(?P<gloss>\S.*)$"
)

# `term　gloss` — kana-only or expression entries with no reading column,
# separated by an ideographic space (U+3000).
_KANA_ENTRY_RE = re.compile(r"^(?P<term>[^　]+)　+(?P<gloss>\S.*)$")


def _parse_entry_line(line: str) -> dict[str, str] | None:
    m = _READING_ENTRY_RE.match(line)
    if m:
        return {
            "headword": m.group("term").strip(),
            "reading": m.group("reading"),
            "meaning": m.group("gloss").strip(),
        }
    m = _KANA_ENTRY_RE.match(line)
    # Glosses are English; requiring an ASCII letter rejects section
    # headers that happen to contain an ideographic space.
    if m and re.search(r"[A-Za-z]", m.group("gloss")):
        return {
            "headword": m.group("term").strip(),
            "reading": "",
            "meaning": m.group("gloss").strip(),
        }
    return None


def parse_vocab_list_markdown(markdown: str) -> list[dict[str, Any]]:
    """Extract vocab entries from a vocab_list transcription.

    Returns one dict per entry (``headword``/``reading``/``meaning`` plus
    ``line_index`` and the original ``line``). Section headers, blank
    lines, and anything else that doesn't parse are skipped.
    """
    entries: list[dict[str, Any]] = []
    for i, raw in enumerate(markdown.splitlines()):
        line = raw.strip()
        if not line:
            continue
        # Try with the leading item index stripped first — otherwise a
        # `1 国民（こくみん）…` line parses with the index absorbed into
        # the term. Fall back to the raw line for index-less entries.
        parsed = None
        stripped = _INDEX_RE.sub("", line, count=1)
        if stripped != line:
            parsed = _parse_entry_line(stripped)
        if parsed is None:
            parsed = _parse_entry_line(line)
        if parsed is None:
            continue
        entries.append({**parsed, "line_index": i, "line": line})
    return entries


def ingest_vocab_list_region(
    doc_id: str, chapter_id: str, region: dict[str, Any]
) -> dict[str, int]:
    """Harvest a transcribed vocab_list region into the vocab store."""
    markdown = region.get("transcription_md") or ""
    parsed = parse_vocab_list_markdown(markdown)
    entries = [
        {
            "headword": e["headword"],
            "reading": e["reading"],
            "meaning": e["meaning"],
            "sentence_index": e["line_index"],
            "surface": e["headword"],
            "sentence_text": e["line"],
        }
        for e in parsed
    ]
    result = store.replace_region_sightings(
        "vocab",
        doc_id=doc_id,
        chapter_id=chapter_id,
        region_id=region["id"],
        source="vocab_list",
        entries=entries,
    )
    log.info(
        "harvest_vocab_list",
        extra={
            "doc_id": doc_id,
            "chapter_id": chapter_id,
            "region_id": region["id"],
            "parsed": len(entries),
            **result,
        },
    )
    return result


def ingest_breakdown(
    doc_id: str, chapter_id: str, region_id: str, breakdown: dict[str, Any]
) -> dict[str, dict[str, int]]:
    """Harvest a sentence breakdown's vocab and grammar into the store."""
    vocab_entries: list[dict[str, Any]] = []
    grammar_entries: list[dict[str, Any]] = []
    for i, sentence in enumerate(breakdown.get("sentences") or []):
        text = sentence.get("text") or ""
        for v in sentence.get("vocab") or []:
            vocab_entries.append(
                {
                    "headword": v.get("word") or "",
                    "reading": v.get("reading") or "",
                    "meaning": v.get("meaning") or "",
                    "sentence_index": i,
                    "surface": v.get("word") or "",
                    "sentence_text": text,
                }
            )
        for g in sentence.get("grammar") or []:
            surfaces = g.get("surfaces") or []
            grammar_entries.append(
                {
                    "pattern": g.get("pattern") or "",
                    "explanation": g.get("explanation") or "",
                    "sentence_index": i,
                    "surface": surfaces[0] if surfaces else (g.get("pattern") or ""),
                    "sentence_text": text,
                }
            )

    result = {
        "vocab": store.replace_region_sightings(
            "vocab",
            doc_id=doc_id,
            chapter_id=chapter_id,
            region_id=region_id,
            source="breakdown",
            entries=vocab_entries,
        ),
        "grammar": store.replace_region_sightings(
            "grammar",
            doc_id=doc_id,
            chapter_id=chapter_id,
            region_id=region_id,
            source="breakdown",
            entries=grammar_entries,
        ),
    }
    log.info(
        "harvest_breakdown",
        extra={
            "doc_id": doc_id,
            "chapter_id": chapter_id,
            "region_id": region_id,
            "vocab_created": result["vocab"]["created"],
            "grammar_created": result["grammar"]["created"],
        },
    )
    return result


def backfill() -> dict[str, Any]:
    """Re-harvest every vocab_list transcription and breakdown on disk.

    Idempotent — safe to run repeatedly; existing sightings converge via
    replace_region_sightings. Used to seed the store from data that
    predates it.
    """
    totals = {
        "vocab_list_regions": 0,
        "breakdowns": 0,
        "vocab_created": 0,
        "grammar_created": 0,
    }
    for doc in storage.list_documents():
        doc_id = doc["id"]
        for chapter in storage.list_chapters(doc_id):
            chapter_id = chapter["id"]
            for region in storage.list_regions(doc_id, chapter_id):
                if region.get("tag") == "vocab_list" and region.get("transcription_md"):
                    result = ingest_vocab_list_region(doc_id, chapter_id, region)
                    totals["vocab_list_regions"] += 1
                    totals["vocab_created"] += result["created"]
                breakdown = storage.load_breakdown(doc_id, chapter_id, region["id"])
                if breakdown:
                    result = ingest_breakdown(
                        doc_id, chapter_id, region["id"], breakdown
                    )
                    totals["breakdowns"] += 1
                    totals["vocab_created"] += result["vocab"]["created"]
                    totals["grammar_created"] += result["grammar"]["created"]
    log.info("harvest_backfill_done", extra=totals)
    return totals
