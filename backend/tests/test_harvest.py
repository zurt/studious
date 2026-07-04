from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from PIL import Image

from app.jobs import JobManager
from app.providers import registry
from app.services import harvest, storage, store

VOCAB_LIST_MD = """\
【📖】読む前に（p. 28）

1 国民（こくみん）the people; nation
(4) 口べた（くちべた）poor speaker
（前文）関わる（かかわる）to be involved
〜によって　by means of; according to

■ 内容を確認しよう（p. 31）
1．（p. 33）
読む前に　準備しましょう
"""


class TestParseVocabListMarkdown:
    def test_parses_reading_entries_and_strips_indices(self):
        entries = harvest.parse_vocab_list_markdown(VOCAB_LIST_MD)
        by_hw = {e["headword"]: e for e in entries}
        assert set(by_hw) == {"国民", "口べた", "関わる", "〜によって"}
        assert by_hw["国民"]["reading"] == "こくみん"
        assert by_hw["国民"]["meaning"] == "the people; nation"
        assert by_hw["関わる"]["reading"] == "かかわる"

    def test_kana_entry_without_reading(self):
        entries = harvest.parse_vocab_list_markdown("〜カ国　~ countries")
        assert entries == [
            {
                "headword": "〜カ国",
                "reading": "",
                "meaning": "~ countries",
                "line_index": 0,
                "line": "〜カ国　~ countries",
            }
        ]

    def test_section_headers_and_blanks_skipped(self):
        md = "【📖】読む前に（p. 28）\n\n■ 内容（p. 31）\n1．（p. 33）\n"
        assert harvest.parse_vocab_list_markdown(md) == []

    def test_japanese_only_line_with_ideographic_space_skipped(self):
        # Looks like a kana entry but the "gloss" is Japanese — a header.
        assert harvest.parse_vocab_list_markdown("読む前に　準備しましょう") == []

    def test_half_width_parens_accepted(self):
        entries = harvest.parse_vocab_list_markdown("犬(いぬ)dog")
        assert entries[0]["headword"] == "犬"
        assert entries[0]["reading"] == "いぬ"

    def test_bullet_markers_stripped(self):
        # The prompt forbids bullets but models occasionally emit them.
        entries = harvest.parse_vocab_list_markdown("- 勉強（べんきょう）study\n* 犬（いぬ）dog")
        assert [e["headword"] for e in entries] == ["勉強", "犬"]

    def test_page_reference_parens_not_a_reading(self):
        # Parenthesized non-kana content must not parse as a reading.
        assert harvest.parse_vocab_list_markdown("読む前に（p. 28）") == []

    def test_line_index_preserved(self):
        entries = harvest.parse_vocab_list_markdown(VOCAB_LIST_MD)
        by_hw = {e["headword"]: e for e in entries}
        assert by_hw["国民"]["line_index"] == 2
        assert by_hw["〜によって"]["line_index"] == 5


def _make_doc(n_pages: int = 1) -> dict:
    fd, p = tempfile.mkstemp(suffix=".pdf")
    Path(p).write_bytes(b"%PDF-1.4 dummy")
    meta = storage.create_document(
        name="dummy.pdf", source_type="pdf", page_count=n_pages, original_path=Path(p)
    )
    pages_dir = storage.document_dir(meta["id"]) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_pages + 1):
        Image.new("RGB", (32, 32), (255, 255, 255)).save(pages_dir / f"{i:04d}.png")
    return meta


BREAKDOWN = {
    "sentences": [
        {
            "text": "口べたで料理好きの父親。",
            "gloss": "A father who is bad at speaking but loves cooking.",
            "vocab": [{"word": "口べた", "reading": "くちべた", "meaning": "poor speaker"}],
            "grammar": [],
        },
        {
            "text": "天候に関わらず行われる。",
            "gloss": "Held regardless of the weather.",
            "vocab": [],
            "grammar": [
                {
                    "pattern": "〜に関わらず",
                    "explanation": "regardless of",
                    "surfaces": ["に関わらず"],
                }
            ],
        },
    ]
}


