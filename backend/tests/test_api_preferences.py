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


def test_defaults_to_opus_5_5(client):
    r = client.get("/api/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["default_vlm_model"] == "claude-opus-5-5"
    assert body["vlm_model"] == "claude-opus-5-5"
    assert body["vlm_model_override"] is None
    assert body["available_vlm_models"][0] == "claude-opus-5-5"
    assert "claude-sonnet-5-5" in body["available_vlm_models"]
    assert "claude-sonnet-5" in body["available_vlm_models"]
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
    assert body["vlm_model"] == "claude-opus-5-5"


def test_providers_endpoint_reflects_preference(client):
    client.put("/api/preferences", json={"vlm_model": "claude-opus-4-7"})
    r = client.get("/api/providers")
    assert r.status_code == 200
    assert r.json()["defaults"]["vlm_model"] == "claude-opus-4-7"


# ---------- learner profile ----------


def test_learner_profile_defaults(client):
    body = client.get("/api/preferences").json()
    assert body["learner_level"] is None
    assert body["learner_note"] == ""
    assert body["answer_length"] == "brief"


def test_learner_profile_update_and_clear(client, isolated_data_dir):
    r = client.put(
        "/api/preferences",
        json={"learner_level": "n3", "learner_note": " writing closer to N4 ", "answer_length": "Standard"},
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["learner_level"], body["learner_note"], body["answer_length"]) == (
        "N3", "writing closer to N4", "standard",
    )
    # Unrelated updates leave the profile alone.
    client.put("/api/preferences", json={"vlm_model": "claude-opus-4-7"})
    assert client.get("/api/preferences").json()["learner_level"] == "N3"

    r = client.put("/api/preferences", json={"learner_level": "", "learner_note": "", "answer_length": ""})
    body = r.json()
    assert (body["learner_level"], body["learner_note"], body["answer_length"]) == (None, "", "brief")
    stored = json.loads((isolated_data_dir / "preferences.json").read_text())
    assert not {"learner_level", "learner_note", "answer_length"} & stored.keys()


@pytest.mark.parametrize(
    "patch",
    [{"learner_level": "N6"}, {"answer_length": "verbose"}, {"learner_note": "x" * 201}],
)
def test_learner_profile_rejects_invalid(client, patch):
    assert client.put("/api/preferences", json=patch).status_code == 400


def test_helper_model_defaults_and_override(client):
    body = client.get("/api/preferences").json()
    assert body["default_helper_model"] == "claude-haiku-5-5"
    assert body["helper_model"] == "claude-haiku-5-5"
    assert body["helper_model_override"] is None
    assert "claude-opus-5-5" in body["available_helper_models"]

    body = client.put("/api/preferences", json={"helper_model": "claude-sonnet-5-5"}).json()
    assert body["helper_model"] == "claude-sonnet-5-5"
    assert body["helper_model_override"] == "claude-sonnet-5-5"
    assert preferences.get_active_helper_model() == "claude-sonnet-5-5"
    # The main model is untouched.
    assert body["vlm_model_override"] is None

    # None leaves it unchanged; "" clears it.
    assert client.put("/api/preferences", json={}).json()["helper_model"] == "claude-sonnet-5-5"
    body = client.put("/api/preferences", json={"helper_model": ""}).json()
    assert body["helper_model_override"] is None
    assert body["helper_model"] == "claude-haiku-5-5"


def test_unsupported_helper_model_rejected(client):
    r = client.put("/api/preferences", json={"helper_model": "claude-opus-4-7"})
    assert r.status_code == 400
