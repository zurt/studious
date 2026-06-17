from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from app.jobs import JobManager
from app.middleware import correlation_id_var
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


async def test_submit_captures_caller_correlation_id(isolated_data_dir, mock_vlm_provider):
    """Phase 1.6 #2: a job's audit log carries the request's correlation id,
    not the empty default that the worker task would otherwise see."""
    meta = _make_doc_with_pages(1)
    mgr = JobManager()
    await mgr.start()
    token = correlation_id_var.set("trace_xyz")
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "vlm",
                "provider": "mock-vlm",
                "pages": [1],
                "config": {"model": "mock-model"},
                "prompt": "hi",
                "overwrite": False,
                "current_page": None,
            }
        )
        # The CID should be persisted on the job payload immediately.
        persisted = storage.load_job(job["id"])
        assert persisted["correlation_id"] == "trace_xyz"
        for _ in range(50):
            await asyncio.sleep(0.05)
            current = storage.load_job(job["id"])
            if current and current.get("status", "").startswith("completed"):
                break
    finally:
        correlation_id_var.reset(token)
        await mgr.stop()

    entries = llm_audit.read_all()
    assert len(entries) == 1
    assert entries[0]["correlation_id"] == "trace_xyz"


class _MockVlmWithProvenance:
    name = "mock-vlm-prov"

    def info(self):
        return {"name": "mock-vlm-prov", "kind": "vlm"}

    def transcribe(self, image_bytes: bytes, prompt: str, config: dict):
        return registry.TranscriptionResult(
            markdown="ok",
            raw="ok",
            meta={
                "model": config.get("model") or "mock-model",
                "request_id": "req_test_123",
                "prompt_hash": "abc12345",
                "image_bytes": len(image_bytes),
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 2,
                    "cache_creation_input_tokens": 0,
                },
            },
        )


async def test_audit_log_captures_provider_provenance(isolated_data_dir):
    """Phase 1.6 #4: the audit log gains request_id, prompt_hash, image_bytes,
    and cache token fields from the provider's `result.meta`."""
    registry.register_vlm("mock-vlm-prov", lambda: _MockVlmWithProvenance())
    meta = _make_doc_with_pages(1)
    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "doc_id": meta["id"],
                "engine": "vlm",
                "provider": "mock-vlm-prov",
                "pages": [1],
                "config": {"model": "mock-model"},
                "prompt": "hi",
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
    e = entries[0]
    assert e["request_id"] == "req_test_123"
    assert e["prompt_hash"] == "abc12345"
    assert e["image_bytes"] > 0
    assert e["cache_read_tokens"] == 2
    assert e["cache_creation_tokens"] == 0


class _MockBreakdownVlm:
    """Mock VLM that satisfies the call_tool protocol for breakdown jobs."""

    name = "mock-breakdown-vlm"

    def __init__(
        self,
        *,
        tool_input: dict | None = None,
        raise_exc: Exception | None = None,
        stop_reason: str | None = None,
        responses: list[dict] | None = None,
    ) -> None:
        self.tool_input = tool_input
        self.raise_exc = raise_exc
        self.stop_reason = stop_reason
        # Optional per-call script: list of {"tool_input": ..., "stop_reason": ...}.
        # Consumed by call index; the last entry repeats once exhausted. Lets a
        # test drive retry behaviour (e.g. malformed then well-formed).
        self.responses = responses
        self.calls: list[tuple[str, str, dict, dict]] = []

    def info(self):
        return {"name": self.name, "kind": "vlm"}

    def transcribe(self, image_bytes, prompt, config):
        raise NotImplementedError

    def call_tool(self, prompt, tool_name, tool_schema, config):
        self.calls.append((prompt, tool_name, tool_schema, config))
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.responses:
            scripted = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
            tool_input = scripted.get("tool_input") or {}
            stop_reason = scripted.get("stop_reason")
        else:
            tool_input = self.tool_input or {}
            stop_reason = self.stop_reason
        return registry.ToolCallResult(
            tool_input=tool_input,
            meta={
                "model": config.get("model", "mock-model"),
                "request_id": "req_breakdown_1",
                "prompt_hash": "deadbeef",
                "image_bytes": 0,
                "stop_reason": stop_reason,
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 80,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
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


def _make_region_with_transcription(doc_id: str) -> tuple[str, str]:
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=1)
    region = storage.create_region(
        doc_id, ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    storage.update_region(
        doc_id, ch["id"], region["id"], transcription_md="口べたで料理好きの父親。"
    )
    return ch["id"], region["id"]


async def test_breakdown_job_happy_path(isolated_data_dir):
    sentences = [
        {
            "text": "口べたで料理好きの父親。",
            "vocab": [{"word": "口べた", "reading": "くちべた", "meaning": "poor speaker"}],
            "grammar": [],
            "gloss": "A father who is bad at speaking but loves cooking.",
        }
    ]
    mock = _MockBreakdownVlm(tool_input={"sentences": sentences})
    registry.register_vlm("mock-breakdown-vlm", lambda: mock)

    meta = _make_doc_with_pages(1)
    chapter_id, region_id = _make_region_with_transcription(meta["id"])

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "breakdown_region",
                "doc_id": meta["id"],
                "chapter_id": chapter_id,
                "region_id": region_id,
                "engine": "vlm",
                "provider": "mock-breakdown-vlm",
                "config": {"model": "mock-model"},
                "prompt": "BREAKDOWN_PROMPT",
                "tool_name": "record_breakdown",
                "tool_schema": {"type": "object"},
            }
        )
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "completed"
    saved = storage.load_breakdown(meta["id"], chapter_id, region_id)
    assert saved is not None
    assert saved["sentences"] == sentences
    assert saved["model"] == "mock-model"

    # The prompt sent to the provider should embed the transcription.
    assert mock.calls, "provider was not called"
    sent_prompt = mock.calls[0][0]
    assert "口べたで料理好きの父親。" in sent_prompt
    assert "BREAKDOWN_PROMPT" in sent_prompt

    entries = llm_audit.read_all()
    assert len(entries) == 1
    e = entries[0]
    assert e["job_type"] == "breakdown_region"
    assert e["status"] == "success"
    assert e["region_id"] == region_id
    assert e["chapter_id"] == chapter_id
    assert e["input_tokens"] == 200


