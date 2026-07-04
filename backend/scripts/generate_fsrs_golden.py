"""Generate golden fixtures for the Swift FSRS/queue port.

The iOS companion re-derives SRS state by replaying the review-event log
through its own FSRS-4.5 implementation (docs/cloudkit-sync-plan.md), so
the Swift port must match this backend bit-for-bit. This script replays
deterministic review sequences through ``app.services.srs`` and snapshots
the expected per-step state, plus a ``build_queue`` snapshot over a
synthetic store, into the Swift test fixtures:

    apple/StudiousKit/Sources/studious-tests/Fixtures/

Rerun after any change to ``app/services/srs.py`` and commit the output:

    cd backend && uv run python scripts/generate_fsrs_golden.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
FIXTURES = (
    BACKEND.parent / "apple" / "StudiousKit" / "Sources" / "studious-tests" / "Fixtures"
)
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)

sys.path.insert(0, str(BACKEND))
# Point the backend at a scratch data dir before importing app.config.
_tmp = tempfile.mkdtemp(prefix="studious-golden-")
os.environ["STUDIOUS_DATA_DIR"] = _tmp

from app.services import srs  # noqa: E402
from app.services.srs import CardState, apply_review, interval_days  # noqa: E402


def snapshot(state: CardState) -> dict:
    return {
        "reps": state.reps,
        "lapses": state.lapses,
        "stability": state.stability,
        "difficulty": state.difficulty,
        "last_grade": state.last_grade,
        "due_epoch": srs._parse_ts(state.due).timestamp() if state.due else None,
        "interval_days": interval_days(state.stability) if state.stability is not None else None,
    }


def run_case(name: str, reviews: list[tuple[int, datetime]]) -> dict:
    state = CardState()
    steps = []
    for grade, ts in reviews:
        state = apply_review(state, grade, ts)
        steps.append(snapshot(state))
    return {
        "name": name,
        "reviews": [{"grade": g, "ts": ts.isoformat()} for g, ts in reviews],
        "expected": steps,
    }


def at_due_chain(name: str, first_grade: int, grades: list[int]) -> dict:
    """Review exactly when the card comes due, like a diligent student."""
    reviews = [(first_grade, BASE)]
    state = apply_review(CardState(), first_grade, BASE)
    for grade in grades:
        ts = srs._parse_ts(state.due)
        reviews.append((grade, ts))
        state = apply_review(state, grade, ts)
    return run_case(name, reviews)


def fsrs_cases() -> list[dict]:
    cases = []
    for grade in srs.GRADES:
        cases.append(run_case(f"single_grade_{grade}", [(grade, BASE)]))

    cases.append(at_due_chain("good_chain_at_due", 3, [3] * 12))
    cases.append(at_due_chain("hard_chain_at_due", 2, [2] * 10))
    cases.append(at_due_chain("easy_chain_at_due", 4, [4] * 10))
    cases.append(at_due_chain("mixed_with_lapses_at_due", 3, [3, 1, 3, 2, 1, 4, 3, 3]))

    # Fixed offsets (days from BASE), including same-day relearn steps and
    # reviews long past due.
    fixed = [
        ("cram_same_day", [(3, 0.0), (1, 0.001), (1, 0.008), (3, 0.01), (4, 0.02)]),
        ("zero_elapsed_repeat", [(4, 0.0), (4, 0.0), (3, 0.0)]),
        ("very_late_reviews", [(3, 0.0), (3, 60.0), (3, 400.0), (4, 3000.0)]),
        ("lapse_after_long_gap", [(4, 0.0), (1, 250.0), (3, 250.007), (3, 251.0)]),
    ]
    for name, spec in fixed:
        cases.append(
            run_case(name, [(g, BASE + timedelta(days=offset)) for g, offset in spec])
        )

    # Seeded random walk: broad coverage of the state space.
    rng = random.Random(42)
    ts = BASE
    reviews = []
    for _ in range(200):
        reviews.append((rng.choice(srs.GRADES), ts))
        ts = ts + timedelta(days=rng.uniform(0.0007, 90.0))
    cases.append(run_case("random_walk_seed42", reviews))
    return cases


NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _vocab(id_, headword, reading, meaning, status, *, priority=None, created=None,
           sentence=None, deleted=False):
    created_at = _iso(created or BASE)
    sightings = []
    if sentence is not None:
        sightings.append(
            {
                "doc_id": "docgold", "chapter_id": "chgold", "region_id": "rgold",
                "sentence_index": 0, "surface": headword,
                "sentence_text": sentence, "source": "breakdown",
                "seen_at": created_at,
            }
        )
    return {
        "id": id_, "headword": headword, "reading": reading, "meaning": meaning,
        "meaning_source": "llm", "pos": [], "jmdict_seq": None, "status": status,
        "classifications": {}, "priority_group": priority, "sightings": sightings,
        "links": {}, "notes": "", "created_at": created_at,
        "updated_at": created_at, "deleted": deleted,
    }


def _grammar(id_, pattern, explanation, status, *, created=None, deleted=False):
    created_at = _iso(created or BASE)
    return {
        "id": id_, "pattern": pattern, "pattern_normalized": pattern,
        "explanation": explanation, "status": status, "classifications": {},
        "sightings": [], "links": {}, "notes": "", "created_at": created_at,
        "updated_at": created_at, "deleted": deleted,
    }


def _review(id_, item_id, kind, card_type, grade, ts):
    return {
        "id": id_, "item_id": item_id, "kind": kind, "card_type": card_type,
        "grade": grade, "ts": _iso(ts), "elapsed_ms": 1500,
    }


def queue_fixture() -> dict:
    day = timedelta(days=1)
    vocab = [
        _vocab("v1", "勉強", "べんきょう", "study", "active", priority=1,
               created=BASE + 4 * day, sentence="私は日本語を勉強しています。"),
        _vocab("v2", "先生", "せんせい", "teacher", "active",
               created=BASE + 10 * day),
        _vocab("v3", "図書館", "としょかん", "library", "active", priority=2,
               created=BASE + 2 * day,
               sentence="図書館で本を読みながら、静かな午後を過ごしました。"),
        _vocab("v4", "水", "みず", "water", "known", created=BASE),
        _vocab("v5", "犬", "いぬ", "dog", "unreviewed", created=BASE + day),
        _vocab("v6", "猫", "ねこ", "cat", "active", created=BASE + 3 * day,
               deleted=True),
        _vocab("v7", "本", "ほん", "book", "active", priority=1,
               created=BASE + 5 * day, sentence="   "),
    ]
    grammar = [
        _grammar("g1", "〜ながら", "while doing", "active", created=BASE + 6 * day),
        _grammar("g2", "〜そうです", "hearsay", "active", created=BASE + 7 * day),
        _grammar("g3", "〜まま", "as is", "ignored", created=BASE + 8 * day),
    ]
    reviews = [
        # v1 word card: reviewed long ago -> overdue at NOW.
        _review("r1", "v1", "vocab", "word", 3, BASE + 20 * day),
        # v3 word card: reviewed with Easy recently -> due far in future.
        _review("r2", "v3", "vocab", "word", 4, NOW - 2 * day),
        # v3 context card: overdue, and *more* overdue than v1's word card.
        _review("r3", "v3", "vocab", "context", 3, BASE + 10 * day),
        # g1 pattern card: relearn step earlier today -> due before NOW.
        _review("r4", "g1", "grammar", "pattern", 1, NOW - timedelta(hours=2)),
        # v4 is 'known': its events must not surface in the queue.
        _review("r5", "v4", "vocab", "word", 3, BASE + 20 * day),
    ]

    data_dir = Path(_tmp)
    store_dir = data_dir / "store"
    store_dir.mkdir(parents=True, exist_ok=True)
    with open(store_dir / "vocab.jsonl", "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in vocab)
    with open(store_dir / "grammar.jsonl", "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in grammar)
    with open(store_dir / "reviews.jsonl", "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in reviews)

    cases = []
    for limit, new_limit in [(50, 10), (3, 2), (5, 0), (50, 1)]:
        queue = srs.build_queue(limit=limit, new_limit=new_limit, now=NOW)
        cases.append(
            {
                "limit": limit,
                "new_limit": new_limit,
                "counts": queue["counts"],
                "expected": [
                    {
                        "kind": c["kind"],
                        "item_id": c["item_id"],
                        "card_type": c["card_type"],
                        "seen": c["state"]["reps"] > 0,
                    }
                    for c in queue["cards"]
                ],
            }
        )
    return {
        "now": _iso(NOW),
        "store": {"vocab": vocab, "grammar": grammar, "reviews": reviews},
        "cases": cases,
    }


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    fsrs_path = FIXTURES / "fsrs_golden.json"
    fsrs_path.write_text(
        json.dumps({"cases": fsrs_cases()}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    queue_path = FIXTURES / "queue_golden.json"
    queue_path.write_text(
        json.dumps(queue_fixture(), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {fsrs_path}")
    print(f"wrote {queue_path}")


if __name__ == "__main__":
    main()
