from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from app.jobs import JobManager
from app.providers import registry
from app.services import storage


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


@pytest.fixture
def mock_ocr_provider():
    instance = _MockOcr()
    registry.register_ocr("mock", lambda: instance)
    yield instance
    # No deregister API needed; test isolation via isolated_data_dir is sufficient.


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
