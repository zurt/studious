"""Read-only lookups against the local JPDB frequency index.

Built by ``make refs`` (see ``refs_build.build_freq_sqlite``); until it
exists every lookup returns ``None`` and enrichment skips ``freq_rank``.

Ranks are JPDB corpus ranks, 1 = most frequent. The source list ranks
*spellings*: 嬉しい (kanji) and うれしい (kana) have different ranks. The
lookup therefore prefers the row matching the item's own spelling and
reading, and only falls back to the word alone:

1. ``(word, reading)`` — a kanji spelling with the item's reading;
2. ``word`` with any reading — a kana-only term (stored with reading
   ``""``) or a kanji spelling whose reading differs. When a word has
   several rows (homographs), the most frequent one wins.

Data: https://github.com/MarvNC/jpdb-freq-list (derived from jpdb.io); a
local download, never committed.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import unicodedata

from . import refs_build
from .store import kata_to_hira, stem_parts

log = logging.getLogger("studious.freq")

_conn: sqlite3.Connection | None = None
_conn_key: tuple[str, int] | None = None
_lock = threading.Lock()

_EDGE_CHARS = "〜～~…・ 　"

# Bump when lookup logic changes so already-enriched items are re-checked once
# (it is folded into revision(), which enrichment stamps as ``freq_checked``).
LOOKUP_VERSION = 2

# Textbook vocab lists write 企画する, 料理(する), 重要な; the list ranks the
# stem. Runs on NFKC text, so full-width brackets are already half-width.
# (No existing helper handles this: jmdict.lookup and the Anki matching only
# normalise NFKC and edge characters.)


def _get_conn() -> sqlite3.Connection | None:
    """Cached read-only connection, re-opened when the db path or file
    changes (``make refs`` replaces the file atomically). Hold _lock."""
    global _conn, _conn_key
    path = refs_build.freq_db_path()
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except FileNotFoundError:
        key = None
    if _conn is not None and _conn_key == key:
        return _conn
    if _conn is not None:
        _conn.close()
        _conn = None
        _conn_key = None
    if key is None:
        return None
    _conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    _conn_key = key
    return _conn


def close() -> None:
    global _conn, _conn_key
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _conn_key = None


def is_available() -> bool:
    with _lock:
        return _get_conn() is not None


def meta() -> dict[str, str]:
    with _lock:
        con = _get_conn()
        return dict(con.execute("SELECT key, value FROM meta")) if con else {}


def revision() -> str | None:
    """Identifier of the built list; stamped on items so a different list
    triggers re-enrichment."""
    rev = meta().get("revision")
    return f"{rev}+l{LOOKUP_VERSION}" if rev else None


def _stem(word: str, reading: str) -> tuple[str, str] | None:
    """The shared stem rule (store.stem_parts); kept as a name for the callers here."""
    return stem_parts(word, reading)


def _rank(con: sqlite3.Connection, word: str, reading: str) -> int | None:
    if reading:
        row = con.execute(
            "SELECT MIN(rank) FROM freq WHERE term = ? AND reading = ?", (word, reading)
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
    row = con.execute("SELECT MIN(rank) FROM freq WHERE term = ?", (word,)).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def lookup(word: str, reading: str | None = None) -> int | None:
    """Frequency rank (1 = most frequent) or None when unranked. A headword
    with no row of its own is retried without a trailing する / な."""
    word_n = unicodedata.normalize("NFKC", (word or "").strip()).strip(_EDGE_CHARS)
    if not word_n:
        return None
    reading_n = kata_to_hira(unicodedata.normalize("NFKC", (reading or "").strip()))
    with _lock:
        con = _get_conn()
        if con is None:
            return None
        rank = _rank(con, word_n, reading_n)
        if rank is None and (stem := _stem(word_n, reading_n)):
            rank = _rank(con, *stem)
        return rank
