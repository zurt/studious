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
import re
import sqlite3
import threading
import unicodedata
from typing import Any

from . import refs_build
from .store import kata_to_hira, stem_parts, strip_list_marker

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


_TILDES = "〜～~"
_PATTERN_PARTICLES = ("から", "より", "に", "を", "が", "と", "で", "へ", "も", "は")
_KANJI_NUMERALS = str.maketrans("〇一二三四五六七八九", "0123456789")
_KANJI_RE = re.compile("[㐀-䶿一-鿿豈-﫿々]")
_KANA_ONLY_RE = re.compile("^[ぁ-ゖァ-ヺー・]+$")


def _forms(surface: str) -> list[tuple[str, str]]:
    """(form, match kind) to try in order: the surface as written, with any
    list marker removed, with a leading pattern tilde (and one particle)
    removed. Duplicates are dropped."""
    out: list[tuple[str, str]] = []

    def add(form: str, kind: str) -> None:
        form = form.strip(_EDGE_CHARS)
        if form and all(form != f for f, _ in out):
            out.append((form, kind))

    raw = unicodedata.normalize("NFKC", (surface or "").strip())
    add(raw, "surface")
    base = strip_list_marker(surface)
    add(base, "marker")
    if base[:1] in tuple(_TILDES):
        rest = base.lstrip(_TILDES + " ")
        for particle in _PATTERN_PARTICLES:
            if rest.startswith(particle) and len(rest) > len(particle):
                add(rest[len(particle) :], "pattern")
                break
    return out


def _canon(s: str) -> str:
    return s.translate(_KANJI_NUMERALS)


def _plausible_reading_hit(headword: str, entry: dict[str, Any]) -> bool:
    """A reading-only candidate is believable when the headword is kana-only,
    or every kanji (and digit, kanji numerals counting as digits) in it occurs
    in one of the entry's kanji forms: 子供のころ -> 子供の頃, but not
    成功する -> 性交."""
    if _KANA_ONLY_RE.match(headword):
        return True
    if not _KANJI_RE.search(headword):
        return False
    need = {c for c in _canon(headword) if _KANJI_RE.match(c) or c.isdigit()}
    return any(need <= set(_canon(k)) for k in entry.get("kanji", []))


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


def _best(con: sqlite3.Connection, cands: list[tuple[int, int]], reading_n: str, accept=None):
    """(seq, entry) preferred among candidates: reading match, common, lowest seq."""
    scored: list[tuple[tuple[int, int, int], int, dict[str, Any]]] = []
    for seq, common in cands:
        entry = _load_entry(con, seq)
        if entry is None or (accept is not None and not accept(entry)):
            continue
        reading_match = int(
            bool(reading_n) and any(kata_to_hira(k) == reading_n for k in entry.get("kana", []))
        )
        scored.append(((-reading_match, -common, seq), seq, entry))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0])
    return scored[0][1], scored[0][2]


def lookup(surface: str, reading: str | None = None) -> dict[str, Any] | None:
    """Best JMdict entry for a textbook surface form.

    Tried in order: the surface as written (``match: "surface"``), with a
    leading list marker removed (``marker``), with a pattern tilde and one
    particle removed (``pattern``), each of those without a trailing する / な
    (``stem``), and only then the reading alone (``reading``), accepted only
    for a kana-only headword or when every kanji of the headword occurs in one
    of the entry's kanji forms. Within a step, candidates matching the given
    reading are preferred, then common entries, then the lowest sequence
    number. Returns ``{seq, gloss, senses, pos, common, kanji, kana, match}``
    or ``None``.
    """
    forms = _forms(surface)
    if not forms:
        return None
    reading_n = kata_to_hira(unicodedata.normalize("NFKC", (reading or "").strip()))
    steps: list[tuple[str, str]] = list(forms)
    for form, _kind in forms:
        parts = stem_parts(form, reading_n)
        if parts and all(parts[0] != f for f, _ in steps):
            steps.append((parts[0], "stem"))
    stem_reading = {parts[0]: parts[1] for f, _ in forms if (parts := stem_parts(f, reading_n))}

    with _lock:
        con = _get_conn()
        if con is None:
            return None
        found = None
        match = ""
        for form, kind in steps:
            cands = _candidates(con, form)
            if not cands:
                continue
            read = kata_to_hira(stem_reading.get(form, reading_n)) if kind == "stem" else reading_n
            found = _best(con, cands, read)
            if found:
                match = kind
                break
        if found is None and reading_n:
            headword = forms[-1][0]  # the most stripped form
            if reading_n != headword:
                cands = _candidates(con, reading_n)
                found = _best(con, cands, reading_n, lambda e: _plausible_reading_hit(headword, e))
                match = "reading"
        if found is None:
            return None
        seq, entry = found

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
        "match": match,
    }


def jlpt_level(headword: str, reading: str | None = None) -> int | None:
    """JLPT level (5 = N5 … 1 = N1) for a word, or None if unlisted.

    Matches the expression column first (with the reading as a
    tie-breaker when supplied), then falls back to matching the reading
    column for kana-only textbook forms.
    """
    forms = [f for f, _ in _forms(headword)]
    if not forms:
        return None
    headword_n = forms[-1]
    reading_n = kata_to_hira(unicodedata.normalize("NFKC", (reading or "").strip()))
    # The lists write the stem (成功, not 成功する): try it after each form.
    variants = list(forms)
    for f in forms:
        parts = stem_parts(f, reading_n)
        if parts and parts[0] not in variants:
            variants.append(parts[0])

    with _lock:
        con = _get_conn()
        if con is None:
            return None
        rows = []
        for variant in variants:
            rows = con.execute(
                "SELECT reading, level FROM jlpt WHERE expression = ?", (variant,)
            ).fetchall()
            if rows:
                break
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
