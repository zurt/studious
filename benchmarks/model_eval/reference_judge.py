"""Judge ONE transcription against its source image plus a reviewed
reference transcription. Used by the regression benchmark
(benchmarks/run_benchmark.py); the model-comparison `judge` subcommand
ranks several candidates blind and has no reference.

Same rubric, schema, API call and response validation as `judge_cmd`, so a
regression score and a comparison score mean the same thing.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from .judge_cmd import VOCAB_GLOSS_POLICY, build_rubric_text, call_judge
from .judging import validate_and_clamp_response
from .pricing import estimate_cost

CANDIDATE_LABEL = "A"

def build_reference_judge_content(
    image_b64: str,
    prompt_kind: str,
    reference_md: str,
    candidate_md: str,
) -> list[dict[str, Any]]:
    """User-message content blocks for one reference-judge call."""
    intro = (
        "You are grading one markdown transcription of a scanned "
        f"Japanese-textbook image (prompt kind: {prompt_kind}). The image "
        "below is the ground truth. A REFERENCE transcription, written and "
        "reviewed by a person, follows it to help you check details quickly; "
        "where the reference and the image disagree, trust the image. The "
        "candidate does not need to match the reference's wording or "
        "markdown choices exactly — grade what a learner would get from it."
    )
    if prompt_kind == "vocab_list":
        intro += VOCAB_GLOSS_POLICY
    text = (
        f"{intro}\n\n{build_rubric_text()}\n\n"
        f"--- Reference transcription ---\n{reference_md}\n\n"
        f"--- Candidate {CANDIDATE_LABEL} ---\n{candidate_md}"
    )
    return [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
        },
        {"type": "text", "text": text},
    ]


def parse_reference_judgment(message: Any) -> dict[str, Any]:
    """Turn a judge response into `{"status": ..., scores...}`. Never raises
    for a bad response: a regression run should record it and carry on."""
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        return {"status": "refused"}
    text_blocks = [
        b.text for b in getattr(message, "content", []) if getattr(b, "type", None) == "text"
    ]
    if not text_blocks:
        return {"status": "error", "error": f"no text block (stop_reason={stop_reason!r})"}
    try:
        normalized = validate_and_clamp_response(json.loads(text_blocks[0]), [CANDIDATE_LABEL])
    except (json.JSONDecodeError, ValueError) as exc:
        return {"status": "error", "error": f"could not parse judge JSON: {exc}"}
    scores = dict(normalized["candidates"][0])
    scores.pop("label", None)
    return {"status": "ok", **scores, "rationale": normalized["rationale"]}


def judge_against_reference(
    client: Any,
    image_png: bytes,
    prompt_kind: str,
    reference_md: str,
    candidate_md: str,
    judge_model: str,
    fallback_model: str,
) -> dict[str, Any]:
    """Score `candidate_md` 0-10 on each rubric dimension.

    `image_png` should be the exact PNG bytes the transcriber was sent
    (`pdf.prepare_for_vlm` output), so the judge grades against what the
    model could actually see. Returns a dict with `status` ("ok" /
    "refused" / "error") and, when ok, one key per rubric dimension plus
    `notes`, `rationale`, `judge_model` and `estimated_cost_usd`."""
    image_b64 = base64.standard_b64encode(image_png).decode("ascii")
    content = build_reference_judge_content(image_b64, prompt_kind, reference_md, candidate_md)
    try:
        message = call_judge(client, judge_model, fallback_model, content)
    except Exception as exc:  # noqa: BLE001 - one failed judgment must not end the run
        return {"status": "error", "error": str(exc), "judge_model": judge_model}

    result = parse_reference_judgment(message)
    result["judge_model"] = judge_model
    usage = getattr(message, "usage", None)
    if usage is not None:
        result["estimated_cost_usd"] = estimate_cost(
            judge_model,
            {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
                "cache_creation_input_tokens": getattr(
                    usage, "cache_creation_input_tokens", None
                ),
            },
        )
    return result
