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


def _fold(s: str) -> str:
    return store.kata_to_hira(s)


def _align(word: str, read: str, relaxed: bool = True) -> str | None:
    """Furigana string when the reading aligns uniquely, else None. A kana
    prefix or suffix of the headword that the reading omits (お笑い / わらい)
    is kept outside the brackets."""
    segs = _segments(word)
    folded = _fold(read)
    attempts: list[tuple[list[tuple[bool, str]], str, str]] = [(segs, "", "")]
    lead = segs[0][1] if segs[0][0] else ""
    trail = segs[-1][1] if segs[-1][0] else ""
    cut_lead = relaxed and bool(lead) and not folded.startswith(_fold(lead))
    cut_trail = relaxed and bool(trail) and len(segs) > 1 and not folded.endswith(_fold(trail))
    if cut_lead:
        attempts.append((segs[1:], lead, ""))
    if cut_trail:
        attempts.append((segs[:-1], "", trail))
    if cut_lead and cut_trail and len(segs) > 2:
        attempts.append((segs[1:-1], lead, trail))
    for body, pre, post in attempts:
        if not body or all(k for k, _ in body):
            continue
        found = _alignments(body, read)
        if len(found) != 1:
            continue
        parts: list[str] = [pre] if pre else []
        for (is_kana, text), piece in zip(body, found[0], strict=True):
            parts.append(text if is_kana else (" " if parts else "") + f"{text}[{piece}]")
        return "".join(parts) + post
    return None


_ALT_SPLIT_RE = re.compile(r"\s*[・/／,、]\s*")


def _all_katakana(word: str) -> bool:
    return bool(word) and all("ァ" <= c <= "ヺ" or c in "ー・" for c in word) and any(
        "ァ" <= c <= "ヺ" for c in word
    )


def pick_reading(headword: str, reading: str) -> str:
    """One reading from a stored value that may list alternatives
    (ほか・そのた, やめる / とめる): the first one that aligns uniquely with the
    headword, else the first. An all-katakana headword is its own reading."""
    word = (headword or "").strip()
    if _all_katakana(word):
        return word
    alts = [a for a in _ALT_SPLIT_RE.split((reading or "").strip()) if a]
    if not alts:
        return ""
    for relaxed in (False, True):  # an exact alignment beats one that drops omitted kana
        for alt in alts:
            try:
                if _align(word, alt, relaxed) is not None:
                    return alt
            except Exception:  # noqa: BLE001
                continue
    return alts[0]


def furigana(headword: str, reading: str) -> str:
    """Anki furigana syntax for a word, e.g. 手[て]に 入[い]れる. Never raises."""
    try:
        word = (headword or "").strip()
        read = (reading or "").strip()
        if not word or not read or all(_is_kana(c) for c in word):
            return word
        return _align(word, read) or f"{word}[{read}]"
    except Exception:  # noqa: BLE001 - a bad item must never break a preview
        return f"{headword}[{reading}]" if reading else (headword or "")


# ---------- Sentence ----------

_FURI_RE = re.compile(r"([㐀-䶿一-鿿豈-﫿々〆ヵヶ]+)[(（][ぁ-ゖー]+[)）]")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_EMPH_RE = re.compile(r"(\*\*|\*|`|~~)")  # not "_": blanks are underscores
_SPACE_RE = re.compile(r"\s+")
# Whitespace between two non-ASCII characters is line-wrap noise in Japanese.
_JA_GAP_RE = re.compile(r"(?<=[^\x00-\x7f])\s+(?=[^\x00-\x7f])")
# Markdown block prefixes, then an exercise item marker: circled digit,
# 1. / 1) / １． / (1), a bare number then a space, or a bullet.
_BLOCK_RE = re.compile(r"^\s*(?:#{1,6}\s+|>\s*)")
_MARKER_RE = re.compile(
    r"^\s*(?:(?P<circled>[①-⑳])\s*"
    r"|[(（](?P<paren>\d+)[)）]\s*"
    r"|(?P<dot>\d+)\s*[.)．）]\s*"
    r"|(?P<bare>\d+)\s+"
    r"|[-*+•●○▪・]\s+)"
)
_EMPTY_BRACKETS_RE = re.compile(r"[(（\[［【「『]\s*[)）\]］】」』]")
_UNDERSCORE_RUN_RE = re.compile(r"_{2,}")
_TERMINATORS = "。！？!?"
_CLOSERS = "」』）)”\"'’】］]"


def split_marker(text: str) -> tuple[str, int | None]:
    """(text without a leading item marker, the marker's number if any)."""
    text = _BLOCK_RE.sub("", text or "")
    m = _MARKER_RE.match(text)
    if not m:
        return text, None
    num: int | None = None
    if m.group("circled"):
        num = ord(m.group("circled")) - 0x2460 + 1
    else:
        digits = m.group("paren") or m.group("dot") or m.group("bare")
        if digits:
            num = int(digits)
    return text[m.end() :], num


def plain_sentence(text: str) -> str:
    """Markdown, item markers and 漢字(かな) annotations removed, whitespace collapsed."""
    text, _ = split_marker(text)
    text = _LINK_RE.sub(r"\1", text)
    text = _FURI_RE.sub(r"\1", text)
    text = _EMPH_RE.sub("", text)
    return _SPACE_RE.sub(" ", _JA_GAP_RE.sub("", text)).strip()


