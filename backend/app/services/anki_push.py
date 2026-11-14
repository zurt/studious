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

import base64
import html
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import anki, examples, store, tts

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

# The card's Word Meaning: dictionary glosses are cut to this many, and to
# this many characters (the first gloss is always kept).
MAX_CARD_GLOSSES = 3
MAX_CARD_MEANING_CHARS = 40
MAX_CONTEXT_MEANING_CHARS = 60
AUDIO_WORKERS = 4

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


def split_glosses(meaning: str) -> list[str]:
    """Glosses separated by ';' (also ；), ignoring separators inside parentheses."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in meaning or "":
        if ch in "(（":
            depth += 1
        elif ch in ")）":
            depth = max(0, depth - 1)
        if ch in ";；" and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [g.strip() for g in out if g.strip()]


def card_meaning(meaning: str) -> str:
    """A short meaning for the card: the first three glosses, stopping early
    when the next would take the result past 40 characters. The first gloss
    is always kept, however long."""
    kept: list[str] = []
    for gloss in split_glosses(meaning):
        if len(kept) >= MAX_CARD_GLOSSES:
            break
        if kept and len(", ".join([*kept, gloss])) > MAX_CARD_MEANING_CHARS:
            break
        kept.append(gloss)
    return ", ".join(kept)


_TRAILING_GROUP_RE = re.compile(r"\s*[(（][^()（）]*[)）]\s*$")


def speech_word(headword: str) -> str:
    """The Word as spoken: as written, a trailing bracket group removed."""
    return _TRAILING_GROUP_RE.sub("", headword or "").strip()


# ---------- Note ----------


def stored_example(item: dict[str, Any]) -> dict[str, Any] | None:
    """The item's stored generated example when it has the fields a note needs.
    Anything else (no example, a ``source: "textbook"`` one from an earlier
    build) counts as no example."""
    ex = item.get("example")
    if (
        isinstance(ex, dict)
        and ex.get("source", "generated") == "generated"
        and ex.get("sentence")
        and ex.get("furigana")
    ):
        return ex
    return None


def sentence_html(text: str, surface: str, headword: str = "") -> str:
    """Escaped sentence with the first occurrence of the word wrapped in <b>."""
    for needle in (surface, headword):
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


def word_meaning(item: dict[str, Any]) -> str:
    """The card meaning. The textbook-context meaning (``meaning_context``)
    when the item has one, with ';' written as ', ' and shortened like a
    dictionary gloss if it is over 60 characters. Otherwise the stored
    meaning, shortened only when it came from the dictionary
    (``meaning_source`` "jmdict"); an owner's ("user") or the model's ("llm")
    meaning goes on the card as it is."""
    ctx = (item.get("meaning_context") or "").strip()
    if ctx:
        joined = ", ".join(split_glosses(ctx))
        return card_meaning(ctx) if len(joined) > MAX_CONTEXT_MEANING_CHARS else joined
    meaning = item.get("meaning") or ""
    return card_meaning(meaning) if item.get("meaning_source") == "jmdict" else meaning


def build_note(
    item: dict[str, Any],
    doc_id: str | None = None,
    chapter_id: str | None = None,
) -> dict[str, Any]:
    """{"fields", "tags", "has_sentence", "has_gloss", "sentence_source"} for one
    store item. The sentence is always the item's stored generated example
    (with real furigana), else empty: textbook sentences are above the
    learner's level, so they never go on a card."""
    headword = strip_suffix_group(item.get("headword") or "")
    reading = pick_reading(headword, strip_suffix_group(item.get("reading") or ""))
    sentence = meaning = sentence_furigana = spoken = spoken_reading = ""
    source: str | None = None
    if (ex := stored_example(item)) is not None:
        sentence = sentence_html(ex["sentence"], ex.get("surface") or "", headword)
        sentence_furigana = examples.wrap_surface(ex["furigana"], ex.get("surface") or "")
        meaning = html.escape(ex.get("gloss") or "", quote=False)
        source = "generated"
        spoken = ex["sentence"]
        spoken_reading = examples.furigana_reading(ex["furigana"])
    own = (item.get("notes") or "").strip()
    notes = html.escape(own, quote=False).replace("\n", "<br>") if own else ""
    rank = (item.get("classifications") or {}).get("freq_rank")
    fields = dict.fromkeys(KAISHI_FIELDS, "")
    fields.update(
        {
            "Word": html.escape(headword, quote=False),
            "Word Reading": html.escape(reading, quote=False),
            "Word Meaning": html.escape(word_meaning(item), quote=False),
            "Word Furigana": html.escape(furigana(headword, reading), quote=False),
            "Sentence": sentence,
            "Sentence Meaning": meaning,
            "Sentence Furigana": sentence_furigana,
            "Notes": notes,
            "Frequency": str(int(rank)) if isinstance(rank, (int, float)) and rank > 0 else "",
        }
    )
    tags = ["studious"]
    if doc_id and chapter_id:
        tags.append(f"studious::{doc_id}::{chapter_id}")
    return {"fields": fields, "tags": tags, "has_sentence": bool(sentence), "has_gloss": bool(meaning),
        "sentence_source": source,
        "word_text": speech_word(headword),
        "word_reading": reading,
        "sentence_text": spoken,
        "sentence_reading": spoken_reading,
    }


