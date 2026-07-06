from __future__ import annotations

from pathlib import Path

from app.services import bulk_ops, storage


def _make_doc(tmp_path: Path) -> dict:
    src = tmp_path / "fake.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    return storage.create_document(
        name="fake.pdf", source_type="pdf", page_count=5, original_path=src
    )


def test_select_transcribe_targets_skips_transcribed_unless_overwrite(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=3)
    done = storage.create_region(doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage")
    storage.update_region(doc["id"], ch["id"], done["id"], transcription_md="already done")
    pending = storage.create_region(doc["id"], ch["id"], page=2, bbox=[0, 0, 1, 1], tag="vocab_list")

    targets = bulk_ops.select_transcribe_targets(doc["id"], ch["id"])
    assert [r["id"] for r in targets] == [pending["id"]]

    widened = bulk_ops.select_transcribe_targets(doc["id"], ch["id"], overwrite=True)
    assert {r["id"] for r in widened} == {done["id"], pending["id"]}


def test_select_breakdown_targets_excludes_vocab_list_and_untranscribed(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=3)
    vocab = storage.create_region(doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="vocab_list")
    storage.update_region(doc["id"], ch["id"], vocab["id"], transcription_md="本（ほん）book")
    storage.create_region(doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage")  # untranscribed
    ready = storage.create_region(doc["id"], ch["id"], page=2, bbox=[0, 0, 1, 1], tag="reading_passage")
    storage.update_region(doc["id"], ch["id"], ready["id"], transcription_md="一文。")

    targets = bulk_ops.select_breakdown_targets(doc["id"], ch["id"])
    assert [r["id"] for r in targets] == [ready["id"]]


def test_select_breakdown_targets_excludes_continuation_targets(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=3)
    head = storage.create_region(doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage")
    storage.update_region(doc["id"], ch["id"], head["id"], transcription_md="一文。")
    tail = storage.create_region(doc["id"], ch["id"], page=2, bbox=[0, 0, 1, 1], tag="reading_passage")
    storage.update_region(doc["id"], ch["id"], tail["id"], transcription_md="二文。")
    storage.update_region(doc["id"], ch["id"], head["id"], continues_to=tail["id"])

    # Only the head is a breakdown candidate — the tail is a continuation
    # target and generates from the head's chain instead.
    targets = bulk_ops.select_breakdown_targets(doc["id"], ch["id"])
    assert [r["id"] for r in targets] == [head["id"]]


def test_select_breakdown_targets_overwrite_widens_plan(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=3)
    region = storage.create_region(doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage")
    storage.update_region(doc["id"], ch["id"], region["id"], transcription_md="一文。")
    storage.save_breakdown(
        doc["id"], ch["id"], region["id"], {"sentences": [{"text": "一文。", "gloss": "x"}]}
    )

    assert bulk_ops.select_breakdown_targets(doc["id"], ch["id"]) == []
    widened = bulk_ops.select_breakdown_targets(doc["id"], ch["id"], overwrite=True)
    assert [r["id"] for r in widened] == [region["id"]]


def test_select_targets_order_matches_list_regions(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=3)
    r2 = storage.create_region(doc["id"], ch["id"], page=2, bbox=[0, 0, 1, 1], tag="other")
    r1 = storage.create_region(doc["id"], ch["id"], page=1, bbox=[0, 0, 1, 1], tag="other")

    targets = bulk_ops.select_transcribe_targets(doc["id"], ch["id"])
    assert [r["id"] for r in targets] == [r1["id"], r2["id"]]
