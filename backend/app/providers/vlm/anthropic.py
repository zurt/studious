from __future__ import annotations

import base64
import hashlib
import logging
import time
from typing import Any

import anthropic

from ...config import get_settings
from ..registry import ToolCallResult, TranscriptionResult


_TEMPERATURE_DEPRECATED_PREFIXES = ("claude-opus-4-7", "claude-opus-4-8")
# Models that support adaptive thinking (`thinking: {type: "adaptive"}`).
_ADAPTIVE_THINKING_PREFIXES = (
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-4-6",
)
# Models that support the `effort` output_config parameter.
_EFFORT_PREFIXES = (
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-4-6",
)

log = logging.getLogger("studious.providers.anthropic")


def _model_deprecates_temperature(model: str) -> bool:
    return any(model.startswith(p) for p in _TEMPERATURE_DEPRECATED_PREFIXES)


def _model_supports_adaptive_thinking(model: str) -> bool:
    return any(model.startswith(p) for p in _ADAPTIVE_THINKING_PREFIXES)


def _model_supports_effort(model: str) -> bool:
    return any(model.startswith(p) for p in _EFFORT_PREFIXES)


def _build_common_kwargs(
    model: str, max_tokens: int, config: dict[str, Any], effort: str
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
    if "temperature" in config and not _model_deprecates_temperature(model):
        kwargs["temperature"] = float(config["temperature"])
    if _model_supports_adaptive_thinking(model):
        kwargs["thinking"] = {"type": "adaptive"}
    if _model_supports_effort(model):
        # Per-call override via config wins over the settings default.
        chosen = str(config.get("effort") or effort)
        kwargs["output_config"] = {"effort": chosen}
    return kwargs


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]


