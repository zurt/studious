from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from app.jobs import JobManager
from app.providers import registry
from app.services import llm_audit, storage


class _MockOcr:
    name = "mock"

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def info(self):
        return {"name": "mock", "kind": "ocr"}

    def transcribe(self, image_path: Path, config: dict):
        self.calls.append(image_path)
        return registry.TranscriptionResult(
            markdown=f"# page from {image_path.name}",
            raw=image_path.name,
            meta={"called": True},
        )


class _MockVlm:
    name = "mock-vlm"

    def __init__(self, *, raise_for_pages: set[int] | None = None) -> None:
        self.calls: list[tuple[bytes, str, dict]] = []
        self.raise_for_pages = raise_for_pages or set()
        self._page_counter = 0

    def info(self):
        return {"name": "mock-vlm", "kind": "vlm"}

    def transcribe(self, image_bytes: bytes, prompt: str, config: dict):
        self._page_counter += 1
        if self._page_counter in self.raise_for_pages:
            raise RuntimeError(f"boom on call {self._page_counter}")
        self.calls.append((image_bytes, prompt, config))
        return registry.TranscriptionResult(
            markdown="# transcription",
            raw="raw",
            meta={
                "model": config.get("model", "mock-model"),
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )


@pytest.fixture
def mock_ocr_provider():
    instance = _MockOcr()
    registry.register_ocr("mock", lambda: instance)
    yield instance
    # No deregister API needed; test isolation via isolated_data_dir is sufficient.


@pytest.fixture
def mock_vlm_provider():
    instance = _MockVlm()
    registry.register_vlm("mock-vlm", lambda: instance)
    yield instance


@pytest.fixture
def mock_vlm_provider_failing():
    instance = _MockVlm(raise_for_pages={1})
    registry.register_vlm("mock-vlm-fail", lambda: instance)
    yield instance


def _make_doc_with_pages(n_pages: int) -> dict:
    # Use a tiny synthetic PDF via Pillow -> PIL doesn't write PDFs with multiple
    # pages easily, so synthesize the on-disk layout directly.
    import tempfile

    # We need a real "original" file path because create_document moves it.
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


async def test_sequential_job_runs_each_page(isolated_data_dir, mock_ocr_provider):
    meta = _make_doc_with_pages(3)
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "ocr",
                "provider": "mock",
                "pages": [1, 2, 3],
                "config": {},
                "prompt": None,
                "overwrite": False,
                "current_page": None,
            }
        )
        # Poll until completed.
        for _ in range(50):
            await asyncio.sleep(0.05)
            current = storage.load_job(job["id"])
            if current and current.get("status") in {"completed", "completed_with_errors", "failed"}:
                break
        assert current is not None
        assert current["status"] == "completed"
        for p in (1, 2, 3):
            t = storage.load_transcription(meta["id"], p)
            assert t is not None
            assert t["markdown"].startswith("# page from")
        assert len(mock_ocr_provider.calls) == 3
    finally:
        await mgr.stop()


async def test_vlm_job_writes_llm_audit_log(isolated_data_dir, mock_vlm_provider):
    meta = _make_doc_with_pages(2)
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "vlm",
                "provider": "mock-vlm",
                "pages": [1, 2],
                "config": {"model": "mock-model"},
                "prompt": "transcribe please",
                "overwrite": False,
                "current_page": None,
            }
        )
        for _ in range(50):
            await asyncio.sleep(0.05)
            current = storage.load_job(job["id"])
            if current and current.get("status", "").startswith("completed"):
                break
        assert current["status"] == "completed"
    finally:
        await mgr.stop()

    entries = llm_audit.read_all()
    assert len(entries) == 2
    for entry, expected_page in zip(entries, [1, 2]):
        assert entry["provider"] == "mock-vlm"
        assert entry["model"] == "mock-model"
        assert entry["job_type"] == "transcribe_pages"
        assert entry["status"] == "success"
        assert entry["error"] is None
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 50
        assert entry["doc_id"] == meta["id"]
        assert entry["page"] == expected_page
        assert entry["job_id"] == job["id"]
        assert isinstance(entry["duration_ms"], int)


async def test_vlm_job_audit_log_records_failures(isolated_data_dir, mock_vlm_provider_failing):
    meta = _make_doc_with_pages(1)
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "vlm",
                "provider": "mock-vlm-fail",
                "pages": [1],
                "config": {"model": "mock-model"},
                "prompt": "transcribe",
                "overwrite": False,
                "current_page": None,
            }
        )
        for _ in range(50):
            await asyncio.sleep(0.05)
            current = storage.load_job(job["id"])
            if current and current.get("status", "").startswith("completed"):
                break
    finally:
        await mgr.stop()

    entries = llm_audit.read_all()
    assert len(entries) == 1
    assert entries[0]["status"] == "error"
    assert "boom" in entries[0]["error"]
    assert entries[0]["job_type"] == "transcribe_pages"
    assert entries[0]["model"] == "mock-model"
    assert entries[0]["input_tokens"] is None


async def test_ocr_job_does_not_write_audit_log(isolated_data_dir, mock_ocr_provider):
    meta = _make_doc_with_pages(1)
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "ocr",
                "provider": "mock",
                "pages": [1],
                "config": {},
                "prompt": None,
                "overwrite": False,
                "current_page": None,
            }
        )
        for _ in range(50):
            await asyncio.sleep(0.05)
            current = storage.load_job(job["id"])
            if current and current.get("status", "").startswith("completed"):
                break
    finally:
        await mgr.stop()

    assert llm_audit.read_all() == []


async def test_overwrite_false_skips_existing(isolated_data_dir, mock_ocr_provider):
    meta = _make_doc_with_pages(2)
    storage.save_transcription(
        meta["id"],
        1,
        {"page": 1, "engine": "ocr", "provider": "x", "markdown": "preexisting", "raw": "",
         "tokens": [], "annotations": {}, "meta": {}, "created_at": "", "duration_ms": 0},
    )
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "ocr",
                "provider": "mock",
                "pages": [1, 2],
                "config": {},
                "prompt": None,
                "overwrite": False,
                "current_page": None,
            }
        )
        for _ in range(50):
            await asyncio.sleep(0.05)
            current = storage.load_job(job["id"])
            if current and current.get("status", "").startswith("completed"):
                break
        # Page 1 should still hold the preexisting markdown.
        t1 = storage.load_transcription(meta["id"], 1)
        assert t1["markdown"] == "preexisting"
        t2 = storage.load_transcription(meta["id"], 2)
        assert t2["markdown"].startswith("# page from")
    finally:
        await mgr.stop()
