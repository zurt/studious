"""Read-only import of Anki card state through the AnkiConnect add-on.

The owner studies flashcards in Anki. This module pulls a snapshot of every
card (word, reading, state) so the vocab store can show "already in Anki"
badges. It only ever calls the read actions ``version``, ``findCards`` and
``cardsInfo`` — it never writes to Anki.

Snapshot: ``data/refs/anki/snapshot.json``, replaced atomically on each
successful sync. A failed sync leaves the previous snapshot in place. Anki
state changes daily, so it is joined onto store items at read time and is
never written into the append-only store JSONL.

AnkiConnect only answers while the Anki desktop app is open. URL comes from
``ANKI_CONNECT_URL`` (default ``http://127.0.0.1:8765``).
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
import unicodedata
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import jmdict, refs_build, store

log = logging.getLogger("studious.anki")

API_VERSION = 6
CARDS_CHUNK = 500
CONNECT_TIMEOUT = 5  # seconds; Anki is either open or it is not
CARDS_TIMEOUT = 120  # cardsInfo on a big deck returns a lot

WORD_FIELD_CANDIDATES = ("Word", "Expression", "Vocabulary", "Vocab", "Kanji", "Front")
READING_FIELD_CANDIDATES = (
    "Word Reading",
    "Reading",
    "Kana",
    "Furigana",
    "Expression Reading",
    "Vocabulary-Kana",
)
MAX_WORD_LENGTH = 30
MATURE_INTERVAL_DAYS = 21

# Least to most advanced; lookup keeps the highest rank.
STATES = ("suspended", "new", "learning", "young", "mature")
_RANK = {s: i for i, s in enumerate(STATES)}

_TAG_RE = re.compile(r"<[^>]*>")
_SPACE_RE = re.compile(r"\s+")

_lock = threading.Lock()
# (exact index, JMdict-seq index, headword index)
Index = tuple[dict[tuple[str, str], dict[str, Any]], dict[int, dict[str, Any]], dict[str, dict[str, Any]]]
_index_cache: dict[str, tuple[tuple[int, int], Index]] = {}


class AnkiUnavailable(RuntimeError):
    """AnkiConnect is unreachable or returned an error."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def cache_dir() -> Path:
    return get_settings().data_dir / "refs" / "anki"


def snapshot_path() -> Path:
    return cache_dir() / "snapshot.json"


# ---------- AnkiConnect transport ----------


