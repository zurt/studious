"""Read-only lookups against the local JMdict/JLPT SQLite index.

The index is built by ``make refs`` (see ``refs_build.py``); until it
exists every lookup returns ``None`` and enrichment is a no-op — the
store works fine without it, just without dictionary data.

JMdict is property of the Electronic Dictionary Research and Development
Group, used under the EDRDG licence (CC BY-SA 4.0).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import unicodedata
from typing import Any

from . import refs_build
from .store import kata_to_hira

log = logging.getLogger("studious.jmdict")

_conn: sqlite3.Connection | None = None
_conn_path: str | None = None
_lock = threading.Lock()

# Stripped from lookup surfaces: textbook entries write particles and
# suffix patterns as 〜によって / ～カ国 etc.
_EDGE_CHARS = "〜～~…・ 　"


def _get_conn() -> sqlite3.Connection | None:
    """Cached read-only connection, re-opened if the db path changes
    (tests point STUDIOUS_DATA_DIR at temp dirs). Callers must hold _lock."""
    global _conn, _conn_path
    path = refs_build.jmdict_db_path()
    if _conn is not None and _conn_path == str(path):
        return _conn
    if _conn is not None:
        _conn.close()
        _conn = None
        _conn_path = None
    if not path.exists():
        return None
    _conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    _conn_path = str(path)
    return _conn


def close() -> None:
    """Close the cached connection (tests, shutdown)."""
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _conn_path = None


def is_available() -> bool:
    with _lock:
        return _get_conn() is not None


def meta() -> dict[str, str]:
    with _lock:
        con = _get_conn()
        if con is None:
            return {}
        return dict(con.execute("SELECT key, value FROM meta"))


def _normalize_surface(surface: str) -> str:
    return unicodedata.normalize("NFKC", (surface or "").strip()).strip(_EDGE_CHARS)


def _candidates(con: sqlite3.Connection, surface: str) -> list[tuple[int, int]]:
    """(seq, common) rows for a surface, deduped by seq keeping max common."""
    rows = con.execute(
        "SELECT seq, MAX(common) FROM lookup WHERE surface = ? GROUP BY seq", (surface,)
    ).fetchall()
    return [(int(seq), int(common)) for seq, common in rows]


def _load_entry(con: sqlite3.Connection, seq: int) -> dict[str, Any] | None:
    row = con.execute("SELECT data FROM entries WHERE seq = ?", (seq,)).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def lookup(surface: str, reading: str | None = None) -> dict[str, Any] | None:
    """Best JMdict entry for a textbook surface form.

    Candidates matching the given reading are preferred, then common
    entries, then the lowest sequence number (older, more established
    entries). Returns ``{seq, gloss, senses, pos, common, kanji, kana}``
    or ``None``.
    """
    surface_n = _normalize_surface(surface)
    if not surface_n:
        return None
    reading_n = kata_to_hira(unicodedata.normalize("NFKC", (reading or "").strip()))

    with _lock:
        con = _get_conn()
        if con is None:
            return None
        cands = _candidates(con, surface_n)
        if not cands and reading_n and reading_n != surface_n:
            # Kanji form unknown to JMdict (rare variant) — try the reading.
            cands = _candidates(con, reading_n)
        if not cands:
            return None

        scored: list[tuple[tuple[int, int, int], int, dict[str, Any]]] = []
        for seq, common in cands:
            entry = _load_entry(con, seq)
            if entry is None:
                continue
            reading_match = int(
                bool(reading_n)
                and any(kata_to_hira(k) == reading_n for k in entry.get("kana", []))
            )
            scored.append(((-reading_match, -common, seq), seq, entry))
        if not scored:
            return None
        scored.sort(key=lambda t: t[0])
        _, seq, entry = scored[0]

    senses = entry.get("senses", [])
    first = senses[0] if senses else {}
    return {
        "seq": seq,
        "gloss": first.get("gloss", ""),
        "pos": first.get("pos", []),
        "senses": senses,
        "common": bool(entry.get("common")),
        "kanji": entry.get("kanji", []),
        "kana": entry.get("kana", []),
    }


def jlpt_level(headword: str, reading: str | None = None) -> int | None:
    """JLPT level (5 = N5 … 1 = N1) for a word, or None if unlisted.

    Matches the expression column first (with the reading as a
    tie-breaker when supplied), then falls back to matching the reading
    column for kana-only textbook forms.
    """
    headword_n = _normalize_surface(headword)
    if not headword_n:
        return None
    reading_n = kata_to_hira(unicodedata.normalize("NFKC", (reading or "").strip()))

    with _lock:
        con = _get_conn()
        if con is None:
            return None
        rows = con.execute(
            "SELECT reading, level FROM jlpt WHERE expression = ?", (headword_n,)
        ).fetchall()
        if rows:
            if reading_n:
                matched = [lvl for r, lvl in rows if kata_to_hira(r) == reading_n]
                if matched:
                    return max(matched)
            return max(lvl for _, lvl in rows)
        # The lists write some words in kana (e.g. かかわる for 関わる):
        # match the word's reading against kana-written expressions. Only
        # kana-listed entries participate, so homophone collisions with
        # kanji-listed words can't occur.
        if reading_n and reading_n != headword_n:
            rows = con.execute(
                "SELECT level FROM jlpt WHERE expression = ?", (reading_n,)
            ).fetchall()
            if rows:
                return max(lvl for (lvl,) in rows)
        # Kana-only form: the lists key kanji in `expression`, kana in `reading`.
        rows = con.execute(
            "SELECT level FROM jlpt WHERE reading = ?", (headword_n,)
        ).fetchall()
        if rows:
            return max(lvl for (lvl,) in rows)
    return None
