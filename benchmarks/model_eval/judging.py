"""Pure logic for the blind judge: label shuffling, schema, and response
validation/clamping. No network calls, no file I/O — judge_cmd.py handles
the actual Anthropic API call and file reads/writes.
"""
from __future__ import annotations

import random
from typing import Any

# Support up to 6 candidate models per item; in practice we run 3-4.
LABELS = ["A", "B", "C", "D", "E", "F"]

RUBRIC_DIMENSIONS = [
    "character_accuracy",
    "completeness",
    "formatting",
    "hallucination_control",
    "overall",
]

RUBRIC_DESCRIPTIONS = {
    "character_accuracy": "kanji/kana/furigana read correctly vs. the image",
    "completeness": "all visible content transcribed, nothing skipped",
    "formatting": "markdown structure faithful to layout (tables/lists/headers/underlines/blanks)",
    "hallucination_control": "10 = nothing invented or filled in that isn't in the image",
    "overall": "overall transcription quality",
}


def shuffle_candidates(seed_key: str, model_names: list[str]) -> dict[str, str]:
    """Return {label: model_name}, order shuffled deterministically from seed_key.

    `seed_key` should be f"{seed}:{item_id}" so every item gets an
    independent-looking but reproducible shuffle.
    """
    if len(model_names) > len(LABELS):
        raise ValueError(f"too many candidates ({len(model_names)}) for available labels")
    rng = random.Random(seed_key)
    order = list(model_names)
    rng.shuffle(order)
    labels = LABELS[: len(order)]
    return dict(zip(labels, order))


def invert_label_map(label_to_model: dict[str, str]) -> dict[str, str]:
    return {model: label for label, model in label_to_model.items()}


def clamp_score(value: Any) -> int:
    """Clamp a judge-reported score into [0, 10] as an int. Non-numeric -> 0."""
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(10, v))


def _candidate_schema() -> dict[str, Any]:
    props: dict[str, Any] = {"label": {"type": "string"}}
    for dim in RUBRIC_DIMENSIONS:
        props[dim] = {"type": "integer"}
    props["notes"] = {"type": "string"}
    return {
        "type": "object",
        "properties": props,
        "required": ["label", *RUBRIC_DIMENSIONS, "notes"],
        "additionalProperties": False,
    }


# Structured-outputs schema. Per spec: no min/max numeric constraints (not
# part of the structured-outputs schema subset) — 0-10 is enforced by prompt
# text and by clamp_score() in code.
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {"type": "array", "items": _candidate_schema()},
        "ranking": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["candidates", "ranking", "rationale"],
    "additionalProperties": False,
}


def validate_and_clamp_response(raw: dict[str, Any], valid_labels: list[str]) -> dict[str, Any]:
    """Normalize a parsed judge response: clamp scores, keep only known labels.

    Raises ValueError if the response is structurally unusable (no
    candidates, or ranking doesn't reference any valid label).
    """
    candidates_in = raw.get("candidates")
    if not isinstance(candidates_in, list) or not candidates_in:
        raise ValueError("judge response missing candidates")

    valid_set = set(valid_labels)
    candidates_out = []
    for c in candidates_in:
        if not isinstance(c, dict):
            continue
        label = c.get("label")
        if label not in valid_set:
            continue
        entry = {"label": label, "notes": str(c.get("notes", ""))}
        for dim in RUBRIC_DIMENSIONS:
            entry[dim] = clamp_score(c.get(dim))
        candidates_out.append(entry)

    if not candidates_out:
        raise ValueError("judge response had no candidates matching valid labels")

    ranking_in = raw.get("ranking")
    ranking_out = [
        label for label in (ranking_in or []) if isinstance(label, str) and label in valid_set
    ]
    # Fill in any candidate missing from a malformed ranking, preserving the
    # judge's declared order first.
    for label in valid_labels:
        if label in {c["label"] for c in candidates_out} and label not in ranking_out:
            ranking_out.append(label)

    return {
        "candidates": candidates_out,
        "ranking": ranking_out,
        "rationale": str(raw.get("rationale", "")),
    }
