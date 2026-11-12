"""Enrich vocab store items from the local JMdict/JLPT index.

Enrichment is a separate pass over store items rather than part of item
creation, so the store never depends on the (optional) reference index:

- ``enrich_pending`` runs after every harvest and only touches items
  that have never been attempted (``enriched_at`` is null), so it stays
  cheap and idempotent.
- ``enrich_pending(force=True)`` re-links everything — used by
  ``POST /api/store/enrich`` after the index is (re)built.
- Items are re-linked once whenever ``ENRICH_VERSION`` is bumped (the
  dictionary lookup rules changed), stamped on each item as
  ``enrich_version``.
- Items already enriched are also revisited, once, when the frequency
  index is available and they have not been checked against its current
  revision (``freq_checked``), so a newly built frequency list reaches
  existing items without a flag.

Field policy: JMdict data fills ``jmdict_seq``/``pos``/classifications
and replaces ``meaning`` only while ``meaning_source`` is ``"llm"`` —
a user-edited meaning (``meaning_source: "user"``) is never overwritten.
``meaning_context`` (the textbook-context meaning) is set once, from the
item or its history, and never replaced. When a re-link drops a dictionary
link, ``meaning`` is restored from it.
``priority_group`` is a pure function of the classifications and is
recomputed on every enrichment pass.
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import UTC, datetime
from typing import Any

from . import freq, jmdict, store, wanikani

log = logging.getLogger("studious.enrich")

# Bump when the dictionary lookup rules change so every item is re-linked once.
# 3: reading-only matches need a plausible headword; list markers, pattern
# tildes and する/な stems are looked up before the reading.
ENRICH_VERSION = 3


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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


def vocab_changes(
    item: dict[str, Any], history: dict[str, tuple[str, str]] | None = None
) -> dict[str, Any]:
    """Enrichment changes for one vocab item (may be empty).

    Always stamps ``enriched_at`` and recomputes ``priority_group`` —
    a JMdict miss is still a completed (and meaningful) attempt.
    ``history`` is ``store.meaning_history()``; it backfills ``meaning_context``
    and supplies the meaning to restore when a wrong link is dropped.
    """
    headword = item.get("headword") or ""
    reading = item.get("reading") or ""
    hit = jmdict.lookup(headword, reading)

    changes: dict[str, Any] = {"enriched_at": _now_iso(), "enrich_version": ENRICH_VERSION}
    classifications = dict(item.get("classifications") or {})
    source = item.get("meaning_source", "llm")
    ctx = (item.get("meaning_context") or "").strip()
    ctx_source = source if source in store.CONTEXT_SOURCES else "llm"
    if not ctx:
        hist = (history or {}).get(item.get("id") or "")
        if hist:
            ctx, ctx_source = hist
        elif source in store.CONTEXT_SOURCES and (item.get("meaning") or "").strip():
            ctx = item["meaning"].strip()
        if ctx:
            changes["meaning_context"] = ctx
    links = dict(item.get("links") or {})
    links.setdefault("jisho", jisho_link(headword))

    if hit:
        changes["jmdict_seq"] = hit["seq"]
        if hit["pos"]:
            changes["pos"] = hit["pos"]
        if hit["gloss"] and source in ("llm", "jmdict"):
            changes["meaning"] = hit["gloss"]
            changes["meaning_source"] = "jmdict"
        classifications["jmdict_common"] = hit["common"]
        classifications.pop("jlpt", None)

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
        if item.get("jmdict_seq") is not None:
            # The old link no longer holds (or the index lost it): drop what
            # came from it and bring back the textbook meaning.
            changes["jmdict_seq"] = None
            changes["pos"] = []
            classifications.pop("jmdict_common", None)
            if source == "jmdict" and ctx:
                changes["meaning"] = ctx
                changes["meaning_source"] = ctx_source
        classifications.pop("jlpt", None)
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

    # Frequency rank (JPDB corpus). freq_checked records which list was
    # consulted, even on a miss, so unranked items are not retried forever.
    freq_revision = freq.revision()
    if freq_revision:
        rank = freq.lookup(headword, reading)
        if rank is not None:
            classifications["freq_rank"] = rank
        else:
            classifications.pop("freq_rank", None)
        changes["freq_checked"] = freq_revision

    changes["classifications"] = classifications
    changes["links"] = links
    changes["priority_group"] = compute_priority(
        {**item, **changes, "classifications": classifications}
    )
    return changes


def _is_noop(item: dict[str, Any], changes: dict[str, Any]) -> bool:
    """True when a re-enrichment would only restamp ``enriched_at`` — not worth
    an append."""
    return all(item.get(k) == v for k, v in changes.items() if k != "enriched_at")


def enrich_pending(*, force: bool = False) -> dict[str, Any]:
    """Enrich vocab items that haven't been attempted yet (or all, with
    force). No-op until at least one source (JMdict index, WaniKani
    subjects cache) exists."""
    if not jmdict.is_available() and not wanikani.has_subjects() and not freq.is_available():
        return {"available": False, "attempted": 0, "linked": 0}

    freq_revision = freq.revision()
    attempted = linked = relinked = unlinked = unchanged = 0
    history = store.meaning_history("vocab")
    for item in store.list_items("vocab"):
        if (
            not force
            and item.get("enriched_at")
            and item.get("enrich_version") == ENRICH_VERSION
            and (not freq_revision or item.get("freq_checked") == freq_revision)
        ):
            continue
        changes = vocab_changes(item, history)
        if not _is_noop(item, changes):
            store.update_item("vocab", item["id"], **changes)
        attempted += 1
        before, after = item.get("jmdict_seq"), changes.get("jmdict_seq", item.get("jmdict_seq"))
        if after:
            linked += 1
        if before and after is None:
            unlinked += 1
        elif before and after != before:
            relinked += 1
        elif before == after:
            unchanged += 1
    result = {"available": True, "attempted": attempted, "linked": linked}
    if attempted:
        log.info(
            "enrich_done",
            extra={**result, "force": force, "relinked": relinked, "unlinked": unlinked, "unchanged": unchanged},
        )
    return result
