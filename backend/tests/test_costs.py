from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import costs, llm_audit


def test_estimate_cost_known_model():
    entry = {"model": "claude-sonnet-4-6", "input_tokens": 1_000_000, "output_tokens": 500_000}
    # 1M * $3 + 0.5M * $15 = $3 + $7.5 = $10.5
    assert costs.estimate_cost(entry) == 10.5


def test_estimate_cost_unknown_model_returns_none():
    assert costs.estimate_cost({"model": "made-up-model", "input_tokens": 1, "output_tokens": 1}) is None


def test_estimate_cost_handles_missing_tokens():
    entry = {"model": "claude-opus-4-7", "input_tokens": None, "output_tokens": None}
    assert costs.estimate_cost(entry) == 0.0


def test_summary_aggregates_by_model_and_doc(isolated_data_dir):
    llm_audit.record(
        provider="anthropic",
        model="claude-opus-4-7",
        job_type="transcribe_pages",
        status="success",
        duration_ms=100,
        input_tokens=1_000_000,
        output_tokens=100_000,
        doc_id="d1",
    )
    llm_audit.record(
        provider="anthropic",
        model="claude-sonnet-4-6",
        job_type="transcribe_region",
        status="error",
        duration_ms=50,
        input_tokens=1000,
        output_tokens=0,
        doc_id="d1",
        error="boom",
    )
    llm_audit.record(
        provider="anthropic",
        model="mystery-model",
        job_type="transcribe_pages",
        status="success",
        duration_ms=10,
        input_tokens=10,
        output_tokens=10,
        doc_id="d2",
    )

    s = costs.summary()
    assert s["total_requests"] == 3
    assert s["success_count"] == 2
    assert s["error_count"] == 1
    # Opus 4.7: 1M*5 + 0.1M*25 = 5 + 2.5 = 7.5
    # Sonnet: 1000*3/1M = 0.003
    # Mystery: unknown -> 0
    assert abs(s["total_estimated_cost_usd"] - 7.503) < 1e-6
    assert "claude-opus-4-7" in s["by_model"]
    assert s["by_model"]["claude-opus-4-7"]["requests"] == 1
    assert s["by_doc"]["d1"]["requests"] == 2
    assert "mystery-model" in s["unknown_models"]


def test_paginated_audit_newest_first(isolated_data_dir):
    for i in range(5):
        llm_audit.record(
            provider="a",
            model="claude-opus-4-7",
            job_type="transcribe_pages",
            status="success",
            duration_ms=i,
            input_tokens=i,
            output_tokens=i,
        )
    page = costs.paginated_audit(limit=2, offset=0)
    assert page["total"] == 5
    assert len(page["entries"]) == 2
    # Newest first: duration_ms 4 then 3.
    assert page["entries"][0]["duration_ms"] == 4
    assert page["entries"][1]["duration_ms"] == 3
    assert "estimated_cost_usd" in page["entries"][0]


def test_costs_summary_endpoint(isolated_data_dir):
    llm_audit.record(
        provider="a",
        model="claude-opus-4-7",
        job_type="transcribe_pages",
        status="success",
        duration_ms=1,
        input_tokens=1000,
        output_tokens=500,
    )
    client = TestClient(app)
    r = client.get("/api/costs/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_requests"] == 1
    assert body["total_estimated_cost_usd"] > 0


def test_costs_audit_endpoint(isolated_data_dir):
    llm_audit.record(
        provider="a",
        model="claude-opus-4-7",
        job_type="transcribe_pages",
        status="success",
        duration_ms=1,
        input_tokens=1,
        output_tokens=1,
    )
    client = TestClient(app)
    r = client.get("/api/costs/audit?limit=10&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["entries"][0]["estimated_cost_usd"] is not None


def test_costs_pricing_endpoint(isolated_data_dir):
    client = TestClient(app)
    r = client.get("/api/costs/pricing")
    assert r.status_code == 200
    body = r.json()
    assert "claude-opus-4-7" in body["models"]
