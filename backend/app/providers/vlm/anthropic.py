from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import time
from typing import Any

import anthropic

from ...config import get_settings
from ..registry import Prompt, ToolCallResult, TranscriptionResult, prompt_text


# Prefix matching: "claude-sonnet-5" also covers claude-sonnet-5-5, and
# "claude-opus-5" covers claude-opus-5-5.
_TEMPERATURE_DEPRECATED_PREFIXES = ("claude-opus-4-7", "claude-opus-4-8", "claude-opus-5", "claude-sonnet-5")
# Models that support adaptive thinking (`thinking: {type: "adaptive"}`).
_ADAPTIVE_THINKING_PREFIXES = (
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
)
# Models that support the `effort` output_config parameter.
_EFFORT_PREFIXES = (
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
)
# Models that 400 on a forced `tool_choice` (`any` / `tool`). Their tool calls
# go through structured outputs (`output_config.format`) instead: the forced
# call only ever existed to get schema-shaped JSON back.
_STRUCTURED_OUTPUT_PREFIXES = ("claude-opus-5-5", "claude-sonnet-5-5")
# Of those, models whose thinking can be switched off for tool calls with
# `between_tools` (accepted only at effort `high` or below). The rest think
# adaptively and need `max_tokens` headroom, since thinking counts toward it.
_BETWEEN_TOOLS_PREFIXES = ("claude-sonnet-5-5",)
# Tool-call effort when the job config doesn't set one, for models whose
# effort levels don't carry over from the settings default (`xhigh`, tuned for
# thinking-off forced tool calls on earlier models). Opus 5.5 thinks on every
# call; Anthropic's guidance is to start it at `medium`.
_TOOL_CALL_EFFORT_DEFAULTS = {"claude-opus-5-5": "medium"}
_THINKING_HEADROOM_TOKENS = 16000
_EFFORT_ORDER = ["low", "medium", "high", "xhigh", "max"]
# Server-side refusal fallback: a policy decline is re-run on the model
# Anthropic recommends for its category instead of failing the job.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# JSON-schema keywords structured outputs don't accept; the jobs validate the
# shapes that matter themselves.
_UNSUPPORTED_SCHEMA_KEYS = {
    "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "uniqueItems",
}

log = logging.getLogger("studious.providers.anthropic")


def _model_deprecates_temperature(model: str) -> bool:
    return any(model.startswith(p) for p in _TEMPERATURE_DEPRECATED_PREFIXES)


def _model_supports_adaptive_thinking(model: str) -> bool:
    return any(model.startswith(p) for p in _ADAPTIVE_THINKING_PREFIXES)


def _model_supports_effort(model: str) -> bool:
    return any(model.startswith(p) for p in _EFFORT_PREFIXES)


def _model_rejects_forced_tool_choice(model: str) -> bool:
    return any(model.startswith(p) for p in _STRUCTURED_OUTPUT_PREFIXES)


def _fallback_kwargs(model: str) -> dict[str, Any]:
    if not _model_rejects_forced_tool_choice(model):
        return {}
    return {"betas": [_FALLBACK_BETA], "extra_body": {"fallbacks": "default"}}


