from __future__ import annotations

import io
import json
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import storage


def _make_pdf_bytes(num_pages: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((20, 50), f"page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def _make_png_bytes(size: tuple[int, int] = (32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(isolated_data_dir):
    with TestClient(app) as c:
        yield c


def test_upload_pdf_renders_pages(client):
    files = {"file": ("test.pdf", _make_pdf_bytes(3), "application/pdf")}
    r = client.post("/api/documents", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["source_type"] == "pdf"
    assert body["page_count"] == 3
    # meta.json should reflect the page count after rendering
    meta = storage.load_document(body["id"])
    assert meta["page_count"] == 3
    # Pages were written to disk
    for p in (1, 2, 3):
        assert storage.page_image_path(body["id"], p).exists()


def test_upload_image_creates_one_page(client):
    files = {"file": ("test.png", _make_png_bytes(), "image/png")}
    r = client.post("/api/documents", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["source_type"] == "image"
    assert body["page_count"] == 1
    assert storage.page_image_path(body["id"], 1).exists()


def test_upload_unsupported_suffix_returns_400(client):
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    r = client.post("/api/documents", files=files)
    assert r.status_code == 400
    assert "unsupported" in r.json()["detail"]


def test_reupload_replaces_original_and_rerenders(client):
    files = {"file": ("a.pdf", _make_pdf_bytes(2), "application/pdf")}
    doc_id = client.post("/api/documents", files=files).json()["id"]
    assert storage.load_document(doc_id)["page_count"] == 2

    new_files = {"file": ("b.pdf", _make_pdf_bytes(4), "application/pdf")}
    r = client.put(f"/api/documents/{doc_id}/file", files=new_files)
    assert r.status_code == 200
    body = r.json()
    assert body["page_count"] == 4
    assert body["name"] == "b.pdf"
    # New pages exist; old extra is gone
    for p in (1, 2, 3, 4):
        assert storage.page_image_path(doc_id, p).exists()


def test_reupload_unknown_returns_404(client):
    r = client.put("/api/documents/missing/file", files={"file": ("x.pdf", _make_pdf_bytes(1), "application/pdf")})
    assert r.status_code == 404


def test_reupload_unsupported_suffix_returns_400(client):
    files = {"file": ("a.pdf", _make_pdf_bytes(1), "application/pdf")}
    doc_id = client.post("/api/documents", files=files).json()["id"]
    r = client.put(f"/api/documents/{doc_id}/file", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_delete_document_removes_directory(client):
    files = {"file": ("a.pdf", _make_pdf_bytes(1), "application/pdf")}
    doc_id = client.post("/api/documents", files=files).json()["id"]
    assert storage.document_dir(doc_id).exists()
    r = client.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 200
    assert not storage.document_dir(doc_id).exists()


def test_delete_unknown_returns_404(client):
    r = client.delete("/api/documents/nope")
    assert r.status_code == 404


def test_get_document_includes_chapters_and_regions(client):
    files = {"file": ("a.pdf", _make_pdf_bytes(5), "application/pdf")}
    doc_id = client.post("/api/documents", files=files).json()["id"]

    ch = storage.create_chapter(doc_id, title="Ch1", page_start=1, page_end=3)
    region = storage.create_region(
        doc_id, ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    storage.update_region(
        doc_id, ch["id"], region["id"], transcription_md="# hi"
    )
    storage.create_region(
        doc_id, ch["id"], page=2, bbox=[0, 0, 1, 1], tag="other"
    )
    storage.save_transcription(
        doc_id, 1, {"page": 1, "engine": "ocr", "provider": "x", "markdown": "x",
                    "raw": "", "tokens": [], "annotations": {}, "meta": {}, "created_at": ""}
    )

    r = client.get(f"/api/documents/{doc_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["transcribed_pages"] == [1]
    assert len(body["chapters"]) == 1
    assert body["chapters"][0]["id"] == ch["id"]
    assert body["regions_total"] == 2
    assert body["regions_transcribed"] == 1


def test_get_unknown_document_returns_404(client):
    r = client.get("/api/documents/nope")
    assert r.status_code == 404


def test_list_documents_returns_array(client):
    client.post("/api/documents", files={"file": ("a.pdf", _make_pdf_bytes(1), "application/pdf")})
    client.post("/api/documents", files={"file": ("b.pdf", _make_pdf_bytes(1), "application/pdf")})
    r = client.get("/api/documents")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_get_page_image_404_when_missing(client):
    files = {"file": ("a.pdf", _make_pdf_bytes(1), "application/pdf")}
    doc_id = client.post("/api/documents", files=files).json()["id"]
    r = client.get(f"/api/documents/{doc_id}/pages/99/image")
    assert r.status_code == 404


def test_get_page_image_serves_png(client):
    files = {"file": ("a.pdf", _make_pdf_bytes(1), "application/pdf")}
    doc_id = client.post("/api/documents", files=files).json()["id"]
    r = client.get(f"/api/documents/{doc_id}/pages/1/image")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")


def test_get_transcription_404_when_missing(client):
    files = {"file": ("a.pdf", _make_pdf_bytes(1), "application/pdf")}
    doc_id = client.post("/api/documents", files=files).json()["id"]
    r = client.get(f"/api/documents/{doc_id}/pages/1/transcription")
    assert r.status_code == 404


def test_get_transcription_returns_payload(client):
    files = {"file": ("a.pdf", _make_pdf_bytes(1), "application/pdf")}
    doc_id = client.post("/api/documents", files=files).json()["id"]
    payload = {
        "page": 1, "engine": "ocr", "provider": "x", "markdown": "hi",
        "raw": "", "tokens": [], "annotations": {}, "meta": {}, "created_at": "",
    }
    storage.save_transcription(doc_id, 1, payload)
    r = client.get(f"/api/documents/{doc_id}/pages/1/transcription")
    assert r.status_code == 200
    assert r.json()["markdown"] == "hi"