def clip_specs(item: dict[str, Any], note: dict[str, Any] | None = None) -> list[tuple[str, str, str | None, str]]:
    """The clips a vocab item needs: ``(part, text, reading, seed)`` for the word
    and, when the item has an example sentence, the sentence. The one place that
    decides the text, expected reading and voice seed of a clip, so the Play
    endpoint, the Anki push and the background queue can never disagree about a
    cache key. ``note`` is ``build_note(item)`` when the caller already has it."""
    note = note or build_note(item)
    seed = note["fields"]["Word"]
    specs: list[tuple[str, str, str | None, str]] = []
    for part, text, reading in (
        ("word", note["word_text"], note["word_reading"]),
        ("sentence", note["sentence_text"], note["sentence_reading"]),
    ):
        if text:
            specs.append((part, text, expected_reading(reading), seed))
    return specs


# ---------- Preview / push ----------


def select_items(doc_id: str, chapter_id: str, limit: int, source: str | None = None) -> list[dict[str, Any]]:
    """The first ``limit`` shortlist candidates, via the list endpoint's code path."""
    from ..api.store import _list_items  # local: the api package imports services

    return _list_items(
        "vocab",
        status=None,
        q=None,
        doc_id=doc_id,
        chapter_id=chapter_id,
        source=source,
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


def _stem_key(headword: str) -> str:
    """Spelling that a word and its する / な form share (管理, 管理する)."""
    word = strip_suffix_group(headword)
    parts = store.stem_parts(word)
    return parts[0] if parts else word


def _check_with_variants(
    items: list[dict[str, Any]], payload: list[dict[str, Any]], check_deck: str
) -> list[tuple[bool, str]]:
    """can-add verdicts where a note also counts as a duplicate when its stem
    variant (管理 <-> 管理する, 重要 <-> 重要な) exists. The variants ride in the
    same read-only canAddNotesWithErrorDetail call as extra notes."""
    notes = [{**n, "deckName": check_deck} for n in payload]
    extra: list[tuple[int, str]] = []
    for i, (item, n) in enumerate(zip(items, payload, strict=True)):
        word = strip_suffix_group(item.get("headword") or "")
        reading = strip_suffix_group(item.get("reading") or "")
        for variant, _ in store.stem_variants(word, reading):
            extra.append((i, variant))
            notes.append(
                {**notes[i], "fields": {**n["fields"], "Word": html.escape(variant, quote=False)}}
            )
    verdicts = _can_add(notes)
    own = verdicts[: len(payload)]
    for (i, variant), (can, _reason) in zip(extra, verdicts[len(payload) :], strict=True):
        if not can and own[i][0]:
            own[i] = (False, f"{variant} (same word with or without する/な) is already in Anki")
    return own


def audio_status() -> dict[str, Any]:
    st = tts.status()
    return {
        "enabled": get_settings().anki_push_audio,
        "available": st["available"],
        "voice": st["voice"],
        "voices": st["voices"],
        "engine": st["engine"],
        "reason": st["reason"],
        "pending": st["pending"],
    }


_UNSPEAKABLE_RE = re.compile(r"[0-9A-Za-z０-９Ａ-Ｚａ-ｚ]")


def expected_reading(reading: str) -> str | None:
    """A reading worth checking the engine against: not empty, and without
    digits or Latin letters (which the engine reads in its own way)."""
    reading = (reading or "").strip()
    return None if not reading or _UNSPEAKABLE_RE.search(reading) else reading


def attach_audio(note: dict[str, Any], clips: list[tuple[str, Path]]) -> dict[str, Any]:
    """The note with AnkiConnect per-note media for ``clips`` ((field, file)).
    AnkiConnect stores each file and appends [sound:<filename>] to the field.
    This payload shape is NOT verified against a real Anki; it is the only
    place that knows it. Never used for the can-add check."""
    if not clips:
        return note
    return {
        **note,
        "audio": [
            {
                "filename": f"studious_{path.stem}{path.suffix}",
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                "fields": [field],
            }
            for field, path in clips
        ],
    }


_FIELD_OF_PART = {"word": "Word Audio", "sentence": "Sentence Audio"}


def _note_with_audio(row: dict[str, Any], down: threading.Event) -> tuple[dict[str, Any], int, int, int, int]:
    """(note, clips attached, clips failed, readings corrected, clips missing).
    A failed clip is left out. While the engine is down (``down`` is set, at
    the start or once a clip finds it unreachable) only clips already cached are
    attached, without waiting on the network; the rest count as missing."""
    clips: list[tuple[str, Path]] = []
    failed = corrected = missing = 0
    for part, text, reading, seed in row["_clips"]:
        field = _FIELD_OF_PART[part]
        if not down.is_set():
            report: dict[str, Any] = {}
            try:
                clips.append((field, tts.synthesize(text, reading, report=report, seed=seed)))
                corrected += bool(report.get("corrected"))
                continue
            except tts.TtsUnavailable:
                down.set()
            except tts.TtsError as exc:
                failed += 1
                log.warning("anki_push_audio_failed", extra={"word": row["headword"], "field": field, "error": str(exc)})
                continue
        cached = tts.cached_clip(text, reading, seed=seed)
        if cached is not None:
            clips.append((field, cached))
        else:
            missing += 1
    return attach_audio(row["_note"], clips), len(clips), failed, corrected, missing


def _prepare(doc_id: str, chapter_id: str, limit: int, source: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    deck, model = settings.anki_push_deck, settings.anki_push_note_type
    items = select_items(doc_id, chapter_id, limit, source)
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
        # A deck that does not exist yet makes AnkiConnect refuse every note
        # ("deck was not found"). Duplicates are checked across the whole
        # collection, so ask with a deck that exists; push creates the real one.
        check_deck = deck
        if not deck_exists and deck_names:
            check_deck = "Default" if "Default" in deck_names else deck_names[0]
        verdicts = _check_with_variants(items, payload, check_deck)
    except anki.AnkiUnavailable as exc:
        raise AnkiPushError(503, str(exc)) from exc

    seen: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for item, b, note, (ok, reason) in zip(items, built, payload, verdicts, strict=True):
        word = b["fields"]["Word"]
        key = _stem_key(item.get("headword") or "")
        if ok and key in seen:
            ok, reason = False, f"Same word as {seen[key]} earlier in this batch (with or without する/な)"
        seen.setdefault(key, word)
        rows.append(
            {
                "id": item["id"],
                "headword": item.get("headword") or "",
                "reading": item.get("reading") or "",
                "fields": b["fields"],
                "tags": b["tags"],
                "has_sentence": b["has_sentence"],
                "has_gloss": b["has_gloss"],
                "sentence_source": b["sentence_source"],
                "can_add": ok,
                "reason": reason,
                "headword_match": (item.get("anki") or {}).get("match") == "headword",
                "_note": note,
                "_clips": clip_specs(item, b),
            }
        )
    return {"deck": deck, "deck_exists": deck_exists, "note_type": model, "rows": rows}


def preview(doc_id: str, chapter_id: str, limit: int, source: str | None = None) -> dict[str, Any]:
    """What a send would do. Read actions only."""
    prepared = _prepare(doc_id, chapter_id, limit, source)
    rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in prepared["rows"]]
    addable = [r for r in rows if r["can_add"]]
    needs = [r for r in addable if not r["has_sentence"]]
    return {
        "deck": prepared["deck"],
        "deck_exists": prepared["deck_exists"],
        "will_create_deck": not prepared["deck_exists"],
        "note_type": prepared["note_type"],
        "audio": audio_status(),
        "counts": {
            "candidates": len(rows),
            "will_add": len(addable),
            "skipped": len(rows) - len(addable),
            "with_sentence": sum(1 for r in addable if r["has_sentence"]),
            "with_gloss": sum(1 for r in addable if r["has_gloss"]),
            "without_sentence": len(needs),
            "needs_example": len(needs),
            "needs_example_ids": [r["id"] for r in needs],
            "headword_match": sum(1 for r in addable if r["headword_match"]),
        },
        "items": rows,
    }


def push(
    doc_id: str, chapter_id: str, limit: int, audio: bool | None = None, source: str | None = None
) -> dict[str, Any]:
    """Create the notes in Anki. 409 if another send is running. ``audio``
    (default: the ANKI_PUSH_AUDIO setting) attaches Mac-voice clips. When the
    engine is down only clips already cached are attached and the rest count
    as ``missing``; a clip that fails for another reason counts as ``failed``
    and leaves that note without it."""
    if not _push_lock.acquire(blocking=False):
        raise AnkiPushError(409, "A send to Anki is already running.")
    try:
        log.info("anki_push_start", extra={"doc_id": doc_id, "chapter_id": chapter_id, "limit": limit, "source": source})
        prepared = _prepare(doc_id, chapter_id, limit, source)
        rows = prepared["rows"]
        todo = [r for r in rows if r["can_add"]]
        skipped = [{"id": r["id"], "headword": r["headword"], "reason": r["reason"]} for r in rows if not r["can_add"]]
        failed: list[dict[str, Any]] = []
        want_audio = get_settings().anki_push_audio if audio is None else audio
        use_audio = bool(want_audio)
        down = threading.Event()
        if use_audio and not tts.is_available():
            down.set()
        audio_stats = {"attached": 0, "failed": 0, "reading_corrected": 0, "missing": 0}
        notes = [r["_note"] for r in todo]
        if use_audio and todo:
            with ThreadPoolExecutor(max_workers=AUDIO_WORKERS) as pool:
                done = list(pool.map(lambda r: _note_with_audio(r, down), todo))
            notes = [d[0] for d in done]
            audio_stats = {
                "attached": sum(d[1] for d in done),
                "failed": sum(d[2] for d in done),
                "reading_corrected": sum(d[3] for d in done),
                "missing": sum(d[4] for d in done),
            }
        created = 0
        deck_created = False
        if todo:
            try:
                _write("createDeck", {"deck": prepared["deck"]})
                deck_created = not prepared["deck_exists"]
                results = _write("addNotes", {"notes": notes}, timeout=ADD_TIMEOUT)
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
            "audio": {"enabled": use_audio, "unavailable": use_audio and down.is_set(), **audio_stats},
        }
    finally:
        _push_lock.release()
