"""Cost estimation derived from the LLM audit log.

Anthropic includes token counts in API responses; combined with a per-model
pricing table we compute a USD estimate per request. Estimates are not
billing-accurate — they ignore prompt caching discounts and any pricing
changes that happened after the audit entry was written.
"""
from __future__ import annotations

from typing import Any

from ..config import MODEL_PRICING
from . import llm_audit


def rate_for(model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    return MODEL_PRICING.get(model)


def estimate_cost(entry: dict[str, Any]) -> float | None:
    """USD cost estimate for one audit entry, or None if the model is unknown."""
    rate = rate_for(entry.get("model"))
    if rate is None:
        return None
    input_tokens = entry.get("input_tokens") or 0
    output_tokens = entry.get("output_tokens") or 0
    return (input_tokens * rate["input"] + output_tokens * rate["output"]) / 1_000_000


def annotate(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    out["estimated_cost_usd"] = estimate_cost(entry)
    return out


def summary() -> dict[str, Any]:
    """Aggregate audit entries into totals overall, by model, and by doc."""
    entries = llm_audit.read_all()

    total_input = 0
    total_output = 0
    total_cost = 0.0
    total_requests = len(entries)
    success_count = 0
    error_count = 0
    by_model: dict[str, dict[str, Any]] = {}
    by_doc: dict[str, dict[str, Any]] = {}
    unknown_models: set[str] = set()

    first_ts: str | None = None
    last_ts: str | None = None

    for e in entries:
        cost = estimate_cost(e)
        ti = e.get("input_tokens") or 0
        to = e.get("output_tokens") or 0
        total_input += ti
        total_output += to
        if cost is not None:
            total_cost += cost
        elif e.get("model"):
            unknown_models.add(e["model"])

        status = e.get("status")
        if status == "success":
            success_count += 1
        elif status == "error":
            error_count += 1

        ts = e.get("timestamp")
        if ts:
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

        model_key = e.get("model") or "(unknown)"
        bucket = by_model.setdefault(
            model_key,
            {"requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0},
        )
        bucket["requests"] += 1
        bucket["input_tokens"] += ti
        bucket["output_tokens"] += to
        if cost is not None:
            bucket["estimated_cost_usd"] += cost

        doc_key = e.get("doc_id") or "(none)"
        dbucket = by_doc.setdefault(
            doc_key,
            {"requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0},
        )
        dbucket["requests"] += 1
        dbucket["input_tokens"] += ti
        dbucket["output_tokens"] += to
        if cost is not None:
            dbucket["estimated_cost_usd"] += cost

    return {
        "total_requests": total_requests,
        "success_count": success_count,
        "error_count": error_count,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_estimated_cost_usd": total_cost,
        "by_model": by_model,
        "by_doc": by_doc,
        "unknown_models": sorted(unknown_models),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
    }


def paginated_audit(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    entries = llm_audit.read_all()
    # Newest first.
    entries.reverse()
    total = len(entries)
    page = entries[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "entries": [annotate(e) for e in page],
    }
