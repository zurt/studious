"""Cost-estimation math for model_eval and the regression benchmark.

Prices come from one place: `backend/app/config.py`'s MODEL_PRICING, the
table the app's own cost tracking uses. `EVAL_ONLY_PRICING` adds models the
eval calls but the app does not offer (e.g. a judge model). A model listed
in both uses the app's row, so the two can never disagree.

Rates are USD per 1,000,000 tokens, in the app's row format:
`input`, `output`, and optional `cache_write` / `cache_read` overrides.
"""
from __future__ import annotations

from typing import Any

from .common import ensure_backend_on_path

# Models the eval uses that the app's settings do not offer.
EVAL_ONLY_PRICING: dict[str, dict[str, float]] = {
    "claude-fable-5": {"input": 10.00, "output": 50.00},
}

# Defaults when a row carries no explicit cache rates: a cache read is billed
# at a fraction of the input rate, a (5-minute) cache write at a surcharge.
CACHE_READ_MULTIPLIER = 0.1
CACHE_CREATION_MULTIPLIER = 1.25


def pricing_table() -> dict[str, dict[str, float]]:
    """The merged table: eval-only rows, overridden by the app's rows."""
    ensure_backend_on_path()
    from app.config import MODEL_PRICING as APP_PRICING

    return {**EVAL_ONLY_PRICING, **APP_PRICING}


def _rate_for(model: str) -> dict[str, float] | None:
    """Look up the pricing row for `model`, allowing dated-suffix aliases.

    e.g. "claude-haiku-4-5-20251001" resolves to the "claude-haiku-4-5" row.
    The longest matching name wins, so a dated "claude-sonnet-5-5-..." id
    resolves to "claude-sonnet-5-5" and never to "claude-sonnet-5".
    """
    table = pricing_table()
    if model in table:
        return table[model]
    matches = [known for known in table if model.startswith(known + "-")]
    if not matches:
        return None
    return table[max(matches, key=len)]


def estimate_cost(model: str, usage: dict[str, Any] | None) -> float | None:
    """USD cost estimate for one call, or None if `model` is unknown.

    `usage` is expected to look like the Anthropic SDK's usage object as a
    dict: input_tokens, output_tokens, cache_read_input_tokens,
    cache_creation_input_tokens. Missing/None fields are treated as 0.
    """
    rate = _rate_for(model)
    if rate is None:
        return None
    usage = usage or {}
    input_tokens = usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    cache_read_tokens = usage.get("cache_read_input_tokens") or 0
    cache_creation_tokens = usage.get("cache_creation_input_tokens") or 0

    cache_read_rate = rate.get("cache_read", rate["input"] * CACHE_READ_MULTIPLIER)
    cache_write_rate = rate.get("cache_write", rate["input"] * CACHE_CREATION_MULTIPLIER)

    cost = (
        input_tokens * rate["input"]
        + output_tokens * rate["output"]
        + cache_read_tokens * cache_read_rate
        + cache_creation_tokens * cache_write_rate
    ) / 1_000_000
    return cost
