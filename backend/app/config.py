from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


DEFAULT_VLM_PROMPT = """\
You are an expert OCR transcriber specializing in Japanese textbooks
for English speakers. The image is a single page that mixes Japanese
(kanji, hiragana, katakana, possibly with furigana) and English.

<task>
Transcribe the page into clean Markdown. Preserve the original reading
order — top-to-bottom for horizontal text, right-to-left and
top-to-bottom for vertical text. Preserve paragraph breaks. Convert
visual structure to Markdown semantics:
- Headings (chapter/section titles) → # / ## / ###
- Bold or boxed terms → **bold**
- Vocabulary lists or dialogue turns → bulleted or numbered lists
- Tables (conjugation charts, vocab tables) → Markdown tables
- Furigana (small kana annotating a kanji's reading, appearing
  either above or below the word) → inline parens immediately
  after the kanji, e.g. 食(た)べる. Capture furigana whether it
  appears above or below the line.
- Example sentences and their translations → keep on adjacent lines
</task>

<rules>
- Transcribe Japanese exactly as printed. Do not "correct" spelling,
  punctuation (including 、 and 。), or kana/kanji choices.
- Transcribe English exactly as printed.
- Ignore decorative underlines (e.g. dotted underlines marking
  textbook grammar points). Transcribe the underlined text as plain
  text — do not emit <u>…</u> tags.
- Ignore body-text line numbers in the page margin (e.g. small "5",
  "10", "15" markers every Nth line). Do not include them in the
  transcription.
- If a character or word is unclear, write [?] in its place. Do not
  guess.
- If a region is too blurry, illegible, or cut off to read, write
  [illegible] and continue.
- Do not add commentary, translations, or explanations that are not
  on the page.
- Do not summarize. Output the full page text.
</rules>

<output_format>
Return only the Markdown transcription, with no preamble or closing
remarks. Begin directly with the first line of the page.
</output_format>
"""


REGION_TRANSCRIBE_PROMPT = """\
You are an expert OCR transcriber specializing in Japanese textbooks
for English speakers. The image is a selected region from a single
page — it may be a passage, vocabulary list, table, or other element.

<task>
Transcribe the region into clean Markdown. Preserve the original
reading order — top-to-bottom for horizontal text, right-to-left and
top-to-bottom for vertical text — and preserve paragraph breaks. Use
Markdown lists for enumerations and tables for tabular content.
Render furigana inline with parens, e.g. 食(た)べる; capture furigana
whether it appears above or below the word. Do not invent a heading
if the region has no title.
</task>

<rules>
- Transcribe Japanese and English exactly as printed. Do not
  "correct" spelling, punctuation (including 、 and 。), or
  kana/kanji choices.
- Ignore decorative underlines (e.g. dotted underlines marking
  textbook grammar points). Transcribe the underlined text as
  plain text — do not emit <u>…</u> tags.
- Ignore body-text line numbers in the page margin (e.g. small
  "5", "10", "15" markers every Nth line). Do not include them.
- If a character or word is unclear, write [?]. If part of the region
  is illegible or cut off, write [illegible] and continue.
- Do not add commentary or translations that are not on the page.
</rules>

<output_format>
Return only the Markdown transcription, with no preamble or closing
remarks.
</output_format>
"""


# Per-model pricing in USD per 1M tokens. Keep in sync with Anthropic's
# published pricing. Image tokens are billed as input tokens by Anthropic
# and are already included in `usage.input_tokens`, so no separate rate.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude 4 family
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-opus-4-5": {"input": 15.0, "output": 75.0},
    "claude-opus-4-1": {"input": 15.0, "output": 75.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
}


class Settings(BaseModel):
    data_dir: Path
    anthropic_api_key: str | None
    tesseract_cmd: str | None
    default_vlm_model: str = "claude-opus-4-7"
    default_vlm_prompt: str = DEFAULT_VLM_PROMPT
    vlm_max_edge: int = 1568
    pdf_render_dpi: int = 300


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("STUDIOUS_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "documents").mkdir(exist_ok=True)
    (data_dir / "jobs").mkdir(exist_ok=True)
    overrides: dict = {}
    dpi_env = os.environ.get("STUDIOUS_PDF_RENDER_DPI")
    if dpi_env:
        overrides["pdf_render_dpi"] = int(dpi_env)
    return Settings(
        data_dir=data_dir,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        tesseract_cmd=os.environ.get("TESSERACT_CMD") or None,
        **overrides,
    )