def _post(action: str, params: dict[str, Any] | None = None, *, timeout: float = CONNECT_TIMEOUT) -> Any:
    """One AnkiConnect call. Raises AnkiUnavailable on any failure."""
    url = get_settings().anki_connect_url
    body = json.dumps({"action": action, "version": API_VERSION, "params": params or {}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-configured local URL
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("anki_unreachable", extra={"url": url, "error": str(exc)})
        raise AnkiUnavailable(
            f"Anki is not reachable at {url}. "
            "Open Anki on this Mac with the AnkiConnect add-on installed."
        ) from exc
    if not isinstance(payload, dict):
        raise AnkiUnavailable(f"AnkiConnect returned an unexpected response to {action!r}")
    if payload.get("error"):
        raise AnkiUnavailable(f"AnkiConnect error on {action}: {payload['error']}")
    return payload.get("result")


# ---------- Cleaning / selection ----------


def clean(value: Any) -> str:
    """Strip HTML tags, entities and whitespace."""
    text = html.unescape(_TAG_RE.sub("", str(value or "")))
    return _SPACE_RE.sub("", text)


def _pick_field(fields: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    lowered = {name.casefold(): name for name in fields}
    for cand in candidates:
        if cand.casefold() in lowered:
            return lowered[cand.casefold()]
    return None


def choose_fields(fields: dict[str, Any]) -> tuple[str | None, str | None]:
    """(word field, reading field) names for one note type."""
    word = _pick_field(fields, WORD_FIELD_CANDIDATES)
    if word is None and fields:
        word = min(fields, key=lambda n: (fields[n] or {}).get("order", 0))
    return word, _pick_field(fields, READING_FIELD_CANDIDATES)


def card_state(card: dict[str, Any]) -> str:
    if card.get("queue") == -1:
        return "suspended"
    ctype = card.get("type")
    if ctype == 0:
        return "new"
    if ctype in (1, 3):
        return "learning"
    return "mature" if (card.get("interval") or 0) >= MATURE_INTERVAL_DAYS else "young"


def _field_value(fields: dict[str, Any], name: str | None) -> str:
    if not name:
        return ""
    entry = fields.get(name)
    return clean(entry.get("value") if isinstance(entry, dict) else entry)


# ---------- Sync ----------


def sync() -> dict[str, Any]:
    """Pull every card, write a new snapshot atomically, return status()."""
    with _lock:
        version = _post("version")
        card_ids = _post("findCards", {"query": "deck:*"}) or []
        infos: list[dict[str, Any]] = []
        for i in range(0, len(card_ids), CARDS_CHUNK):
            chunk = card_ids[i : i + CARDS_CHUNK]
            infos.extend(_post("cardsInfo", {"cards": chunk}, timeout=CARDS_TIMEOUT) or [])

        models: dict[str, dict[str, str | None]] = {}
        decks: dict[str, dict[str, int]] = {}
        cards: list[dict[str, Any]] = []
        skipped = 0
        for info in infos:
            fields = info.get("fields") or {}
            model = info.get("modelName") or ""
            if model not in models:
                word_f, reading_f = choose_fields(fields)
                models[model] = {"word_field": word_f, "reading_field": reading_f}
            used = models[model]
            word = _field_value(fields, used["word_field"])
            if not word or len(word) > MAX_WORD_LENGTH:
                skipped += 1
                continue
            state = card_state(info)
            deck = info.get("deckName") or ""
            counts = decks.setdefault(deck, {s: 0 for s in STATES})
            counts[state] += 1
            cards.append(
                {
                    "word": word,
                    "reading": _field_value(fields, used["reading_field"]),
                    "state": state,
                    "deck": deck,
                    "interval": info.get("interval") or 0,
                    "note_id": info.get("note"),
                    "card_id": info.get("cardId"),
                }
            )

        snapshot = {
            "synced_at": _now_iso(),
            "anki_connect_version": version,
            "decks": decks,
            "note_types": models,
            "skipped": skipped,
            "cards": cards,
        }
        path = snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    log.info("anki_sync_done", extra={"cards": len(cards), "skipped": skipped, "decks": len(decks)})
    return status()


def _load_snapshot() -> dict[str, Any] | None:
    try:
        return json.loads(snapshot_path().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def status() -> dict[str, Any]:
    """Describe the local snapshot. Never calls Anki."""
    snap = _load_snapshot()
    if snap is None:
        return {
            "has_snapshot": False,
            "synced_at": None,
            "anki_connect_version": None,
            "total_cards": 0,
            "counts": {s: 0 for s in STATES},
            "decks": {},
            "note_types": {},
        }
    counts = {s: 0 for s in STATES}
    for card in snap.get("cards", []):
        counts[card["state"]] = counts.get(card["state"], 0) + 1
    return {
        "has_snapshot": True,
        "synced_at": snap.get("synced_at"),
        "anki_connect_version": snap.get("anki_connect_version"),
        "total_cards": len(snap.get("cards", [])),
        "counts": counts,
        "decks": snap.get("decks", {}),
        "note_types": snap.get("note_types", {}),
    }


# ---------- Lookup (store item -> Anki card state) ----------


def _better(new: dict[str, Any], old: dict[str, Any] | None) -> bool:
    return old is None or _RANK[new["state"]] > _RANK[old["state"]]


def _card_seq(card: dict[str, Any]) -> int | None:
    """JMdict entry for an Anki card, or None when we can't be sure.

    Deliberately conservative: the card needs a reading, the card's spelling
    must be one of the entry's written forms, and the entry must carry that
    reading. ``jmdict.lookup`` also falls back to reading-only or
    surface-only hits, which would make 漢字 and 感じ (both かんじ) collide.
    """
    reading = store.kata_to_hira(unicodedata.normalize("NFKC", card.get("reading") or ""))
    word = unicodedata.normalize("NFKC", card.get("word") or "")
    if not reading or not word:
        return None
    hit = jmdict.lookup(word, reading)
    if hit is None:
        return None
    forms = {unicodedata.normalize("NFKC", f) for f in (*hit["kanji"], *hit["kana"])}
    kana = {store.kata_to_hira(unicodedata.normalize("NFKC", k)) for k in hit["kana"]}
    if word not in forms or reading not in kana:
        return None
    return hit["seq"]


def _cache_stamp(path: Path) -> tuple[int, int] | None:
    """(snapshot mtime, JMdict db mtime); the seq tier depends on both."""
    try:
        snap = path.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    try:
        jm = refs_build.jmdict_db_path().stat().st_mtime_ns
    except FileNotFoundError:
        jm = 0
    return snap, jm


def get_index() -> Index:
    """(exact index, JMdict-seq index, headword index), cached on the
    snapshot and JMdict db mtimes. Without a JMdict index the seq tier is
    empty and lookup falls through to the headword tier."""
    path = snapshot_path()
    stamp = _cache_stamp(path)
    if stamp is None:
        _index_cache.pop(str(path), None)
        return {}, {}, {}
    cached = _index_cache.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    cards = (_load_snapshot() or {}).get("cards", [])
    resolve = jmdict.is_available()
    exact: dict[tuple[str, str], dict[str, Any]] = {}
    by_seq: dict[int, dict[str, Any]] = {}
    by_headword: dict[str, dict[str, Any]] = {}
    for card in cards:
        key = store.vocab_key(card["word"], card.get("reading"))
        if _better(card, exact.get(key)):
            exact[key] = card
        if _better(card, by_headword.get(key[0])):
            by_headword[key[0]] = card
        if resolve:
            seq = _card_seq(card)
            if seq is not None and _better(card, by_seq.get(seq)):
                by_seq[seq] = card
    index = (exact, by_seq, by_headword)
    _index_cache[str(path)] = (stamp, index)
    return index


def lookup(
    headword: str,
    reading: str | None,
    jmdict_seq: int | None = None,
    index: Index | None = None,
) -> dict[str, Any] | None:
    """Anki state for one store item.

    Tiers: ``exact`` (word + reading), ``entry`` (same JMdict entry, so a
    variant spelling like うれしい / 嬉しい matches), ``headword`` (word
    alone, reading differs).
    """
    exact, by_seq, by_headword = index or get_index()
    key = store.vocab_key(headword, reading)
    card, match = exact.get(key), "exact"
    if card is None and jmdict_seq is not None:
        card, match = by_seq.get(jmdict_seq), "entry"
    if card is None:
        card, match = by_headword.get(key[0]), "headword"
    if card is None:
        return None
    return {"state": card["state"], "deck": card["deck"], "interval": card["interval"], "match": match}
