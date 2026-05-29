from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import preferences


@pytest.fixture
def client(isolated_data_dir):
    with TestClient(app) as c:
        yield c


def test_defaults_to_opus_4_8(client):
    r = client.get("/api/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["default_vlm_model"] == "claude-opus-4-8"
    assert body["vlm_model"] == "claude-opus-4-8"
    assert body["vlm_model_override"] is None
    assert "claude-opus-4-8" in body["available_vlm_models"]
    assert "claude-opus-4-7" in body["available_vlm_models"]


def test_update_selects_opus_4_7(client, isolated_data_dir):
    r = client.put("/api/preferences", json={"vlm_model": "claude-opus-4-7"})
    assert r.status_code == 200
    body = r.json()
    assert body["vlm_model"] == "claude-opus-4-7"
    assert body["vlm_model_override"] == "claude-opus-4-7"

    # Persisted to data_dir/preferences.json
    prefs_path = isolated_data_dir / "preferences.json"
    assert prefs_path.exists()
    assert json.loads(prefs_path.read_text())["vlm_model"] == "claude-opus-4-7"

    # Helper resolves to the override.
    assert preferences.get_active_vlm_model() == "claude-opus-4-7"


def test_unsupported_model_rejected(client):
    r = client.put("/api/preferences", json={"vlm_model": "claude-opus-9-9"})
    assert r.status_code == 400


def test_empty_string_clears_override(client):
    client.put("/api/preferences", json={"vlm_model": "claude-opus-4-7"})
    r = client.put("/api/preferences", json={"vlm_model": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["vlm_model_override"] is None
    assert body["vlm_model"] == "claude-opus-4-8"


def test_providers_endpoint_reflects_preference(client):
    client.put("/api/preferences", json={"vlm_model": "claude-opus-4-7"})
    r = client.get("/api/providers")
    assert r.status_code == 200
    assert r.json()["defaults"]["vlm_model"] == "claude-opus-4-7"
