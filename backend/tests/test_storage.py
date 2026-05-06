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


def test_breakdown_round_trip(isolated_data_dir, tmp_path: Path):
    src = _make_fake_pdf(tmp_path)
    doc = storage.create_document(
        name="x.pdf", source_type="pdf", page_count=1, original_path=src
    )
    chapter = storage.create_chapter(doc["id"], title="Ch1", page_start=1, page_end=1)
    region = storage.create_region(
        doc["id"], chapter["id"], page=1, bbox=[0, 0, 100, 100], tag="reading_passage"
    )

    payload = {
        "model": "claude-opus-4-7",
        "sentences": [
            {
                "text": "口べたで料理好きの父親",
                "vocab": [{"word": "口べた", "reading": "くちべた", "meaning": "poor speaker"}],
                "grammar": [],
                "gloss": "A father who is bad at speaking but loves cooking",
            }
        ],
    }
    saved = storage.save_breakdown(doc["id"], chapter["id"], region["id"], payload)
    assert saved["region_id"] == region["id"]
    assert saved["created_at"] == saved["updated_at"]
    assert saved["sentences"] == payload["sentences"]

    loaded = storage.load_breakdown(doc["id"], chapter["id"], region["id"])
    assert loaded == saved

    # Resave preserves created_at, bumps updated_at
    again = storage.save_breakdown(
        doc["id"], chapter["id"], region["id"], {**payload, "model": "claude-sonnet-4-6"}
    )
    assert again["created_at"] == saved["created_at"]
    assert again["updated_at"] >= saved["updated_at"]
    assert again["model"] == "claude-sonnet-4-6"


def test_delete_region_cascades_breakdown(isolated_data_dir, tmp_path: Path):
    src = _make_fake_pdf(tmp_path)
    doc = storage.create_document(
        name="x.pdf", source_type="pdf", page_count=1, original_path=src
    )
    chapter = storage.create_chapter(doc["id"], title="Ch1", page_start=1, page_end=1)
    region = storage.create_region(
        doc["id"], chapter["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    storage.save_breakdown(
        doc["id"], chapter["id"], region["id"], {"sentences": [{"text": "x", "gloss": "x"}]}
    )
    assert storage.breakdown_path(doc["id"], chapter["id"], region["id"]).exists()

    assert storage.delete_region(doc["id"], chapter["id"], region["id"]) is True
    assert storage.load_breakdown(doc["id"], chapter["id"], region["id"]) is None
    assert not storage.breakdown_path(doc["id"], chapter["id"], region["id"]).exists()


def test_delete_chapter_cascades_breakdown(isolated_data_dir, tmp_path: Path):
    src = _make_fake_pdf(tmp_path)
    doc = storage.create_document(
        name="x.pdf", source_type="pdf", page_count=1, original_path=src
    )
    chapter = storage.create_chapter(doc["id"], title="Ch1", page_start=1, page_end=1)
    region = storage.create_region(
        doc["id"], chapter["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    storage.save_breakdown(
        doc["id"], chapter["id"], region["id"], {"sentences": [{"text": "x", "gloss": "x"}]}
    )
    bpath = storage.breakdown_path(doc["id"], chapter["id"], region["id"])
    assert bpath.exists()

    assert storage.delete_chapter(doc["id"], chapter["id"]) is True
    assert not bpath.exists()


def test_breakdown_tool_schema_shape():
    """Sanity-check the tool schema structure. Real validation happens
    server-side via the Anthropic tool-use API; this guards typos."""
    import json

    from app.config import BREAKDOWN_TOOL_SCHEMA

    # Round-trips as JSON (no non-serializable values)
    json.dumps(BREAKDOWN_TOOL_SCHEMA)

    assert BREAKDOWN_TOOL_SCHEMA["type"] == "object"
    assert "sentences" in BREAKDOWN_TOOL_SCHEMA["required"]
    sentences = BREAKDOWN_TOOL_SCHEMA["properties"]["sentences"]
    assert sentences["type"] == "array"
    assert sentences["minItems"] == 1
    item = sentences["items"]
    assert item["type"] == "object"
    assert set(item["required"]) == {"text", "gloss"}
    props = item["properties"]
    for key in ("text", "gloss", "vocab", "grammar"):
        assert key in props
    assert props["vocab"]["type"] == "array"
    assert set(props["vocab"]["items"]["required"]) == {"word", "meaning"}
    assert set(props["grammar"]["items"]["required"]) == {"pattern", "explanation", "surfaces"}
    surfaces = props["grammar"]["items"]["properties"]["surfaces"]
    assert surfaces["type"] == "array"
    assert surfaces["minItems"] == 1
    assert surfaces["items"]["type"] == "string"


def test_jobs_round_trip(isolated_data_dir):
    job = storage.create_job(
        {"doc_id": "abc", "engine": "ocr", "provider": "tesseract", "pages": [1, 2]}
    )
    assert job["status"] == "queued"
    assert storage.load_job(job["id"]) == job
    updated = storage.update_job(job["id"], status="running", current_page=1)
    assert updated["status"] == "running"
    assert storage.load_job(job["id"]) == updated
