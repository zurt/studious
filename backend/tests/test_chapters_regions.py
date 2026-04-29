from __future__ import annotations

from pathlib import Path

from app.services import storage


def _make_doc(tmp_path: Path) -> dict:
    src = tmp_path / "fake.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    meta = storage.create_document(
        name="fake.pdf", source_type="pdf", page_count=10, original_path=src
    )
    return meta


def test_chapter_crud(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]

    # Create
    ch = storage.create_chapter(doc_id, title="Chapter 1", page_start=1, page_end=5, order=1)
    assert ch["title"] == "Chapter 1"
    assert ch["page_start"] == 1
    assert ch["page_end"] == 5
    assert ch["doc_id"] == doc_id

    # Load
    loaded = storage.load_chapter(doc_id, ch["id"])
    assert loaded == ch

    # List
    ch2 = storage.create_chapter(doc_id, title="Chapter 2", page_start=6, page_end=10, order=2)
    chapters = storage.list_chapters(doc_id)
    assert len(chapters) == 2
    assert chapters[0]["order"] == 1
    assert chapters[1]["order"] == 2

    # Update
    updated = storage.update_chapter(doc_id, ch["id"], title="Ch 1 Revised")
    assert updated["title"] == "Ch 1 Revised"
    assert storage.load_chapter(doc_id, ch["id"])["title"] == "Ch 1 Revised"

    # Delete
    assert storage.delete_chapter(doc_id, ch2["id"])
    assert storage.load_chapter(doc_id, ch2["id"]) is None
    assert len(storage.list_chapters(doc_id)) == 1

    # Delete nonexistent
    assert not storage.delete_chapter(doc_id, "nonexistent")

    # Load nonexistent
    assert storage.load_chapter(doc_id, "nonexistent") is None


def test_region_crud(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)

    # Create
    region = storage.create_region(
        doc_id, ch["id"],
        page=2, bbox=[0.1, 0.2, 0.9, 0.8], tag="reading_passage", label="本文",
    )
    assert region["page"] == 2
    assert region["bbox"] == [0.1, 0.2, 0.9, 0.8]
    assert region["tag"] == "reading_passage"
    assert region["transcription_md"] is None
    assert region["transcribed_at"] is None
    assert region["transcribed_model"] is None

    # Load
    loaded = storage.load_region(doc_id, ch["id"], region["id"])
    assert loaded == region

    # List
    r2 = storage.create_region(
        doc_id, ch["id"],
        page=3, bbox=[0.0, 0.0, 1.0, 0.5], tag="vocab_list",
    )
    regions = storage.list_regions(doc_id, ch["id"])
    assert len(regions) == 2
    assert regions[0]["page"] <= regions[1]["page"]

    # Update transcription
    updated = storage.update_region(
        doc_id, ch["id"], region["id"],
        transcription_md="# Hello",
        transcribed_at="2026-04-27T12:00:00Z",
        transcribed_model="claude-sonnet-4-6",
    )
    assert updated["transcription_md"] == "# Hello"
    assert updated["transcribed_at"] == "2026-04-27T12:00:00Z"
    assert updated["transcribed_model"] == "claude-sonnet-4-6"
    assert storage.load_region(doc_id, ch["id"], region["id"])["transcription_md"] == "# Hello"

    # Delete
    assert storage.delete_region(doc_id, ch["id"], r2["id"])
    assert storage.load_region(doc_id, ch["id"], r2["id"]) is None
    assert len(storage.list_regions(doc_id, ch["id"])) == 1

    # Delete nonexistent
    assert not storage.delete_region(doc_id, ch["id"], "nonexistent")

    # Load nonexistent
    assert storage.load_region(doc_id, ch["id"], "nonexistent") is None


def test_delete_chapter_cascades_regions(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)
    storage.create_region(doc_id, ch["id"], page=1, bbox=[0, 0, 1, 1], tag="other")
    storage.create_region(doc_id, ch["id"], page=2, bbox=[0, 0, 1, 1], tag="other")

    assert len(storage.list_regions(doc_id, ch["id"])) == 2
    storage.delete_chapter(doc_id, ch["id"])
    assert storage.list_regions(doc_id, ch["id"]) == []
