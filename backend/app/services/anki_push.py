"""Send chapter shortlist words to Anki through AnkiConnect.

This is the only module that writes to Anki, and only when the owner presses
"Send to Anki" (``push``). Everything else, ``preview`` included, only reads.
The writes are limited to two AnkiConnect actions, ``createDeck`` and
``addNotes``; ``_write`` refuses anything else, so existing notes, cards,
decks and deck options can never be updated or deleted from here.

Notes use the owner's existing note type (default ``Kaishi 1.5k``) in a
separate deck (default ``Studious``). Building a note from a store item is a
set of pure functions (``build_note`` and friends).
"""
from __future__ import annotations

import html
import logging
import re
import threading
from typing import Any

from ..config import get_settings
from . import anki, blanks, storage, store

log = logging.getLogger("studious.anki")

WRITE_ACTIONS = frozenset({"createDeck", "addNotes"})
READ_ACTIONS = frozenset(
    {"modelNames", "modelFieldNames", "deckNames", "canAddNotes", "canAddNotesWithErrorDetail"}
)
DUPLICATE_OPTIONS = {"allowDuplicate": False, "duplicateScope": "collection"}
ADD_TIMEOUT = 60  # seconds; addNotes on a few hundred notes

# Every field of the Kaishi 1.5k note type, in order.
KAISHI_FIELDS = (
    "Word",
    "Word Reading",
    "Word Meaning",
    "Word Furigana",
    "Word Audio",
    "Sentence",
    "Sentence Meaning",
    "Sentence Furigana",
    "Sentence Audio",
    "Notes",
    "Pitch Accent",
    "Pitch Accent Notes",
    "Frequency",
    "Picture",
)
# The fields we fill; the note type must have at least these.
FILLED_FIELDS = (
    "Word",
    "Word Reading",
    "Word Meaning",
    "Word Furigana",
    "Sentence",
    "Sentence Meaning",
    "Sentence Furigana",
    "Notes",
    "Frequency",
)

MAX_SENTENCE_CHARS = 120

_push_lock = threading.Lock()


