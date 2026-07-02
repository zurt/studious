from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import srs, store

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


class TestScheduler:
    def test_first_review_seeds_state_from_weights(self):
        state = srs.apply_review(srs.CardState(), 3, NOW)
        assert state.reps == 1
        assert state.lapses == 0
        assert state.stability == pytest.approx(srs.W[2])
        assert 1.0 <= state.difficulty <= 10.0
        # At retention 0.9, interval == stability (rounded, min 1 day).
        assert srs.interval_days(state.stability) == round(srs.W[2])

    def test_easy_first_review_gets_longer_interval_than_hard(self):
        hard = srs.apply_review(srs.CardState(), 2, NOW)
        easy = srs.apply_review(srs.CardState(), 4, NOW)
        assert easy.stability > hard.stability
        assert srs.interval_days(easy.stability) > srs.interval_days(hard.stability)

    def test_good_reviews_grow_stability(self):
        state = srs.apply_review(srs.CardState(), 3, NOW)
        first = state.stability
        later = NOW + timedelta(days=srs.interval_days(first))
        state = srs.apply_review(state, 3, later)
        assert state.stability > first
        assert state.reps == 2

    def test_again_lapses_and_schedules_relearn_step(self):
        state = srs.apply_review(srs.CardState(), 3, NOW)
        later = NOW + timedelta(days=5)
        failed = srs.apply_review(state, 1, later)
        assert failed.lapses == 1
        assert failed.stability <= state.stability
        due = datetime.fromisoformat(failed.due)
        assert due == later + timedelta(minutes=srs.RELEARN_MINUTES)

    def test_difficulty_clamped_after_many_extremes(self):
        state = srs.CardState()
        ts = NOW
        for _ in range(20):
            state = srs.apply_review(state, 1, ts)
            ts += timedelta(days=1)
        assert 1.0 <= state.difficulty <= 10.0
        for _ in range(20):
            state = srs.apply_review(state, 4, ts)
            ts += timedelta(days=srs.interval_days(state.stability))
        assert 1.0 <= state.difficulty <= 10.0

    def test_retrievability_decays(self):
        assert srs.retrievability(0, 10) == pytest.approx(1.0)
        assert srs.retrievability(10, 10) == pytest.approx(0.9)
        assert srs.retrievability(100, 10) < 0.9

    def test_invalid_grade_rejected(self):
        with pytest.raises(ValueError):
            srs.apply_review(srs.CardState(), 0, NOW)
        with pytest.raises(ValueError):
            srs.apply_review(srs.CardState(), 5, NOW)


class TestEventLog:
    def test_record_review_appends_and_replays(self, isolated_data_dir: Path):
        state = srs.record_review(
            kind="vocab", item_id="i1", card_type="word", grade=3, elapsed_ms=1200
        )
        assert state.reps == 1
        lines = srs.reviews_path().read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["item_id"] == "i1"
        assert event["grade"] == 3
        assert event["elapsed_ms"] == 1200
        # Replay from disk matches the returned state.
        assert srs.card_state("vocab", "i1", "word").as_dict() == state.as_dict()

    def test_cards_scheduled_independently(self, isolated_data_dir: Path):
        srs.record_review(kind="vocab", item_id="i1", card_type="word", grade=3)
        srs.record_review(kind="vocab", item_id="i1", card_type="context", grade=1)
        assert srs.card_state("vocab", "i1", "word").lapses == 0
        assert srs.card_state("vocab", "i1", "context").lapses == 1

    def test_record_review_validates(self, isolated_data_dir: Path):
        with pytest.raises(ValueError):
            srs.record_review(kind="vocab", item_id="i1", card_type="pattern", grade=3)
        with pytest.raises(ValueError):
            srs.record_review(kind="bogus", item_id="i1", card_type="word", grade=3)
        with pytest.raises(ValueError):
            srs.record_review(kind="vocab", item_id="i1", card_type="word", grade=7)

    def test_malformed_lines_skipped(self, isolated_data_dir: Path):
        srs.record_review(kind="vocab", item_id="i1", card_type="word", grade=3)
        with open(srs.reviews_path(), "a", encoding="utf-8") as fh:
            fh.write("not json\n")
        assert srs.card_state("vocab", "i1", "word").reps == 1