def _clamp_effort(effort: str, ceiling: str) -> str:
    if effort in _EFFORT_ORDER and _EFFORT_ORDER.index(effort) > _EFFORT_ORDER.index(ceiling):
        return ceiling
    return effort


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adapt a tool input schema for `output_config.format`.

    Structured outputs require `additionalProperties: false` on every object
    and reject length/count/range keywords, so those are stripped here.
    """

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {k: walk(v) for k, v in node.items() if k not in _UNSUPPORTED_SCHEMA_KEYS}
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
        return out

    return walk(copy.deepcopy(schema))


def _content_blocks(prompt: Prompt) -> list[dict[str, Any]]:
    """User-message text blocks, with a cache breakpoint where requested.

    A plain string is one cached block (the historical shape). A block list
    keeps each block's `cache` flag, so a caller can cache the prefix shared
    across calls and leave the per-call tail uncached.
    """
    if isinstance(prompt, str):
        return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
    blocks: list[dict[str, Any]] = []
    for block in prompt:
        text = str(block.get("text") or "")
        if not text.strip():
            continue
        out: dict[str, Any] = {"type": "text", "text": text}
        if block.get("cache"):
            out["cache_control"] = {"type": "ephemeral"}
        blocks.append(out)
    return blocks


def _raise_if_refused(message: Any) -> None:
    """A safety decline is an HTTP 200 with stop_reason "refusal"; content is
    empty or partial, so it must never be read as a result."""
    if getattr(message, "stop_reason", None) != "refusal":
        return
    details = getattr(message, "stop_details", None)
    category = details.get("category") if isinstance(details, dict) else getattr(details, "category", None)
    suffix = f", category={category}" if category else ""
    raise RuntimeError(f"model declined the request (refusal{suffix})")


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


def _find_tool_input(message: Any, tool_name: str) -> dict[str, Any]:
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            raw_input = getattr(block, "input", None)
            if isinstance(raw_input, dict):
                return raw_input
            break
    raise RuntimeError(
        f"model did not return a tool_use block for {tool_name!r} "
        f"(stop_reason={message.stop_reason!r})"
    )


def _parse_structured_output(message: Any, tool_name: str) -> dict[str, Any]:
    """The JSON object a structured-output call returned, as a tool input.

    A response cut off at max_tokens comes back as `{}` so callers report it
    as truncation (they check `stop_reason`), the same as a partial tool call.
    """
    text = "".join(
        getattr(block, "text", "") for block in message.content if getattr(block, "type", None) == "text"
    ).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if message.stop_reason == "max_tokens":
            return {}
        raise RuntimeError(
            f"model returned invalid JSON for {tool_name!r} (stop_reason={message.stop_reason!r})"
        ) from None
    if not isinstance(data, dict):
        raise RuntimeError(f"model returned non-object JSON for {tool_name!r}")
    return data


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
                "claude-sonnet-5-5",
                "claude-opus-5-5",
                "claude-opus-4-8",
                "claude-opus-4-7",
                "claude-sonnet-5",
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

        fallback = _fallback_kwargs(model)
        messages_api = self._client.beta.messages if fallback else self._client.messages

        t0 = time.monotonic()
        try:
            message = messages_api.create(
                **kwargs,
                **fallback,
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
        _raise_if_refused(message)

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
        prompt: Prompt,
        tool_name: str,
        tool_schema: dict[str, Any],
        config: dict[str, Any],
    ) -> ToolCallResult:
        settings = get_settings()
        model = str(config.get("model") or self._default_model)
        max_tokens = int(config.get("max_tokens", 8192))
        prompt_hash = _prompt_hash(prompt_text(prompt))
        structured = _model_rejects_forced_tool_choice(model)

        request: dict[str, Any]
        if structured:
            request = self._structured_request(model, max_tokens, config, tool_schema)
        else:
            request = _build_common_kwargs(
                model, max_tokens, config, settings.vlm_effort_breakdown
            )
            # Anthropic rejects `thinking` when `tool_choice` forces a specific
            # tool. Drop it for forced-tool calls; `output_config.effort` still
            # tunes the model's reasoning budget.
            request.pop("thinking", None)
            request["tools"] = [
                {
                    "name": tool_name,
                    "description": f"Record the structured result for {tool_name}.",
                    "input_schema": tool_schema,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            request["tool_choice"] = {"type": "tool", "name": tool_name}

        log.info(
            "vlm_tool_call_start",
            extra={
                "provider": self.name,
                "model": model,
                "max_tokens": request["max_tokens"],
                "tool_name": tool_name,
                "prompt_hash": prompt_hash,
                "mode": "structured_output" if structured else "forced_tool",
            },
        )

        messages_api = self._client.beta.messages if structured else self._client.messages
        t0 = time.monotonic()
        try:
            # Stream the response: large max_tokens budgets can push the request
            # past the SDK's 10-minute non-streaming limit, which raises
            # "Streaming is required for operations that may take longer than 10
            # minutes." get_final_message() accumulates the stream into the same
            # Message shape the non-streaming path returned.
            with messages_api.stream(
                **request,
                messages=[{"role": "user", "content": _content_blocks(prompt)}],
            ) as stream:
                message = stream.get_final_message()
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

        _raise_if_refused(message)
        tool_input = (
            _parse_structured_output(message, tool_name)
            if structured
            else _find_tool_input(message, tool_name)
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
        served = getattr(message, "model", None)
        if isinstance(served, str) and served != model:
            # A refusal fallback answered instead of the requested model.
            meta["served_model"] = served
        if usage_dict:
            meta["usage"] = usage_dict
        return ToolCallResult(tool_input=tool_input, meta=meta)

    def _structured_request(
        self, model: str, max_tokens: int, config: dict[str, Any], tool_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Request kwargs for a tool call on a model without forced tool use."""
        settings = get_settings()
        effort = str(
            config.get("effort")
            or next((e for p, e in _TOOL_CALL_EFFORT_DEFAULTS.items() if model.startswith(p)), None)
            or settings.vlm_effort_breakdown
        )
        request: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
        if any(model.startswith(p) for p in _BETWEEN_TOOLS_PREFIXES):
            # Closest match to the thinking-off forced tool calls other models
            # make; `between_tools` is only accepted at effort `high` or below.
            request["thinking"] = {"type": "between_tools"}
            effort = _clamp_effort(effort, "high")
        else:
            request["thinking"] = {"type": "adaptive"}
            request["max_tokens"] = max_tokens + _THINKING_HEADROOM_TOKENS
        request["output_config"] = {
            "effort": effort,
            "format": {"type": "json_schema", "schema": _strict_json_schema(tool_schema)},
        }
        request.update(_fallback_kwargs(model))
        return request
