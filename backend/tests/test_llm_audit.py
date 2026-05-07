from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image

from app.jobs import JobManager
from app.providers import registry
from app.services import llm_audit, storage


def test_record_appends_jsonl(isolated_data_dir):
    entry = llm_audit.record(
        provider="anthropic",
        model="claude-sonnet-4-6",
        job_type="transcribe_region",
        status="success",
        duration_ms=1234,
        input_tokens=100,
        output_tokens=50,
        doc_id="d1",
        chapter_id="c1",
        region_id="r1",
        page=4,
    )
    assert entry["id"].startswith("req_")
    assert entry["timestamp"]
    path = llm_audit.audit_log_path()
    assert path.exists()
    lines = path.read_text("utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["provider"] == "anthropic"
    assert parsed["model"] == "claude-sonnet-4-6"
    assert parsed["status"] == "success"
    assert parsed["duration_ms"] == 1234
    assert parsed["input_tokens"] == 100
    assert parsed["output_tokens"] == 50
    assert parsed["doc_id"] == "d1"
    assert parsed["chapter_id"] == "c1"
    assert parsed["region_id"] == "r1"
    assert parsed["page"] == 4


def test_record_multiple_appends_in_order(isolated_data_dir):
    llm_audit.record(provider="a", model="m", job_type="transcribe_pages", status="success", duration_ms=10)
    llm_audit.record(provider="b", model="m", job_type="transcribe_pages", status="error", duration_ms=20, error="boom")
    entries = llm_audit.read_all()
    assert [e["provider"] for e in entries] == ["a", "b"]
    assert entries[1]["error"] == "boom"


def test_read_all_skips_malformed_lines(isolated_data_dir):
    llm_audit.record(provider="a", model="m", job_type="transcribe_pages", status="success", duration_ms=10)
    with open(llm_audit.audit_log_path(), "a", encoding="utf-8") as fh:
        fh.write("not json at all\n")
    entries = llm_audit.read_all()
    assert len(entries) == 1


def test_read_all_empty_when_no_file(isolated_data_dir):
    assert llm_audit.read_all() == []


def test_record_writes_to_current_month_file(isolated_data_dir):
    """Phase 1.6 #12: writes go to llm_audit.YYYY-MM.jsonl."""
    llm_audit.record(provider="x", model="m", job_type="transcribe_pages", status="success", duration_ms=1)
    current = llm_audit.audit_log_path()
    assert current.exists()
    assert current.name.startswith("llm_audit.")
    assert current.name.endswith(".jsonl")
    # Must NOT have created the legacy un-rotated file.
    assert not (isolated_data_dir / "llm_audit.jsonl").exists()


def test_read_all_concatenates_legacy_and_monthly_files(isolated_data_dir):
    """Legacy llm_audit.jsonl from before rotation is still readable."""
    legacy = isolated_data_dir / "llm_audit.jsonl"
    legacy.write_text(
        json.dumps({"id": "old1", "provider": "old", "model": "m", "job_type": "transcribe_pages", "status": "success"}) + "\n",
        encoding="utf-8",
    )
    archive = isolated_data_dir / "llm_audit.2024-01.jsonl"
    archive.write_text(
        json.dumps({"id": "arch1", "provider": "arch", "model": "m", "job_type": "transcribe_pages", "status": "success"}) + "\n",
        encoding="utf-8",
    )
    llm_audit.record(provider="now", model="m", job_type="transcribe_pages", status="success", duration_ms=1)

    entries = llm_audit.read_all()
    providers = [e["provider"] for e in entries]
    assert "old" in providers
    assert "arch" in providers
    assert "now" in providers
    # Legacy entries come first.
    assert providers[0] == "old"


def test_summary_cache_round_trip(isolated_data_dir):
    cache = {"2024-01": {"total_requests": 17, "by_model": {"m": {"requests": 17}}}}
    llm_audit.save_summary_cache(cache)
    assert llm_audit.load_summary_cache() == cache


def test_summary_cache_missing_file_returns_empty(isolated_data_dir):
    assert llm_audit.load_summary_cache() == {}


def test_extract_usage_pulls_token_fields():
    meta = {
        "usage": {
            "input_tokens": 1500,
            "output_tokens": 800,
            "image_tokens": 2400,
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 50,
        }
    }
    assert llm_audit.extract_usage(meta) == {
        "input_tokens": 1500,
        "output_tokens": 800,
        "image_tokens": 2400,
        "cache_read_tokens": 100,
        "cache_creation_tokens": 50,
    }


def test_extract_usage_handles_missing():
    expected_empty = {
        "input_tokens": None,
        "output_tokens": None,
        "image_tokens": None,
        "cache_read_tokens": None,
        "cache_creation_tokens": None,
    }
    assert llm_audit.extract_usage(None) == expected_empty
    assert llm_audit.extract_usage({}) == expected_empty


def test_extract_provenance_pulls_request_metadata():
    meta = {
        "request_id": "req_abc",
        "prompt_hash": "deadbeef",
        "image_bytes": 12345,
        "stop_reason": "tool_use",
        "other": "ignored",
    }
    assert llm_audit.extract_provenance(meta) == {
        "request_id": "req_abc",
        "prompt_hash": "deadbeef",
        "image_bytes": 12345,
        "stop_reason": "tool_use",
    }


def test_extract_provenance_handles_missing():
    expected_empty = {
        "request_id": None,
        "prompt_hash": None,
        "image_bytes": None,
        "stop_reason": None,
    }
    assert llm_audit.extract_provenance(None) == expected_empty
    assert llm_audit.extract_provenance({}) == expected_empty


# ---------- Job integration tests ----------


class _MockVlm:
    name = "mockvlm"

    def __init__(self) -> None:
        self.calls: list[bytes] = []
        self.fail = False

    def info(self):
        return {"name": "mockvlm", "kind": "vlm"}

    def transcribe(self, image_bytes: bytes, prompt: str, config: dict):
        self.calls.append(image_bytes)
        if self.fail:
            raise RuntimeError("mock vlm failure")
        return registry.TranscriptionResult(
            markdown="# transcribed",
            raw="transcribed",
            meta={
                "model": config.get("model") or "mock-model",
                "usage": {"input_tokens": 42, "output_tokens": 7},
            },
        )


@pytest.fixture
def mock_vlm_provider():
    instance = _MockVlm()
    registry.register_vlm("mockvlm", lambda: instance)
    yield instance


def _make_doc_with_pages(n_pages: int) -> dict:
    import tempfile

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


async def _wait_done(mgr_job_id: str, attempts: int = 50) -> dict:
    for _ in range(attempts):
        await asyncio.sleep(0.05)
        current = storage.load_job(mgr_job_id)
        if current and current.get("status") in {"completed", "completed_with_errors", "failed"}:
            return current
    raise AssertionError(f"job {mgr_job_id} did not finish in time")


async def test_pages_vlm_job_writes_audit_entries(isolated_data_dir, mock_vlm_provider):
    meta = _make_doc_with_pages(2)
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "vlm",
                "provider": "mockvlm",
                "pages": [1, 2],
                "config": {"model": "mock-model"},
                "prompt": "hi",
                "overwrite": False,
                "current_page": None,
            }
        )
        await _wait_done(job["id"])
    finally:
        await mgr.stop()

    entries = llm_audit.read_all()
    assert len(entries) == 2
    for e in entries:
        assert e["provider"] == "mockvlm"
        assert e["model"] == "mock-model"
        assert e["job_type"] == "transcribe_pages"
        assert e["status"] == "success"
        assert e["doc_id"] == meta["id"]
        assert e["job_id"] == job["id"]
        assert e["input_tokens"] == 42
        assert e["output_tokens"] == 7
    assert {e["page"] for e in entries} == {1, 2}


