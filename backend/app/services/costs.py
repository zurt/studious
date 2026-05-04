"""Cost estimation derived from the LLM audit log.

Anthropic includes token counts in API responses; combined with a per-model
pricing table we compute a USD estimate per request. Estimates are not
billing-accurate — they ignore prompt caching discounts and any pricing
changes that happened after the audit entry was written.

The summary endpoint reads a per-month cache (`llm_audit_summary.json`) for
archived months and recomputes the current month live, so cost queries stay
cheap as the audit log grows.
"""
from __future__ import annotations

from typing import Any, Iterable

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


def _empty_aggregate() -> dict[str, Any]:
    return {
        "total_requests": 0,
        "success_count": 0,
        "error_count": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_estimated_cost_usd": 0.0,
        "by_model": {},
        "by_doc": {},
        "unknown_models": [],
        "first_timestamp": None,
        "last_timestamp": None,
    }


def _aggregate(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    agg = _empty_aggregate()
    by_model: dict[str, dict[str, Any]] = agg["by_model"]
    by_doc: dict[str, dict[str, Any]] = agg["by_doc"]
    unknown_models: set[str] = set()

    for e in entries:
        cost = estimate_cost(e)
        ti = e.get("input_tokens") or 0
        to = e.get("output_tokens") or 0
        agg["total_requests"] += 1
        agg["total_input_tokens"] += ti
        agg["total_output_tokens"] += to
        if cost is not None:
            agg["total_estimated_cost_usd"] += cost
        elif e.get("model"):
            unknown_models.add(e["model"])

        status = e.get("status")
        if status == "success":
            agg["success_count"] += 1
        elif status == "error":
            agg["error_count"] += 1

        ts = e.get("timestamp")
        if ts:
            if agg["first_timestamp"] is None or ts < agg["first_timestamp"]:
                agg["first_timestamp"] = ts
            if agg["last_timestamp"] is None or ts > agg["last_timestamp"]:
                agg["last_timestamp"] = ts

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

    agg["unknown_models"] = sorted(unknown_models)
    return agg


def _merge(into: dict[str, Any], other: dict[str, Any]) -> None:
    into["total_requests"] += other.get("total_requests", 0)
    into["success_count"] += other.get("success_count", 0)
    into["error_count"] += other.get("error_count", 0)
    into["total_input_tokens"] += other.get("total_input_tokens", 0)
    into["total_output_tokens"] += other.get("total_output_tokens", 0)
    into["total_estimated_cost_usd"] += other.get("total_estimated_cost_usd", 0.0)

    for key, src in (other.get("by_model") or {}).items():
        dst = into["by_model"].setdefault(
            key,
            {"requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0},
        )
        for f in ("requests", "input_tokens", "output_tokens", "estimated_cost_usd"):
            dst[f] += src.get(f, 0)
    for key, src in (other.get("by_doc") or {}).items():
        dst = into["by_doc"].setdefault(
            key,
            {"requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0},
        )
        for f in ("requests", "input_tokens", "output_tokens", "estimated_cost_usd"):
            dst[f] += src.get(f, 0)

    seen = set(into["unknown_models"])
    seen.update(other.get("unknown_models") or [])
    into["unknown_models"] = sorted(seen)

    for key in ("first_timestamp",):
        v = other.get(key)
        if v and (into[key] is None or v < into[key]):
            into[key] = v
    for key in ("last_timestamp",):
        v = other.get(key)
        if v and (into[key] is None or v > into[key]):
            into[key] = v


def summary() -> dict[str, Any]:
    """Aggregate audit entries into totals overall, by model, and by doc.

    Past months are cached in `llm_audit_summary.json`; only the current
    month and any uncached files are re-aggregated on each call.
    """
    cache = llm_audit.load_summary_cache()
    files = llm_audit.audit_log_files()
    current_tag = llm_audit._current_month_tag()
    cache_dirty = False

    out = _empty_aggregate()
    for path in files:
        tag = llm_audit._month_of(path)
        if tag and tag != current_tag and tag in cache:
            _merge(out, cache[tag])
            continue
        agg = _aggregate(llm_audit._iter_file(path))
        _merge(out, agg)
        # Cache fully-archived months only — the current month is still being
        # written to and the legacy file (tag is None) has no rotation guarantee.
        if tag and tag != current_tag:
            cache[tag] = agg
            cache_dirty = True

    if cache_dirty:
        llm_audit.save_summary_cache(cache)

    return out


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
