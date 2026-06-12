from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass
class TranscriptionResult:
    markdown: str
    raw: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResult:
    tool_input: dict[str, Any]
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

    def call_tool(
        self,
        prompt: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        config: dict[str, Any],
    ) -> ToolCallResult: ...

    def info(self) -> dict[str, Any]: ...


_OCR: dict[str, Callable[[], OcrProvider]] = {}
_VLM: dict[str, Callable[[], VlmProvider]] = {}


# Lazily-constructed singletons. Providers hold reusable resources (the
# Anthropic VLM keeps an HTTP client), so one instance per name is shared
# across jobs. A factory that raises (e.g. missing API key) caches nothing,
# so availability is re-checked on the next get.
_OCR_INSTANCES: dict[str, OcrProvider] = {}
_VLM_INSTANCES: dict[str, VlmProvider] = {}


def register_ocr(name: str, factory: Callable[[], OcrProvider]) -> None:
    _OCR[name] = factory
    _OCR_INSTANCES.pop(name, None)


def register_vlm(name: str, factory: Callable[[], VlmProvider]) -> None:
    _VLM[name] = factory
    _VLM_INSTANCES.pop(name, None)


def get_ocr(name: str) -> OcrProvider:
    if name not in _OCR:
        raise KeyError(f"unknown OCR provider: {name!r}")
    if name not in _OCR_INSTANCES:
        _OCR_INSTANCES[name] = _OCR[name]()
    return _OCR_INSTANCES[name]


def get_vlm(name: str) -> VlmProvider:
    if name not in _VLM:
        raise KeyError(f"unknown VLM provider: {name!r}")
    if name not in _VLM_INSTANCES:
        _VLM_INSTANCES[name] = _VLM[name]()
    return _VLM_INSTANCES[name]


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
