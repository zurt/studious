"""Background card clips: the pending list, drain, kick, the job hooks and the catch-up endpoint."""
from __future__ import annotations

import json
import threading

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.providers import registry
from app.services import say_remote, speech_queue, storage, store, tts
from tests.test_harvest import _BreakdownVlm
from tests.test_say_remote_engine import _item

client = TestClient(app)


@pytest.fixture
def inline(monkeypatch):
    """kick() runs the drain on the calling thread."""
    monkeypatch.setattr(speech_queue, "_start_thread", lambda fn: fn())


def _words(n: int) -> list[str]:
    return [store.create_item("vocab", headword=w, reading=w, meaning="m")["id"] for w in ("犬", "猫", "鳥", "魚", "馬")[:n]]


def _pending() -> list[str]:
    return json.loads(speech_queue.pending_path().read_text(encoding="utf-8"))


# ---------- the list ----------


class TestPendingList:
    def test_enqueue_keeps_order_and_drops_duplicates(self, isolated_data_dir):
        assert speech_queue.enqueue(["a", "b", "a"]) == 2
        assert speech_queue.enqueue(["c", "b"]) == 1
        assert _pending() == ["a", "b", "c"] and speech_queue.pending_count() == 3
        assert not list(speech_queue.pending_path().parent.glob("*.tmp"))

    def test_empty_and_corrupt_files(self, isolated_data_dir):
        assert speech_queue.pending_count() == 0
        speech_queue.pending_path().parent.mkdir(parents=True)
        speech_queue.pending_path().write_text("{not json", encoding="utf-8")
        assert speech_queue.pending_count() == 0
        assert speech_queue.enqueue(["a"]) == 1

    def test_enqueue_region(self, isolated_data_dir):
        a = store.create_item("vocab", headword="犬", reading="いぬ", meaning="m")
        b = store.create_item("vocab", headword="猫", reading="ねこ", meaning="m")
        gone = store.create_item("vocab", headword="鳥", reading="とり", meaning="m")
        sight = {"doc_id": "d", "chapter_id": "c", "region_id": "r", "source": "breakdown"}
        store.update_item("vocab", a["id"], sightings=[sight])
        store.update_item("vocab", b["id"], sightings=[{**sight, "region_id": "other"}])
        store.update_item("vocab", gone["id"], sightings=[sight])
        store.delete_item("vocab", gone["id"])
        assert speech_queue.enqueue_region("d", "c", "r") == 1
        assert _pending() == [a["id"]]

    def test_enqueue_all_skips_deleted(self, isolated_data_dir):
        ids = _words(3)
        store.delete_item("vocab", ids[1])
        assert speech_queue.enqueue_all() == 2
        assert set(_pending()) == {ids[0], ids[2]}

    def test_pregenerate_off_disables_the_automatic_callers_only(self, isolated_data_dir, monkeypatch):
        monkeypatch.setenv("STUDIOUS_TTS_PREGENERATE", "0")
        config.get_settings.cache_clear()
        ids = _words(2)
        assert speech_queue.enqueue(ids) == 0
        assert speech_queue.enqueue_all() == 0
        assert speech_queue.enqueue_region("d", "c", "r") == 0
        assert speech_queue.kick() is False
        assert speech_queue.enqueue(ids, manual=True) == 2
        assert speech_queue.kick(manual=True) is True


# ---------- drain ----------


