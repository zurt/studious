"""WaniKani API v2 sync and local cache.

Purpose (docs/vocab-store-plan.md): surface WK levels, mnemonics, the
user's own study notes, and the vocab → kanji → radical component graph
inside the vocab store. The user completed all 60 levels years ago and
that knowledge has atrophied — WK SRS state is a **display signal only**
and must never auto-mark store items as known.

Cache layout (``data/refs/wanikani/``, gitignored — WK content is
licensed for personal use only):

- ``subjects.jsonl`` / ``study_materials.jsonl`` / ``assignments.jsonl``
  — append-only, latest line per id wins (same pattern as the store)
- ``sync_state.json`` — per-resource ``updated_after`` cursors

The API token comes from the ``WANIKANI_API_TOKEN`` env var (store it
in the macOS Keychain like ``ANTHROPIC_API_KEY``). Rate limit is 60
requests/minute; a full first sync is ~30 requests.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import get_settings

log = logging.getLogger("studious.wanikani")

_lock = threading.Lock()
_cache: dict[str, tuple[tuple[int, int], dict[int, dict[str, Any]]]] = {}

BASE_URL = "https://api.wanikani.com/v2"
REVISION = "20170710"

RESOURCES = ("subjects", "study_materials", "assignments")

SRS_STAGE_NAMES = {
    0: "initiate",
    1: "apprentice",
    2: "apprentice",
    3: "apprentice",
    4: "apprentice",
    5: "guru",
    6: "guru",
    7: "master",
    8: "enlightened",
    9: "burned",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cache_dir() -> Path:
    return get_settings().data_dir / "refs" / "wanikani"


def _resource_path(resource: str) -> Path:
    if resource not in RESOURCES:
        raise ValueError(f"unknown wanikani resource: {resource!r}")
    return cache_dir() / f"{resource}.jsonl"


def _state_path() -> Path:
    return cache_dir() / "sync_state.json"


def token() -> str | None:
    return get_settings().wanikani_api_token


def is_configured() -> bool:
    return bool(token())


# ---------- HTTP ----------


def _fetch_json(url: str) -> dict[str, Any]:
    """One authenticated GET. Waits out a 429 once using Retry-After."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token()}",
            "Wanikani-Revision": REVISION,
        },
    )
    for attempt in (0, 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https host
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt == 0:
                delay = min(int(exc.headers.get("Retry-After") or 10), 70)
                log.info("wanikani_rate_limited", extra={"retry_after": delay})
                time.sleep(delay)
                continue
            raise
    raise AssertionError("unreachable")


def _iter_collection(resource: str, updated_after: str | None) -> Iterable[dict[str, Any]]:
    params = {}
    if updated_after:
        params["updated_after"] = updated_after
    url = f"{BASE_URL}/{resource}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    while url:
        payload = _fetch_json(url)
        yield from payload.get("data", [])
        url = (payload.get("pages") or {}).get("next_url")


# ---------- Cache read/write ----------


def _append_records(resource: str, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path = _resource_path(resource)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _load_latest(resource: str) -> dict[int, dict[str, Any]]:
    """id -> latest record, cached against (mtime_ns, size)."""
    path = _resource_path(resource)
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
    records: dict[int, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("id"), int):
                records[obj["id"]] = obj
    _cache[key] = (sig, records)
    return records


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


def status() -> dict[str, Any]:
    state = load_state()
    return {
        "configured": is_configured(),
        "synced_at": state.get("synced_at"),
        "counts": {r: len(_load_latest(r)) for r in RESOURCES},
    }


# ---------- Sync ----------


def sync(*, full: bool = False) -> dict[str, Any]:
    """Pull new/changed records for every resource. Incremental via each
    resource's updated_after cursor unless ``full``."""
    if not is_configured():
        raise RuntimeError("WANIKANI_API_TOKEN is not set")
    state = load_state()
    fetched: dict[str, int] = {}
    with _lock:
        for resource in RESOURCES:
            cursor = None if full else state.get(resource, {}).get("updated_after")
            records = []
            max_updated = cursor or ""
            for item in _iter_collection(resource, cursor):
                record = {
                    "id": item["id"],
                    "object": item.get("object"),
                    "data_updated_at": item.get("data_updated_at"),
                    "data": item.get("data") or {},
                }
                records.append(record)
                if record["data_updated_at"] and record["data_updated_at"] > max_updated:
                    max_updated = record["data_updated_at"]
            _append_records(resource, records)
            fetched[resource] = len(records)
            if max_updated:
                state[resource] = {"updated_after": max_updated}
        state["synced_at"] = _now_iso()
        _save_state(state)
    log.info("wanikani_sync_done", extra={**fetched, "full": full})
    return {"synced_at": state["synced_at"], "fetched": fetched}


# ---------- Queries ----------


def _subjects_by_characters() -> dict[tuple[str, str], dict[str, Any]]:
    """(object_type, characters) -> subject record."""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for record in _load_latest("subjects").values():
        chars = (record.get("data") or {}).get("characters")
        if chars and not (record.get("data") or {}).get("hidden_at"):
            index[(record.get("object", ""), chars)] = record
    return index


def vocab_subject(characters: str) -> dict[str, Any] | None:
    index = _subjects_by_characters()
    return index.get(("vocabulary", characters)) or index.get(("kana_vocabulary", characters))


def level_for(characters: str) -> int | None:
    subject = vocab_subject(characters)
    if subject is None:
        return None
    return (subject.get("data") or {}).get("level")


def has_subjects() -> bool:
    return bool(_load_latest("subjects"))


def _study_material_for(subject_id: int) -> dict[str, Any] | None:
    for record in _load_latest("study_materials").values():
        if (record.get("data") or {}).get("subject_id") == subject_id:
            return record["data"]
    return None


def _assignment_for(subject_id: int) -> dict[str, Any] | None:
    for record in _load_latest("assignments").values():
        if (record.get("data") or {}).get("subject_id") == subject_id:
            return record["data"]
    return None


def _subject_view(record: dict[str, Any]) -> dict[str, Any]:
    """Display payload for one subject: mnemonics + the user's own notes
    and SRS history (display only — never feeds item status)."""
    data = record.get("data") or {}
    sid = record["id"]
    view = {
        "id": sid,
        "object": record.get("object"),
        "characters": data.get("characters"),
        "slug": data.get("slug"),
        "level": data.get("level"),
        "document_url": data.get("document_url"),
        "meanings": [m.get("meaning") for m in data.get("meanings", []) if m.get("primary")]
        or [m.get("meaning") for m in data.get("meanings", [])][:1],
        "readings": [r.get("reading") for r in data.get("readings", []) if r.get("primary")]
        or [r.get("reading") for r in data.get("readings", [])][:1],
        "meaning_mnemonic": data.get("meaning_mnemonic") or "",
        "reading_mnemonic": data.get("reading_mnemonic") or "",
    }
    material = _study_material_for(sid)
    if material:
        view["user_notes"] = {
            "meaning_note": material.get("meaning_note") or "",
            "reading_note": material.get("reading_note") or "",
            "synonyms": material.get("meaning_synonyms") or [],
        }
    assignment = _assignment_for(sid)
    if assignment:
        stage = assignment.get("srs_stage")
        view["srs"] = {
            "stage": stage,
            "stage_name": SRS_STAGE_NAMES.get(stage, "unknown"),
            "burned_at": assignment.get("burned_at"),
            "passed_at": assignment.get("passed_at"),
        }
    return view


def drilldown(characters: str) -> dict[str, Any] | None:
    """Vocab subject → component kanji → component radicals, each with
    mnemonics, the user's notes, and SRS history."""
    subject = vocab_subject(characters)
    if subject is None:
        return None
    subjects = _load_latest("subjects")
    view = _subject_view(subject)
    kanji_views = []
    for kanji_id in (subject.get("data") or {}).get("component_subject_ids", []):
        kanji_record = subjects.get(kanji_id)
        if kanji_record is None:
            continue
        kanji_view = _subject_view(kanji_record)
        kanji_view["radicals"] = [
            _subject_view(subjects[rid])
            for rid in (kanji_record.get("data") or {}).get("component_subject_ids", [])
            if rid in subjects
        ]
        kanji_views.append(kanji_view)
    view["kanji"] = kanji_views
    return view
