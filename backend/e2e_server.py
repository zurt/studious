"""ASGI entrypoint for the Playwright E2E suite.

Serves the real app with the "anthropic" VLM name bound to a canned mock
provider, so browser journeys exercise the full upload → chapter → region →
transcribe pipeline deterministically: no API key, no tokens, no network.

The mock must be registered before app startup: `bootstrap_default_providers`
only registers the real Anthropic provider when the name is unclaimed.

Run via `make test-e2e` (Playwright launches it with an isolated
STUDIOUS_DATA_DIR). Never use this entrypoint outside E2E runs.
"""

from __future__ import annotations

from typing import Any

from app.providers import registry

MOCK_MODEL = "mock-vlm-model"

MOCK_TRANSCRIPTION_MD = """\
# Mock transcription

私(わたし)は日本語(にほんご)を勉強(べんきょう)しています。

- 勉強（べんきょう）study
- 日本語（にほんご）Japanese language

Canned output from the E2E mock VLM provider.
"""

MOCK_BREAKDOWN: dict[str, Any] = {
    "sentences": [
        {
            "text": "私(わたし)は日本語(にほんご)を勉強(べんきょう)しています。",
            "gloss": "I am studying Japanese.",
            "vocab": [
                {"word": "勉強", "reading": "べんきょう", "meaning": "study"},
                {"word": "日本語", "reading": "にほんご", "meaning": "Japanese language"},
            ],
            "grammar": [
                {
                    "pattern": "〜ている",
                    "explanation": "Ongoing action or continuing state.",
                    "surfaces": ["しています"],
                }
            ],
        }
    ]
}

MOCK_GRAMMAR_GUIDE: dict[str, Any] = {
    "intro": "Mock grammar guide for E2E runs.",
    "points": [
        {
            "title": "〜ている",
            "subtitle": "Ongoing action",
            "sections": [
                {
                    "heading": "Meaning",
                    "body_md": "Describes an action in progress or a continuing state.",
                },
                {
                    "heading": "Examples",
                    "body_md": "勉強しています。\nI am studying.",
                },
            ],
        }
    ],
}

MOCK_EXERCISE_COMPLETION: dict[str, Any] = {
    "answer": "私は日本語を勉強しています。",
    "answer_english": "I am studying Japanese.",
    "explanation": "Mock completion: the blank takes the て-form plus います.",
    "examples": [
        {
            "japanese": "私は日本語を勉強しています。",
            "reading": "わたしはにほんごをべんきょうしています。",
            "english": "I am studying Japanese.",
            "explanation": "The simplest, most natural completion.",
        },
        {
            "japanese": "私は日本語を読んでいます。",
            "reading": "わたしはにほんごをよんでいます。",
            "english": "I am reading Japanese.",
            "explanation": "Alternative verb showing the same pattern.",
        },
        {
            "japanese": "私は日本語を教えています。",
            "reading": "わたしはにほんごをおしえています。",
            "english": "I am teaching Japanese.",
            "explanation": "Alternative verb showing the same pattern.",
        },
    ],
}

_TOOL_RESPONSES: dict[str, dict[str, Any]] = {
    "record_breakdown": MOCK_BREAKDOWN,
    "record_grammar_guide": MOCK_GRAMMAR_GUIDE,
    "record_exercise_completion": MOCK_EXERCISE_COMPLETION,
}


class MockVlm:
    name = "anthropic"

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "vlm",
            "mock": True,
            "default_config": {"model": MOCK_MODEL, "max_tokens": 8192},
        }

    def transcribe(
        self, image_bytes: bytes | None, prompt: str, config: dict[str, Any]
    ) -> registry.TranscriptionResult:
        return registry.TranscriptionResult(
            markdown=MOCK_TRANSCRIPTION_MD,
            raw=MOCK_TRANSCRIPTION_MD,
            meta=self._meta(config),
        )

    def call_tool(
        self,
        prompt: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        config: dict[str, Any],
    ) -> registry.ToolCallResult:
        if tool_name not in _TOOL_RESPONSES:
            raise ValueError(f"e2e mock has no canned response for tool {tool_name!r}")
        return registry.ToolCallResult(
            tool_input=_TOOL_RESPONSES[tool_name],
            meta=self._meta(config),
        )

    @staticmethod
    def _meta(config: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": config.get("model", MOCK_MODEL),
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }


registry.register_vlm("anthropic", MockVlm)

from app.main import app  # noqa: E402  (import after mock registration)

__all__ = ["app"]
