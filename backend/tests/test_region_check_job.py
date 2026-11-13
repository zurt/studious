"""Job-level behaviour of the region check: it runs after a region
transcription and can never fail it."""
from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image

from app.jobs import JobManager
from app.providers import registry
from app.services import storage
from tests.test_region_check import GOOD, _doc, _region, _Vlm


class _TranscribingVlm(_Vlm):
    def transcribe(self, image_bytes, prompt, config):
        return registry.TranscriptionResult(
            markdown="問題です。", raw="raw", meta={"model": config.get("model", "m")}
        )


async def _run_region_job(d: str, c: str, region: dict) -> dict:
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "transcribe_region",
                "doc_id": d,
                "chapter_id": c,
                "region_id": region["id"],
                "page": 1,
                "bbox": [0, 0, 1, 1],
                "engine": "vlm",
                "provider": "anthropic",
                "config": {"model": "mock-model"},
                "prompt": "P",
            }
        )
        for _ in range(100):
            await asyncio.sleep(0.05)
            cur = storage.load_job(job["id"])
            if cur and cur.get("status") in {"completed", "failed"}:
                return cur
    finally:
        await mgr.stop()
    raise AssertionError("job did not finish")


def _with_page_image(d: str) -> None:
    path: Path = storage.page_image_path(d, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (255, 255, 255)).save(path)


async def test_failing_check_does_not_fail_transcription_job(isolated_data_dir, tmp_path):
    registry.register_vlm("anthropic", lambda: _TranscribingVlm(raise_exc=RuntimeError("check down")))
    d, c = _doc(tmp_path)
    _with_page_image(d)
    r = _region(d, c, text=None)
    final = await _run_region_job(d, c, r)
    assert final["status"] == "completed"
    saved = storage.load_region(d, c, r["id"])
    assert saved["transcription_md"] == "問題です。"
    assert "check" not in saved


async def test_transcription_job_stores_check(isolated_data_dir, tmp_path):
    registry.register_vlm("anthropic", lambda: _TranscribingVlm(tool_input=GOOD))
    d, c = _doc(tmp_path)
    _with_page_image(d)
    r = _region(d, c, text=None)
    final = await _run_region_job(d, c, r)
    assert final["status"] == "completed"
    saved = storage.load_region(d, c, r["id"])
    assert saved["check"]["transcribed_at"] == saved["transcribed_at"]