class TestDrain:
    def test_makes_the_clips_and_empties_the_list(self, mac):
        ids = _words(2)
        speech_queue.enqueue(ids)
        out = speech_queue.drain()
        assert out == {"running": False, "made": 2, "cached": 0, "failed": 0, "remaining": 0, "unavailable": False}
        assert _pending() == [] and len(mac.say_calls) == 2

    def test_word_and_sentence_clips_and_already_cached(self, mac):
        item = _item(example={"sentence": "犬がいる。", "surface": "犬", "furigana": "犬[いぬ]がいる。", "gloss": "A dog."})
        tts.synthesize("犬", "いぬ", seed="犬")
        speech_queue.enqueue([item["id"]])
        out = speech_queue.drain()
        assert (out["made"], out["cached"]) == (1, 1)
        # the word was cached (and counted as such), only the sentence was made
        assert [t for _, t in mac.say_calls][-1:] == ["犬がいる。"] and len(mac.say_calls) == 2

    def test_stops_when_unavailable_and_keeps_the_rest(self, mac):
        ids = _words(3)
        speech_queue.enqueue(ids)
        mac.up = False
        tts.reset_cache()
        out = speech_queue.drain()
        assert out["unavailable"] is True and out["remaining"] == 3 and _pending() == ids

    def test_mac_goes_away_mid_drain(self, mac, monkeypatch):
        ids = _words(3)
        speech_queue.enqueue(ids)
        real = mac.__call__
        seen = []

        def flaky(req, timeout):
            if req.full_url.endswith("/say"):
                seen.append(1)
                if len(seen) == 2:
                    mac.up = False
            return real(req, timeout)

        monkeypatch.setattr(say_remote, "_open", flaky)
        out = speech_queue.drain()
        assert out["made"] == 1 and out["unavailable"] is True
        assert _pending() == ids[1:]

    def test_a_failed_clip_does_not_block_the_list(self, mac, caplog):
        ids = _words(2)
        mac.fail_voices = set(tts.pick_voices(["Kyoko (Enhanced)", "O-Ren (Enhanced)", "Otoya (Enhanced)"], "犬")) | {"Kyoko"}
        long = store.create_item("vocab", headword="あ" * 250, reading="あ", meaning="m")
        speech_queue.enqueue([long["id"], *ids])
        with caplog.at_level("WARNING", logger="studious.speech_queue"):
            out = speech_queue.drain()
        assert out["failed"] >= 2 and out["remaining"] == 0 and _pending() == []
        assert any(r.getMessage() == "speech_queue_clip_failed" for r in caplog.records)

    def test_deleted_and_missing_items_are_dropped(self, mac):
        ids = _words(2)
        store.delete_item("vocab", ids[0])
        speech_queue.enqueue([ids[0], "no-such-id", ids[1]])
        out = speech_queue.drain()
        assert out["made"] == 1 and out["remaining"] == 0

    def test_an_item_with_no_clips_is_dropped(self, mac):
        item = store.create_item("vocab", headword="(", reading="", meaning="m")
        speech_queue.enqueue([item["id"]])
        assert speech_queue.drain()["remaining"] == 0

    def test_unavailable_engine_leaves_the_list_alone(self, isolated_data_dir):
        speech_queue.enqueue(["a", "b"])
        out = speech_queue.drain()
        assert out["unavailable"] is True and _pending() == ["a", "b"]

    def test_only_one_drain_at_a_time(self, mac, monkeypatch):
        ids = _words(1)
        speech_queue.enqueue(ids)
        gate, entered = threading.Event(), threading.Event()
        real = mac.__call__

        def slow(req, timeout):
            if req.full_url.endswith("/say"):
                entered.set()
                gate.wait(5)
            return real(req, timeout)

        monkeypatch.setattr(say_remote, "_open", slow)
        first: list = []
        t = threading.Thread(target=lambda: first.append(speech_queue.drain()))
        t.start()
        assert entered.wait(5)
        second = speech_queue.drain()
        assert second["running"] is True and second["made"] == 0
        assert speech_queue.kick() is False
        gate.set()
        t.join(5)
        assert first[0]["made"] == 1

    def test_logs_the_counts(self, mac, caplog):
        speech_queue.enqueue(_words(1))
        with caplog.at_level("INFO", logger="studious.speech_queue"):
            speech_queue.drain()
        rec = next(r for r in caplog.records if r.getMessage() == "speech_queue_drained")
        assert rec.made == 1 and rec.remaining == 0


class TestKick:
    def test_starts_a_thread_only_when_something_is_waiting(self, isolated_data_dir, monkeypatch):
        started = []
        monkeypatch.setattr(speech_queue, "_start_thread", started.append)
        assert speech_queue.kick() is False and started == []
        speech_queue.enqueue(["a"])
        assert speech_queue.kick() is True and started == [speech_queue.drain]

    def test_never_raises(self, isolated_data_dir, monkeypatch):
        speech_queue.enqueue(["a"])

        def boom(fn):
            raise RuntimeError("no threads")

        monkeypatch.setattr(speech_queue, "_start_thread", boom)
        assert speech_queue.kick() is False

    def test_the_real_starter_makes_a_daemon_thread(self):
        ran: list[bool] = []
        done = threading.Event()

        def target():
            ran.append(threading.current_thread().daemon)
            done.set()

        speech_queue._spawn(target)
        assert done.wait(5) and ran == [True]


# ---------- hooks ----------


