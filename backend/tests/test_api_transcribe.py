from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_VLM_PROMPT
from app.main import app
from app.services import storage


def _make_doc(tmp_path: Path, page_count: int = 5) -> dict:
    src = tmp_path / "fake.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    return storage.create_document(
        name="fake.pdf", source_type="pdf", page_count=page_count, original_path=src
    )


@pytest.fixture
def client(isolated_data_dir):
    with TestClient(app) as c:
        yield c


def test_submit_transcription_unknown_doc_404(client):
    r = client.post("/api/documents/missing/transcribe", json={
        "engine": "ocr", "provider": "tesseract", "pages": "all"
    })
    assert r.status_code == 404


def test_submit_transcription_invalid_pages_400(client, tmp_path):
    doc = _make_doc(tmp_path, page_count=3)
    r = client.post(f"/api/documents/{doc['id']}/transcribe", json={
        "engine": "ocr", "provider": "tesseract", "pages": "100"
    })
    assert r.status_code == 400


def test_submit_transcription_uses_default_vlm_prompt_when_omitted(client, tmp_path):
    doc = _make_doc(tmp_path, page_count=2)
    r = client.post(f"/api/documents/{doc['id']}/transcribe", json={
        "engine": "vlm", "provider": "anthropic", "pages": "1"
    })
    assert r.status_code == 200
    job = storage.load_job(r.json()["job_id"])
    assert job["prompt"] == DEFAULT_VLM_PROMPT


def test_submit_transcription_explicit_prompt_kept(client, tmp_path):
    doc = _make_doc(tmp_path, page_count=2)
    r = client.post(f"/api/documents/{doc['id']}/transcribe", json={
        "engine": "vlm", "provider": "anthropic", "pages": "1-2",
        "prompt": "custom prompt"
    })
    assert r.status_code == 200
    job = storage.load_job(r.json()["job_id"])
    assert job["prompt"] == "custom prompt"
    assert job["pages"] == [1, 2]