async def test_breakdown_job_fails_on_malformed_tool_response(isolated_data_dir):
    mock = _MockBreakdownVlm(tool_input={"sentences": []})  # empty list → fail
    registry.register_vlm("mock-breakdown-bad", lambda: mock)

    meta = _make_doc_with_pages(1)
    chapter_id, region_id = _make_region_with_transcription(meta["id"])

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "breakdown_region",
                "doc_id": meta["id"],
                "chapter_id": chapter_id,
                "region_id": region_id,
                "provider": "mock-breakdown-bad",
                "config": {"model": "mock-model"},
                "prompt": "P",
                "tool_name": "record_breakdown",
                "tool_schema": {"type": "object"},
            }
        )
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "failed"
    assert "sentences" in final["errors"][0]["message"]
    assert storage.load_breakdown(meta["id"], chapter_id, region_id) is None
    entries = llm_audit.read_all()
    assert entries and entries[0]["status"] == "error"
    assert entries[0]["job_type"] == "breakdown_region"


async def test_exercise_completion_job_reports_truncation_at_max_tokens(isolated_data_dir):
    # Partial tool input (no `answer`/`examples`) + stop_reason=max_tokens is the
    # truncation signature; the error must say so rather than the generic
    # "missing" message. See docs/troubleshooting.md.
    mock = _MockBreakdownVlm(tool_input={"explanation": "cut off"}, stop_reason="max_tokens")
    registry.register_vlm("mock-exercise-trunc", lambda: mock)

    meta = _make_doc_with_pages(1)
    chapter_id, region_id = _make_region_with_transcription(meta["id"])

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "exercise_completion",
                "doc_id": meta["id"],
                "chapter_id": chapter_id,
                "region_id": region_id,
                "sentence_index": 0,
                "sentence_text": "1. 私は学校＿＿行く。",
                "region_transcription": "口べたで料理好きの父親。",
                "engine": "vlm",
                "provider": "mock-exercise-trunc",
                "config": {"model": "mock-model", "max_tokens": 8192},
                "prompt": "EXERCISE_COMPLETION_PROMPT",
                "tool_name": "record_exercise_completion",
                "tool_schema": {"type": "object"},
            }
        )
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "failed"
    assert "truncated at max_tokens" in final["errors"][0]["message"]
    # Truncation is not retried — a resend with the same budget can't help.
    assert len(mock.calls) == 1
    entries = llm_audit.read_all()
    assert entries and entries[0]["status"] == "error"
    assert entries[0]["job_type"] == "exercise_completion"