class TestJobHooks:
    async def _vocab_list_job(self):
        from app.jobs import JobManager
        from tests.test_harvest import _make_doc, _VocabListVlm, _wait_for_terminal

        registry.register_vlm("mock-vocab-vlm", lambda: _VocabListVlm())
        meta = _make_doc()
        ch = storage.create_chapter(meta["id"], title="Ch", page_start=1, page_end=1)
        region = storage.create_region(meta["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="vocab_list")
        mgr = JobManager()
        await mgr.start()
        try:
            job = mgr.submit(
                {
                    "job_type": "transcribe_region", "doc_id": meta["id"], "chapter_id": ch["id"],
                    "region_id": region["id"], "page": 1, "bbox": [0, 0, 1, 1], "engine": "vlm",
                    "provider": "mock-vocab-vlm", "config": {"model": "mock-model"}, "prompt": "P",
                }
            )
            return await _wait_for_terminal(job["id"])
        finally:
            await mgr.stop()

    async def _breakdown_job(self):
        from app.jobs import JobManager
        from tests.test_harvest import _make_doc, _wait_for_terminal

        registry.register_vlm("mock-breakdown-harvest-vlm", lambda: _BreakdownVlm())
        meta = _make_doc()
        ch = storage.create_chapter(meta["id"], title="Ch", page_start=1, page_end=1)
        region = storage.create_region(meta["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage")
        storage.update_region(meta["id"], ch["id"], region["id"], transcription_md="本文です。")
        mgr = JobManager()
        await mgr.start()
        try:
            job = mgr.submit(
                {
                    "job_type": "breakdown_region", "doc_id": meta["id"], "chapter_id": ch["id"],
                    "region_id": region["id"], "engine": "vlm", "provider": "mock-breakdown-harvest-vlm",
                    "config": {"model": "mock-model"}, "prompt": "P", "tool_name": "record_breakdown",
                    "tool_schema": {"type": "object"},
                }
            )
            return await _wait_for_terminal(job["id"])
        finally:
            await mgr.stop()

    async def test_vocab_list_transcription_enqueues_and_kicks(self, isolated_data_dir, monkeypatch):
        started = []
        monkeypatch.setattr(speech_queue, "_start_thread", started.append)
        final = await self._vocab_list_job()
        assert final["status"] == "completed"
        headwords = {store.get_item("vocab", i)["headword"] for i in _pending()}
        assert headwords == {"国民", "〜によって"}
        assert started == [speech_queue.drain]

    async def test_breakdown_enqueues_and_kicks(self, isolated_data_dir, monkeypatch):
        started = []
        monkeypatch.setattr(speech_queue, "_start_thread", started.append)
        final = await self._breakdown_job()
        assert final["status"] == "completed"
        assert {store.get_item("vocab", i)["headword"] for i in _pending()} == {"口べた"}
        assert started == [speech_queue.drain]

    async def test_nothing_is_queued_with_pregenerate_off(self, isolated_data_dir, monkeypatch):
        monkeypatch.setenv("STUDIOUS_TTS_PREGENERATE", "0")
        config.get_settings.cache_clear()
        started = []
        monkeypatch.setattr(speech_queue, "_start_thread", started.append)
        assert (await self._vocab_list_job())["status"] == "completed"
        assert (await self._breakdown_job())["status"] == "completed"
        assert not speech_queue.pending_path().exists() and started == []

    async def test_a_queue_failure_never_fails_the_job(self, isolated_data_dir, monkeypatch, caplog):
        def boom(*a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(speech_queue, "enqueue_region", boom)
        with caplog.at_level("ERROR"):
            assert (await self._vocab_list_job())["status"] == "completed"
            assert (await self._breakdown_job())["status"] == "completed"
        assert sum(r.getMessage() == "speech_queue_enqueue_error" for r in caplog.records) == 2


# ---------- endpoint ----------


class TestCatchUpEndpoint:
    def test_reports_pending_and_availability(self, isolated_data_dir):
        speech_queue.enqueue(["a"])
        d = client.post("/api/tts/catch-up").json()
        assert d["pending"] == 1 and d["available"] is False and "macOS" in d["reason"]

    def test_all_queues_every_item_even_when_pregenerate_is_off(self, isolated_data_dir, monkeypatch):
        monkeypatch.setenv("STUDIOUS_TTS_PREGENERATE", "0")
        config.get_settings.cache_clear()
        ids = _words(3)
        d = client.post("/api/tts/catch-up", json={"all": True}).json()
        assert d["pending"] == 3 and set(_pending()) == set(ids)

    def test_starts_a_drain_and_returns_at_once(self, mac, inline):
        ids = _words(2)
        d = client.post("/api/tts/catch-up", json={"all": True}).json()
        # inline runs the drain before the response is built
        assert d["available"] is True and d["pending"] == 0 and len(mac.say_calls) == 2
        assert set(ids)

    def test_unavailable_keeps_the_list(self, mac, inline):
        _words(2)
        mac.up = False
        tts.reset_cache()
        d = client.post("/api/tts/catch-up", json={"all": True}).json()
        assert d["pending"] == 2 and d["available"] is False and "make say-helper" in d["reason"]


class TestExamplesRequeue:
    def test_removing_an_example_requeues_the_item(self, isolated_data_dir):
        item = _item(example={"sentence": "犬がいる。", "surface": "犬", "furigana": "犬[いぬ]がいる。", "gloss": "x"})
        assert client.delete(f"/api/vocab/{item['id']}/example").status_code == 200
        assert _pending() == [item["id"]]

    def test_generating_requeues_generated_items_only(self, isolated_data_dir, monkeypatch):
        from app.services import examples

        monkeypatch.setattr(
            examples,
            "generate_examples",
            lambda ids, force=False: {"items": [{"id": "a", "status": "generated"}, {"id": "b", "status": "kept"}]},
        )
        assert client.post("/api/vocab/examples", json={"item_ids": ["a", "b"]}).status_code == 200
        assert _pending() == ["a"]


def test_periodic_task_kicks(isolated_data_dir, monkeypatch):
    import asyncio

    kicks: list[int] = []
    monkeypatch.setattr(speech_queue, "STARTUP_DELAY_SECONDS", 0)
    monkeypatch.setattr(speech_queue, "CATCH_UP_SECONDS", 0.01)
    monkeypatch.setattr(speech_queue, "kick", lambda **k: kicks.append(1) or False)

    async def run():
        task = asyncio.create_task(speech_queue.periodic())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert len(kicks) >= 2

