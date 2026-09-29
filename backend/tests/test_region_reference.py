from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import region_reference, storage


def _make_doc(tmp_path: Path, name: str = "fake.pdf") -> dict:
    src = tmp_path / f"src-{name}"
    src.write_bytes(b"%PDF-1.4 fake")
    return storage.create_document(
        name=name, source_type="pdf", page_count=10, original_path=src
    )


def _reading(doc_id: str, chapter_id: str, page: int, text: str | None, *, label: str = "") -> dict:
    region = storage.create_region(
        doc_id, chapter_id, page=page, bbox=[0.0, 0.0, 1.0, 0.5], tag="reading_passage", label=label
    )
    if text is not None:
        region = storage.update_region(doc_id, chapter_id, region["id"], transcription_md=text)
    return region


def _ref(doc_id: str, chapter_id: str, region_id: str) -> dict:
    return {"doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id}


@pytest.fixture
def setup(isolated_data_dir, tmp_path: Path):
    """A textbook chapter with a two-page reading and an exercises region,
    plus a second document with its own reading."""
    doc = _make_doc(tmp_path, "生きた素材で学ぶ.pdf")
    ch = storage.create_chapter(doc["id"], title="第5課", page_start=1, page_end=10)
    r1 = _reading(doc["id"], ch["id"], 1, "本文その一")
    r2 = _reading(doc["id"], ch["id"], 2, "本文その二")
    ex = storage.create_region(
        doc["id"], ch["id"], page=2, bbox=[0.0, 0.5, 1.0, 1.0], tag="exercises"
    )
    other_doc = _make_doc(tmp_path, "other.pdf")
    other_ch = storage.create_chapter(other_doc["id"], title="Unit 3", page_start=1, page_end=10)
    other = _reading(other_doc["id"], other_ch["id"], 7, "別の本の読み物")
    return {
        "doc": doc, "ch": ch, "r1": r1, "r2": r2, "ex": ex,
        "other_doc": other_doc, "other_ch": other_ch, "other": other,
    }


def _put(client: TestClient, s: dict, refs: list[dict], *, region_id: str | None = None):
    rid = region_id or s["ex"]["id"]
    return client.put(
        f"/api/documents/{s['doc']['id']}/chapters/{s['ch']['id']}/regions/{rid}/references",
        json={"references": refs},
    )


# ---------- storage ----------


def test_new_region_defaults_to_no_references(setup):
    assert setup["ex"]["references"] == []
    loaded = storage.load_region(setup["doc"]["id"], setup["ch"]["id"], setup["ex"]["id"])
    assert loaded["references"] == []


# ---------- resolve_references ----------


def test_resolve_preserves_order_across_documents(setup):
    s = setup
    refs = [
        _ref(s["other_doc"]["id"], s["other_ch"]["id"], s["other"]["id"]),
        _ref(s["doc"]["id"], s["ch"]["id"], s["r2"]["id"]),
        _ref(s["doc"]["id"], s["ch"]["id"], s["r1"]["id"]),
    ]
    storage.update_region(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"], references=refs)

    resolved = region_reference.resolve_references(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"])

    assert [r["region_id"] for r in resolved] == [s["other"]["id"], s["r2"]["id"], s["r1"]["id"]]
    assert resolved[0]["doc_name"] == "other.pdf"
    assert resolved[0]["chapter_title"] == "Unit 3"
    assert resolved[0]["page"] == 7
    assert resolved[0]["transcription_md"] == "別の本の読み物"


def test_resolve_skips_missing_and_untranscribed_targets(setup):
    s = setup
    blank = _reading(s["doc"]["id"], s["ch"]["id"], 3, None)
    refs = [
        _ref(s["doc"]["id"], s["ch"]["id"], "deadbeef0000"),  # deleted region
        _ref("feedface0000", s["ch"]["id"], s["r1"]["id"]),  # deleted document
        _ref(s["doc"]["id"], "cafebabe0000", s["r1"]["id"]),  # deleted chapter
        _ref(s["doc"]["id"], s["ch"]["id"], blank["id"]),  # not transcribed yet
        {"doc_id": "../etc", "chapter_id": "x", "region_id": "y"},  # unsafe id
        "not-a-dict",
        _ref(s["doc"]["id"], s["ch"]["id"], s["r1"]["id"]),
    ]
    storage.update_region(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"], references=refs)

    resolved = region_reference.resolve_references(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"])

    assert [r["region_id"] for r in resolved] == [s["r1"]["id"]]


def test_resolve_region_without_references_field(setup):
    # Regions created before this feature have no `references` key at all.
    s = setup
    path = storage._region_path(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"])
    import json

    data = json.loads(path.read_text("utf-8"))
    del data["references"]
    path.write_text(json.dumps(data), "utf-8")
    assert region_reference.resolve_references(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"]) == []
    assert region_reference.resolve_references(s["doc"]["id"], s["ch"]["id"], "nope00000000") == []


# ---------- combined_reference_text ----------


def test_combined_text_groups_consecutive_same_chapter_regions(setup):
    s = setup
    refs = [
        _ref(s["doc"]["id"], s["ch"]["id"], s["r1"]["id"]),
        _ref(s["doc"]["id"], s["ch"]["id"], s["r2"]["id"]),
        _ref(s["other_doc"]["id"], s["other_ch"]["id"], s["other"]["id"]),
    ]
    storage.update_region(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"], references=refs)
    resolved = region_reference.resolve_references(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"])

    text = region_reference.combined_reference_text(resolved)

    # One passage split over two pages gets one source line, not one per
    # region — a per-region label would land mid-sentence at a page break.
    assert text == (
        "[Source: 生きた素材で学ぶ.pdf — chapter \"第5課\", pp.1–2]\n"
        "本文その一\n\n本文その二\n\n"
        "[Source: other.pdf — chapter \"Unit 3\", p.7]\n"
        "別の本の読み物"
    )


def test_combined_text_splits_on_label_change(setup):
    s = setup
    a = _reading(s["doc"]["id"], s["ch"]["id"], 3, "読み物A", label="本文")
    b = _reading(s["doc"]["id"], s["ch"]["id"], 3, "読み物B", label="読み物")
    storage.update_region(
        s["doc"]["id"], s["ch"]["id"], s["ex"]["id"],
        references=[_ref(s["doc"]["id"], s["ch"]["id"], a["id"]), _ref(s["doc"]["id"], s["ch"]["id"], b["id"])],
    )
    resolved = region_reference.resolve_references(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"])

    text = region_reference.combined_reference_text(resolved)

    assert text == (
        "[Source: 生きた素材で学ぶ.pdf — chapter \"第5課\", 本文, p.3]\n読み物A\n\n"
        "[Source: 生きた素材で学ぶ.pdf — chapter \"第5課\", 読み物, p.3]\n読み物B"
    )


def test_combined_text_empty():
    assert region_reference.combined_reference_text([]) == ""


# ---------- PUT .../references ----------


def test_put_references_replaces_whole_list(setup):
    s = setup
    client = TestClient(app)
    first = [
        _ref(s["doc"]["id"], s["ch"]["id"], s["r1"]["id"]),
        _ref(s["doc"]["id"], s["ch"]["id"], s["r2"]["id"]),
    ]
    r = _put(client, s, first)
    assert r.status_code == 200, r.text
    assert r.json()["references"] == first

    second = [
        _ref(s["other_doc"]["id"], s["other_ch"]["id"], s["other"]["id"]),
        _ref(s["doc"]["id"], s["ch"]["id"], s["r1"]["id"]),
    ]
    r = _put(client, s, second)
    assert r.status_code == 200, r.text
    stored = storage.load_region(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"])
    assert stored["references"] == second

    r = _put(client, s, [])
    assert r.status_code == 200, r.text
    assert storage.load_region(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"])["references"] == []


def test_put_references_drops_duplicates_keeping_first_position(setup):
    s = setup
    client = TestClient(app)
    r1 = _ref(s["doc"]["id"], s["ch"]["id"], s["r1"]["id"])
    r2 = _ref(s["doc"]["id"], s["ch"]["id"], s["r2"]["id"])
    r = _put(client, s, [r1, r2, r1])
    assert r.status_code == 200, r.text
    assert r.json()["references"] == [r1, r2]


def test_put_references_rejects_non_exercises_source(setup):
    s = setup
    client = TestClient(app)
    r = _put(client, s, [], region_id=s["r1"]["id"])
    assert r.status_code == 400
    assert "exercises" in r.json()["detail"]


def test_put_references_rejects_non_reading_target(setup):
    s = setup
    vocab = storage.create_region(
        s["doc"]["id"], s["ch"]["id"], page=1, bbox=[0.0, 0.5, 1.0, 1.0], tag="vocab_list"
    )
    client = TestClient(app)
    r = _put(client, s, [_ref(s["doc"]["id"], s["ch"]["id"], vocab["id"])])
    assert r.status_code == 400
    assert "reading_passage" in r.json()["detail"]
    # Nothing was written.
    assert storage.load_region(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"])["references"] == []


@pytest.mark.parametrize("missing", ["doc", "chapter", "region"])
def test_put_references_404_on_missing_target(setup, missing):
    s = setup
    ref = _ref(s["doc"]["id"], s["ch"]["id"], s["r1"]["id"])
    ref[f"{missing}_id"] = "000000000000"
    client = TestClient(app)
    r = _put(client, s, [ref])
    assert r.status_code == 404
    assert missing in r.json()["detail"]


def test_put_references_404_on_missing_source(setup):
    client = TestClient(app)
    r = _put(client, setup, [], region_id="000000000000")
    assert r.status_code == 404


def test_put_references_404_on_unsafe_target_id(setup):
    # Path-unsafe ids are treated as not-found app-wide (main.py handler).
    s = setup
    client = TestClient(app)
    r = _put(client, s, [{"doc_id": "../x", "chapter_id": s["ch"]["id"], "region_id": s["r1"]["id"]}])
    assert r.status_code == 404


def test_put_references_rejects_continuation_region(setup):
    # References belong to the chain head, which is where completions run.
    s = setup
    tail = storage.create_region(
        s["doc"]["id"], s["ch"]["id"], page=3, bbox=[0.0, 0.0, 1.0, 0.5], tag="exercises"
    )
    storage.update_region(s["doc"]["id"], s["ch"]["id"], s["ex"]["id"], continues_to=tail["id"])
    client = TestClient(app)
    r = _put(client, s, [], region_id=tail["id"])
    assert r.status_code == 409
    assert s["ex"]["id"] in r.json()["detail"]