def _has_blank(text: str) -> bool:
    return blanks.BLANK_CHAR in blanks.normalize_blanks(text) or bool(_UNDERSCORE_RUN_RE.search(text))


def usable_sentence(raw: str) -> str | None:
    """Cleaned sentence text, or None when it is exercise debris: a table, a
    word bank, a blank in any style, empty brackets (checked before and after
    cleaning), no sentence-ending mark, or too long."""
    if not raw:
        return None
    text = plain_sentence(raw)
    if not text or len(text) > MAX_SENTENCE_CHARS:
        return None
    for probe in (raw, text):
        if "|" in probe or "□" in probe or _has_blank(probe) or _EMPTY_BRACKETS_RE.search(probe):
            return None
    if not any(t in text for t in _TERMINATORS):
        return None
    if text.rstrip(_CLOSERS + " ")[-1:] not in tuple(_TERMINATORS):
        return None
    return text


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


def _region_tag(sighting: dict[str, Any], cache: dict[tuple, str | None]) -> str | None:
    key = (sighting.get("doc_id"), sighting.get("chapter_id"), sighting.get("region_id"))
    if key not in cache:
        try:
            region = storage.load_region(*key)
        except (ValueError, OSError, TypeError):
            region = None
        cache[key] = (region or {}).get("tag")
    return cache[key]


def choose_sentence(
    item: dict[str, Any],
    chapter_id: str | None = None,
    cache: dict[tuple, str | None] | None = None,
) -> tuple[dict[str, Any], str] | None:
    """(sighting, plain text) of the best usable breakdown sentence, or None.
    Vocab-list sightings are list rows, not sentences, so they never count.
    Ranked: reading_passage regions first, then the given chapter, then the
    shorter sentence."""
    cache = {} if cache is None else cache
    ranked: list[tuple[tuple, dict[str, Any], str]] = []
    for s in item.get("sightings") or []:
        if s.get("source") != "breakdown":
            continue
        text = usable_sentence(s.get("sentence_text") or "")
        if text is None:
            continue
        key = (
            0 if _region_tag(s, cache) == "reading_passage" else 1,
            0 if chapter_id and s.get("chapter_id") == chapter_id else 1,
            len(text),
        )
        ranked.append((key, s, text))
    if not ranked:
        return None
    best = min(ranked, key=lambda r: r[0])
    return best[1], best[2]


def sentence_gloss(sighting: dict[str, Any]) -> str:
    """The breakdown's English gloss for the sighting's sentence. Found by
    region and sentence index, and accepted only when that sentence's text is
    the one the sighting recorded (a re-run breakdown may have shifted it).
    A leading item number matching the sentence's own is removed."""
    try:
        breakdown = storage.load_breakdown(sighting["doc_id"], sighting["chapter_id"], sighting["region_id"])
        sentence = ((breakdown or {}).get("sentences") or [])[sighting["sentence_index"]]
        if (sentence.get("text") or "") != (sighting.get("sentence_text") or ""):
            return ""
        gloss = (sentence.get("gloss") or "").strip()
    except (KeyError, IndexError, TypeError, ValueError, OSError, AttributeError):
        return ""
    _, number = split_marker(sighting.get("sentence_text") or "")
    if number is not None:
        rest, gloss_number = split_marker(gloss)
        if gloss_number == number:
            gloss = rest.strip()
    return gloss


# ---------- Note ----------


def build_note(
    item: dict[str, Any],
    doc_id: str | None = None,
    chapter_id: str | None = None,
    cache: dict[tuple, str | None] | None = None,
) -> dict[str, Any]:
    """{"fields", "tags", "has_sentence", "has_gloss"} for one store item."""
    headword = strip_suffix_group(item.get("headword") or "")
    reading = pick_reading(headword, strip_suffix_group(item.get("reading") or ""))
    chosen = choose_sentence(item, chapter_id, cache)
    sentence = meaning = ""
    if chosen:
        sighting, text = chosen
        sentence = sentence_html(text, sighting.get("surface") or "", headword)
        meaning = html.escape(sentence_gloss(sighting), quote=False)
    own = (item.get("notes") or "").strip()
    notes = html.escape(own, quote=False).replace("\n", "<br>") if own else ""
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
    return {"fields": fields, "tags": tags, "has_sentence": bool(sentence), "has_gloss": bool(meaning)}


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
        deck_names = _read("deckNames") or []
        deck_exists = deck in deck_names
        cache: dict[tuple, str | None] = {}
        built = [build_note(i, doc_id, chapter_id, cache) for i in items]
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
        # A deck that does not exist yet makes AnkiConnect refuse every note
        # ("deck was not found"). Duplicates are checked across the whole
        # collection, so ask with a deck that exists; push creates the real one.
        if not deck_exists and deck_names:
            check_deck = "Default" if "Default" in deck_names else deck_names[0]
            verdicts = _can_add([{**n, "deckName": check_deck} for n in payload])
        else:
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
                "tags": b["tags"],
                "has_sentence": b["has_sentence"],
                "has_gloss": b["has_gloss"],
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
            "with_sentence": sum(1 for r in addable if r["has_sentence"]),
            "with_gloss": sum(1 for r in addable if r["has_gloss"]),
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
