"""Central vocab/grammar store.

Append-only JSONL files under ``data/store/`` — one JSON object per
line, the latest line per ``id`` wins, deletes are tombstone lines
(``deleted: true``). Records carry full-UUID ids, ``updated_at``
timestamps, and per-occurrence ``sightings`` so the store stays
sync-friendly (see docs/vocab-store-plan.md).

The headword/reading (vocab) and normalized-pattern (grammar) indexes
are derived in memory from the JSONL on read and cached against the
file's mtime+size; there is no separate index file to drift.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import get_settings

log = logging.getLogger("studious.store")

_lock = threading.Lock()

# (mtime_ns, size) -> parsed items, keyed by absolute path string.
_cache: dict[str, tuple[tuple[int, int], dict[str, dict[str, Any]]]] = {}

KINDS = ("vocab", "grammar")
STATUSES = ("unreviewed", "active", "known", "ignored")
SOURCES = ("breakdown", "vocab_list", "manual")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_dir() -> Path:
    return get_settings().data_dir / "store"


def store_path(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unknown store kind: {kind!r}")
    return store_dir() / f"{kind}.jsonl"


# ---------- Normalization ----------


def kata_to_hira(s: str) -> str:
    return "".join(
        chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in s
    )


def _is_kana(ch: str) -> bool:
    cp = ord(ch)
    return 0x3041 <= cp <= 0x3096 or 0x30A1 <= cp <= 0x30FA or cp in (0x30FC, 0x30FB)


def _all_kana(s: str) -> bool:
    return bool(s) and all(_is_kana(c) for c in s)


def normalize_reading(reading: str | None, headword: str) -> str:
    """Canonical hiragana reading used for dedup.

    Kana-only headwords with no printed reading (textbooks omit the
    reading column for them) get their own kana as the reading so the
    same word harvested from a breakdown (which does supply a reading)
    dedups onto one entry.
    """
    r = kata_to_hira(unicodedata.normalize("NFKC", (reading or "").strip()))
    if r:
        return r
    hw = unicodedata.normalize("NFKC", headword.strip())
    if _all_kana(hw):
        return kata_to_hira(hw)
    return ""


def vocab_key(headword: str, reading: str | None) -> tuple[str, str]:
    hw = unicodedata.normalize("NFKC", (headword or "").strip())
    return (hw, normalize_reading(reading, hw))


_TILDE_CHARS = "〜～~…・"


def normalize_pattern(pattern: str) -> str:
    """Canonical grammar-pattern key: tildes/ellipses stripped everywhere,
    then NFKC, then whitespace removed (〜に関わらず, ～に関わらず and
    に関わらず collide). Tildes are stripped *before* NFKC because NFKC
    expands … to three ASCII dots."""
    p = "".join(c for c in (pattern or "") if c not in _TILDE_CHARS)
    p = unicodedata.normalize("NFKC", p)
    return "".join(c for c in p if not c.isspace())


def item_key(kind: str, item: dict[str, Any]) -> tuple[str, ...]:
    if kind == "vocab":
        return vocab_key(item.get("headword", ""), item.get("reading"))
    return (normalize_pattern(item.get("pattern", "")),)


# ---------- Read path ----------


def _iter_lines(path: Path) -> Iterable[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                log.warning(
                    "store_skip_malformed", extra={"file": path.name, "line": lineno}
                )
                continue
            if isinstance(obj, dict) and obj.get("id"):
                yield obj


def _load_latest(path: Path) -> dict[str, dict[str, Any]]:
    """id -> latest record, cached against the file's (mtime_ns, size)."""
    key = str(path)
    try:
        st = path.stat()
    except FileNotFoundError:
        _cache.pop(key, None)
        return {}
    sig = (st.st_mtime_ns, st.st_size)
    cached = _cache.get(key)
    if cached and cached[0] == sig:
        return cached[1]
    items: dict[str, dict[str, Any]] = {}
    for obj in _iter_lines(path):
        items[obj["id"]] = obj
    _cache[key] = (sig, items)
    return items


