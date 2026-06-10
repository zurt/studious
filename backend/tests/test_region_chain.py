from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import region_chain, storage


def _make_doc(tmp_path: Path) -> dict:
    src = tmp_path / "fake.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    return storage.create_document(
        name="fake.pdf", source_type="pdf", page_count=10, original_path=src
    )


def _setup_chapter_with_two_regions(tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=10)
    r1 = storage.create_region(
        doc["id"], ch["id"], page=1, bbox=[0.0, 0.0, 1.0, 0.5], tag="reading_passage"
    )
    r2 = storage.create_region(
        doc["id"], ch["id"], page=2, bbox=[0.0, 0.0, 1.0, 0.5], tag="reading_passage"
    )
    storage.update_region(doc["id"], ch["id"], r1["id"], transcription_md="HEAD")
    storage.update_region(doc["id"], ch["id"], r2["id"], transcription_md="TAIL")
    return doc, ch, r1, r2


def test_resolve_chain_single_region(isolated_data_dir, tmp_path: Path):
    doc, ch, r1, _ = _setup_chapter_with_two_regions(tmp_path)
    chain = region_chain.resolve_chain(doc["id"], ch["id"], r1["id"])
    assert [r["id"] for r in chain] == [r1["id"]]


def test_resolve_chain_walks_pointer(isolated_data_dir, tmp_path: Path):
    doc, ch, r1, r2 = _setup_chapter_with_two_regions(tmp_path)
    storage.update_region(doc["id"], ch["id"], r1["id"], continues_to=r2["id"])
    chain = region_chain.resolve_chain(doc["id"], ch["id"], r1["id"])
    assert [r["id"] for r in chain] == [r1["id"], r2["id"]]
    combined = region_chain.combined_transcription(chain)
    assert "HEAD" in combined and "TAIL" in combined
    assert "continues on page 2" in combined


def test_resolve_chain_cycle_guard(isolated_data_dir, tmp_path: Path):
    doc, ch, r1, r2 = _setup_chapter_with_two_regions(tmp_path)
    # Manually write a cycle via storage (bypassing API validation).
    storage.update_region(doc["id"], ch["id"], r1["id"], continues_to=r2["id"])
    storage.update_region(doc["id"], ch["id"], r2["id"], continues_to=r1["id"])
    chain = region_chain.resolve_chain(doc["id"], ch["id"], r1["id"])
    assert [r["id"] for r in chain] == [r1["id"], r2["id"]]


def test_resolve_chain_missing_target(isolated_data_dir, tmp_path: Path):
    doc, ch, r1, _ = _setup_chapter_with_two_regions(tmp_path)
    storage.update_region(doc["id"], ch["id"], r1["id"], continues_to="missing-id")
    chain = region_chain.resolve_chain(doc["id"], ch["id"], r1["id"])
    assert [r["id"] for r in chain] == [r1["id"]]


def test_link_api_happy_path(isolated_data_dir, tmp_path: Path):
    doc, ch, r1, r2 = _setup_chapter_with_two_regions(tmp_path)
    client = TestClient(app)
    r = client.post(
        f"/api/documents/{doc['id']}/chapters/{ch['id']}/regions/{r1['id']}/link",
        json={"continues_to": r2["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["continues_to"] == r2["id"]

    # Unlink
    r = client.post(
        f"/api/documents/{doc['id']}/chapters/{ch['id']}/regions/{r1['id']}/link",
        json={"continues_to": None},
    )
    assert r.status_code == 200
    assert r.json()["continues_to"] is None


def test_link_api_rejects_backward(isolated_data_dir, tmp_path: Path):
    doc, ch, r1, r2 = _setup_chapter_with_two_regions(tmp_path)
    client = TestClient(app)
    r = client.post(
        f"/api/documents/{doc['id']}/chapters/{ch['id']}/regions/{r2['id']}/link",
        json={"continues_to": r1["id"]},
    )
    assert r.status_code == 400


def test_link_api_rejects_cycle(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=10)
    r1 = storage.create_region(doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 0.5], tag="reading_passage")
    r2 = storage.create_region(doc["id"], ch["id"], page=2, bbox=[0, 0, 1, 0.5], tag="reading_passage")
    r3 = storage.create_region(doc["id"], ch["id"], page=3, bbox=[0, 0, 1, 0.5], tag="reading_passage")
    storage.update_region(doc["id"], ch["id"], r1["id"], continues_to=r2["id"])
    storage.update_region(doc["id"], ch["id"], r2["id"], continues_to=r3["id"])
    client = TestClient(app)
    # r3 -> r1 would create r1->r2->r3->r1.
    r = client.post(
        f"/api/documents/{doc['id']}/chapters/{ch['id']}/regions/{r3['id']}/link",
        json={"continues_to": r1["id"]},
    )
    assert r.status_code == 400


def test_delete_clears_inbound_link(isolated_data_dir, tmp_path: Path):
    doc, ch, r1, r2 = _setup_chapter_with_two_regions(tmp_path)
    storage.update_region(doc["id"], ch["id"], r1["id"], continues_to=r2["id"])
    storage.delete_region(doc["id"], ch["id"], r2["id"])
    reloaded = storage.load_region(doc["id"], ch["id"], r1["id"])
    assert reloaded is not None
    assert reloaded.get("continues_to") is None