class AnkiPushError(Exception):
    """A push/preview failure with the HTTP status the API should answer."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class AnkiWriteRefused(RuntimeError):
    """An action outside the allow-list was attempted."""


# ---------- Transport (the only write path) ----------


def _write(action: str, params: dict[str, Any] | None = None, *, timeout: float = anki.CONNECT_TIMEOUT) -> Any:
    if action not in WRITE_ACTIONS:
        raise AnkiWriteRefused(f"Refusing AnkiConnect action {action!r}: only {sorted(WRITE_ACTIONS)} may write")
    return anki._post(action, params, timeout=timeout)


def _read(action: str, params: dict[str, Any] | None = None, *, timeout: float = anki.CONNECT_TIMEOUT) -> Any:
    if action not in READ_ACTIONS:
        raise AnkiWriteRefused(f"Refusing AnkiConnect read {action!r}: not a known read action")
    return anki._post(action, params, timeout=timeout)


# ---------- Word, reading, furigana ----------

_SUFFIX_GROUP_RE = re.compile(r"\s*[(（](?:する|な)[)）]\s*$")


def strip_suffix_group(text: str) -> str:
    """料理(する) -> 料理; a plain trailing する or な stays."""
    return _SUFFIX_GROUP_RE.sub("", text or "").strip()


def _is_kana(ch: str) -> bool:
    return "ぁ" <= ch <= "ゖ" or "ァ" <= ch <= "ヺ" or ch == "ー"


def _segments(word: str) -> list[tuple[bool, str]]:
    """Split into (is_kana, text) runs."""
    out: list[tuple[bool, str]] = []
    for ch in word:
        k = _is_kana(ch)
        if out and out[-1][0] == k:
            out[-1] = (k, out[-1][1] + ch)
        else:
            out.append((k, ch))
    return out


def _alignments(segs: list[tuple[bool, str]], reading: str, limit: int = 2) -> list[list[str]]:
    """Every way to give each non-kana run a non-empty slice of the reading
    while the kana runs match it (katakana folded to hiragana). Stops at ``limit``."""
    folded = store.kata_to_hira(reading)
    results: list[list[str]] = []

    def go(i: int, pos: int, acc: list[str]) -> None:
        if len(results) >= limit:
            return
        if i == len(segs):
            if pos == len(reading):
                results.append(acc)
            return
        is_kana, text = segs[i]
        if is_kana:
            if folded.startswith(store.kata_to_hira(text), pos):
                go(i + 1, pos + len(text), [*acc, text])
            return
        for end in range(pos + 1, len(reading) + 1):
            go(i + 1, end, [*acc, reading[pos:end]])

    go(0, 0, [])
    return results


def furigana(headword: str, reading: str) -> str:
    """Anki furigana syntax for a word, e.g. 手[て]に 入[い]れる. Never raises."""
    try:
        word = (headword or "").strip()
        read = (reading or "").strip()
        if not word or not read or all(_is_kana(c) for c in word):
            return word
        segs = _segments(word)
        found = _alignments(segs, read)
        if len(found) != 1:
            return f"{word}[{read}]"
        parts: list[str] = []
        for (is_kana, text), piece in zip(segs, found[0], strict=True):
            if is_kana:
                parts.append(text)
            else:
                parts.append((" " if parts else "") + f"{text}[{piece}]")
        return "".join(parts)
    except Exception:  # noqa: BLE001 - a bad item must never break a preview
        return f"{headword}[{reading}]" if reading else (headword or "")


# ---------- Sentence ----------

_FURI_RE = re.compile(r"([㐀-䶿一-鿿豈-﫿々〆ヵヶ]+)[(（][ぁ-ゖー]+[)）]")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_LEAD_RE = re.compile(r"^\s*(?:#{1,6}|>|[-*+]|\d+[.)])\s+")
_EMPH_RE = re.compile(r"(\*\*|\*|`|~~)")  # not "_": blanks are underscores
_SPACE_RE = re.compile(r"\s+")
# Whitespace between two non-ASCII characters is line-wrap noise in Japanese.
_JA_GAP_RE = re.compile(r"(?<=[^\x00-\x7f])\s+(?=[^\x00-\x7f])")


def plain_sentence(text: str) -> str:
    """Markdown and 漢字(かな) annotations removed, whitespace collapsed."""
    text = _LEAD_RE.sub("", text or "")
    text = _LINK_RE.sub(r"\1", text)
    text = _FURI_RE.sub(r"\1", text)
    text = _EMPH_RE.sub("", text)
    return _SPACE_RE.sub(" ", _JA_GAP_RE.sub("", text)).strip()


def _has_blank(text: str) -> bool:
    return blanks.BLANK_CHAR in blanks.normalize_blanks(text)


def sentence_html(text: str, surface: str, headword: str = "") -> str:
    """Escaped sentence with the first occurrence of the word wrapped in <b>."""
    for needle in (surface, headword):
        needle = plain_sentence(needle) if needle else ""
        pos = text.find(needle) if needle else -1
        if pos >= 0:
            return (
                html.escape(text[:pos], quote=False)
                + "<b>"
                + html.escape(needle, quote=False)
                + "</b>"
                + html.escape(text[pos + len(needle) :], quote=False)
            )
    return html.escape(text, quote=False)


def choose_sentence(item: dict[str, Any], chapter_id: str | None = None) -> tuple[dict[str, Any], str] | None:
    """(sighting, plain text) of the best usable breakdown sentence, or None.
    Vocab-list sightings are list rows, not sentences, so they never count."""
    sightings = [s for s in item.get("sightings") or [] if s.get("source") == "breakdown"]
    in_chapter = [s for s in sightings if chapter_id and s.get("chapter_id") == chapter_id]
    elsewhere = [s for s in sightings if s not in in_chapter]
    for s in in_chapter + elsewhere:
        raw = s.get("sentence_text") or ""
        text = plain_sentence(raw)
        if text and len(text) <= MAX_SENTENCE_CHARS and not _has_blank(raw):
            return s, text
    return None


def sentence_gloss(sighting: dict[str, Any]) -> str:
    """The breakdown's English gloss for the sighting's sentence. Found by
    region and sentence index, and accepted only when that sentence's text is
    the one the sighting recorded (a re-run breakdown may have shifted it)."""
    try:
        breakdown = storage.load_breakdown(sighting["doc_id"], sighting["chapter_id"], sighting["region_id"])
        sentence = ((breakdown or {}).get("sentences") or [])[sighting["sentence_index"]]
        if (sentence.get("text") or "") != (sighting.get("sentence_text") or ""):
            return ""
        return (sentence.get("gloss") or "").strip()
    except (KeyError, IndexError, TypeError, ValueError, OSError, AttributeError):
        return ""


def _provenance(doc_id: str | None, chapter_id: str | None) -> str:
    parts = ["Studious"]
    try:
        doc = storage.load_document(doc_id) if doc_id else None
        chapter = storage.load_chapter(doc_id, chapter_id) if doc_id and chapter_id else None
    except (ValueError, OSError):
        doc = chapter = None
    if doc and doc.get("name"):
        parts.append(doc["name"])
    if chapter and chapter.get("title"):
        parts.append(chapter["title"])
    return html.escape(" · ".join(parts), quote=False)


# ---------- Note ----------


def build_note(item: dict[str, Any], doc_id: str | None = None, chapter_id: str | None = None) -> dict[str, Any]:
    """{"fields", "tags", "has_sentence"} for one store item."""
    headword = strip_suffix_group(item.get("headword") or "")
    reading = strip_suffix_group(item.get("reading") or "")
    chosen = choose_sentence(item, chapter_id)
    sentence = meaning = ""
    note_doc, note_chapter = doc_id, chapter_id
    if chosen:
        sighting, text = chosen
        sentence = sentence_html(text, sighting.get("surface") or "", headword)
        meaning = html.escape(sentence_gloss(sighting), quote=False)
        note_doc = sighting.get("doc_id") or doc_id
        note_chapter = sighting.get("chapter_id") or chapter_id
    notes = _provenance(note_doc, note_chapter)
    own = (item.get("notes") or "").strip()
    if own:
        notes += "<br>" + html.escape(own, quote=False).replace("\n", "<br>")
    rank = (item.get("classifications") or {}).get("freq_rank")
    fields = dict.fromkeys(KAISHI_FIELDS, "")
    fields.update(
        {
            "Word": html.escape(headword, quote=False),
            "Word Reading": html.escape(reading, quote=False),
            "Word Meaning": html.escape(item.get("meaning") or "", quote=False),
            "Word Furigana": html.escape(furigana(headword, reading), quote=False),
            "Sentence": sentence,
            "Sentence Meaning": meaning,
            "Sentence Furigana": sentence,
            "Notes": notes,
            "Frequency": str(int(rank)) if isinstance(rank, (int, float)) and rank > 0 else "",
        }
    )
    tags = ["studious"]
    if doc_id and chapter_id:
        tags.append(f"studious::{doc_id}::{chapter_id}")
    return {"fields": fields, "tags": tags, "has_sentence": bool(sentence)}


# ---------- Preview / push ----------


def select_items(doc_id: str, chapter_id: str, limit: int) -> list[dict[str, Any]]:
    """The first ``limit`` shortlist candidates, via the list endpoint's code path."""
    from ..api.store import _list_items  # local: the api package imports services

    return _list_items(
        "vocab",
        status=None,
        q=None,
        doc_id=doc_id,
        chapter_id=chapter_id,
        source=None,
        sort="recent",
        limit=limit,
        offset=0,
        shortlist=True,
    )["items"]


