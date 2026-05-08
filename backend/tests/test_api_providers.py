from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers import registry


@pytest.fixture
def client(isolated_data_dir):
    with TestClient(app) as c:
        yield c


def test_providers_lists_defaults(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["defaults"]["ocr"] == "tesseract"
    assert body["defaults"]["vlm"] == "anthropic"
    assert any(o["name"] == "tesseract" for o in body["ocr"])
    assert any(v["name"] == "anthropic" for v in body["vlm"])


def test_providers_unavailable_branch_when_info_raises(client, monkeypatch):
    class _Raises:
        name = "boom"
        def info(self): raise RuntimeError("no api key")

    registry.register_vlm("boom", lambda: _Raises())
    try:
        r = client.get("/api/providers")
        assert r.status_code == 200
        body = r.json()
        boom = next(v for v in body["vlm"] if v["name"] == "boom")
        assert "no api key" in boom["unavailable"]
    finally:
        registry._VLM.pop("boom", None)
