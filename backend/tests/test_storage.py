from __future__ import annotations

from pathlib import Path

from app.services import storage


def _make_fake_pdf(tmp: Path) -> Path:
    p = tmp / "fake.pdf"
    p.write_bytes(b"%PDF-1.4 fake content")
    return p


def test_create_and_load_document(isolated_data_dir, tmp_path: Path):
    src = _make_fake_pdf(tmp_path)
    meta = storage.create_document(
        name="fake.pdf", source_type="pdf", page_count=3, original_path=src
    )
    assert meta["page_count"] == 3
    assert meta["source_type"] == "pdf"
    loaded = storage.load_document(meta["id"])
    assert loaded == meta
    assert (storage.document_dir(meta["id"]) / "original.pdf").exists()


def test_save_and_load_transcription(isolated_data_dir, tmp_path: Path):
    src = _make_fake_pdf(tmp_path)
    meta = storage.create_document(
        name="x.pdf", source_type="pdf", page_count=2, original_path=src
    )
    payload = {
        "page": 1,
        "engine": "ocr",
        "provider": "tesseract",
        "markdown": "# hi\n\n本",
        "raw": "hi\n本",
        "tokens": [],
        "annotations": {},
        "meta": {},
        "created_at": "2026-04-23T00:00:00Z",
        "duration_ms": 12,
    }
    storage.save_transcription(meta["id"], 1, payload)
    assert storage.load_transcription(meta["id"], 1) == payload
    assert storage.load_transcription(meta["id"], 2) is None
    assert storage.transcribed_pages(meta["id"]) == [1]


def test_list_documents_returns_recent_first(isolated_data_dir, tmp_path: Path):
    a = storage.create_document(
        name="a.pdf", source_type="pdf", page_count=1, original_path=_make_fake_pdf(tmp_path)
    )
    b = storage.create_document(
        name="b.pdf", source_type="pdf", page_count=1, original_path=_make_fake_pdf(tmp_path)
    )
    ids = [d["id"] for d in storage.list_documents()]
    assert set(ids) == {a["id"], b["id"]}


def test_jobs_round_trip(isolated_data_dir):
    job = storage.create_job(
        {"doc_id": "abc", "engine": "ocr", "provider": "tesseract", "pages": [1, 2]}
    )
    assert job["status"] == "queued"
    assert storage.load_job(job["id"]) == job
    updated = storage.update_job(job["id"], status="running", current_page=1)
    assert updated["status"] == "running"
    assert storage.load_job(job["id"]) == updated
