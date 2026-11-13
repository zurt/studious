"""Canned mock VLM provider: no API key, no tokens, no network.

Selected with STUDIOUS_VLM_PROVIDER=mock (see `registry.bootstrap_default_providers`),
which registers it under the "anthropic" name so the rest of the app (jobs,
API routes, saved preferences) is unchanged. Used by the Playwright E2E suite
and by `make dev-backend`. Its output is asserted on by
`frontend/e2e/smoke.spec.ts`, so keep the canned responses stable.
"""

from __future__ import annotations

import json
from typing import Any

from app.providers import registry
from app.services import anki_push

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
    "exercise_type": "open",
    # Readings on every kanji word, as EXERCISE_COMPLETION_PROMPT asks.
    "answer": "私(わたし)は日本語(にほんご)を勉強(べんきょう)しています。",
    "answer_english": "I am studying Japanese.",
    "explanation": "Mock completion: the blank takes the て-form plus います.",
    "filled_text": "勉強(べんきょう)しています",
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

# Returned instead of MOCK_EXERCISE_COMPLETION when the prompt carries a
# reading-reference block (its closing tag — the instructions mention the
# opening one), so a journey can see that an exercises region's
# reading references actually reached the completion prompt.
MOCK_REFERENCE_EXPLANATION = "Mock completion: answered using the reading reference."

def mock_examples(prompt: Any) -> dict[str, Any]:
    """A valid example-sentence response for every word in the prompt's
    <words> block: これは<word>です。 with real furigana for the word."""
    text = registry.prompt_text(prompt)
    words = json.loads(text.rsplit("<words>", 1)[1].split("</words>", 1)[0])
    out = []
    for w in words:
        head = w["headword"]
        furi = anki_push.furigana(head, anki_push.pick_reading(head, w.get("reading") or ""))
        out.append(
            {
                "id": w["id"],
                "sentence": f"これは{head}です。",
                "surface": head,
                "furigana": "これは" + (" " if furi != head else "") + furi + "です。",
                "gloss": "This is a mock example sentence.",
            }
        )
    return {"examples": out}


# Benign region check: the label is fine and no reading reference is needed.
# suggested_tag echoes the tag named in the prompt's <current_tag> block.
def mock_region_check(prompt: Any) -> dict[str, Any]:
    text = registry.prompt_text(prompt)
    tag = text.rsplit("<current_tag>", 1)[1].split("</current_tag>", 1)[0]
    return {
        "suggested_tag": tag,
        "tag_confidence": "high",
        "tag_reason": "",
        "needs_reference": False,
        "reference_reason": "The questions are self-contained.",
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
        if tool_name == "record_examples":
            return registry.ToolCallResult(tool_input=mock_examples(prompt), meta=self._meta(config))
        if tool_name == "record_region_check":
            return registry.ToolCallResult(tool_input=mock_region_check(prompt), meta=self._meta(config))
        if tool_name not in _TOOL_RESPONSES:
            raise ValueError(f"mock VLM has no canned response for tool {tool_name!r}")
        tool_input = _TOOL_RESPONSES[tool_name]
        if tool_name == "record_exercise_completion" and "</reading_reference>" in registry.prompt_text(prompt):
            tool_input = {**tool_input, "explanation": MOCK_REFERENCE_EXPLANATION}
        return registry.ToolCallResult(
            tool_input=tool_input,
            meta=self._meta(config),
        )

    @staticmethod
    def _meta(config: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": config.get("model", MOCK_MODEL),
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
