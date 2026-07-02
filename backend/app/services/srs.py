"""Built-in spaced repetition (milestone 3.4, docs/vocab-store-plan.md).

Review history is an append-only event log at ``data/store/reviews.jsonl``
(one JSON object per line, never rewritten — the same CloudKit-friendly
shape as the vocab/grammar stores). SRS state is *derived*: replaying a
card's events through the scheduler yields its stability, difficulty,
and next due date, so the log stays the single source of truth and the
scheduling formula can change without a data migration.

The scheduler is FSRS-4.5 (github.com/open-spaced-repetition), a small,
well-specified algorithm implemented here directly to avoid a package
dependency. Grades are 1=Again, 2=Hard, 3=Good, 4=Easy. Intervals target
``DESIRED_RETENTION`` (0.9, where the next interval equals the card's
stability in days); a failed card comes back after a short relearn step
the same day.

Cards are per (kind, item_id, card_type): vocab items get a ``word``
card (headword → reading/meaning) and, when a sighting carries sentence
context, a ``context`` card (sentence → meaning); grammar items get a
``pattern`` card. Each card is scheduled independently. Only items with
curation status ``active`` enter the queue — the whole point of the
curation lifecycle is that auto-ingested/known/ignored words don't.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import get_settings
from . import store

log = logging.getLogger("studious.srs")

_lock = threading.Lock()

# (mtime_ns, size) -> events grouped per card, in file (= chronological) order.
_cache: dict[str, tuple[tuple[int, int], dict[tuple[str, str, str], list[dict[str, Any]]]]] = {}

GRADES = (1, 2, 3, 4)  # Again, Hard, Good, Easy
CARD_TYPES = {"vocab": ("word", "context"), "grammar": ("pattern",)}

DESIRED_RETENTION = 0.9
MAX_INTERVAL_DAYS = 3650
RELEARN_MINUTES = 10

# FSRS-4.5 default parameters (open-spaced-repetition reference weights).
W = (
    0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031,
    1.6474, 0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2272, 2.8755,
)
_DECAY = -0.5
_FACTOR = 19 / 81


def reviews_path() -> Path:
    return get_settings().data_dir / "store" / "reviews.jsonl"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------- FSRS-4.5 ----------


def retrievability(elapsed_days: float, stability: float) -> float:
    return (1 + _FACTOR * max(elapsed_days, 0.0) / stability) ** _DECAY


def _init_stability(grade: int) -> float:
    return max(W[grade - 1], 0.1)


def _init_difficulty(grade: int) -> float:
    return min(max(W[4] - (grade - 3) * W[5], 1.0), 10.0)


def _next_difficulty(difficulty: float, grade: int) -> float:
    d = difficulty - W[6] * (grade - 3)
    d = W[7] * _init_difficulty(3) + (1 - W[7]) * d  # mean reversion
    return min(max(d, 1.0), 10.0)


def _next_stability(difficulty: float, stability: float, r: float, grade: int) -> float:
    if grade == 1:
        forget = (
            W[11]
            * difficulty ** -W[12]
            * ((stability + 1) ** W[13] - 1)
            * math.exp(W[14] * (1 - r))
        )
        return max(min(forget, stability), 0.1)
    hard_penalty = W[15] if grade == 2 else 1.0
    easy_bonus = W[16] if grade == 4 else 1.0
    grow = (
        math.exp(W[8])
        * (11 - difficulty)
        * stability ** -W[9]
        * (math.exp(W[10] * (1 - r)) - 1)
        * hard_penalty
        * easy_bonus
    )
    return max(stability * (1 + grow), 0.1)


def interval_days(stability: float) -> int:
    """Next interval at DESIRED_RETENTION, whole days, clamped to sane bounds."""
    ivl = stability / _FACTOR * (DESIRED_RETENTION ** (1 / _DECAY) - 1)
    return int(min(max(round(ivl), 1), MAX_INTERVAL_DAYS))


# ---------- State replay ----------


@dataclass
class CardState:
    reps: int = 0
    lapses: int = 0
    stability: float | None = None
    difficulty: float | None = None
    last_grade: int | None = None
    last_ts: str | None = None
    due: str | None = None

    @property
    def seen(self) -> bool:
        return self.reps > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "reps": self.reps,
            "lapses": self.lapses,
            "stability": round(self.stability, 4) if self.stability is not None else None,
            "difficulty": round(self.difficulty, 4) if self.difficulty is not None else None,
            "last_grade": self.last_grade,
            "last_ts": self.last_ts,
            "due": self.due,
            "interval_days": interval_days(self.stability) if self.stability is not None else None,
        }


def apply_review(state: CardState, grade: int, ts: datetime) -> CardState:
    """One scheduler step: fold a graded review into the card state."""
    if grade not in GRADES:
        raise ValueError(f"invalid grade: {grade!r}")
    if state.stability is None or state.difficulty is None or state.last_ts is None:
        stability = _init_stability(grade)
        difficulty = _init_difficulty(grade)
    else:
        elapsed = max((ts - _parse_ts(state.last_ts)).total_seconds() / 86400, 0.0)
        r = retrievability(elapsed, state.stability)
        stability = _next_stability(state.difficulty, state.stability, r, grade)
        difficulty = _next_difficulty(state.difficulty, grade)
    if grade == 1:
        due = ts + timedelta(minutes=RELEARN_MINUTES)
    else:
        due = ts + timedelta(days=interval_days(stability))
    return CardState(
        reps=state.reps + 1,
        lapses=state.lapses + (1 if grade == 1 else 0),
        stability=stability,
        difficulty=difficulty,
        last_grade=grade,
        last_ts=ts.isoformat(),
        due=due.isoformat(),
    )


def replay(events: Iterable[dict[str, Any]]) -> CardState:
    state = CardState()
    for event in events:
        try:
            state = apply_review(state, int(event.get("grade", 0)), _parse_ts(event["ts"]))
        except (ValueError, KeyError):
            log.warning("srs_skip_bad_event", extra={"event_id": event.get("id")})
    return state


# ---------- Event log ----------


def _card_key(event: dict[str, Any]) -> tuple[str, str, str]:
    return (event.get("kind", ""), event.get("item_id", ""), event.get("card_type", ""))


def _load_events() -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Events grouped per card in file order, cached against mtime+size."""
    path = reviews_path()
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
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("srs_skip_malformed", extra={"line": lineno})
                continue
            if isinstance(obj, dict) and obj.get("item_id"):
                grouped.setdefault(_card_key(obj), []).append(obj)
    _cache[key] = (sig, grouped)
    return grouped


