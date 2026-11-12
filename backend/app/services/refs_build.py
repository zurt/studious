"""Download pinned reference datasets and build the local lookup index.

Artifacts (JMdict, JLPT lists) are pinned by exact URL + SHA-256 in
``backend/refs.lock.json``; downloads that don't match the recorded hash
are rejected and deleted. The output is a single read-only SQLite file
at ``data/refs/jmdict/jmdict.sqlite`` consumed by ``services.jmdict``.

A third artifact, the JPDB-derived frequency list (a Yomitan/Yomichan
frequency dictionary zip), is built into its own SQLite file at
``data/refs/freq/jpdb-freq.sqlite`` consumed by ``services.freq``. The zip
is untrusted input: it is only ever read in memory as zip + JSON, never
extracted, with size and member-name guards (see ``build_freq_sqlite``).

Stdlib only — no new runtime dependencies. Invoked via
``scripts/fetch_refs.py`` (``make refs``).
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import sqlite3
import tarfile
import tempfile
import unicodedata
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from ..config import get_settings
from .store import kata_to_hira

log = logging.getLogger("studious.refs_build")

SCHEMA_VERSION = 1

# Senses tagged search-only (sK/sk) are indexed for lookup but their
# surfaces are never chosen for display.
_SEARCH_ONLY_TAGS = {"sK", "sk"}

_JLPT_TAG_RE = re.compile(r"JLPT_(\d)")


def lock_path() -> Path:
    return Path(__file__).resolve().parents[2] / "refs.lock.json"


def load_lock() -> dict[str, Any]:
    return json.loads(lock_path().read_text("utf-8"))


def refs_dir() -> Path:
    return get_settings().data_dir / "refs"


def jmdict_db_path() -> Path:
    return refs_dir() / "jmdict" / "jmdict.sqlite"


def freq_db_path() -> Path:
    return refs_dir() / "freq" / "jpdb-freq.sqlite"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_verified(url: str, sha256: str, dest: Path) -> Path:
    """Download url to dest and verify its SHA-256; mismatches are deleted."""
    if dest.exists() and sha256_file(dest) == sha256:
        log.info("refs_download_cached", extra={"dest": str(dest)})
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("refs_download_start", extra={"url": url})
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 - pinned https URLs from refs.lock.json
    actual = sha256_file(tmp)
    if actual != sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"checksum mismatch for {url}: expected {sha256}, got {actual} — "
            "refusing to use the download. If the artifact was legitimately "
            "updated, re-pin refs.lock.json deliberately."
        )
    tmp.replace(dest)
    return dest


# ---------- JMdict JSON -> rows ----------


def _entry_payload(word: dict[str, Any]) -> dict[str, Any]:
    """Compact display payload stored per entry."""
    kanji = [k["text"] for k in word.get("kanji", []) if not (set(k.get("tags", [])) & _SEARCH_ONLY_TAGS)]
    kana = [k["text"] for k in word.get("kana", []) if not (set(k.get("tags", [])) & _SEARCH_ONLY_TAGS)]
    senses = []
    for sense in word.get("sense", []):
        glosses = [g["text"] for g in sense.get("gloss", []) if g.get("lang") == "eng" and g.get("text")]
        if glosses:
            senses.append({"pos": sense.get("partOfSpeech", []), "gloss": "; ".join(glosses[:5])})
    common = any(k.get("common") for k in word.get("kanji", [])) or any(
        k.get("common") for k in word.get("kana", [])
    )
    return {"kanji": kanji, "kana": kana, "senses": senses, "common": common}


def _lookup_rows(word: dict[str, Any]) -> list[tuple[str, int, str, int]]:
    seq = int(word["id"])
    rows = []
    for kind, elements in (("kanji", word.get("kanji", [])), ("kana", word.get("kana", []))):
        for el in elements:
            text = el.get("text")
            if text:
                rows.append((text, seq, kind, 1 if el.get("common") else 0))
    return rows


def _jlpt_rows(files: dict[int, Path]) -> list[tuple[str, str, int]]:
    """(expression, reading, level) with the easiest level (largest N) kept
    when a word appears on multiple lists."""
    best: dict[tuple[str, str], int] = {}
    for level, path in files.items():
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                expression = (row.get("expression") or "").strip()
                reading = (row.get("reading") or "").strip()
                if not expression:
                    continue
                tag_levels = [int(m) for m in _JLPT_TAG_RE.findall(row.get("tags") or "")]
                row_level = max([level, *tag_levels]) if tag_levels else level
                key = (expression, reading)
                best[key] = max(best.get(key, 0), row_level)
    return [(exp, read, lvl) for (exp, read), lvl in best.items()]


def build_sqlite(
    jmdict_json_path: Path,
    jlpt_csvs: dict[int, Path],
    out_path: Path,
    *,
    version: str = "",
) -> dict[str, int]:
    """Build the lookup SQLite from a jmdict-simplified JSON + JLPT CSVs."""
    log.info("refs_build_start", extra={"out": str(out_path)})
    with open(jmdict_json_path, encoding="utf-8") as fh:
        data = json.load(fh)
    words = data.get("words", [])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE entries (seq INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE lookup (
              surface TEXT NOT NULL,
              seq INTEGER NOT NULL,
              kind TEXT NOT NULL,
              common INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX idx_lookup_surface ON lookup (surface);
            CREATE TABLE jlpt (
              expression TEXT NOT NULL,
              reading TEXT NOT NULL DEFAULT '',
              level INTEGER NOT NULL
            );
            CREATE INDEX idx_jlpt_expression ON jlpt (expression);
            CREATE INDEX idx_jlpt_reading ON jlpt (reading);
            """
        )
        entry_rows = []
        lookup_rows = []
        for word in words:
            payload = _entry_payload(word)
            if not payload["senses"]:
                continue
            entry_rows.append((int(word["id"]), json.dumps(payload, ensure_ascii=False)))
            lookup_rows.extend(_lookup_rows(word))
        con.executemany("INSERT OR REPLACE INTO entries VALUES (?, ?)", entry_rows)
        con.executemany("INSERT INTO lookup VALUES (?, ?, ?, ?)", lookup_rows)

        jlpt_rows = _jlpt_rows(jlpt_csvs)
        con.executemany("INSERT INTO jlpt VALUES (?, ?, ?)", jlpt_rows)

        con.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", str(SCHEMA_VERSION)),
                ("jmdict_version", version or str(data.get("version", ""))),
                ("jmdict_date", str(data.get("dictDate", ""))),
                ("entries", str(len(entry_rows))),
                ("jlpt_rows", str(len(jlpt_rows))),
            ],
        )
        con.commit()
    finally:
        con.close()
    tmp.replace(out_path)
    stats = {"entries": len(entry_rows), "lookup_rows": len(lookup_rows), "jlpt_rows": len(jlpt_rows)}
    log.info("refs_build_done", extra=stats)
    return stats


