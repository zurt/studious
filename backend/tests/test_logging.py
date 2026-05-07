"""Tests for `app.middleware.StructuredFormatter` and `CorrelationMiddleware`.

These guard against regression of the allowlist behaviour fixed in Phase 1.6
(item #1 in `docs/logging-improvements.md`): every `extra={...}` field a
caller passes must end up in the emitted JSON. Adding a new log field
should not require touching the formatter.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.middleware import (
    CorrelationMiddleware,
    StructuredFormatter,
    correlation_id_var,
)


def _format(record: logging.LogRecord) -> dict:
    out = StructuredFormatter().format(record)
    return json.loads(out)


def _make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="studious.test",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_emits_valid_json_with_core_fields():
    record = _make_record()
    entry = _format(record)
    assert entry["level"] == "INFO"
    assert entry["logger"] == "studious.test"
    assert entry["msg"] == "hello"
    assert "ts" in entry
    assert "correlation_id" in entry


def test_includes_correlation_id_from_contextvar():
    token = correlation_id_var.set("abc123")
    try:
        entry = _format(_make_record())
    finally:
        correlation_id_var.reset(token)
    assert entry["correlation_id"] == "abc123"


def test_default_correlation_id_is_empty_string():
    entry = _format(_make_record())
    assert entry["correlation_id"] == ""


def test_preserves_arbitrary_extra_fields():
    """The whole point of #1: no allowlist. Everything in `extra=` lands."""
    record = _make_record(
        chapter_id="ch_42",
        region_id="rg_99",
        engine="vlm",
        provider="anthropic",
        render_ms=123,
        source_type="pdf",
        page_count=12,
        error_count=0,
        src_chapter_id="src",
        dst_chapter_id="dst",
        prompt_hash="abc12345",
        request_id="req_xyz",
        image_bytes=98765,
        cache_read_tokens=10,
    )
    entry = _format(record)
    assert entry["chapter_id"] == "ch_42"
    assert entry["region_id"] == "rg_99"
    assert entry["engine"] == "vlm"
    assert entry["provider"] == "anthropic"
    assert entry["render_ms"] == 123
    assert entry["source_type"] == "pdf"
    assert entry["page_count"] == 12
    assert entry["error_count"] == 0
    assert entry["src_chapter_id"] == "src"
    assert entry["dst_chapter_id"] == "dst"
    assert entry["prompt_hash"] == "abc12345"
    assert entry["request_id"] == "req_xyz"
    assert entry["image_bytes"] == 98765
    assert entry["cache_read_tokens"] == 10


def test_preserves_documented_request_fields():
    """The original allowlist set; still works, now via the denylist path."""
    record = _make_record(
        method="POST", path="/api/x", status=201, duration_ms=42,
        job_id="job_1", page=3, doc_id="doc_x",
    )
    entry = _format(record)
    assert entry["method"] == "POST"
    assert entry["path"] == "/api/x"
    assert entry["status"] == 201
    assert entry["duration_ms"] == 42
    assert entry["job_id"] == "job_1"
    assert entry["page"] == 3
    assert entry["doc_id"] == "doc_x"


def test_does_not_leak_stdlib_record_attrs():
    """LogRecord internal attrs (filename, levelno, threadName, ...) must not
    pollute the JSON output."""
    entry = _format(_make_record())
    for forbidden in (
        "args", "filename", "funcName", "levelno", "lineno", "module",
        "msecs", "pathname", "process", "processName", "relativeCreated",
        "thread", "threadName", "stack_info",
    ):
        assert forbidden not in entry, f"{forbidden} leaked into JSON"


def test_handles_exc_info():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="studious.test", level=logging.ERROR, pathname="x.py",
            lineno=1, msg="oops", args=(), exc_info=sys.exc_info(),
        )
    entry = _format(record)
    assert "exception" in entry
    assert "ValueError" in entry["exception"]
    assert "boom" in entry["exception"]


def test_non_ascii_round_trips_unescaped():
    """ensure_ascii=False keeps Japanese and other UTF-8 readable in logs."""
    record = _make_record(chapter_title="第14課", region_label="本文")
    raw = StructuredFormatter().format(record)
    assert "第14課" in raw
    assert "本文" in raw
    entry = json.loads(raw)
    assert entry["chapter_title"] == "第14課"


def test_non_serialisable_values_fall_back_to_str():
    class Weird:
        def __repr__(self) -> str:
            return "<Weird>"

    record = _make_record(thing=Weird())
    entry = _format(record)
    assert entry["thing"] == "<Weird>"


# ---------------------------------------------------------------------------
# CorrelationMiddleware
# ---------------------------------------------------------------------------


def _starlette_request(headers: list[tuple[bytes, bytes]] | None = None):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "raw_path": b"/test",
        "headers": headers or [],
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1234),
        "root_path": "",
    }

    async def receive():
        return {"type": "http.request", "body": b""}

    return Request(scope, receive=receive)


@pytest.mark.asyncio
async def test_middleware_echoes_incoming_correlation_id():
    from starlette.responses import Response

    middleware = CorrelationMiddleware(app=None)
    request = _starlette_request([(b"x-correlation-id", b"deadbeef0000")])
    captured = {}

    async def call_next(req):
        captured["cid"] = correlation_id_var.get()
        return Response("ok")

    response = await middleware.dispatch(request, call_next)
    assert response.headers["x-correlation-id"] == "deadbeef0000"
    assert captured["cid"] == "deadbeef0000"


@pytest.mark.asyncio
async def test_middleware_generates_correlation_id_when_absent():
    from starlette.responses import Response

    middleware = CorrelationMiddleware(app=None)
    request = _starlette_request()

    async def call_next(req):
        return Response("ok")

    response = await middleware.dispatch(request, call_next)
    cid = response.headers["x-correlation-id"]
    assert isinstance(cid, str) and len(cid) == 16


@pytest.mark.asyncio
async def test_middleware_resets_contextvar_even_on_exception():
    middleware = CorrelationMiddleware(app=None)
    request = _starlette_request([(b"x-correlation-id", b"will_reset_____")])

    async def call_next(req):
        assert correlation_id_var.get() == "will_reset_____"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await middleware.dispatch(request, call_next)
    # Outside the dispatch call the var should be back to its default.
    assert correlation_id_var.get("DEFAULT") == "DEFAULT"
