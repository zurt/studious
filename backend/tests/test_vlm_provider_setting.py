"""STUDIOUS_VLM_PROVIDER picks what backs the "anthropic" VLM name."""
from __future__ import annotations

import logging

import pytest

from app import config
from app.providers import registry
from app.providers.vlm.mock import MockVlm


@pytest.fixture(autouse=True)
def _restore_registry():
    """bootstrap_default_providers mutates the module-level registry."""
    saved = (dict(registry._VLM), dict(registry._VLM_INSTANCES), dict(registry._OCR), dict(registry._OCR_INSTANCES))
    yield
    registry._VLM.clear(), registry._VLM_INSTANCES.clear(), registry._OCR.clear(), registry._OCR_INSTANCES.clear()
    registry._VLM.update(saved[0]), registry._VLM_INSTANCES.update(saved[1])
    registry._OCR.update(saved[2]), registry._OCR_INSTANCES.update(saved[3])
    config.get_settings.cache_clear()


def _bootstrap(monkeypatch, tmp_path, value: str | None):
    monkeypatch.setenv("STUDIOUS_DATA_DIR", str(tmp_path))
    if value is None:
        monkeypatch.delenv("STUDIOUS_VLM_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("STUDIOUS_VLM_PROVIDER", value)
    config.get_settings.cache_clear()
    registry._VLM.pop("anthropic", None)
    registry._VLM_INSTANCES.pop("anthropic", None)
    registry.bootstrap_default_providers()


def test_default_is_the_real_provider(monkeypatch, tmp_path):
    from app.providers.vlm.anthropic import AnthropicVlm

    _bootstrap(monkeypatch, tmp_path, None)
    assert config.get_settings().vlm_provider == "anthropic"
    assert registry._VLM["anthropic"] is AnthropicVlm


def test_mock_is_registered_under_the_anthropic_name(monkeypatch, tmp_path):
    _bootstrap(monkeypatch, tmp_path, "mock")
    assert config.get_settings().vlm_provider == "mock"
    provider = registry.get_vlm("anthropic")
    assert isinstance(provider, MockVlm)
    assert provider.info()["mock"] is True


def test_mock_replaces_an_already_registered_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIOUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STUDIOUS_VLM_PROVIDER", "mock")
    config.get_settings.cache_clear()
    registry.register_vlm("anthropic", lambda: object())  # type: ignore[arg-type,return-value]
    registry.bootstrap_default_providers()
    assert isinstance(registry.get_vlm("anthropic"), MockVlm)


def test_value_is_case_insensitive(monkeypatch, tmp_path):
    _bootstrap(monkeypatch, tmp_path, " Mock ")
    assert isinstance(registry.get_vlm("anthropic"), MockVlm)


def test_invalid_value_is_rejected_with_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIOUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STUDIOUS_VLM_PROVIDER", "openai")
    config.get_settings.cache_clear()
    with pytest.raises(ValueError, match="STUDIOUS_VLM_PROVIDER.*anthropic, mock"):
        config.get_settings()


def test_mock_logs_a_warning_at_startup(monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="studious.providers"):
        _bootstrap(monkeypatch, tmp_path, "mock")
    assert any(r.getMessage() == "mock_vlm_active" and r.levelno == logging.WARNING for r in caplog.records)


def test_providers_endpoint_reports_the_mock(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app

    _bootstrap(monkeypatch, tmp_path, "mock")
    with TestClient(app) as client:
        vlm = client.get("/api/providers").json()["vlm"]
    assert [p["mock"] for p in vlm if p["name"] == "anthropic"] == [True]
