"""Tests for the Anthropic VLM provider.

Phase 1.6 #3: every outbound call is logged (start / done / error) with the
fields the audit log later threads through (request_id, prompt_hash,
image_bytes, cache tokens).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.providers.vlm.anthropic import AnthropicVlm, _model_deprecates_temperature


class _StubMessage:
    """Mimics the shape of an `anthropic.types.Message` we read."""

    def __init__(
        self,
        *,
        text: str = "ok",
        model_id: str = "msg_stub",
        request_id: str | None = "req_stub_1",
        stop_reason: str = "end_turn",
        usage: dict | None = None,
    ) -> None:
        self.id = model_id
        self._request_id = request_id
        self.stop_reason = stop_reason
        self.content = [SimpleNamespace(type="text", text=text)]
        self.usage = SimpleNamespace(**(usage or {
            "input_tokens": 7,
            "output_tokens": 3,
            "cache_read_input_tokens": None,
            "cache_creation_input_tokens": None,
        }))


class _StubMessages:
    def __init__(self, message: _StubMessage) -> None:
        self.calls: list[dict] = []
        self._message = message

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._message


class _StubClient:
    def __init__(self, message: _StubMessage) -> None:
        self.messages = _StubMessages(message)


@pytest.fixture
def vlm(monkeypatch: pytest.MonkeyPatch):
    """Return an `AnthropicVlm` whose SDK client is a controllable stub."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app import config as cfg
    cfg.get_settings.cache_clear()

    inst = AnthropicVlm()
    stub_message = _StubMessage()
    inst._client = _StubClient(stub_message)
    return inst, inst._client.messages, stub_message


def test_temperature_dropped_for_opus_4_7(vlm):
    inst, messages, _ = vlm
    inst.transcribe(b"img", "prompt", {"model": "claude-opus-4-7", "temperature": 0.5})
    assert "temperature" not in messages.calls[0]


def test_temperature_kept_for_other_models(vlm):
    inst, messages, _ = vlm
    inst.transcribe(b"img", "prompt", {"model": "claude-sonnet-4-6", "temperature": 0.5})
    assert messages.calls[0]["temperature"] == 0.5


def test_temperature_helper_recognises_4_7_prefix():
    assert _model_deprecates_temperature("claude-opus-4-7")
    assert _model_deprecates_temperature("claude-opus-4-7-20251010")
    assert not _model_deprecates_temperature("claude-opus-4-6")
    assert not _model_deprecates_temperature("claude-sonnet-4-6")


def test_default_model_used_when_config_missing(vlm):
    inst, messages, _ = vlm
    inst.transcribe(b"img", "prompt", {})
    assert messages.calls[0]["model"] == inst._default_model


def test_message_envelope_shape(vlm):
    inst, messages, _ = vlm
    inst.transcribe(b"some-bytes", "describe", {"model": "claude-haiku-4-5", "max_tokens": 1024})
    call = messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["max_tokens"] == 1024
    assert isinstance(call["messages"], list) and len(call["messages"]) == 1
    msg = call["messages"][0]
    assert msg["role"] == "user"
    image_block, text_block = msg["content"]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    assert text_block == {"type": "text", "text": "describe"}


def test_meta_has_provenance_fields(vlm):
    inst, _, _ = vlm
    result = inst.transcribe(b"img-bytes", "prompt-text", {"model": "claude-opus-4-7"})
    assert result.meta["model"] == "claude-opus-4-7"
    assert result.meta["request_id"] == "req_stub_1"
    assert result.meta["image_bytes"] == len(b"img-bytes")
    assert result.meta["prompt_hash"] and len(result.meta["prompt_hash"]) == 8
    assert result.meta["stop_reason"] == "end_turn"
    assert result.meta["usage"]["input_tokens"] == 7
    assert result.meta["usage"]["output_tokens"] == 3
    # Cache fields surface even when None.
    assert "cache_read_input_tokens" in result.meta["usage"]
    assert "cache_creation_input_tokens" in result.meta["usage"]


def test_logs_start_and_done(vlm, caplog):
    inst, _, _ = vlm
    with caplog.at_level(logging.DEBUG, logger="studious.providers.anthropic"):
        inst.transcribe(b"img", "prompt", {"model": "claude-opus-4-7"})

    msgs = [r.getMessage() for r in caplog.records if r.name == "studious.providers.anthropic"]
    assert "vlm_call_start" in msgs
    assert "vlm_call_done" in msgs

    start_record = next(r for r in caplog.records if r.getMessage() == "vlm_call_start")
    done_record = next(r for r in caplog.records if r.getMessage() == "vlm_call_done")
    # Start: model, image_bytes, prompt_hash present.
    assert start_record.model == "claude-opus-4-7"
    assert start_record.image_bytes == len(b"img")
    assert start_record.prompt_hash and len(start_record.prompt_hash) == 8
    # Done: request_id, duration_ms, token counts present.
    assert done_record.request_id == "req_stub_1"
    assert isinstance(done_record.duration_ms, int)
    assert done_record.input_tokens == 7
    assert done_record.output_tokens == 3
    # Cache fields: schema-stable even when None.
    assert hasattr(done_record, "cache_read_tokens")
    assert hasattr(done_record, "cache_creation_tokens")


