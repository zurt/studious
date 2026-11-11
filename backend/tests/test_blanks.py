import pytest

from app.config import (
    BLANK_TRANSCRIBE_RULES,
    DEFAULT_VLM_PROMPT,
    REGION_TRANSCRIBE_PROMPT,
    SENTENCE_BREAKDOWN_PROMPT,
)
from app.services.blanks import BLANK, normalize_blanks


@pytest.mark.parametrize(
    "raw",
    [
        "いつもより＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿だけです",  # long full-width run
        "いつもより＿だけです",  # lone full-width
        r"いつもより\_\_\_\_\_\_\_\_\_\_\_\_だけです",  # markdown-escaped
        "いつもより______だけです",  # ASCII
        r"いつもより\_＿_\_＿だけです",  # mixed styles
    ],
)
def test_every_blank_style_becomes_canonical(raw):
    assert normalize_blanks(raw) == f"いつもより{BLANK}だけです"


def test_idempotent():
    once = normalize_blanks(r"A：\_\_\_\_\_\_と言っても、＿＿＿が。")
    assert normalize_blanks(once) == once


def test_multiple_blanks_and_newlines_preserved():
    raw = "① ______を______。\n② ＿＿＿＿＿＿ね"
    assert normalize_blanks(raw) == f"① {BLANK}を{BLANK}。\n② {BLANK}ね"


@pytest.mark.parametrize(
    "text",
    [
        "**bold** and __bold__ stay",  # two underscores is markdown, not a blank
        "snake_case_name",
        "（　　）はそのまま",
        "彼は……と言った",
        "よ　　　　ね",  # full-width spaces are indentation/legacy, not rewritten
        "",
    ],
)
def test_non_blanks_untouched(text):
    assert normalize_blanks(text) == text


def test_stray_escaped_underscore_unescaped():
    assert normalize_blanks(r"snake\_case") == "snake_case"


def test_transcription_prompts_carry_blank_rules():
    assert "{{BLANK_RULES}}" not in DEFAULT_VLM_PROMPT + REGION_TRANSCRIBE_PROMPT
    for prompt in (DEFAULT_VLM_PROMPT, REGION_TRANSCRIBE_PROMPT):
        assert BLANK_TRANSCRIBE_RULES in prompt
    assert BLANK in BLANK_TRANSCRIBE_RULES


def test_breakdown_prompt_lists_blank_styles():
    for style in ("＿＿＿＿＿", "……", "（　　）", "□", "full-width spaces"):
        assert style in SENTENCE_BREAKDOWN_PROMPT
