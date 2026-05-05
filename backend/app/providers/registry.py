from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass
class TranscriptionResult:
    markdown: str
    raw: str
    meta: dict[str, Any] = field(default_factory=dict)


class OcrProvider(Protocol):
    name: str

    def transcribe(self, image_path: Path, config: dict[str, Any]) -> TranscriptionResult: ...

    def info(self) -> dict[str, Any]: ...


class VlmProvider(Protocol):
    name: str

    def transcribe(
        self, image_bytes: bytes | None, prompt: str, config: dict[str, Any]
    ) -> TranscriptionResult: ...

    def info(self) -> dict[str, Any]: ...


_OCR: dict[str, Callable[[], OcrProvider]] = {}
_VLM: dict[str, Callable[[], VlmProvider]] = {}


def register_ocr(name: str, factory: Callable[[], OcrProvider]) -> None:
    _OCR[name] = factory


def register_vlm(name: str, factory: Callable[[], VlmProvider]) -> None:
    _VLM[name] = factory


def get_ocr(name: str) -> OcrProvider:
    if name not in _OCR:
        raise KeyError(f"unknown OCR provider: {name!r}")
    return _OCR[name]()


def get_vlm(name: str) -> VlmProvider:
    if name not in _VLM:
        raise KeyError(f"unknown VLM provider: {name!r}")
    return _VLM[name]()


def list_ocr() -> list[str]:
    return sorted(_OCR.keys())


def list_vlm() -> list[str]:
    return sorted(_VLM.keys())


def bootstrap_default_providers() -> None:
    """Register the default providers. Called once at app startup."""
    from .ocr.tesseract import TesseractOcr
    from .vlm.anthropic import AnthropicVlm

    if "tesseract" not in _OCR:
        register_ocr("tesseract", TesseractOcr)
    if "anthropic" not in _VLM:
        register_vlm("anthropic", AnthropicVlm)