def test_text_only_call_omits_image_block(vlm):
    inst, messages, _ = vlm
    inst.transcribe(None, "analyze this", {"model": "claude-sonnet-4-6"})
    msg = messages.calls[0]["messages"][0]
    assert msg["role"] == "user"
    assert msg["content"] == [{"type": "text", "text": "analyze this"}]


def test_text_only_call_records_zero_image_bytes(vlm):
    inst, _, _ = vlm
    result = inst.transcribe(None, "p", {"model": "claude-opus-4-7"})
    assert result.meta["image_bytes"] == 0
    # Usage extraction still works.
    assert result.meta["usage"]["input_tokens"] == 7
    assert result.meta["usage"]["output_tokens"] == 3


def test_text_only_logs_image_bytes_zero(vlm, caplog):
    inst, _, _ = vlm
    with caplog.at_level(logging.DEBUG, logger="studious.providers.anthropic"):
        inst.transcribe(None, "p", {"model": "claude-opus-4-7"})
    start = next(r for r in caplog.records if r.getMessage() == "vlm_call_start")
    done = next(r for r in caplog.records if r.getMessage() == "vlm_call_done")
    assert start.image_bytes == 0
    assert done.image_bytes == 0


class _StubToolMessage:
    def __init__(self, *, tool_name: str = "record_breakdown", tool_input: dict | None = None,
                 stop_reason: str = "tool_use", include_text: bool = False) -> None:
        self.id = "msg_stub"
        self._request_id = "req_stub_tool"
        self.stop_reason = stop_reason
        blocks: list = []
        if include_text:
            blocks.append(SimpleNamespace(type="text", text="thinking..."))
        if tool_input is not None:
            blocks.append(SimpleNamespace(type="tool_use", name=tool_name, input=tool_input))
        self.content = blocks
        self.usage = SimpleNamespace(
            input_tokens=12, output_tokens=4,
            cache_read_input_tokens=None, cache_creation_input_tokens=None,
        )


def test_call_tool_returns_parsed_tool_input(vlm):
    inst, messages, _ = vlm
    inst._client.messages._message = _StubToolMessage(
        tool_input={"sentences": [{"text": "x", "gloss": "y"}]}
    )
    result = inst.call_tool(
        "prompt", "record_breakdown", {"type": "object"}, {"model": "claude-opus-4-7"}
    )
    assert result.tool_input == {"sentences": [{"text": "x", "gloss": "y"}]}
    assert result.meta["model"] == "claude-opus-4-7"
    assert result.meta["request_id"] == "req_stub_tool"
    assert result.meta["tool_name"] == "record_breakdown"
    assert result.meta["image_bytes"] == 0

    call = messages.calls[0]
    assert call["tools"][0]["name"] == "record_breakdown"
    assert call["tool_choice"] == {"type": "tool", "name": "record_breakdown"}
    msg = call["messages"][0]
    assert msg["content"] == [{"type": "text", "text": "prompt"}]


def test_call_tool_raises_when_no_tool_use_block(vlm):
    inst, _, _ = vlm
    inst._client.messages._message = _StubToolMessage(tool_input=None, stop_reason="end_turn", include_text=True)
    with pytest.raises(RuntimeError, match="did not return a tool_use block"):
        inst.call_tool("p", "record_breakdown", {"type": "object"}, {})


def test_logs_error_and_reraises(vlm, caplog):
    inst, messages, _ = vlm

    class _BoomMessages:
        def create(self, **kwargs):
            raise RuntimeError("boom from sdk")

    inst._client.messages = _BoomMessages()

    with caplog.at_level(logging.DEBUG, logger="studious.providers.anthropic"):
        with pytest.raises(RuntimeError, match="boom from sdk"):
            inst.transcribe(b"img", "prompt", {"model": "claude-opus-4-7"})

    error_record = next(r for r in caplog.records if r.getMessage() == "vlm_call_error")
    assert error_record.error_class == "RuntimeError"
    assert error_record.model == "claude-opus-4-7"
    assert isinstance(error_record.duration_ms, int)
