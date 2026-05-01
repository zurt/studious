from __future__ import annotations

import base64
from typing import Any

import anthropic

from ...config import get_settings
from ..registry import TranscriptionResult


_TEMPERATURE_DEPRECATED_PREFIXES = ("claude-opus-4-7",)


def _model_deprecates_temperature(model: str) -> bool:
    return any(model.startswith(p) for p in _TEMPERATURE_DEPRECATED_PREFIXES)


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
                "max_tokens": 4096,
            },
            "default_prompt": settings.default_vlm_prompt,
            "models": [
                "claude-opus-4-7",
                "claude-sonnet-4-6",
                "claude-haiku-4-5-20251001",
            ],
            "config_schema": {
                "model": {"type": "string"},
                "max_tokens": {"type": "integer", "default": 4096, "min": 256, "max": 8192},
                "temperature": {"type": "number", "min": 0, "max": 1},
            },
        }

    def transcribe(
        self, image_bytes: bytes, prompt: str, config: dict[str, Any]
    ) -> TranscriptionResult:
        model = str(config.get("model") or self._default_model)
        max_tokens = int(config.get("max_tokens", 4096))

        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
        if "temperature" in config and not _model_deprecates_temperature(model):
            kwargs["temperature"] = float(config["temperature"])

        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        message = self._client.messages.create(
            **kwargs,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )

        text_chunks = [
            block.text for block in message.content if getattr(block, "type", None) == "text"
        ]
        raw = "".join(text_chunks).strip()

        usage = getattr(message, "usage", None)
        meta: dict[str, Any] = {"model": model, "stop_reason": message.stop_reason}
        if usage is not None:
            meta["usage"] = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }

        return TranscriptionResult(markdown=raw, raw=raw, meta=meta)
