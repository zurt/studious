from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers import registry
from app.services import llm_audit, preferences, region_check, storage

GOOD = {
    "suggested_tag": "reading_passage",
    "tag_confidence": "high",
    "tag_reason": "It is a word list.",
    "needs_reference": True,
    "reference_reason": "Asks about the passage.",
}


class _Vlm:
    name = "anthropic"

    def __init__(self, tool_input=None, raise_exc: Exception | None = None):
        self.tool_input = GOOD if tool_input is None else tool_input
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, str, dict]] = []

    def info(self):
        return {"name": self.name, "kind": "vlm"}

    def transcribe(self, *a, **k):
        raise NotImplementedError

    def call_tool(self, prompt, tool_name, tool_schema, config):
        self.calls.append((registry.prompt_text(prompt), tool_name, config))
        if self.raise_exc:
            raise self.raise_exc
        return registry.ToolCallResult(
            tool_input=self.tool_input,
            meta={
                "model": config["model"],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )


@pytest.fixture
def vlm(isolated_data_dir):
    instance = _Vlm()
    registry.register_vlm("anthropic", lambda: instance)
    return instance


def _doc(tmp_path: Path) -> tuple[str, str]:
    src = tmp_path / "src.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    doc = storage.create_document(name="d.pdf", source_type="pdf", page_count=3, original_path=src)
    ch = storage.create_chapter(doc["id"], title="Ch", page_start=1, page_end=3)
    return doc["id"], ch["id"]


def _region(doc_id, ch_id, page=1, tag="exercises", text: str | None = "本文を読んで答えなさい。"):
    r = storage.create_region(doc_id, ch_id, page=page, bbox=[0, 0, 1, 1], tag=tag)
    if text is not None:
        r = storage.update_region(
            doc_id, ch_id, r["id"], transcription_md=text, transcribed_at=f"2026-01-0{page}T00:00:00"
        )
    return r


def _audits():
    return [e for e in llm_audit.read_all() if e.get("job_type") == "region_check"]


def test_happy_path_stores_check(vlm, tmp_path):
    d, c = _doc(tmp_path)
    r = _region(d, c)
    out = region_check.check_region(d, c, r["id"])
    check = out["check"]
    assert check["suggested_tag"] == "reading_passage"
    assert check["needs_reference"] is True
    assert check["tag"] == "exercises"
    assert check["transcribed_at"] == r["transcribed_at"]
    assert check["label_dismissed"] is False
    assert storage.load_region(d, c, r["id"])["check"] == check
    prompt, tool, config = vlm.calls[0]
    assert tool == "record_region_check"
    assert "<current_tag>exercises</current_tag>" in prompt
    assert "</continuation>" not in prompt
    assert config["effort"] == "low"


def test_no_transcription_returns_none(vlm, tmp_path):
    d, c = _doc(tmp_path)
    r = _region(d, c, text=None)
    assert region_check.check_region(d, c, r["id"]) is None
    assert vlm.calls == []


def test_chain_head_gets_continuation_text(vlm, tmp_path):
    d, c = _doc(tmp_path)
    head = _region(d, c, 1, text="HEAD TEXT")
    tail = _region(d, c, 2, text="TAIL TEXT")
    storage.update_region(d, c, head["id"], continues_to=tail["id"])
    region_check.check_region(d, c, head["id"])
    assert "<continuation>\nTAIL TEXT\n</continuation>" in vlm.calls[0][0]
    # A continuation is checked on its own text only.
    region_check.check_region(d, c, tail["id"])
    assert "</continuation>" not in vlm.calls[1][0]


def test_continuation_rechecks_head(vlm, tmp_path):
    d, c = _doc(tmp_path)
    head = _region(d, c, 1, text="HEAD TEXT")
    tail = _region(d, c, 2, text="TAIL TEXT")
    storage.update_region(d, c, head["id"], continues_to=tail["id"])
    region_check.run_after_transcription(d, c, tail["id"])
    assert len(vlm.calls) == 2
    assert "check" in storage.load_region(d, c, tail["id"])
    assert "check" in storage.load_region(d, c, head["id"])


def test_invalid_output_raises_and_is_audited(vlm, tmp_path):
    vlm.tool_input = {**GOOD, "suggested_tag": "poetry"}
    d, c = _doc(tmp_path)
    r = _region(d, c)
    with pytest.raises(region_check.RegionCheckError):
        region_check.check_region(d, c, r["id"])
    assert "check" not in storage.load_region(d, c, r["id"])
    (entry,) = _audits()
    assert entry["status"] == "error"
    assert "suggested_tag" in entry["error"]


@pytest.mark.parametrize(
    "bad",
    [
        {"tag_confidence": "certain"},
        {"needs_reference": "yes"},
        {"tag_reason": None},
    ],
)
def test_validation_rejects_bad_fields(vlm, tmp_path, bad):
    vlm.tool_input = {**GOOD, **bad}
    d, c = _doc(tmp_path)
    r = _region(d, c)
    with pytest.raises(region_check.RegionCheckError):
        region_check.check_region(d, c, r["id"])


def test_run_after_transcription_never_raises(vlm, tmp_path):
    vlm.raise_exc = RuntimeError("boom")
    d, c = _doc(tmp_path)
    r = _region(d, c)
    region_check.run_after_transcription(d, c, r["id"])
    (entry,) = _audits()
    assert entry["status"] == "error" and entry["error"] == "boom"


def test_audit_entry_uses_helper_model_not_main(vlm, tmp_path):
    preferences.save({"vlm_model": "claude-sonnet-5", "helper_model": "claude-sonnet-5-5"})
    d, c = _doc(tmp_path)
    r = _region(d, c)
    out = region_check.check_region(d, c, r["id"])
    assert vlm.calls[0][2]["model"] == "claude-sonnet-5-5"
    assert out["check"]["model"] == "claude-sonnet-5-5"
    (entry,) = _audits()
    assert entry["model"] == "claude-sonnet-5-5"
    assert entry["status"] == "success"
    assert entry["doc_id"] == d and entry["region_id"] == r["id"]
    assert entry["input_tokens"] == 10


def test_default_helper_model_is_haiku(vlm, tmp_path):
    d, c = _doc(tmp_path)
    r = _region(d, c)
    region_check.check_region(d, c, r["id"])
    assert vlm.calls[0][2]["model"] == "claude-haiku-5-5"


# ---------- API ----------


@pytest.fixture
def client(vlm):
    with TestClient(app) as cl:
        yield cl


def test_api_check(client, tmp_path):
    d, c = _doc(tmp_path)
    r = _region(d, c)
    resp = client.post(f"/api/documents/{d}/chapters/{c}/regions/{r['id']}/check")
    assert resp.status_code == 200
    assert resp.json()["check"]["needs_reference"] is True


def test_api_check_errors(client, vlm, tmp_path):
    d, c = _doc(tmp_path)
    base = f"/api/documents/{d}/chapters/{c}/regions"
    assert client.post(f"{base}/nope/check").status_code == 404
    empty = _region(d, c, text=None)
    assert client.post(f"{base}/{empty['id']}/check").status_code == 409
    r = _region(d, c)
    vlm.raise_exc = RuntimeError("model down")
    resp = client.post(f"{base}/{r['id']}/check")
    assert resp.status_code == 502
    assert "model down" in resp.json()["detail"]


def test_api_dismiss(client, tmp_path):
    d, c = _doc(tmp_path)
    base = f"/api/documents/{d}/chapters/{c}/regions"
    r = _region(d, c)
    assert client.post(f"{base}/{r['id']}/check/dismiss").status_code == 404
    assert client.post(f"{base}/nope/check/dismiss").status_code == 404
    client.post(f"{base}/{r['id']}/check")
    resp = client.post(f"{base}/{r['id']}/check/dismiss")
    assert resp.status_code == 200
    assert resp.json()["check"]["label_dismissed"] is True
    assert storage.load_region(d, c, r["id"])["check"]["label_dismissed"] is True
