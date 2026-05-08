from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from app.jobs import JobManager
from app.providers import registry
from app.services import storage


class _MockOcr:
    name = "mock-edge"

    def info(self):
        return {"name": self.name, "kind": "ocr"}

    def transcribe(self, image_path: Path, config: dict):
        return registry.TranscriptionResult(
            markdown="# ok", raw="ok", meta={}
        )


def _make_doc(n_pages: int) -> dict:
    import tempfile
    p = Path(tempfile.mkstemp(suffix=".pdf")[1])
    p.write_bytes(b"%PDF-1.4 dummy")
    meta = storage.create_document(
        name="x.pdf", source_type="pdf", page_count=n_pages, original_path=p
    )
    pages_dir = storage.document_dir(meta["id"]) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_pages + 1):
        Image.new("RGB", (16, 16), (255, 255, 255)).save(pages_dir / f"{i:04d}.png")
    return meta


async def _wait_terminal(job_id: str, timeout: float = 3.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.03)
        cur = storage.load_job(job_id)
        if cur and cur.get("status") in {"completed", "completed_with_errors", "failed"}:
            return cur
    raise AssertionError(f"job {job_id} did not finish")


async def test_unknown_engine_marks_job_failed(isolated_data_dir):
    meta = _make_doc(1)
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit({
            "doc_id": meta["id"],
            "engine": "no-such-engine",
            "provider": "x",
            "pages": [1],
            "config": {},
            "prompt": None,
            "overwrite": False,
            "current_page": None,
        })
        final = await _wait_terminal(job["id"])
    finally:
        await mgr.stop()
    assert final["status"] == "failed"
    assert "unknown engine" in final["errors"][0]["message"]


async def test_missing_page_image_recorded_as_page_error(isolated_data_dir):
    """Per the plan, a missing page image is a per-page error and the job
    finishes with `completed_with_errors` — not `failed`."""
    registry.register_ocr("mock-edge", lambda: _MockOcr())
    meta = _make_doc(2)
    # Remove page 1 image so it's "missing".
    storage.page_image_path(meta["id"], 1).unlink()

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit({
            "doc_id": meta["id"],
            "engine": "ocr",
            "provider": "mock-edge",
            "pages": [1, 2],
            "config": {},
            "prompt": None,
            "overwrite": False,
            "current_page": None,
        })
        final = await _wait_terminal(job["id"])
    finally:
        await mgr.stop()
    assert final["status"] == "completed_with_errors"
    assert len(final["errors"]) == 1
    assert final["errors"][0]["page"] == 1
    assert "missing page image" in final["errors"][0]["message"]
    # Page 2 was still transcribed.
    assert storage.load_transcription(meta["id"], 2) is not None


async def test_subscribe_unsubscribe_lifecycle():
    """`_emit` is a no-op when there are no listeners; subscribe/unsubscribe
    add and remove queues from the listener map."""
    mgr = JobManager()
    # No listeners — emit must not raise.
    mgr._emit("job-x", {"event": "ping", "data": {}})

    q1 = mgr.subscribe("job-x")
    q2 = mgr.subscribe("job-x")
    assert len(mgr._listeners["job-x"]) == 2

    mgr._emit("job-x", {"event": "page-done", "data": {"page": 1}})
    assert q1.qsize() == 1
    assert q2.qsize() == 1

    mgr.unsubscribe("job-x", q1)
    assert mgr._listeners["job-x"] == [q2]

    mgr.unsubscribe("job-x", q2)
    # Last unsubscribe drops the key entirely.
    assert "job-x" not in mgr._listeners

    # Unsubscribing an unknown queue is a no-op.
    mgr.unsubscribe("job-x", q1)
    mgr.unsubscribe("never-existed", q1)


async def test_jobs_run_sequentially(isolated_data_dir):
    """Two jobs queued together must run one-at-a-time."""
    registry.register_ocr("mock-edge", lambda: _MockOcr())
    meta = _make_doc(1)
    mgr = JobManager()
    await mgr.start()

    started: list[str] = []
    finished: list[str] = []

    class _Tracking:
        name = "track"
        def info(self):
            return {"name": self.name, "kind": "ocr"}
        def transcribe(self, image_path, config):
            jid = config.get("_job_id", "?")
            started.append(jid)
            # Block briefly so a sequential vs parallel difference is observable.
            import time as _t
            _t.sleep(0.05)
            finished.append(jid)
            return registry.TranscriptionResult(markdown="ok", raw="ok", meta={})

    registry.register_ocr("track", lambda: _Tracking())

    try:
        j1 = mgr.submit({
            "doc_id": meta["id"], "engine": "ocr", "provider": "track",
            "pages": [1], "config": {"_job_id": "j1"}, "prompt": None,
            "overwrite": True, "current_page": None,
        })
        j2 = mgr.submit({
            "doc_id": meta["id"], "engine": "ocr", "provider": "track",
            "pages": [1], "config": {"_job_id": "j2"}, "prompt": None,
            "overwrite": True, "current_page": None,
        })
        await _wait_terminal(j1["id"])
        await _wait_terminal(j2["id"])
    finally:
        await mgr.stop()

    # j1 must fully complete before j2 starts.
    assert started == ["j1", "j2"]
    assert finished == ["j1", "j2"]