def card_state(kind: str, item_id: str, card_type: str) -> CardState:
    return replay(_load_events().get((kind, item_id, card_type), []))


def record_review(
    *,
    kind: str,
    item_id: str,
    card_type: str,
    grade: int,
    elapsed_ms: int | None = None,
    ts: datetime | None = None,
) -> CardState:
    """Append one review event and return the card's new derived state."""
    if kind not in store.KINDS:
        raise ValueError(f"unknown kind: {kind!r}")
    if card_type not in CARD_TYPES[kind]:
        raise ValueError(f"unknown card_type for {kind}: {card_type!r}")
    if grade not in GRADES:
        raise ValueError(f"invalid grade: {grade!r}")
    when = ts or _now()
    event = {
        "id": uuid.uuid4().hex,
        "item_id": item_id,
        "kind": kind,
        "card_type": card_type,
        "grade": grade,
        "ts": when.isoformat(),
        "elapsed_ms": elapsed_ms,
    }
    with _lock:
        state = apply_review(card_state(kind, item_id, card_type), grade, when)
        path = reviews_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return state


# ---------- Queue ----------


def _context_sighting(item: dict[str, Any]) -> dict[str, Any] | None:
    """Best sentence-context sighting: the longest sentence gives the card
    the most to work with; breakdown sightings usually win (vocab lists
    rarely carry sentences)."""
    best = None
    for s in item.get("sightings", []):
        text = (s.get("sentence_text") or "").strip()
        if text and (best is None or len(text) > len((best.get("sentence_text") or ""))):
            best = s
    return best


def _item_cards(kind: str, item: dict[str, Any]) -> list[tuple[str, dict[str, Any] | None]]:
    if kind == "grammar":
        return [("pattern", None)]
    cards: list[tuple[str, dict[str, Any] | None]] = [("word", None)]
    context = _context_sighting(item)
    if context is not None:
        cards.append(("context", context))
    return cards


def _card_payload(
    kind: str,
    item: dict[str, Any],
    card_type: str,
    sighting: dict[str, Any] | None,
    state: CardState,
) -> dict[str, Any]:
    if kind == "vocab":
        summary = {
            "headword": item.get("headword"),
            "reading": item.get("reading"),
            "meaning": item.get("meaning"),
            "pos": item.get("pos") or [],
            "notes": item.get("notes") or "",
            "links": item.get("links") or {},
            "classifications": item.get("classifications") or {},
        }
    else:
        summary = {
            "pattern": item.get("pattern"),
            "explanation": item.get("explanation"),
            "notes": item.get("notes") or "",
            "links": item.get("links") or {},
            "classifications": item.get("classifications") or {},
        }
    return {
        "kind": kind,
        "item_id": item["id"],
        "card_type": card_type,
        "item": summary,
        "sighting": sighting,
        "state": state.as_dict(),
    }


def build_queue(
    *, limit: int = 20, new_limit: int = 10, now: datetime | None = None
) -> dict[str, Any]:
    """Due cards first (most overdue first), then unseen cards up to
    ``new_limit``, over all active items of both kinds. New vocab follows
    the dashboard's priority ordering so high-signal words are learned
    first; a brand-new item's ``word`` card enters before its ``context``
    card."""
    at = now or _now()
    events = _load_events()

    due: list[tuple[datetime, dict[str, Any]]] = []
    fresh: list[tuple[tuple, dict[str, Any]]] = []
    counts = {"due": 0, "new": 0, "active_items": 0}

    for kind in store.KINDS:
        for item in store.list_items(kind):
            if (item.get("status") or "unreviewed") != "active":
                continue
            counts["active_items"] += 1
            for order, (card_type, sighting) in enumerate(_item_cards(kind, item)):
                state = replay(events.get((kind, item["id"], card_type), []))
                if state.seen:
                    if state.due is not None and _parse_ts(state.due) <= at:
                        counts["due"] += 1
                        due.append(
                            (_parse_ts(state.due), _card_payload(kind, item, card_type, sighting, state))
                        )
                else:
                    counts["new"] += 1
                    priority = (
                        item.get("priority_group") or 9,
                        item.get("created_at") or "",
                        order,
                    )
                    fresh.append((priority, _card_payload(kind, item, card_type, sighting, state)))

    due.sort(key=lambda pair: pair[0])
    fresh.sort(key=lambda pair: pair[0])

    limit = max(1, min(limit, 200))
    new_limit = max(0, min(new_limit, limit))
    cards = [payload for _, payload in due[:limit]]
    if len(cards) < limit:
        cards.extend(payload for _, payload in fresh[: min(new_limit, limit - len(cards))])
    return {"cards": cards, "counts": counts}
