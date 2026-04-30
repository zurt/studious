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
- Furigana above kanji → inline parens, e.g. 食(た)べる
- Example sentences and their translations → keep on adjacent lines
</task>

<rules>
- Transcribe Japanese exactly as printed. Do not "correct" spelling,
  punctuation (including 、 and 。), or kana/kanji choices.
- Transcribe English exactly as printed.
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
Render furigana inline with parens, e.g. 食(た)べる. Do not invent a
heading if the region has no title.
</task>

<rules>
- Transcribe Japanese and English exactly as printed. Do not
  "correct" spelling, punctuation (including 、 and 。), or
  kana/kanji choices.
- If a character or word is unclear, write [?]. If part of the region
  is illegible or cut off, write [illegible] and continue.
- Do not add commentary or translations that are not on the page.
</rules>

<output_format>
Return only the Markdown transcription, with no preamble or closing
remarks.
</output_format>
"""


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