async def test_pages_vlm_job_records_errors(isolated_data_dir, mock_vlm_provider):
    meta = _make_doc_with_pages(1)
    mock_vlm_provider.fail = True
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "vlm",
                "provider": "mockvlm",
                "pages": [1],
                "config": {"model": "mock-model"},
                "prompt": "hi",
                "overwrite": False,
                "current_page": None,
            }
        )
        await _wait_done(job["id"])
    finally:
        await mgr.stop()

    entries = llm_audit.read_all()
    assert len(entries) == 1
    assert entries[0]["status"] == "error"
    assert "mock vlm failure" in entries[0]["error"]
    assert entries[0]["page"] == 1


async def test_ocr_job_does_not_write_audit_entries(isolated_data_dir):
    # OCR is not an LLM call; the audit log should stay empty.
    class _MockOcr:
        name = "mockocr"

        def info(self):
            return {"name": "mockocr", "kind": "ocr"}

        def transcribe(self, image_path, config):
            return registry.TranscriptionResult(markdown="x", raw="x", meta={})

    registry.register_ocr("mockocr", _MockOcr)
    meta = _make_doc_with_pages(1)
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "ocr",
                "provider": "mockocr",
                "pages": [1],
                "config": {},
                "prompt": None,
                "overwrite": False,
                "current_page": None,
            }
        )
        await _wait_done(job["id"])
    finally:
        await mgr.stop()

    assert llm_audit.read_all() == []


async def test_region_job_writes_audit_entry(isolated_data_dir, mock_vlm_provider):
    meta = _make_doc_with_pages(1)
    chapter = storage.create_chapter(meta["id"], title="Ch1", page_start=1, page_end=1, order=0)
    region = storage.create_region(
        meta["id"],
        chapter["id"],
        page=1,
        bbox=[0.1, 0.1, 0.5, 0.5],
        tag="reading_passage",
    )
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "transcribe_region",
                "doc_id": meta["id"],
                "chapter_id": chapter["id"],
                "region_id": region["id"],
                "page": 1,
                "bbox": region["bbox"],
                "provider": "mockvlm",
                "config": {"model": "mock-model"},
                "prompt": "transcribe this region",
            }
        )
        await _wait_done(job["id"])
    finally:
        await mgr.stop()

    entries = llm_audit.read_all()
    assert len(entries) == 1
    e = entries[0]
    assert e["job_type"] == "transcribe_region"
    assert e["status"] == "success"
    assert e["doc_id"] == meta["id"]
    assert e["chapter_id"] == chapter["id"]
    assert e["region_id"] == region["id"]
    assert e["page"] == 1
    assert e["input_tokens"] == 42
    assert e["output_tokens"] == 7
