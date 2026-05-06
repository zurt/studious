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
    """Merge overlapping links: longer span owns the rendered underline,
    shorter overlappers ride along as `extras` so the popover can show
    both entries.

    Sort order is longer-first, then by match priority
    (exact > reading > stem > llm). The first link that claims a region
    is the rendered primary; any later link overlapping it is appended
    to its `extras` list with just `{kind, index}` — no start/end since
    the span isn't drawn separately.

    Extras are ordered vocab-before-grammar so the popover always
    shows the vocab section first.
    """
    kept: list[dict[str, Any]] = []
    ordered = sorted(
        links,
        key=lambda l: (-(l["end"] - l["start"]), _PRIORITY.get(l["match"], 99)),
    )
    for link in ordered:
        target: dict[str, Any] | None = None
        for k in kept:
            if link["start"] < k["end"] and k["start"] < link["end"]:
                target = k
                break
        if target is None:
            kept.append(link)
            continue
        # Avoid duplicating the primary itself in extras.
        if target["kind"] == link["kind"] and target["index"] == link["index"]:
            continue
        extras = target.setdefault("extras", [])
        if not any(
            e["kind"] == link["kind"] and e["index"] == link["index"] for e in extras
        ):
            extras.append({"kind": link["kind"], "index": link["index"]})
    for k in kept:
        if "extras" in k:
            k["extras"].sort(key=lambda e: 0 if e["kind"] == "vocab" else 1)
    return sorted(kept, key=lambda l: l["start"])


def _links_for_grammar_entry(
    text: str, entry: dict[str, Any], idx: int, used_spans: list[tuple[int, int]]
) -> list[dict[str, Any]]:
    """Locate each LLM-supplied surface string inside the sentence text.

    The model emits literal substrings rather than offsets because span
    arithmetic on long sentences is unreliable. Each surface is
    substring-searched; if the same surface appears more than once
    (e.g., the sentence has two ます), prefer the first occurrence not
    already claimed by a previously-emitted grammar link for this
    entry. Surfaces missing from the text are dropped silently.
    """
    surfaces = entry.get("surfaces")
    if not isinstance(surfaces, list):
        return []
    out: list[dict[str, Any]] = []
    local_used: list[tuple[int, int]] = list(used_spans)
    for surface in surfaces:
        if not isinstance(surface, str) or not surface:
            continue
        pos = _find_unused(text, surface, local_used)
        if pos < 0:
            continue
        end = pos + len(surface)
        out.append({
            "start": pos,
            "end": end,
            "kind": "grammar",
            "index": idx,
            "match": "llm",
        })
        local_used.append((pos, end))
    return out


def _find_unused(text: str, needle: str, used: list[tuple[int, int]]) -> int:
    """Return the first index of `needle` in `text` not already claimed
    at that exact span; -1 if no such occurrence exists.

    "Exact span" rather than "any overlap" so a short surface like `的`
    can still anchor inside a longer surface like `社会文化的な` — those
    are legitimate overlaps that should both surface in the popover.
    The exact-span check still prevents two identical surfaces from
    landing on the same occurrence.
    """
    start = 0
    needle_len = len(needle)
    used_set = {(s, e) for s, e in used}
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            return -1
        if (pos, pos + needle_len) not in used_set:
            return pos
        start = pos + 1


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
        used_grammar_spans: list[tuple[int, int]] = []
        for idx, entry in enumerate(grammar):
            if not isinstance(entry, dict):
                continue
            for link in _links_for_grammar_entry(text, entry, idx, used_grammar_spans):
                raw.append(link)
                used_grammar_spans.append((link["start"], link["end"]))
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
