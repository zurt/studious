"""Enrich vocab store items from the local JMdict/JLPT index.

Enrichment is a separate pass over store items rather than part of item
creation, so the store never depends on the (optional) reference index:

- ``enrich_pending`` runs after every harvest and only touches items
  that have never been attempted (``enriched_at`` is null), so it stays
  cheap and idempotent.
- ``enrich_pending(force=True)`` re-links everything — used by
  ``POST /api/store/enrich`` after the index is (re)built.

Field policy: JMdict data fills ``jmdict_seq``/``pos``/classifications
and replaces ``meaning`` only while ``meaning_source`` is ``"llm"`` —
a user-edited meaning (``meaning_source: "user"``) is never overwritten.
``priority_group`` is a pure function of the classifications and is
recomputed on every enrichment pass.
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from . import jmdict, store, wanikani

log = logging.getLogger("studious.enrich")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def jisho_link(headword: str) -> str:
    return "https://jisho.org/search/" + urllib.parse.quote(headword)


def compute_priority(item: dict[str, Any]) -> int:
    """Study-priority bucket, 1 (study first) … 5 (obscure).

    Pure function of the item's classifications + JMdict linkage so it
    can be recomputed whenever the formula or the signals change.
    """
    c = item.get("classifications") or {}
    jlpt = c.get("jlpt")
    common = bool(c.get("jmdict_common"))
    wk_level = c.get("wanikani_level")
    if jlpt in ("N5", "N4"):
        return 1
    if jlpt in ("N3", "N2") or (common and isinstance(wk_level, int) and wk_level <= 30):
        return 2
    if jlpt == "N1" or common or isinstance(wk_level, int):
        return 3
    if item.get("jmdict_seq"):
        return 4
    return 5


def vocab_changes(item: dict[str, Any]) -> dict[str, Any]:
    """Enrichment changes for one vocab item (may be empty).

    Always stamps ``enriched_at`` and recomputes ``priority_group`` —
    a JMdict miss is still a completed (and meaningful) attempt.
    """
    headword = item.get("headword") or ""
    reading = item.get("reading") or ""
    hit = jmdict.lookup(headword, reading)

    changes: dict[str, Any] = {"enriched_at": _now_iso()}
    classifications = dict(item.get("classifications") or {})
    links = dict(item.get("links") or {})
    links.setdefault("jisho", jisho_link(headword))

    if hit:
        changes["jmdict_seq"] = hit["seq"]
        if hit["pos"]:
            changes["pos"] = hit["pos"]
        if hit["gloss"] and item.get("meaning_source", "llm") == "llm":
            changes["meaning"] = hit["gloss"]
            changes["meaning_source"] = "jmdict"
        classifications["jmdict_common"] = hit["common"]

        # JLPT: the lists may use a variant spelling (係わる for 関わる) —
        # try the headword first, then the entry's other written forms.
        level = jmdict.jlpt_level(headword, reading)
        if level is None:
            for variant in hit["kanji"]:
                if variant != headword:
                    level = jmdict.jlpt_level(variant, reading)
                    if level is not None:
                        break
        if level is not None:
            classifications["jlpt"] = f"N{level}"
    else:
        level = jmdict.jlpt_level(headword, reading)
        if level is not None:
            classifications["jlpt"] = f"N{level}"

    # WaniKani level + link when the subjects cache has been synced.
    # SRS history stays out of classifications — display signal only.
    if wanikani.has_subjects():
        subject = wanikani.vocab_subject(headword)
        if subject is not None:
            wk_data = subject.get("data") or {}
            if isinstance(wk_data.get("level"), int):
                classifications["wanikani_level"] = wk_data["level"]
            if wk_data.get("document_url"):
                links["wanikani"] = wk_data["document_url"]

    changes["classifications"] = classifications
    changes["links"] = links
    changes["priority_group"] = compute_priority(
        {**item, **changes, "classifications": classifications}
    )
    return changes


def enrich_pending(*, force: bool = False) -> dict[str, Any]:
    """Enrich vocab items that haven't been attempted yet (or all, with
    force). No-op until at least one source (JMdict index, WaniKani
    subjects cache) exists."""
    if not jmdict.is_available() and not wanikani.has_subjects():
        return {"available": False, "attempted": 0, "linked": 0}

    attempted = linked = 0
    for item in store.list_items("vocab"):
        if not force and item.get("enriched_at"):
            continue
        changes = vocab_changes(item)
        store.update_item("vocab", item["id"], **changes)
        attempted += 1
        if changes.get("jmdict_seq"):
            linked += 1
    result = {"available": True, "attempted": attempted, "linked": linked}
    if attempted:
        log.info("enrich_done", extra={**result, "force": force})
    return result