_VALID_COMPLETION = {
    "answer": "1. 私は学校に行く。",
    "answer_english": "I go to school.",
    "explanation": "に marks the destination.",
    "examples": [
        {"japanese": "1. 私は学校に行く。", "reading": "わたしはがっこうにいく。", "english": "I go to school.", "explanation": "natural"},
        {"japanese": "1. 私は学校へ行く。", "reading": "わたしはがっこうへいく。", "english": "I head to school.", "explanation": "へ variant"},
        {"japanese": "1. 私は学校まで行く。", "reading": "わたしはがっこうまでいく。", "english": "I go as far as school.", "explanation": "まで variant"},
    ],
}


async def test_exercise_completion_job_retries_malformed_then_succeeds(isolated_data_dir):
    # A clean-stop response missing `answer`/`examples` (not truncation) is the
    # intermittent failure mode; one retry recovers it.
    mock = _MockBreakdownVlm(
        responses=[
            {"tool_input": {"explanation": "oops, no answer"}, "stop_reason": "tool_use"},
            {"tool_input": _VALID_COMPLETION, "stop_reason": "tool_use"},
        ]
    )
    registry.register_vlm("mock-exercise-retry-ok", lambda: mock)

    meta = _make_doc_with_pages(1)
    chapter_id, region_id = _make_region_with_transcription(meta["id"])

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "exercise_completion",
                "doc_id": meta["id"],
                "chapter_id": chapter_id,
                "region_id": region_id,
                "sentence_index": 0,
                "sentence_text": "1. 私は学校＿＿行く。",
                "region_transcription": "口べたで料理好きの父親。",
                "engine": "vlm",
                "provider": "mock-exercise-retry-ok",
                "config": {"model": "mock-model", "max_tokens": 8192},
                "prompt": "EXERCISE_COMPLETION_PROMPT",
                "tool_name": "record_exercise_completion",
                "tool_schema": {"type": "object"},
            }
        )
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "completed"
    assert len(mock.calls) == 2  # one retry
    saved = storage.load_exercise_completion(meta["id"], chapter_id, region_id)
    assert saved["completions"]["0"]["answer"] == _VALID_COMPLETION["answer"]
    # Both attempts are billed → both audited (first error, then success).
    entries = llm_audit.read_all()
    assert [e["status"] for e in entries] == ["error", "success"]


async def test_exercise_completion_job_fails_after_retry_exhausted(isolated_data_dir):
    # Malformed on every attempt → fail with the generic message after retrying.
    mock = _MockBreakdownVlm(tool_input={"explanation": "still no answer"}, stop_reason="tool_use")
    registry.register_vlm("mock-exercise-retry-bad", lambda: mock)

    meta = _make_doc_with_pages(1)
    chapter_id, region_id = _make_region_with_transcription(meta["id"])

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "exercise_completion",
                "doc_id": meta["id"],
                "chapter_id": chapter_id,
                "region_id": region_id,
                "sentence_index": 0,
                "sentence_text": "1. 私は学校＿＿行く。",
                "region_transcription": "口べたで料理好きの父親。",
                "engine": "vlm",
                "provider": "mock-exercise-retry-bad",
                "config": {"model": "mock-model", "max_tokens": 8192},
                "prompt": "EXERCISE_COMPLETION_PROMPT",
                "tool_name": "record_exercise_completion",
                "tool_schema": {"type": "object"},
            }
        )
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "failed"
    assert "missing `answer` or `examples`" in final["errors"][0]["message"]
    assert len(mock.calls) == 2  # initial attempt + one retry, then give up
    entries = llm_audit.read_all()
    assert [e["status"] for e in entries] == ["error", "error"]


async def test_breakdown_job_fails_when_region_has_no_transcription(isolated_data_dir):
    mock = _MockBreakdownVlm(tool_input={"sentences": [{"text": "x", "gloss": "y"}]})
    registry.register_vlm("mock-breakdown-notx", lambda: mock)

    meta = _make_doc_with_pages(1)
    ch = storage.create_chapter(meta["id"], title="Ch", page_start=1, page_end=1)
    region = storage.create_region(
        meta["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    # Note: no transcription_md set.

    mgr = JobManager()
    await mgr.start()
    try:
        job = mgr.submit(
            {
                "job_type": "breakdown_region",
                "doc_id": meta["id"],
                "chapter_id": ch["id"],
                "region_id": region["id"],
                "provider": "mock-breakdown-notx",
                "config": {"model": "mock-model"},
                "prompt": "P",
                "tool_name": "record_breakdown",
                "tool_schema": {"type": "object"},
            }
        )
        final = await _wait_for_terminal(job["id"])
    finally:
        await mgr.stop()

    assert final["status"] == "failed"
    assert "no transcription" in final["errors"][0]["message"]
    assert mock.calls == []  # provider never called


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
