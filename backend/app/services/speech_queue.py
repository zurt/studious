"""Card clips made in the background, with a catch-up list.

When items are harvested (a vocab list is transcribed, a breakdown is saved)
their word and sentence clips are generated, so Play and "Send to Anki" find
them cached. The speech engine may be down (the Mac is asleep, the helper is
not running), so the ids of items that still need clips are kept in
``data/audio/pending.json`` (a JSON list, insertion order, no duplicates) and
``drain`` works through them whenever the engine answers. A periodic task in
``main.py`` calls ``kick`` every ``CATCH_UP_SECONDS``; ``POST /api/tts/catch-up``
does it by hand (``all`` queues every vocab item, for a data move).

Which clips an item needs is decided by ``anki_push.clip_specs``, the same
function the Play endpoint and the Anki push use, so cache keys cannot diverge.
Pre-generation is on by default (``STUDIOUS_TTS_PREGENERATE``); when it is off
the automatic callers do nothing, the manual endpoint still works.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import anki_push, store, tts

log = logging.getLogger("studious.speech_queue")

CATCH_UP_SECONDS = 300
STARTUP_DELAY_SECONDS = 20
PENDING_FILE = "pending.json"

_lock = threading.Lock()  # guards pending.json
_drain_lock = threading.Lock()  # one drain at a time


def pending_path() -> Path:
    return tts.audio_dir() / PENDING_FILE


def _load() -> list[str]:
    try:
        data = json.loads(pending_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [i for i in dict.fromkeys(data) if isinstance(i, str)] if isinstance(data, list) else []


def _save(ids: list[str]) -> None:
    path = pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(ids, fh)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


def pregenerate_enabled() -> bool:
    return get_settings().tts_pregenerate


def pending_count() -> int:
    with _lock:
        return len(_load())


def enqueue(item_ids: Iterable[str], *, manual: bool = False) -> int:
    """Add ids to the list (kept in order, no duplicates). Returns how many were
    new. Does nothing when pre-generation is off, unless ``manual``."""
    if not manual and not pregenerate_enabled():
        return 0
    with _lock:
        have = _load()
        seen = set(have)
        new = [i for i in dict.fromkeys(item_ids) if i not in seen]
        if new:
            _save(have + new)
    return len(new)


def enqueue_region(doc_id: str, chapter_id: str, region_id: str, *, manual: bool = False) -> int:
    """Queue the vocab items that have a sighting in this region."""
    if not manual and not pregenerate_enabled():
        return 0
    ids = [i["id"] for i in store.items_sighted_in_region("vocab", doc_id, chapter_id, region_id)]
    return enqueue(ids, manual=manual)


def enqueue_all(*, manual: bool = False) -> int:
    """Queue every non-deleted vocab item."""
    if not manual and not pregenerate_enabled():
        return 0
    return enqueue((i["id"] for i in store.list_items("vocab")), manual=manual)


def _remove(item_id: str) -> None:
    with _lock:
        have = _load()
        if item_id in have:
            have.remove(item_id)
            _save(have)


def drain() -> dict[str, Any]:
    """Make the clips of every pending item. Only one drain runs at a time.
    Stops (keeping the rest) when the engine is unavailable; a clip that fails
    for any other reason is logged and counted as done, since playback retries
    it on demand and the list must not keep a permanent failure."""
    if not _drain_lock.acquire(blocking=False):
        return {"running": True, "made": 0, "cached": 0, "failed": 0, "remaining": pending_count(), "unavailable": False}
    try:
        return _drain()
    finally:
        _drain_lock.release()


def _drain() -> dict[str, Any]:
    made = cached = failed = 0
    unavailable = False
    if pending_count() and not tts.is_available():
        remaining = pending_count()
        log.info("speech_queue_unavailable", extra={"remaining": remaining, "reason": tts.unavailable_reason()})
        return {"running": False, "made": 0, "cached": 0, "failed": 0, "remaining": remaining, "unavailable": True}
    while not unavailable:
        with _lock:
            have = _load()
        if not have:
            break
        item_id = have[0]
        item = store.get_item("vocab", item_id)
        if item is not None and not item.get("deleted"):
            for part, text, reading, seed in anki_push.clip_specs(item):
                try:
                    if tts.cached_clip(text, reading, seed=seed) is not None:
                        cached += 1
                    else:
                        tts.synthesize(text, reading, seed=seed)
                        made += 1
                except tts.TtsUnavailable:
                    unavailable = True
                    break
                except tts.TtsError as exc:
                    failed += 1
                    log.warning(
                        "speech_queue_clip_failed",
                        extra={"item_id": item_id, "part": part, "error": str(exc)},
                    )
        if unavailable:
            break  # keep this id and the rest
        _remove(item_id)
    remaining = pending_count()
    log.info(
        "speech_queue_drained",
        extra={"made": made, "cached": cached, "failed": failed, "remaining": remaining, "unavailable": unavailable},
    )
    return {
        "running": False,
        "made": made,
        "cached": cached,
        "failed": failed,
        "remaining": remaining,
        "unavailable": unavailable,
    }


def _spawn(target: Callable[[], Any]) -> None:
    threading.Thread(target=target, name="speech-queue-drain", daemon=True).start()


_start_thread = _spawn  # tests replace this name; _spawn stays the real starter


def kick(*, manual: bool = False) -> bool:
    """Start ``drain`` in a daemon thread when the list is non-empty and no drain
    is running. Returns at once and never raises; True when a drain was started.
    Does nothing when pre-generation is off, unless ``manual``."""
    try:
        if not manual and not pregenerate_enabled():
            return False
        if _drain_lock.locked() or pending_count() == 0:
            return False
        _start_thread(drain)
        return True
    except Exception:  # noqa: BLE001 - a background nicety must never break its caller
        log.exception("speech_queue_kick_failed")
        return False


def enqueue_and_kick(item_ids: Iterable[str]) -> None:
    """For callers that changed what the clips of these items say (example sentences)."""
    try:
        enqueue(item_ids)
        kick()
    except Exception:  # noqa: BLE001
        log.exception("speech_queue_enqueue_error")


async def periodic() -> None:
    """Background task: shortly after startup, then every CATCH_UP_SECONDS, start a
    drain when clips are waiting."""
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            await asyncio.to_thread(kick)
        except Exception:  # noqa: BLE001
            log.exception("speech_queue_periodic_failed")
        await asyncio.sleep(CATCH_UP_SECONDS)
