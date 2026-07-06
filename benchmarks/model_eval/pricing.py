"""Pure cost-estimation math for model_eval.

Kept separate from backend/app/config.py's MODEL_PRICING (which drives the
app's own cost-tracking UI) because this eval intentionally covers models —
and introductory/promotional pricing windows — that the shipping app config
does not need to know about.
"""
from __future__ import annotations

from typing import Any

# USD per 1,000,000 tokens. "in" = input tokens, "out" = output tokens.
#
# claude-sonnet-5: introductory pricing in effect through 2026-08-31;
# reverts to sticker $3/$15 after that (matches the launch discount pattern
# Anthropic used for opus-4-5). Re-check before relying on old run costs
# past that date.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
    "claude-sonnet-5": {"in": 2.00, "out": 10.00},
    "claude-opus-4-8": {"in": 5.00, "out": 25.00},
    "claude-fable-5": {"in": 10.00, "out": 50.00},
}

# Cache reads are billed at a fraction of the base input rate; cache writes
# (creation) carry a surcharge over the base input rate. Same multipliers
# Anthropic documents for prompt caching generally.
CACHE_READ_MULTIPLIER = 0.1
CACHE_CREATION_MULTIPLIER = 1.25


def _rate_for(model: str) -> dict[str, float] | None:
    """Look up the pricing row for `model`, allowing dated-suffix aliases.

    e.g. "claude-haiku-4-5-20251001" resolves to the "claude-haiku-4-5" row.
    """
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    for known, rate in MODEL_PRICING.items():
        if model.startswith(known):
            return rate
    return None


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

    cost = (
        input_tokens * rate["in"]
        + output_tokens * rate["out"]
        + cache_read_tokens * (rate["in"] * CACHE_READ_MULTIPLIER)
        + cache_creation_tokens * (rate["in"] * CACHE_CREATION_MULTIPLIER)
    ) / 1_000_000
    return cost
