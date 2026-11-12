"""Chapter shortlist: which vocab items are worth studying in Anki.

The owner studies ~125 new words per chapter. Rather than hunting through
the list, the app proposes a shortlist and the owner strikes words out.
``assess`` returns why an item is NOT a candidate (or None). It is joined
at read time like the Anki state and never written to the store.
"""
from __future__ import annotations

from typing import Any

from . import store

# Check order; the first hit wins.
REASONS = ("status_known", "status_ignored", "in_anki", "grammar_like", "not_dictionary", "basic")

TILDES = ("〜", "～", "~", "…")
BASIC_JLPT = ("N5", "N4")

# JMdict POS codes that mark a kana-only word as grammar rather than a
# content word (particles, conjunctions, set phrases, suffixes, ...). Any
# code starting with "aux" also counts.
GRAMMAR_POS = frozenset(
    {"prt", "conj", "exp", "int", "cop", "ctr", "suf", "n-suf", "pref", "n-pref"}
)


def _grammar_like(item: dict[str, Any]) -> bool:
    headword = (item.get("headword") or "").strip()
    if any(t in headword for t in TILDES):
        return True
    if not store._all_kana(headword):
        return False
    return any(p in GRAMMAR_POS or p.startswith("aux") for p in item.get("pos") or [])


def assess(
    item: dict[str, Any],
    anki: dict[str, Any] | None,
    wk_burned: bool = False,
) -> str | None:
    """None for a candidate, else the first exclusion reason.

    ``wk_burned`` is accepted for the call site's convenience but does not
    exclude: burned WaniKani words are shown with a badge, not hidden.
    """
    status = item.get("status") or "unreviewed"
    if status == "known":
        return "status_known"
    if status == "ignored":
        return "status_ignored"
    if anki and anki.get("match") in ("exact", "stem", "entry"):
        return "in_anki"
    if _grammar_like(item):
        return "grammar_like"
    if item.get("jmdict_seq") is None:
        return "not_dictionary"
    if (item.get("classifications") or {}).get("jlpt") in BASIC_JLPT:
        return "basic"
    return None


def _has_vocab_list_sighting(item: dict[str, Any], chapter_id: str | None) -> bool:
    return any(
        s.get("source") == "vocab_list" and (not chapter_id or s.get("chapter_id") == chapter_id)
        for s in item.get("sightings") or []
    )


def order_key(item: dict[str, Any], chapter_id: str | None) -> tuple:
    """Shortlist order: frequency rank, halved for words from a vocab list
    (in the chapter being viewed, if any). Unranked items come last, vocab-list
    ones first, then by reading. Fully deterministic."""
    rank = (item.get("classifications") or {}).get("freq_rank")
    listed = _has_vocab_list_sighting(item, chapter_id)
    tie = (item.get("reading") or "", item.get("headword") or "", item.get("id") or "")
    if isinstance(rank, (int, float)) and rank > 0:
        return (0, rank / 2 if listed else rank, *tie)
    return (1, 0 if listed else 1, *tie)