def list_items(kind: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    items = list(_load_latest(store_path(kind)).values())
    if not include_deleted:
        items = [i for i in items if not i.get("deleted")]
    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    return items


def get_item(kind: str, item_id: str) -> dict[str, Any] | None:
    return _load_latest(store_path(kind)).get(item_id)


def build_index(kind: str, *, include_deleted: bool = False) -> dict[tuple[str, ...], str]:
    """Dedup key -> item id.

    When two items collide on a key (possible after manual edits), the
    most recently created wins — except that a live item always beats a
    tombstone, so a deleted-then-recreated word resolves to the live
    record. Harvest passes ``include_deleted=True`` so tombstones block
    re-ingest of a deleted item (a delete is final).
    """
    all_items = list_items(kind, include_deleted=True)
    index: dict[tuple[str, ...], str] = {}
    if include_deleted:
        for item in reversed(all_items):  # oldest first; newest overwrites
            if item.get("deleted"):
                index[item_key(kind, item)] = item["id"]
    for item in reversed(all_items):
        if not item.get("deleted"):
            index[item_key(kind, item)] = item["id"]
    return index


def stats(kind: str) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    total = 0
    for item in list_items(kind):
        total += 1
        status = item.get("status") or "unreviewed"
        counts[status] = counts.get(status, 0) + 1
    return {"total": total, **counts}


# ---------- Write path ----------


def _append_lines(kind: str, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path = store_path(kind)
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())


def _new_vocab_item(
    *,
    headword: str,
    reading: str,
    meaning: str,
    status: str = "unreviewed",
    meaning_source: str = "llm",
    notes: str = "",
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": uuid.uuid4().hex,
        "headword": headword,
        "reading": reading,
        "meaning": meaning,
        "meaning_source": meaning_source,
        "pos": [],
        "jmdict_seq": None,
        "status": status,
        "classifications": {},
        "priority_group": None,
        "sightings": [],
        "links": {},
        "notes": notes,
        "created_at": now,
        "updated_at": now,
        "deleted": False,
    }


def _new_grammar_item(
    *,
    pattern: str,
    explanation: str,
    status: str = "unreviewed",
    notes: str = "",
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": uuid.uuid4().hex,
        "pattern": pattern,
        "pattern_normalized": normalize_pattern(pattern),
        "explanation": explanation,
        "status": status,
        "classifications": {},
        "sightings": [],
        "links": {},
        "notes": notes,
        "created_at": now,
        "updated_at": now,
        "deleted": False,
    }


def create_item(kind: str, **fields: Any) -> dict[str, Any]:
    if kind == "vocab":
        item = _new_vocab_item(**fields)
    else:
        item = _new_grammar_item(**fields)
    with _lock:
        _append_lines(kind, [item])
    return item


def update_item(kind: str, item_id: str, **changes: Any) -> dict[str, Any] | None:
    """Append an updated copy of the latest record. Tombstoned items are
    not updatable (a delete is final; re-create instead)."""
    with _lock:
        item = get_item(kind, item_id)
        if item is None or item.get("deleted"):
            return None
        updated = {**item, **changes, "updated_at": _now_iso()}
        if kind == "grammar" and "pattern" in changes:
            updated["pattern_normalized"] = normalize_pattern(updated["pattern"])
        _append_lines(kind, [updated])
    return updated


def delete_item(kind: str, item_id: str) -> bool:
    with _lock:
        item = get_item(kind, item_id)
        if item is None or item.get("deleted"):
            return False
        _append_lines(
            kind, [{**item, "deleted": True, "updated_at": _now_iso()}]
        )
    return True


# ---------- Harvest merge ----------


def replace_region_sightings(
    kind: str,
    *,
    doc_id: str,
    chapter_id: str,
    region_id: str,
    source: str,
    entries: list[dict[str, Any]],
) -> dict[str, int]:
    """Idempotently merge one region's harvested entries into the store.

    All existing sightings for (region_id, source) are dropped first and
    the incoming ones added, so re-running a breakdown or re-transcribing
    a vocab list converges instead of duplicating. Items are matched by
    dedup key; misses create new ``unreviewed`` items. Curated fields
    (status, notes, meaning) on existing items are never touched.

    Each entry: the item fields (headword/reading/meaning for vocab,
    pattern/explanation for grammar) plus ``sentence_index``, ``surface``
    and ``sentence_text`` for the sighting.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown sighting source: {source!r}")
    now = _now_iso()
    created = updated = 0

    with _lock:
        index = build_index(kind, include_deleted=True)
        touched: dict[str, dict[str, Any]] = {}

        # Strip stale sightings from every item that has them, not just the
        # ones re-harvested this run (an entry may have vanished on retranscribe).
        for existing in list_items(kind):
            kept = [
                s
                for s in existing.get("sightings", [])
                if not (s.get("region_id") == region_id and s.get("source") == source)
            ]
            if len(kept) != len(existing.get("sightings", [])):
                touched[existing["id"]] = {**existing, "sightings": kept}

        new_items: dict[tuple[str, ...], dict[str, Any]] = {}
        for entry in entries:
            if kind == "vocab":
                headword = (entry.get("headword") or "").strip()
                if not headword:
                    continue
                key = vocab_key(headword, entry.get("reading"))
            else:
                pattern = (entry.get("pattern") or "").strip()
                if not pattern:
                    continue
                key = (normalize_pattern(pattern),)
                if not key[0]:
                    continue

            sighting = {
                "doc_id": doc_id,
                "chapter_id": chapter_id,
                "region_id": region_id,
                "sentence_index": entry.get("sentence_index"),
                "surface": entry.get("surface") or "",
                "sentence_text": entry.get("sentence_text") or "",
                "source": source,
                "seen_at": now,
            }

            item_id = index.get(key)
            if item_id is not None:
                item = touched.get(item_id) or get_item(kind, item_id)
                if item is None or item.get("deleted"):
                    continue  # tombstoned: a delete is final, don't resurrect
                item = {**item, "sightings": [*item.get("sightings", []), sighting]}
                touched[item_id] = item
            elif key in new_items:
                item = new_items[key]
                item["sightings"].append(sighting)
            else:
                if kind == "vocab":
                    item = _new_vocab_item(
                        headword=headword,
                        reading=normalize_reading(entry.get("reading"), headword),
                        meaning=(entry.get("meaning") or "").strip(),
                    )
                else:
                    item = _new_grammar_item(
                        pattern=pattern,
                        explanation=(entry.get("explanation") or "").strip(),
                    )
                item["sightings"] = [sighting]
                new_items[key] = item
                created += 1

        records = []
        for item in touched.values():
            records.append({**item, "updated_at": now})
            updated += 1
        records.extend(new_items.values())
        _append_lines(kind, records)

    return {"created": created, "updated": updated, "sightings": len(entries)}
