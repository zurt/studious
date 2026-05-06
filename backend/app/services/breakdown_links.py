"""Compute inline vocab links for sentence breakdowns.

Per `docs/breakdown-vocab-links-plan.md`, vocab linking only — grammar
links are deferred until the LLM emits span offsets directly.

Offsets are character indices into the sentence text (Unicode code
points; Python string indexing is code-point based).
"""

from __future__ import annotations

from typing import Any, Iterable

# Hiragana block (U+3040–U+309F). Trailing hiragana is dropped to obtain
# a stem like 飲む -> 飲.
_HIRAGANA_RANGE = (0x3040, 0x309F)
# Kanji ranges used to detect "matched span sits inside a longer kanji
# run" (e.g., 行 inside 銀行). Covers CJK Unified Ideographs main block;
# extensions are uncommon enough in study material to ignore for now.
_KANJI_RANGES = ((0x4E00, 0x9FFF),)


def _is_hiragana(ch: str) -> bool:
    cp = ord(ch)
    return _HIRAGANA_RANGE[0] <= cp <= _HIRAGANA_RANGE[1]


def _is_kanji(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _KANJI_RANGES)


def _all_hiragana(s: str) -> bool:
    return bool(s) and all(_is_hiragana(c) for c in s)


def _stem(surface: str) -> str:
    """Drop trailing hiragana to get the leading stem.

    For all-kana surfaces, fall back to the first ~⅔ of characters so
    that hiragana adjectives like おいしい can still attempt a match —
    callers enforce the min-length rule that ultimately rejects very
    short hiragana stems.
    """
    if not surface:
        return ""
    if _all_hiragana(surface):
        n = max(1, (len(surface) * 2) // 3)
        return surface[:n]
    i = len(surface)
    while i > 0 and _is_hiragana(surface[i - 1]):
        i -= 1
    return surface[:i]


def _kanji_run_violation(text: str, start: int, end: int) -> bool:
    """Reject a stem match if it sits inside a longer kanji run.

    e.g., stem 行 matched at position 1 of 銀行 — the char before is
    also kanji, so this isn't really 行く.
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return _is_kanji(before) or _is_kanji(after)


_PRIORITY = {"exact": 0, "reading": 1, "stem": 2, "llm": 3}


def _link_for_vocab_entry(
    text: str, entry: dict[str, Any], idx: int
) -> dict[str, Any] | None:
    word = (entry.get("word") or "").strip()
    reading = (entry.get("reading") or "").strip()

    # 1. Exact match on surface form
    if word:
        pos = text.find(word)
        if pos >= 0:
            return {
                "start": pos,
                "end": pos + len(word),
                "kind": "vocab",
                "index": idx,
                "match": "exact",
            }

    # 2. Reading match
    if reading:
        pos = text.find(reading)
        if pos >= 0:
            return {
                "start": pos,
                "end": pos + len(reading),
                "kind": "vocab",
                "index": idx,
                "match": "reading",
            }

    # 3. Stem match
    if word:
        stem = _stem(word)
        if stem and not (_all_hiragana(stem) and len(stem) < 2):
            pos = text.find(stem)
            if pos >= 0 and not _kanji_run_violation(text, pos, pos + len(stem)):
                return {
                    "start": pos,
                    "end": pos + len(stem),
                    "kind": "vocab",
                    "index": idx,
                    "match": "stem",
                }

    return None


def _resolve_overlaps(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop links that overlap a stronger neighbour.

    Longer span wins; on equal length, higher-priority match wins
    (exact > reading > stem).
    """
    kept: list[dict[str, Any]] = []
    # Sort: longer first, then by priority.
    ordered = sorted(
        links,
        key=lambda l: (-(l["end"] - l["start"]), _PRIORITY.get(l["match"], 99)),
    )
    for link in ordered:
        overlaps_existing = any(
            link["start"] < k["end"] and k["start"] < link["end"] for k in kept
        )
        if not overlaps_existing:
            kept.append(link)
    return sorted(kept, key=lambda l: l["start"])


def _link_for_grammar_entry(
    text: str, entry: dict[str, Any], idx: int
) -> dict[str, Any] | None:
    """Build a grammar link from an LLM-supplied span. Returns None if
    the span is missing, malformed, or out of range.
    """
    span = entry.get("span")
    if not isinstance(span, dict):
        return None
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if start < 0 or end <= start or end > len(text):
        return None
    return {
        "start": start,
        "end": end,
        "kind": "grammar",
        "index": idx,
        "match": "llm",
    }


def compute_sentence_links(sentence: dict[str, Any]) -> list[dict[str, Any]]:
    text = sentence.get("text") or ""
    vocab = sentence.get("vocab") or []
    grammar = sentence.get("grammar") or []
    if not text:
        return []

    raw: list[dict[str, Any]] = []
    if isinstance(vocab, list):
        for idx, entry in enumerate(vocab):
            if not isinstance(entry, dict):
                continue
            link = _link_for_vocab_entry(text, entry, idx)
            if link is not None:
                raw.append(link)
    if isinstance(grammar, list):
        for idx, entry in enumerate(grammar):
            if not isinstance(entry, dict):
                continue
            link = _link_for_grammar_entry(text, entry, idx)
            if link is not None:
                raw.append(link)
    return _resolve_overlaps(raw)


def annotate(breakdown: dict[str, Any]) -> dict[str, Any]:
    """Mutate the breakdown in place, adding a `links` array per sentence."""
    sentences: Iterable[Any] = breakdown.get("sentences") or []
    for sentence in sentences:
        if not isinstance(sentence, dict):
            continue
        sentence["links"] = compute_sentence_links(sentence)
    return breakdown


def needs_links(breakdown: dict[str, Any]) -> bool:
    """True if any sentence is missing the `links` field."""
    for sentence in breakdown.get("sentences") or []:
        if isinstance(sentence, dict) and "links" not in sentence:
            return True
    return False