def _seed_item(headword="口べた", reading="くちべた", sentence="口べたで料理好きの父親。", **over):
    entry = {
        "headword": headword,
        "reading": reading,
        "meaning": "poor speaker",
        "sentence_index": 0,
        "surface": headword,
        "sentence_text": sentence,
    }
    entry.update(over)
    store.replace_region_sightings(
        "vocab",
        doc_id="d1",
        chapter_id="c1",
        region_id=f"r-{headword}",
        source="breakdown",
        entries=[entry],
    )
    item = store.build_index("vocab")[store.vocab_key(headword, reading)]
    return store.get_item("vocab", item)


class TestQueue:
    def test_only_active_items_enter_queue(self, isolated_data_dir: Path):
        _seed_item()  # stays unreviewed
        queue = srs.build_queue()
        assert queue["cards"] == []
        assert queue["counts"] == {"due": 0, "new": 0, "active_items": 0}

    def test_new_cards_word_before_context(self, isolated_data_dir: Path):
        item = _seed_item()
        store.update_item("vocab", item["id"], status="active")
        queue = srs.build_queue()
        assert [c["card_type"] for c in queue["cards"]] == ["word", "context"]
        assert queue["counts"] == {"due": 0, "new": 2, "active_items": 1}
        assert queue["cards"][1]["sighting"]["sentence_text"] == "口べたで料理好きの父親。"

    def test_no_context_card_without_sentence(self, isolated_data_dir: Path):
        item = _seed_item(sentence="")
        store.update_item("vocab", item["id"], status="active")
        queue = srs.build_queue()
        assert [c["card_type"] for c in queue["cards"]] == ["word"]

    def test_due_cards_come_before_new(self, isolated_data_dir: Path):
        reviewed = _seed_item()
        fresh = _seed_item(headword="猫", reading="ねこ", sentence="猫がいる。")
        store.update_item("vocab", reviewed["id"], status="active")
        store.update_item("vocab", fresh["id"], status="active")
        past = datetime.now(timezone.utc) - timedelta(days=30)
        srs.record_review(
            kind="vocab", item_id=reviewed["id"], card_type="word", grade=3, ts=past
        )
        queue = srs.build_queue()
        assert queue["counts"]["due"] == 1
        first = queue["cards"][0]
        assert first["item_id"] == reviewed["id"]
        assert first["card_type"] == "word"
        assert first["state"]["reps"] == 1

    def test_new_limit_respected(self, isolated_data_dir: Path):
        item = _seed_item()
        store.update_item("vocab", item["id"], status="active")
        queue = srs.build_queue(new_limit=1)
        assert len(queue["cards"]) == 1
        assert queue["counts"]["new"] == 2

    def test_grammar_pattern_cards(self, isolated_data_dir: Path):
        store.replace_region_sightings(
            "grammar",
            doc_id="d1",
            chapter_id="c1",
            region_id="r1",
            source="breakdown",
            entries=[
                {
                    "pattern": "〜に関わらず",
                    "explanation": "regardless of",
                    "sentence_index": 0,
                    "surface": "に関わらず",
                    "sentence_text": "天候に関わらず行う。",
                }
            ],
        )
        gid = store.build_index("grammar")[(store.normalize_pattern("〜に関わらず"),)]
        store.update_item("grammar", gid, status="active")
        queue = srs.build_queue()
        assert [c["card_type"] for c in queue["cards"]] == ["pattern"]
        assert queue["cards"][0]["item"]["pattern"] == "〜に関わらず"