# ---------- Yomitan frequency zip -> rows ----------

FREQ_SCHEMA_VERSION = 1
# The real list is one ~48 MB member; these caps only stop a hostile or
# corrupt archive from exhausting memory. Declared sizes are not trusted:
# reads are bounded as well.
FREQ_MAX_MEMBER_BYTES = 256 * 1024 * 1024
FREQ_MAX_TOTAL_BYTES = 512 * 1024 * 1024
FREQ_MAX_MEMBERS = 256
FREQ_MAX_INDEX_BYTES = 64 * 1024
_FREQ_BANK_RE = re.compile(r"^term_meta_bank_\d+\.json$")
_KANA_MARK = "\u32d5"  # ㋕ — the value is the frequency of the kana spelling
_NOT_IN_CORPUS = "\u274c"  # ❌ — placeholder rank for terms jpdb never saw


def _read_zip_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise ValueError(f"zip member {info.filename!r} too large ({info.file_size} bytes)")
    with zf.open(info) as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"zip member {info.filename!r} exceeds {limit} bytes when read")
    return data


def _freq_value(raw: Any) -> tuple[int, str] | None:
    """(rank, displayValue) from a Yomitan frequency payload, which is either
    an int or ``{"value": int, "displayValue": str}``."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw, ""
    if isinstance(raw, dict) and isinstance(raw.get("value"), int) and not isinstance(raw["value"], bool):
        display = raw.get("displayValue")
        return raw["value"], display if isinstance(display, str) else ""
    return None


def parse_freq_rows(bank: Any, best: dict[tuple[str, str], int]) -> int:
    """Fold one ``term_meta_bank`` JSON array into ``best`` (min rank per
    (term, reading)); returns the number of rows kept.

    The JPDB list has two row shapes for a term:

    - kana-only terms: ``[term, "freq", {"value", "displayValue"}]`` ->
      stored with reading ``""``;
    - kanji terms: ``[term, "freq", {"reading", "frequency": {...}}]`` ->
      stored under the hiragana reading. Rows whose displayValue carries
      ``㋕`` are the kana spelling's rank (duplicated by the kana-only rows,
      but with a reading attached) and are skipped so a kanji spelling is
      only ever ranked by its own frequency.

    ``❌`` rows are a 183459 placeholder for terms absent from the corpus
    and are skipped. Anything malformed is skipped, never raised.
    """
    kept = 0
    if not isinstance(bank, list):
        return 0
    for row in bank:
        if not (isinstance(row, list) and len(row) == 3 and row[1] == "freq"):
            continue
        term, data = row[0], row[2]
        if not isinstance(term, str) or not term or not isinstance(data, dict):
            continue
        reading = ""
        if "frequency" in data:
            parsed = _freq_value(data["frequency"])
            reading_raw = data.get("reading")
            if parsed is None or not isinstance(reading_raw, str):
                continue
            reading = kata_to_hira(unicodedata.normalize("NFKC", reading_raw.strip()))
            if _KANA_MARK in parsed[1]:
                continue
        else:
            parsed = _freq_value(data)
            if parsed is None:
                continue
        rank, display = parsed
        if rank < 1 or _NOT_IN_CORPUS in display:
            continue
        key = (unicodedata.normalize("NFKC", term), reading)
        if rank < best.get(key, rank + 1):
            best[key] = rank
        kept += 1
    return kept


def build_freq_sqlite(zip_path: Path, out_path: Path, *, version: str = "") -> dict[str, int]:
    """Build the frequency SQLite from a Yomitan frequency-dictionary zip.

    Safety: the archive is never extracted. Member names that are absolute,
    contain ``..`` or backslashes reject the whole archive; only
    ``index.json`` and top-level ``term_meta_bank_N.json`` members are read,
    each with a bounded read. ``index.json`` must declare a rank-based,
    format-3 dictionary.
    """
    log.info("freq_build_start", extra={"out": str(out_path)})
    best: dict[tuple[str, str], int] = {}
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > FREQ_MAX_MEMBERS:
            raise ValueError(f"zip has too many members ({len(infos)})")
        for info in infos:
            name = info.filename
            if name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/"):
                raise ValueError(f"unsafe zip member name {name!r}")
        if sum(i.file_size for i in infos) > FREQ_MAX_TOTAL_BYTES:
            raise ValueError("zip declares too much uncompressed data")
        by_name = {i.filename: i for i in infos}
        if "index.json" not in by_name:
            raise ValueError("zip has no index.json — not a Yomitan dictionary")
        index = json.loads(_read_zip_member(zf, by_name["index.json"], FREQ_MAX_INDEX_BYTES))
        if (
            not isinstance(index, dict)
            or index.get("format") != 3
            or index.get("frequencyMode") != "rank-based"
        ):
            raise ValueError("unexpected frequency list format (want format 3, rank-based)")
        banks = sorted(n for n in by_name if _FREQ_BANK_RE.match(n))
        if not banks:
            raise ValueError("zip has no term_meta_bank_*.json members")
        for name in banks:
            parse_freq_rows(json.loads(_read_zip_member(zf, by_name[name], FREQ_MAX_MEMBER_BYTES)), best)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE freq (
              term TEXT NOT NULL,
              reading TEXT NOT NULL DEFAULT '',
              rank INTEGER NOT NULL
            );
            CREATE INDEX idx_freq_term ON freq (term, reading);
            """
        )
        con.executemany("INSERT INTO freq VALUES (?, ?, ?)", [(t, r, v) for (t, r), v in best.items()])
        con.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", str(FREQ_SCHEMA_VERSION)),
                ("version", version),
                ("revision", str(index.get("revision", "")) or version),
                ("title", str(index.get("title", ""))),
                ("rows", str(len(best))),
            ],
        )
        con.commit()
    finally:
        con.close()
    tmp.replace(out_path)
    stats = {"freq_rows": len(best)}
    log.info("freq_build_done", extra=stats)
    return stats


