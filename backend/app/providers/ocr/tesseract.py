from __future__ import annotations

from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image

from ...config import get_settings
from ..registry import TranscriptionResult


class TesseractOcr:
    name = "tesseract"

    def __init__(self) -> None:
        cmd = get_settings().tesseract_cmd
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "ocr",
            "default_config": {"lang": "jpn+jpn_vert", "psm": 6},
            "config_schema": {
                "lang": {"type": "string", "default": "jpn+jpn_vert"},
                "psm": {"type": "integer", "default": 6, "min": 0, "max": 13},
            },
        }

    def transcribe(self, image_path: Path, config: dict[str, Any]) -> TranscriptionResult:
        lang = str(config.get("lang", "jpn+jpn_vert"))
        psm = int(config.get("psm", 6))
        with Image.open(image_path) as im:
            text = pytesseract.image_to_string(im, lang=lang, config=f"--psm {psm}")
        markdown = _to_markdown(text)
        return TranscriptionResult(
            markdown=markdown,
            raw=text,
            meta={"lang": lang, "psm": psm},
        )


def _to_markdown(text: str) -> str:
    """Tesseract returns plain text. Split on blank lines into paragraphs."""
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line.rstrip())
        else:
            if current:
                paragraphs.append("\n".join(current))
                current = []
    if current:
        paragraphs.append("\n".join(current))
    return "\n\n".join(paragraphs).strip() + ("\n" if paragraphs else "")
