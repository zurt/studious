"""Post-transcription region check.

One cheap text-only call to the *helper model* (not the model selected for
transcription) answers two questions about a transcribed region and stores
the result on it as ``region["check"]``::

    {"checked_at", "model", "transcribed_at", "tag",
     "suggested_tag", "tag_confidence", "tag_reason",
     "needs_reference", "reference_reason", "label_dismissed"}

1. Is the region's tag appropriate for its content?
2. For exercise content: do the questions need a reading passage that is
   not in the text? (A missing reference otherwise fails silently and the
   exercise-completion model answers blind.)

``transcribed_at`` and ``tag`` record what was checked, so a re-transcription
or a relabel makes the stored check stale; consumers compare them. Every call
is audited under the ``region_check`` job type.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from ..config import REGION_CHECK_PROMPT, REGION_CHECK_TOOL_SCHEMA
from ..middleware import correlation_id_var
from ..providers import registry
from . import llm_audit, preferences, region_chain, storage

log = logging.getLogger("studious.region_check")

JOB_TYPE = "region_check"
TOOL_NAME = "record_region_check"
PROVIDER = "anthropic"
MAX_TOKENS = 1024

_TAGS = set(REGION_CHECK_TOOL_SCHEMA["properties"]["suggested_tag"]["enum"])
_CONFIDENCES = {"high", "medium", "low"}


class RegionCheckError(Exception):
    """The model's answer was unusable."""


def _prompt(tag: str, own: str, continuation: str) -> list[dict[str, Any]]:
    per_call = f"<current_tag>{tag}</current_tag>\n<region>\n{own}\n</region>"
    if continuation:
        per_call += f"\n<continuation>\n{continuation}\n</continuation>"
    return [{"text": f"{REGION_CHECK_PROMPT}\n\n", "cache": True}, {"text": per_call}]


def _validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise RegionCheckError("tool response is not an object")
    if data.get("suggested_tag") not in _TAGS:
        raise RegionCheckError(f"invalid suggested_tag: {data.get('suggested_tag')!r}")
    if data.get("tag_confidence") not in _CONFIDENCES:
        raise RegionCheckError(f"invalid tag_confidence: {data.get('tag_confidence')!r}")
    if not isinstance(data.get("needs_reference"), bool):
        raise RegionCheckError("needs_reference must be a boolean")
    for key in ("tag_reason", "reference_reason"):
        if not isinstance(data.get(key), str):
            raise RegionCheckError(f"{key} must be a string")
    return {
        "suggested_tag": data["suggested_tag"],
        "tag_confidence": data["tag_confidence"],
        "tag_reason": data["tag_reason"].strip(),
        "needs_reference": data["needs_reference"],
        "reference_reason": data["reference_reason"].strip(),
    }


def _audit(
    status: str,
    t0: float,
    model: Any,
    ctx: dict[str, str],
    *,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    extra = {**llm_audit.extract_usage(meta), **llm_audit.extract_provenance(meta)} if meta else {}
    llm_audit.record(
        provider=PROVIDER,
        model=str(model),
        job_type=JOB_TYPE,
        status=status,
        duration_ms=int((time.monotonic() - t0) * 1000),
        error=error,
        correlation_id=correlation_id_var.get(""),
        **ctx,
        **extra,
    )


def check_region(doc_id: str, chapter_id: str, region_id: str) -> dict[str, Any] | None:
    """Run the check and store it. None when the region has no transcription
    (or does not exist). Raises on provider or validation failure."""
    region = storage.load_region(doc_id, chapter_id, region_id)
    if region is None:
        return None
    own = (region.get("transcription_md") or "").strip()
    if not own:
        return None

    continuation = ""
    if region_chain.find_inbound_source(doc_id, chapter_id, region_id) is None:
        chain = region_chain.resolve_chain(doc_id, chapter_id, region_id)
        if len(chain) > 1:
            continuation = region_chain.combined_transcription(chain[1:])

    tag = region.get("tag") or "other"
    config = {
        "model": preferences.get_active_helper_model(),
        "max_tokens": MAX_TOKENS,
        "effort": "low",
    }
    ctx = {"doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id}
    t0 = time.monotonic()
    try:
        provider = registry.get_vlm(PROVIDER)
        result = provider.call_tool(
            _prompt(tag, own, continuation), TOOL_NAME, REGION_CHECK_TOOL_SCHEMA, config
        )
    except Exception as exc:
        _audit("error", t0, config["model"], ctx, error=str(exc))
        raise
    model = result.meta.get("model") or config["model"]
    try:
        answer = _validate(result.tool_input)
    except RegionCheckError as exc:
        _audit("error", t0, model, ctx, error=str(exc), meta=result.meta)
        raise
    _audit("success", t0, model, ctx, meta=result.meta)

    check = {
        "checked_at": datetime.now(UTC).isoformat(),
        "model": model,
        "transcribed_at": region.get("transcribed_at"),
        "tag": tag,
        **answer,
        "label_dismissed": False,
    }
    return storage.update_region(doc_id, chapter_id, region_id, check=check)


def run_after_transcription(doc_id: str, chapter_id: str, region_id: str) -> None:
    """Check the region just transcribed and, when it continues another
    region, the chain head too (its reference answer depends on the whole
    chain's text). Never raises."""
    extra = {"doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id}
    try:
        check_region(doc_id, chapter_id, region_id)
        head_id = region_id
        seen = {region_id}
        while True:
            inbound = region_chain.find_inbound_source(doc_id, chapter_id, head_id)
            if inbound is None or inbound["id"] in seen:
                break
            head_id = inbound["id"]
            seen.add(head_id)
        if head_id != region_id:
            check_region(doc_id, chapter_id, head_id)
    except Exception:
        log.exception("region_check_error", extra=extra)
