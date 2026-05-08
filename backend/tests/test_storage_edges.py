from __future__ import annotations

from pathlib import Path

import pytest

from app.services import storage
from app.services.storage import _atomic_write_text


def test_atomic_write_no_leftover_tmp(tmp_path: Path):
    target = tmp_path / "out.json"
    _atomic_write_text(target, "hello")
    assert target.read_text() == "hello"
    # No `.tmp` file remains on success.
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_atomic_write_overwrites_preexisting_tmp(tmp_path: Path):
    target = tmp_path / "out.json"
    stale = target.with_suffix(target.suffix + ".tmp")
    stale.write_text("garbage from a prior crashed write")
    # Second write should succeed and clean the tmp.
    _atomic_write_text(target, "fresh")
    assert target.read_text() == "fresh"
    assert not stale.exists()


def test_atomic_write_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "x.json"
    _atomic_write_text(target, "ok")
    assert target.read_text() == "ok"


def test_update_job_missing_id_raises_keyerror(isolated_data_dir):
    with pytest.raises(KeyError):
        storage.update_job("does-not-exist", status="failed")


def test_list_documents_recent_first(isolated_data_dir, tmp_path: Path):
    """`list_documents` is documented as recent-first by `created_at`."""
    a_src = tmp_path / "a.pdf"
    a_src.write_bytes(b"%PDF a")
    a = storage.create_document(name="a.pdf", source_type="pdf", page_count=1, original_path=a_src)

    # Force a's created_at into the past so b is unambiguously newer.
    import json
    meta_path = storage.document_dir(a["id"]) / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["created_at"] = "2020-01-01T00:00:00+00:00"
    meta_path.write_text(json.dumps(meta))

    b_src = tmp_path / "b.pdf"
    b_src.write_bytes(b"%PDF b")
    b = storage.create_document(name="b.pdf", source_type="pdf", page_count=1, original_path=b_src)

    listed = storage.list_documents()
    assert [d["id"] for d in listed] == [b["id"], a["id"]]


def test_japanese_strings_round_trip_through_json(isolated_data_dir, tmp_path: Path):
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF")
    doc = storage.create_document(name="本.pdf", source_type="pdf", page_count=1, original_path=src)
    ch = storage.create_chapter(doc["id"], title="第14課 旅", page_start=1, page_end=1)
    region = storage.create_region(
        doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage", label="本文（前半）"
    )
    # Round-trip via on-disk read.
    assert storage.load_document(doc["id"])["name"] == "本.pdf"
    assert storage.load_chapter(doc["id"], ch["id"])["title"] == "第14課 旅"
    assert storage.load_region(doc["id"], ch["id"], region["id"])["label"] == "本文（前半）"