class AnthropicVlm:
    name = "anthropic"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; configure it in .env to use the Anthropic VLM."
            )
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._default_model = settings.default_vlm_model

    def info(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "name": self.name,
            "kind": "vlm",
            "default_config": {
                "model": settings.default_vlm_model,
                "max_tokens": 8192,
            },
            "default_prompt": settings.default_vlm_prompt,
            "models": [
                "claude-opus-4-8",
                "claude-opus-4-7",
                "claude-sonnet-4-6",
                "claude-haiku-4-5-20251001",
            ],
            "config_schema": {
                "model": {"type": "string"},
                "max_tokens": {"type": "integer", "default": 8192, "min": 256, "max": 16000},
                "temperature": {
                    "type": "number",
                    "min": 0,
                    "max": 1,
                    "note": "Ignored on claude-opus-4-7+/4-8 and other adaptive-thinking models.",
                },
                "effort": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "xhigh", "max"],
                    "note": (
                        "Per-call override. Defaults: vlm_effort_transcription for "
                        "transcribe(), vlm_effort_breakdown for call_tool(). Only "
                        "applies to opus-4-5+/sonnet-4-6."
                    ),
                },
            },
        }

    def transcribe(
        self, image_bytes: bytes | None, prompt: str, config: dict[str, Any]
    ) -> TranscriptionResult:
        settings = get_settings()
        model = str(config.get("model") or self._default_model)
        max_tokens = int(config.get("max_tokens", 8192))
        prompt_hash = _prompt_hash(prompt)
        image_bytes_len = len(image_bytes) if image_bytes is not None else 0

        kwargs = _build_common_kwargs(
            model, max_tokens, config, settings.vlm_effort_transcription
        )

        log.info(
            "vlm_call_start",
            extra={
                "provider": self.name,
                "model": model,
                "max_tokens": max_tokens,
                "image_bytes": image_bytes_len,
                "prompt_hash": prompt_hash,
            },
        )

        content: list[dict[str, Any]]
        if image_bytes is not None:
            b64 = base64.standard_b64encode(image_bytes).decode("ascii")
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                },
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"},
                },
            ]
        else:
            content = [
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        t0 = time.monotonic()
        try:
            message = self._client.messages.create(
                **kwargs,
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIStatusError as exc:
            log.error(
                "vlm_call_error",
                extra={
                    "provider": self.name,
                    "model": model,
                    "status_code": getattr(exc, "status_code", None),
                    "request_id": getattr(exc, "request_id", None),
                    "error_class": type(exc).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "prompt_hash": prompt_hash,
                    "image_bytes": image_bytes_len,
                },
            )
            raise
        except Exception as exc:
            log.error(
                "vlm_call_error",
                extra={
                    "provider": self.name,
                    "model": model,
                    "error_class": type(exc).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "prompt_hash": prompt_hash,
                    "image_bytes": image_bytes_len,
                },
            )
            raise

        duration_ms = int((time.monotonic() - t0) * 1000)
        request_id = getattr(message, "_request_id", None) or getattr(message, "id", None)

        text_chunks = [
            block.text for block in message.content if getattr(block, "type", None) == "text"
        ]
        raw = "".join(text_chunks).strip()

        usage = getattr(message, "usage", None)
        usage_dict: dict[str, Any] = {}
        if usage is not None:
            usage_dict = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            }

        log.info(
            "vlm_call_done",
            extra={
                "provider": self.name,
                "model": model,
                "request_id": request_id,
                "duration_ms": duration_ms,
                "stop_reason": message.stop_reason,
                "input_tokens": usage_dict.get("input_tokens"),
                "output_tokens": usage_dict.get("output_tokens"),
                "cache_read_tokens": usage_dict.get("cache_read_input_tokens"),
                "cache_creation_tokens": usage_dict.get("cache_creation_input_tokens"),
                "prompt_hash": prompt_hash,
                "image_bytes": image_bytes_len,
            },
        )

        meta: dict[str, Any] = {
            "model": model,
            "stop_reason": message.stop_reason,
            "request_id": request_id,
            "prompt_hash": prompt_hash,
            "image_bytes": image_bytes_len,
        }
        if usage_dict:
            meta["usage"] = usage_dict

        return TranscriptionResult(markdown=raw, raw=raw, meta=meta)

    def call_tool(
        self,
        prompt: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        config: dict[str, Any],
    ) -> ToolCallResult:
        settings = get_settings()
        model = str(config.get("model") or self._default_model)
        max_tokens = int(config.get("max_tokens", 8192))
        prompt_hash = _prompt_hash(prompt)

        kwargs = _build_common_kwargs(
            model, max_tokens, config, settings.vlm_effort_breakdown
        )
        # Anthropic rejects `thinking` when `tool_choice` forces a specific
        # tool. Drop it for forced-tool calls; `output_config.effort` still
        # tunes the model's reasoning budget.
        kwargs.pop("thinking", None)

        log.info(
            "vlm_tool_call_start",
            extra={
                "provider": self.name,
                "model": model,
                "max_tokens": max_tokens,
                "tool_name": tool_name,
                "prompt_hash": prompt_hash,
            },
        )

        tools = [
            {
                "name": tool_name,
                "description": f"Record the structured result for {tool_name}.",
                "input_schema": tool_schema,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        t0 = time.monotonic()
        try:
            message = self._client.messages.create(
                **kwargs,
                tools=tools,
                tool_choice={"type": "tool", "name": tool_name},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            log.error(
                "vlm_tool_call_error",
                extra={
                    "provider": self.name,
                    "model": model,
                    "status_code": getattr(exc, "status_code", None),
                    "request_id": getattr(exc, "request_id", None),
                    "error_class": type(exc).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "prompt_hash": prompt_hash,
                    "tool_name": tool_name,
                },
            )
            raise
        except Exception as exc:
            log.error(
                "vlm_tool_call_error",
                extra={
                    "provider": self.name,
                    "model": model,
                    "error_class": type(exc).__name__,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "prompt_hash": prompt_hash,
                    "tool_name": tool_name,
                },
            )
            raise

        duration_ms = int((time.monotonic() - t0) * 1000)
        request_id = getattr(message, "_request_id", None) or getattr(message, "id", None)

        tool_input: dict[str, Any] | None = None
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                raw_input = getattr(block, "input", None)
                if isinstance(raw_input, dict):
                    tool_input = raw_input
                break
        if tool_input is None:
            raise RuntimeError(
                f"model did not return a tool_use block for {tool_name!r} "
                f"(stop_reason={message.stop_reason!r})"
            )

        usage = getattr(message, "usage", None)
        usage_dict: dict[str, Any] = {}
        if usage is not None:
            usage_dict = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            }

        log.info(
            "vlm_tool_call_done",
            extra={
                "provider": self.name,
                "model": model,
                "request_id": request_id,
                "duration_ms": duration_ms,
                "stop_reason": message.stop_reason,
                "input_tokens": usage_dict.get("input_tokens"),
                "output_tokens": usage_dict.get("output_tokens"),
                "cache_read_tokens": usage_dict.get("cache_read_input_tokens"),
                "cache_creation_tokens": usage_dict.get("cache_creation_input_tokens"),
                "prompt_hash": prompt_hash,
                "tool_name": tool_name,
            },
        )

        meta: dict[str, Any] = {
            "model": model,
            "stop_reason": message.stop_reason,
            "request_id": request_id,
            "prompt_hash": prompt_hash,
            "image_bytes": 0,
            "tool_name": tool_name,
        }
        if usage_dict:
            meta["usage"] = usage_dict
        return ToolCallResult(tool_input=tool_input, meta=meta)
