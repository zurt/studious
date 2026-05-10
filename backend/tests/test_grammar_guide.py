from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobManager
from app.main import app
from app.providers import registry
from app.services import grammar_guide, storage


def _make_doc(tmp_path: Path) -> dict:
    src = tmp_path / "fake.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    return storage.create_document(
        name="fake.pdf", source_type="pdf", page_count=10, original_path=src
    )


def _grammar_chapter(doc_id: str, *, transcribe_all: bool = True) -> tuple[str, list[str]]:
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)
    region_ids: list[str] = []
    for i, body in enumerate(["〜ばかりで body", "〜ば〜ほど body"]):
        r = storage.create_region(
            doc_id, ch["id"], page=i + 1, bbox=[0, 0, 1, 1], tag="grammar_points"
        )
        region_ids.append(r["id"])
        if transcribe_all:
            storage.update_region(
                doc_id, ch["id"], r["id"],
                transcription_md=body,
                transcribed_at=f"2026-05-09T0{i}:00:00Z",
            )
    return ch["id"], region_ids


def test_prepare_source_concatenates_transcriptions(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch_id, _ = _grammar_chapter(doc["id"])
    text, regions = grammar_guide.prepare_source(doc["id"], ch_id)
    assert "〜ばかりで body" in text
    assert "〜ば〜ほど body" in text
    assert "---" in text
    assert len(regions) == 2


def test_prepare_source_raises_on_no_grammar(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=2)
    storage.create_region(
        doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    with pytest.raises(grammar_guide.NoGrammarRegionsError):
        grammar_guide.prepare_source(doc["id"], ch["id"])


def test_prepare_source_raises_on_untranscribed(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch_id, ids = _grammar_chapter(doc["id"], transcribe_all=False)
    with pytest.raises(grammar_guide.UntranscribedRegionsError) as e:
        grammar_guide.prepare_source(doc["id"], ch_id)
    assert set(e.value.region_ids) == set(ids)


def test_get_grammar_guide_404_when_absent(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch_id, _ = _grammar_chapter(doc["id"])
    client = TestClient(app)
    r = client.get(f"/api/documents/{doc['id']}/chapters/{ch_id}/grammar-guide")
    assert r.status_code == 404


def test_post_grammar_guide_400_on_no_grammar_regions(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=2)
    client = TestClient(app)
    r = client.post(f"/api/documents/{doc['id']}/chapters/{ch['id']}/grammar-guide")
    assert r.status_code == 400


def test_post_grammar_guide_409_on_untranscribed(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch_id, _ = _grammar_chapter(doc["id"], transcribe_all=False)
    client = TestClient(app)
    r = client.post(f"/api/documents/{doc['id']}/chapters/{ch_id}/grammar-guide")
    assert r.status_code == 409


def test_post_grammar_guide_409_when_exists_without_overwrite(
    isolated_data_dir, tmp_path: Path
):
    doc = _make_doc(tmp_path)
    ch_id, _ = _grammar_chapter(doc["id"])
    storage.save_grammar_guide(doc["id"], ch_id, {"points": [{"title": "x", "sections": []}]})
    client = TestClient(app)
    r = client.post(f"/api/documents/{doc['id']}/chapters/{ch_id}/grammar-guide")
    assert r.status_code == 409
    r = client.post(
        f"/api/documents/{doc['id']}/chapters/{ch_id}/grammar-guide",
        json={"overwrite": True},
    )
    assert r.status_code == 202
    job = storage.load_job(r.json()["job_id"])
    assert job["job_type"] == "grammar_guide"
    assert job["tool_name"] == "record_grammar_guide"


def test_chapter_detail_reports_has_grammar_guide(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch_id, _ = _grammar_chapter(doc["id"])
    client = TestClient(app)
    r = client.get(f"/api/documents/{doc['id']}/chapters/{ch_id}")
    assert r.json()["has_grammar_guide"] is False
    storage.save_grammar_guide(doc["id"], ch_id, {"points": [{"title": "x", "sections": []}]})
    r = client.get(f"/api/documents/{doc['id']}/chapters/{ch_id}")
    assert r.json()["has_grammar_guide"] is True


def test_get_guide_marks_stale_when_source_changes(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch_id, ids = _grammar_chapter(doc["id"])
    fp = grammar_guide.fingerprint(grammar_guide.grammar_regions(doc["id"], ch_id))
    storage.save_grammar_guide(
        doc["id"], ch_id, {"points": [{"title": "x", "sections": []}], "source_fingerprint": fp}
    )
    client = TestClient(app)
    r = client.get(f"/api/documents/{doc['id']}/chapters/{ch_id}/grammar-guide")
    assert r.json()["is_stale"] is False
    storage.update_region(
        doc["id"], ch_id, ids[0], transcribed_at="2026-05-09T99:00:00Z"
    )
    r = client.get(f"/api/documents/{doc['id']}/chapters/{ch_id}/grammar-guide")
    assert r.json()["is_stale"] is True


class _MockGuideVlm:
    name = "mock-guide-vlm"

    def __init__(self, *, tool_input: dict | None = None) -> None:
        self.tool_input = tool_input
        self.calls: list[tuple[str, str, dict, dict]] = []

    def info(self):
        return {"name": self.name, "kind": "vlm"}

    def transcribe(self, *a, **kw):
        raise NotImplementedError

    def call_tool(self, prompt, tool_name, tool_schema, config):
        self.calls.append((prompt, tool_name, tool_schema, config))
        return registry.ToolCallResult(
            tool_input=self.tool_input or {},
            meta={
                "model": config.get("model", "mock-model"),
                "request_id": "req_gg_1",
                "prompt_hash": "abc",
                "image_bytes": 0,
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )


async def _wait_for_terminal(job_id: str, timeout: float = 5.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)
        cur = storage.load_job(job_id)
        if cur and cur.get("status") in {"completed", "completed_with_errors", "failed"}:
            return cur
    raise AssertionError(f"job {job_id} did not finish")


async def test_grammar_guide_job_happy_path(isolated_data_dir, tmp_path: Path):
    points = [
        {
            "title": "〜ばかりで",
            "subtitle": "Only X, and (negative)",
            "sections": [
                {"heading": "Meaning", "body_md": "Nothing but X..."},
                {"heading": "Examples", "body_md": "- 文句ばかりで何もしない。"},
            ],
        }
    ]
    mock = _MockGuideVlm(tool_input={"intro": "Chapter overview", "points": points})
    registry.register_vlm("anthropic", lambda: mock)

    doc = _make_doc(tmp_path)
    ch_id, _ = _grammar_chapter(doc["id"])

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit({
            "job_type": "grammar_guide",
            "doc_id": doc["id"],
            "chapter_id": ch_id,
            "engine": "vlm",
            "provider": "anthropic",
            "config": {"model": "mock-model"},
            "prompt": "GG_PROMPT",
            "tool_name": "record_grammar_guide",
            "tool_schema": {"type": "object"},
        })
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "completed"
    saved = storage.load_grammar_guide(doc["id"], ch_id)
    assert saved is not None
    assert saved["points"] == points
    assert saved["intro"] == "Chapter overview"
    assert saved["model"] == "mock-model"
    assert len(saved["source_fingerprint"]) == 2
    assert mock.calls
    sent_prompt = mock.calls[0][0]
    assert "〜ばかりで body" in sent_prompt
    assert "〜ば〜ほど body" in sent_prompt
    assert "GG_PROMPT" in sent_prompt


async def test_grammar_guide_job_fails_on_empty_points(isolated_data_dir, tmp_path: Path):
    mock = _MockGuideVlm(tool_input={"points": []})
    registry.register_vlm("anthropic", lambda: mock)

    doc = _make_doc(tmp_path)
    ch_id, _ = _grammar_chapter(doc["id"])

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit({
            "job_type": "grammar_guide",
            "doc_id": doc["id"],
            "chapter_id": ch_id,
            "provider": "anthropic",
            "config": {"model": "mock-model"},
            "prompt": "P",
            "tool_name": "record_grammar_guide",
            "tool_schema": {"type": "object"},
        })
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "failed"
    assert "points" in final["errors"][0]["message"]
    assert storage.load_grammar_guide(doc["id"], ch_id) is None


async def test_grammar_guide_job_fails_when_untranscribed(isolated_data_dir, tmp_path: Path):
    mock = _MockGuideVlm(tool_input={"points": [{"title": "x", "sections": [{"heading":"h","body_md":"b"}]}]})
    registry.register_vlm("anthropic", lambda: mock)

    doc = _make_doc(tmp_path)
    ch_id, _ = _grammar_chapter(doc["id"], transcribe_all=False)

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit({
            "job_type": "grammar_guide",
            "doc_id": doc["id"],
            "chapter_id": ch_id,
            "provider": "anthropic",
            "config": {"model": "mock-model"},
            "prompt": "P",
            "tool_name": "record_grammar_guide",
            "tool_schema": {"type": "object"},
        })
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "failed"
    assert mock.calls == []
