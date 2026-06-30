from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import REGION_TRANSCRIBE_PROMPT, VOCAB_LIST_TRANSCRIBE_PROMPT
from app.main import app
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


def test_move_region_between_chapters(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    src = storage.create_chapter(doc_id, title="Src", page_start=1, page_end=3)
    dst = storage.create_chapter(doc_id, title="Dst", page_start=4, page_end=8)
    region = storage.create_region(
        doc_id, src["id"], page=2, bbox=[0, 0, 1, 1], tag="other"
    )
    storage.update_region(
        doc_id, src["id"], region["id"], transcription_md="# preserved"
    )

    moved = storage.move_region(doc_id, src["id"], region["id"], dst["id"])
    assert moved is not None
    assert moved["chapter_id"] == dst["id"]
    assert moved["transcription_md"] == "# preserved"

    assert storage.load_region(doc_id, src["id"], region["id"]) is None
    landed = storage.load_region(doc_id, dst["id"], region["id"])
    assert landed is not None
    assert landed["transcription_md"] == "# preserved"


def test_move_region_missing_returns_none(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    src = storage.create_chapter(doc_id, title="Src", page_start=1, page_end=3)
    dst = storage.create_chapter(doc_id, title="Dst", page_start=4, page_end=8)
    assert storage.move_region(doc_id, src["id"], "nope", dst["id"]) is None


def test_transcribe_region_picks_prompt_by_tag(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)

    img_path = storage.page_image_path(doc_id, 2)
    img_path.parent.mkdir(parents=True, exist_ok=True)
    img_path.write_bytes(b"fake-png")

    vocab = storage.create_region(
        doc_id, ch["id"], page=2, bbox=[0, 0, 1, 1], tag="vocab_list"
    )
    passage = storage.create_region(
        doc_id, ch["id"], page=2, bbox=[0, 0, 1, 1], tag="reading_passage"
    )

    client = TestClient(app)
    r = client.post(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/{vocab['id']}/transcribe"
    )
    assert r.status_code == 200
    job = storage.load_job(r.json()["job_id"])
    assert job["prompt"] == VOCAB_LIST_TRANSCRIBE_PROMPT

    r = client.post(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/{passage['id']}/transcribe"
    )
    assert r.status_code == 200
    job = storage.load_job(r.json()["job_id"])
    assert job["prompt"] == REGION_TRANSCRIBE_PROMPT


def test_breakdown_endpoints_request_validation(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)
    client = TestClient(app)

    # 404 when no breakdown exists yet
    untouched = storage.create_region(
        doc_id, ch["id"], page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    r = client.get(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/{untouched['id']}/breakdown"
    )
    assert r.status_code == 404

    # 400 on vocab_list
    vocab = storage.create_region(
        doc_id, ch["id"], page=1, bbox=[0, 0, 1, 1], tag="vocab_list"
    )
    storage.update_region(
        doc_id, ch["id"], vocab["id"], transcription_md="本（ほん）book"
    )
    r = client.post(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/{vocab['id']}/breakdown"
    )
    assert r.status_code == 400

    # 409 when no transcription
    no_tx = storage.create_region(
        doc_id, ch["id"], page=2, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    r = client.post(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/{no_tx['id']}/breakdown"
    )
    assert r.status_code == 409

    # 404 region not found
    r = client.post(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/missing/breakdown"
    )
    assert r.status_code == 404


def test_breakdown_post_overwrite_semantics(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)
    region = storage.create_region(
        doc_id, ch["id"], page=2, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    storage.update_region(
        doc_id, ch["id"], region["id"], transcription_md="一文目。二文目。"
    )
    # Pre-existing breakdown
    storage.save_breakdown(
        doc_id,
        ch["id"],
        region["id"],
        {"sentences": [{"text": "一文目。", "gloss": "first"}]},
    )

    client = TestClient(app)

    # Without overwrite → 409
    r = client.post(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/{region['id']}/breakdown"
    )
    assert r.status_code == 409

    # With overwrite → 202 + job submitted with the breakdown prompt + schema
    r = client.post(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/{region['id']}/breakdown",
        json={"overwrite": True},
    )
    assert r.status_code == 202
    job = storage.load_job(r.json()["job_id"])
    assert job["job_type"] == "breakdown_region"
    assert job["tool_name"] == "record_breakdown"
    assert job["config"]["max_tokens"] == 16384
    assert job["tool_schema"]["type"] == "object"
    assert "sentences" in job["tool_schema"]["required"]


def test_get_breakdown_returns_stored_payload(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)
    region = storage.create_region(
        doc_id, ch["id"], page=2, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    storage.save_breakdown(
        doc_id,
        ch["id"],
        region["id"],
        {
            "model": "claude-opus-4-7",
            "sentences": [{"text": "本", "gloss": "book"}],
        },
    )
    client = TestClient(app)
    r = client.get(
        f"/api/documents/{doc_id}/chapters/{ch['id']}/regions/{region['id']}/breakdown"
    )
    assert r.status_code == 200
    body = r.json()
    # GET lazy-fills `links` for breakdowns saved before the link feature.
    assert body["sentences"] == [{"text": "本", "gloss": "book", "links": []}]
    assert body["region_id"] == region["id"]
    assert body["model"] == "claude-opus-4-7"


def _exercise_region_with_breakdown(tmp_path: Path) -> tuple[str, str, str]:
    """Helper: create an exercises region with a transcription + 2-sentence breakdown."""
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)
    region = storage.create_region(
        doc_id, ch["id"], page=1, bbox=[0, 0, 1, 1], tag="exercises"
    )
    storage.update_region(
        doc_id, ch["id"], region["id"],
        transcription_md="1. 私は学校＿＿行く。\n2. 友達＿＿映画を見た。",
    )
    storage.save_breakdown(
        doc_id, ch["id"], region["id"],
        {"sentences": [
            {"text": "1. 私は学校＿＿行く。", "gloss": "I go ___ school."},
            {"text": "2. 友達＿＿映画を見た。", "gloss": "I saw a movie ___ a friend."},
        ]},
    )
    return doc_id, ch["id"], region["id"]


def test_exercise_completion_request_validation(isolated_data_dir, tmp_path: Path):
    doc_id, chapter_id, region_id = _exercise_region_with_breakdown(tmp_path)
    base = f"/api/documents/{doc_id}/chapters/{chapter_id}/regions"
    client = TestClient(app)

    # GET 404 when no completion exists
    r = client.get(f"{base}/{region_id}/exercise-completion")
    assert r.status_code == 404

    # POST 400 on non-exercise region
    other = storage.create_region(
        doc_id, chapter_id, page=1, bbox=[0, 0, 1, 1], tag="reading_passage"
    )
    r = client.post(
        f"{base}/{other['id']}/exercise-completion",
        json={"sentence_index": 0},
    )
    assert r.status_code == 400

    # POST 409 when no breakdown yet
    no_bd = storage.create_region(
        doc_id, chapter_id, page=1, bbox=[0, 0, 1, 1], tag="exercises"
    )
    r = client.post(
        f"{base}/{no_bd['id']}/exercise-completion",
        json={"sentence_index": 0},
    )
    assert r.status_code == 409

    # POST 400 when sentence_index is out of range
    r = client.post(
        f"{base}/{region_id}/exercise-completion",
        json={"sentence_index": 5},
    )
    assert r.status_code == 400

    # POST 404 region not found
    r = client.post(
        f"{base}/missing/exercise-completion",
        json={"sentence_index": 0},
    )
    assert r.status_code == 404


def test_exercise_completion_submit_and_overwrite(isolated_data_dir, tmp_path: Path):
    doc_id, chapter_id, region_id = _exercise_region_with_breakdown(tmp_path)
    base = f"/api/documents/{doc_id}/chapters/{chapter_id}/regions"
    client = TestClient(app)

    # Initial POST → 202, job carries the target sentence and region context
    r = client.post(
        f"{base}/{region_id}/exercise-completion",
        json={"sentence_index": 0},
    )
    assert r.status_code == 202
    job = storage.load_job(r.json()["job_id"])
    assert job["job_type"] == "exercise_completion"
    assert job["tool_name"] == "record_exercise_completion"
    assert job["sentence_index"] == 0
    assert job["sentence_text"] == "1. 私は学校＿＿行く。"
    assert "友達" in job["region_transcription"]
    assert job["tool_schema"]["properties"]["examples"]["minItems"] == 3
    # Budget must be large enough for answer + three fully-glossed examples;
    # 2048 truncated longer items mid-`examples`. See docs/troubleshooting.md.
    assert job["config"]["max_tokens"] == 8192

    # Seed an existing completion at idx=0 → second POST without overwrite 409s
    storage.upsert_exercise_completion_entry(
        doc_id, chapter_id, region_id, 0,
        {"answer": "に", "examples": [{"japanese": "a", "reading": "a", "english": "a", "explanation": "a"}]},
    )
    r = client.post(
        f"{base}/{region_id}/exercise-completion",
        json={"sentence_index": 0},
    )
    assert r.status_code == 409

    # overwrite=True → 202
    r = client.post(
        f"{base}/{region_id}/exercise-completion",
        json={"sentence_index": 0, "overwrite": True},
    )
    assert r.status_code == 202

    # A *different* sentence_index without overwrite is allowed
    r = client.post(
        f"{base}/{region_id}/exercise-completion",
        json={"sentence_index": 1},
    )
    assert r.status_code == 202


def test_get_exercise_completion_returns_stored_payload(isolated_data_dir, tmp_path: Path):
    doc_id, chapter_id, region_id = _exercise_region_with_breakdown(tmp_path)
    storage.upsert_exercise_completion_entry(
        doc_id, chapter_id, region_id, 0,
        {
            "answer": "に",
            "explanation": "Direction particle.",
            "examples": [
                {"japanese": "学校に行く。", "reading": "がっこうにいく。",
                 "english": "I go to school.", "explanation": "に marks destination."},
            ],
        },
    )
    client = TestClient(app)
    r = client.get(
        f"/api/documents/{doc_id}/chapters/{chapter_id}/regions/{region_id}/exercise-completion"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["region_id"] == region_id
    assert "0" in body["completions"]
    assert body["completions"]["0"]["answer"] == "に"


def test_breakdown_regeneration_clears_completions(isolated_data_dir, tmp_path: Path):
    """When a breakdown is regenerated the saved completions become index-stale, so
    `save_breakdown` (via the job) must drop them."""
    doc_id, chapter_id, region_id = _exercise_region_with_breakdown(tmp_path)
    storage.upsert_exercise_completion_entry(
        doc_id, chapter_id, region_id, 0,
        {"answer": "に", "examples": []},
    )
    assert storage.load_exercise_completion(doc_id, chapter_id, region_id) is not None

    # Simulate the job's save → delete sequence
    storage.save_breakdown(
        doc_id, chapter_id, region_id,
        {"sentences": [{"text": "different.", "gloss": "different"}]},
    )
    storage.delete_exercise_completion(doc_id, chapter_id, region_id)
    assert storage.load_exercise_completion(doc_id, chapter_id, region_id) is None


def test_region_delete_cascades_exercise_completion(isolated_data_dir, tmp_path: Path):
    doc_id, chapter_id, region_id = _exercise_region_with_breakdown(tmp_path)
    storage.upsert_exercise_completion_entry(
        doc_id, chapter_id, region_id, 0,
        {"answer": "x", "examples": []},
    )
    p = storage.exercise_completion_path(doc_id, chapter_id, region_id)
    assert p.exists()
    storage.delete_region(doc_id, chapter_id, region_id)
    assert not p.exists()


def test_delete_chapter_cascades_regions(isolated_data_dir, tmp_path: Path):
    doc = _make_doc(tmp_path)
    doc_id = doc["id"]
    ch = storage.create_chapter(doc_id, title="Ch", page_start=1, page_end=5)
    storage.create_region(doc_id, ch["id"], page=1, bbox=[0, 0, 1, 1], tag="other")
    storage.create_region(doc_id, ch["id"], page=2, bbox=[0, 0, 1, 1], tag="other")

    assert len(storage.list_regions(doc_id, ch["id"])) == 2
    storage.delete_chapter(doc_id, ch["id"])
    assert storage.list_regions(doc_id, ch["id"]) == []
