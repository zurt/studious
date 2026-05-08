from __future__ import annotations

import pytest

from app.providers import registry
from app.providers.ocr.tesseract import _to_markdown


class _StubOcr:
    name = "stub-ocr"
    def info(self):
        return {"name": self.name, "kind": "ocr"}
    def transcribe(self, image_path, config):
        raise NotImplementedError


class _StubVlm:
    name = "stub-vlm"
    def info(self):
        return {"name": self.name, "kind": "vlm"}
    def transcribe(self, image_bytes, prompt, config):
        raise NotImplementedError
    def call_tool(self, prompt, tool_name, tool_schema, config):
        raise NotImplementedError


def test_register_and_get_ocr():
    registry.register_ocr("stub-ocr", lambda: _StubOcr())
    try:
        assert "stub-ocr" in registry.list_ocr()
        provider = registry.get_ocr("stub-ocr")
        assert provider.name == "stub-ocr"
    finally:
        registry._OCR.pop("stub-ocr", None)


def test_register_and_get_vlm():
    registry.register_vlm("stub-vlm", lambda: _StubVlm())
    try:
        assert "stub-vlm" in registry.list_vlm()
        provider = registry.get_vlm("stub-vlm")
        assert provider.name == "stub-vlm"
    finally:
        registry._VLM.pop("stub-vlm", None)


def test_get_unknown_raises_keyerror():
    with pytest.raises(KeyError, match="unknown OCR provider"):
        registry.get_ocr("not-registered")
    with pytest.raises(KeyError, match="unknown VLM provider"):
        registry.get_vlm("not-registered")


def test_bootstrap_default_providers_is_idempotent():
    registry.bootstrap_default_providers()
    ocr_first = list(registry._OCR.keys())
    vlm_first = list(registry._VLM.keys())
    registry.bootstrap_default_providers()
    assert list(registry._OCR.keys()) == ocr_first
    assert list(registry._VLM.keys()) == vlm_first
    # The defaults are present.
    assert "tesseract" in registry._OCR
    assert "anthropic" in registry._VLM


def test_to_markdown_splits_paragraphs_on_blank_lines():
    text = "first line\nstill first\n\nsecond para\n\nthird"
    md = _to_markdown(text)
    paras = md.strip().split("\n\n")
    assert paras == ["first line\nstill first", "second para", "third"]
    assert md.endswith("\n")


def test_to_markdown_empty_input_returns_empty():
    assert _to_markdown("") == ""
    assert _to_markdown("   \n  \n") == ""


def test_to_markdown_strips_trailing_whitespace_per_line():
    md = _to_markdown("hello   \nworld  ")
    assert md == "hello\nworld\n"
