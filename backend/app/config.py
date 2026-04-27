from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


DEFAULT_VLM_PROMPT = (
    "You are transcribing a page from a Japanese textbook. Output "
    "GitHub-flavored Markdown that preserves the natural reading order of the "
    "page — top-to-bottom for horizontal text, right-to-left and "
    "top-to-bottom for vertical text. Use headings for section titles, "
    "bullet/numbered lists for enumerations, and tables for tabular content. "
    "Preserve all Japanese text exactly as written; do not translate. When "
    "furigana is present, write it inline as 漢字(かんじ). "
    "Output only the Markdown, with no preamble or commentary."
)


REGION_TRANSCRIBE_PROMPT = (
    "You are transcribing a selected region from a Japanese textbook page. "
    "Output GitHub-flavored Markdown preserving the content exactly as written. "
    "When furigana is present, write it inline as 漢字(かんじ). "
    "Output only the Markdown, with no preamble or commentary."
)


class Settings(BaseModel):
    data_dir: Path
    anthropic_api_key: str | None
    tesseract_cmd: str | None
    default_vlm_model: str = "claude-sonnet-4-6"
    default_vlm_prompt: str = DEFAULT_VLM_PROMPT
    vlm_max_edge: int = 1568
    pdf_render_dpi: int = 150


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("STUDIOUS_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "documents").mkdir(exist_ok=True)
    (data_dir / "jobs").mkdir(exist_ok=True)
    return Settings(
        data_dir=data_dir,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        tesseract_cmd=os.environ.get("TESSERACT_CMD") or None,
    )
