from __future__ import annotations

import json

from app.services import storage


def test_append_llm_audit_creates_jsonl_file(isolated_data_dir):
    entry = storage.append_llm_audit(
        {
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "job_type": "transcribe_region",
            "doc_id": "d1",
            "chapter_id": "c1",
            "region_id": "r1",
            "input_tokens": 1500,
            "output_tokens": 800,
            "duration_ms": 3200,
            "status": "success",
            "error": None,
        }
    )
    assert entry["id"].startswith("req_")
    assert entry["timestamp"]
    assert entry["provider"] == "anthropic"

    path = storage.llm_audit_path()
    assert path.exists()
    lines = [ln for ln in path.read_text("utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed == entry


def test_append_llm_audit_appends_multiple_lines(isolated_data_dir):
    storage.append_llm_audit({"provider": "anthropic", "status": "success"})
    storage.append_llm_audit({"provider": "anthropic", "status": "error", "error": "boom"})
    entries = list(storage.read_llm_audit())
    assert len(entries) == 2
    assert entries[0]["status"] == "success"
    assert entries[1]["status"] == "error"
    assert entries[1]["error"] == "boom"
    # Each entry gets its own id and timestamp.
    assert entries[0]["id"] != entries[1]["id"]


def test_read_llm_audit_returns_empty_when_missing(isolated_data_dir):
    assert list(storage.read_llm_audit()) == []


def test_append_llm_audit_preserves_caller_id_and_timestamp(isolated_data_dir):
    entry = storage.append_llm_audit(
        {"id": "req_fixed", "timestamp": "2026-01-01T00:00:00+00:00", "provider": "anthropic"}
    )
    assert entry["id"] == "req_fixed"
    assert entry["timestamp"] == "2026-01-01T00:00:00+00:00"