def _can_add(notes: list[dict[str, Any]]) -> list[tuple[bool, str]]:
    """(can_add, reason) per note. Falls back to canAddNotes on older AnkiConnect."""
    if not notes:
        return []
    try:
        details = _read("canAddNotesWithErrorDetail", {"notes": notes})
        return [
            (bool(d.get("canAdd")), "" if d.get("canAdd") else (d.get("error") or "Anki will not add this note"))
            for d in details
        ]
    except anki.AnkiUnavailable as exc:
        if "unsupported" not in str(exc).lower():
            raise
    flags = _read("canAddNotes", {"notes": notes})
    return [(bool(f), "" if f else "Already in Anki (or cannot be added)") for f in flags]


def _prepare(doc_id: str, chapter_id: str, limit: int) -> dict[str, Any]:
    settings = get_settings()
    deck, model = settings.anki_push_deck, settings.anki_push_note_type
    items = select_items(doc_id, chapter_id, limit)
    try:
        if model not in (_read("modelNames") or []):
            raise AnkiPushError(
                409, f"Anki has no note type named {model!r}. Set ANKI_PUSH_NOTE_TYPE to one of your note types."
            )
        have = set(_read("modelFieldNames", {"modelName": model}) or [])
        missing = [f for f in FILLED_FIELDS if f not in have]
        if missing:
            raise AnkiPushError(409, f"Note type {model!r} is missing field(s): {', '.join(missing)}.")
        deck_exists = deck in (_read("deckNames") or [])
        built = [build_note(i, doc_id, chapter_id) for i in items]
        payload = [
            {
                "deckName": deck,
                "modelName": model,
                "fields": b["fields"],
                "tags": b["tags"],
                "options": dict(DUPLICATE_OPTIONS),
            }
            for b in built
        ]
        verdicts = _can_add(payload)
    except anki.AnkiUnavailable as exc:
        raise AnkiPushError(503, str(exc)) from exc

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item, b, note, (ok, reason) in zip(items, built, payload, verdicts, strict=True):
        word = b["fields"]["Word"]
        if ok and word in seen:
            ok, reason = False, "Another word in this batch has the same spelling"
        seen.add(word)
        rows.append(
            {
                "id": item["id"],
                "headword": item.get("headword") or "",
                "reading": item.get("reading") or "",
                "fields": b["fields"],
                "has_sentence": b["has_sentence"],
                "can_add": ok,
                "reason": reason,
                "headword_match": (item.get("anki") or {}).get("match") == "headword",
                "_note": note,
            }
        )
    return {"deck": deck, "deck_exists": deck_exists, "note_type": model, "rows": rows}