class TestIngest:
    def test_ingest_vocab_list_region(self, isolated_data_dir: Path):
        meta = _make_doc()
        ch = storage.create_chapter(meta["id"], title="Ch", page_start=1, page_end=1)
        region = storage.create_region(
            meta["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="vocab_list"
        )
        region = storage.update_region(
            meta["id"], ch["id"], region["id"], transcription_md=VOCAB_LIST_MD
        )
        result = harvest.ingest_vocab_list_region(meta["id"], ch["id"], region)
        assert result["created"] == 4
        items = store.list_items("vocab")
        assert {i["headword"] for i in items} == {"国民", "口べた", "関わる", "〜によって"}
        s = next(i for i in items if i["headword"] == "国民")["sightings"][0]
        assert s["source"] == "vocab_list"
        assert s["chapter_id"] == ch["id"]
        assert s["sentence_text"].startswith("1 国民")

    def test_ingest_breakdown(self, isolated_data_dir: Path):
        result = harvest.ingest_breakdown("d1", "c1", "r1", BREAKDOWN)
        assert result["vocab"]["created"] == 1
        assert result["grammar"]["created"] == 1
        gram = store.list_items("grammar")[0]
        assert gram["pattern"] == "〜に関わらず"
        assert gram["sightings"][0]["surface"] == "に関わらず"
        assert gram["sightings"][0]["sentence_index"] == 1

    def test_breakdown_and_vocab_list_dedup_on_reading(self, isolated_data_dir: Path):
        harvest.ingest_breakdown("d1", "c1", "r1", BREAKDOWN)
        region = {"id": "r2", "transcription_md": "口べた（くちべた）poor speaker"}
        harvest.ingest_vocab_list_region("d1", "c1", region)
        items = store.list_items("vocab")
        assert len(items) == 1
        assert {s["source"] for s in items[0]["sightings"]} == {"breakdown", "vocab_list"}

    def test_backfill_is_idempotent(self, isolated_data_dir: Path):
        meta = _make_doc()
        ch = storage.create_chapter(meta["id"], title="Ch", page_start=1, page_end=1)
        vocab_region = storage.create_region(
            meta["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="vocab_list"
        )
        storage.update_region(
            meta["id"], ch["id"], vocab_region["id"], transcription_md=VOCAB_LIST_MD
        )
        passage = storage.create_region(
            meta["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
        )
        storage.save_breakdown(meta["id"], ch["id"], passage["id"], dict(BREAKDOWN))

        totals = harvest.backfill()
        assert totals["vocab_list_regions"] == 1
        assert totals["breakdowns"] == 1
        # 4 from the list; the breakdown's 口べた dedups onto the list entry.
        assert totals["vocab_created"] == 4
        assert totals["grammar_created"] == 1
        kuchibeta = next(
            i for i in store.list_items("vocab") if i["headword"] == "口べた"
        )
        assert {s["source"] for s in kuchibeta["sightings"]} == {"breakdown", "vocab_list"}

        again = harvest.backfill()
        assert again["vocab_created"] == 0
        assert again["grammar_created"] == 0
        assert len(store.list_items("vocab")) == 4
        assert len(store.list_items("grammar")) == 1


class _VocabListVlm:
    name = "mock-vocab-vlm"

    def info(self):
        return {"name": self.name, "kind": "vlm"}

    def transcribe(self, image_bytes, prompt, config):
        return registry.TranscriptionResult(
            markdown="国民（こくみん）the people  \n〜によって　by means of  \n",
            raw="",
            meta={"model": "mock-model", "usage": {"input_tokens": 1, "output_tokens": 1}},
        )


class _BreakdownVlm:
    name = "mock-breakdown-harvest-vlm"

    def info(self):
        return {"name": self.name, "kind": "vlm"}

    def call_tool(self, prompt, tool_name, tool_schema, config):
        return registry.ToolCallResult(
            tool_input={"sentences": [dict(s) for s in BREAKDOWN["sentences"]]},
            meta={"model": "mock-model", "usage": {"input_tokens": 1, "output_tokens": 1}},
        )


async def _wait_for_terminal(job_id: str, timeout: float = 5.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)
        cur = storage.load_job(job_id)
        if cur and cur.get("status") in {"completed", "completed_with_errors", "failed"}:
            return cur
    raise AssertionError(f"job {job_id} did not finish")


async def test_region_job_on_vocab_list_harvests_store(isolated_data_dir):
    registry.register_vlm("mock-vocab-vlm", lambda: _VocabListVlm())
    meta = _make_doc()
    ch = storage.create_chapter(meta["id"], title="Ch", page_start=1, page_end=1)
    region = storage.create_region(
        meta["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="vocab_list"
    )
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "transcribe_region",
                "doc_id": meta["id"],
                "chapter_id": ch["id"],
                "region_id": region["id"],
                "page": 1,
                "bbox": [0, 0, 1, 1],
                "engine": "vlm",
                "provider": "mock-vocab-vlm",
                "config": {"model": "mock-model"},
                "prompt": "P",
            }
        )
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "completed"
    items = store.list_items("vocab")
    assert {i["headword"] for i in items} == {"国民", "〜によって"}
    assert all(s["source"] == "vocab_list" for i in items for s in i["sightings"])


async def test_breakdown_job_harvests_store(isolated_data_dir):
    registry.register_vlm("mock-breakdown-harvest-vlm", lambda: _BreakdownVlm())
    meta = _make_doc()
    ch = storage.create_chapter(meta["id"], title="Ch", page_start=1, page_end=1)
    region = storage.create_region(
        meta["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    storage.update_region(
        meta["id"], ch["id"], region["id"], transcription_md="本文です。"
    )
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "breakdown_region",
                "doc_id": meta["id"],
                "chapter_id": ch["id"],
                "region_id": region["id"],
                "engine": "vlm",
                "provider": "mock-breakdown-harvest-vlm",
                "config": {"model": "mock-model"},
                "prompt": "P",
                "tool_name": "record_breakdown",
                "tool_schema": {"type": "object"},
            }
        )
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "completed"
    assert {i["headword"] for i in store.list_items("vocab")} == {"口べた"}
    assert {i["pattern"] for i in store.list_items("grammar")} == {"〜に関わらず"}