def _freq_meta(path: Path) -> dict[str, str]:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT key, value FROM meta"))
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def fetch_and_build_freq(*, force: bool = False) -> dict[str, Any]:
    """Download the pinned frequency zip (checksum-verified) and build its
    SQLite. Skipped when the index already matches the pinned version."""
    spec = load_lock()["freq"]
    out = freq_db_path()
    if out.exists() and not force:
        meta = _freq_meta(out)
        if meta.get("version") == spec["version"]:
            log.info("freq_up_to_date", extra={"version": spec["version"]})
            return {"status": "up_to_date", "version": spec["version"], "freq_rows": meta.get("rows")}
    zip_path = download_verified(spec["url"], spec["sha256"], refs_dir() / "downloads" / "jpdb-freq.zip")
    return {"status": "built", "version": spec["version"], **build_freq_sqlite(zip_path, out, version=spec["version"])}


def fetch_and_build(*, force: bool = False) -> dict[str, Any]:
    """Full pipeline: JMdict/JLPT index, then the frequency index."""
    result = fetch_and_build_jmdict(force=force)
    result["freq"] = fetch_and_build_freq(force=force)
    return result


def fetch_and_build_jmdict(*, force: bool = False) -> dict[str, Any]:
    """Download pinned JMdict/JLPT artifacts, verify, build the SQLite."""
    lock = load_lock()
    out = jmdict_db_path()
    if out.exists() and not force:
        con = sqlite3.connect(out)
        try:
            meta = dict(con.execute("SELECT key, value FROM meta"))
        finally:
            con.close()
        if meta.get("jmdict_version") == lock["jmdict"]["version"].split("+")[0] or meta.get(
            "jmdict_version"
        ) == lock["jmdict"]["version"]:
            log.info("refs_up_to_date", extra={"version": meta.get("jmdict_version")})
            return {"status": "up_to_date", **meta}

    downloads = refs_dir() / "downloads"
    jm = lock["jmdict"]
    tgz = download_verified(jm["url"], jm["sha256"], downloads / "jmdict.json.tgz")

    jlpt_paths: dict[int, Path] = {}
    for name, spec in lock["jlpt"]["files"].items():
        level = int(name[1])
        jlpt_paths[level] = download_verified(spec["url"], spec["sha256"], downloads / f"jlpt-{name}.csv")

    with tempfile.TemporaryDirectory() as td:
        member = jm["json_member"]
        with tarfile.open(tgz, "r:gz") as tf:
            tf.extract(member, td, filter="data")
        stats = build_sqlite(
            Path(td) / member, jlpt_paths, out, version=jm["version"]
        )
    return {"status": "built", **stats}