def preview(doc_id: str, chapter_id: str, limit: int) -> dict[str, Any]:
    """What a send would do. Read actions only."""
    prepared = _prepare(doc_id, chapter_id, limit)
    rows = [{k: v for k, v in r.items() if k != "_note"} for r in prepared["rows"]]
    addable = [r for r in rows if r["can_add"]]
    return {
        "deck": prepared["deck"],
        "deck_exists": prepared["deck_exists"],
        "will_create_deck": not prepared["deck_exists"],
        "note_type": prepared["note_type"],
        "counts": {
            "candidates": len(rows),
            "will_add": len(addable),
            "skipped": len(rows) - len(addable),
            "without_sentence": sum(1 for r in addable if not r["has_sentence"]),
            "headword_match": sum(1 for r in addable if r["headword_match"]),
        },
        "items": rows,
    }


def push(doc_id: str, chapter_id: str, limit: int) -> dict[str, Any]:
    """Create the notes in Anki. 409 if another send is running."""
    if not _push_lock.acquire(blocking=False):
        raise AnkiPushError(409, "A send to Anki is already running.")
    try:
        log.info("anki_push_start", extra={"doc_id": doc_id, "chapter_id": chapter_id, "limit": limit})
        prepared = _prepare(doc_id, chapter_id, limit)
        rows = prepared["rows"]
        todo = [r for r in rows if r["can_add"]]
        skipped = [{"id": r["id"], "headword": r["headword"], "reason": r["reason"]} for r in rows if not r["can_add"]]
        failed: list[dict[str, Any]] = []
        created = 0
        deck_created = False
        if todo:
            try:
                _write("createDeck", {"deck": prepared["deck"]})
                deck_created = not prepared["deck_exists"]
                results = _write("addNotes", {"notes": [r["_note"] for r in todo]}, timeout=ADD_TIMEOUT)
            except anki.AnkiUnavailable as exc:
                raise AnkiPushError(503, str(exc)) from exc
            if not isinstance(results, list) or len(results) != len(todo):
                raise AnkiPushError(
                    502, "AnkiConnect returned an unexpected response to addNotes; check Anki before retrying."
                )
            for row, note_id in zip(todo, results, strict=True):
                if note_id is None:
                    failed.append(
                        {
                            "id": row["id"],
                            "headword": row["headword"],
                            "reason": "Anki rejected the note (likely a duplicate)",
                        }
                    )
                else:
                    created += 1
                    store.update_item("vocab", row["id"], status="active")
        sync_error = None
        if created:
            try:
                anki.sync()
            except anki.AnkiUnavailable as exc:
                sync_error = str(exc)
                log.warning("anki_push_sync_failed", extra={"error": sync_error})
        log.info(
            "anki_push_done",
            extra={"created": created, "skipped": len(skipped), "failed": len(failed), "sync_failed": bool(sync_error)},
        )
        return {
            "created": created,
            "skipped": skipped,
            "failed": failed,
            "deck": prepared["deck"],
            "deck_created": deck_created,
            "sync_ok": sync_error is None,
            "sync_error": sync_error,
        }
    finally:
        _push_lock.release()
