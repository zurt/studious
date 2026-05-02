"""Append-only JSONL audit log for LLM API calls.

Each line records one provider call: who, what, how many tokens, how long,
and enough document/chapter/region context to trace the request back to the
job that triggered it.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings

log = logging.getLogger("studious.llm_audit")

_lock = threading.Lock()


def audit_log_path() -> Path:
    return get_settings().data_dir / "llm_audit.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(
    *,
    provider: str,
    model: str | None,
    job_type: str,
    status: str,
    duration_ms: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    image_tokens: int | None = None,
    doc_id: str | None = None,
    chapter_id: str | None = None,
    region_id: str | None = None,
    job_id: str | None = None,
    page: int | None = None,
    error: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Append one audit entry. Returns the entry that was written."""
    entry: dict[str, Any] = {
        "id": "req_" + uuid.uuid4().hex[:12],
        "timestamp": _now_iso(),
        "provider": provider,
        "model": model,
        "job_type": job_type,
        "status": status,
        "duration_ms": duration_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "image_tokens": image_tokens,
        "doc_id": doc_id,
        "chapter_id": chapter_id,
        "region_id": region_id,
        "job_id": job_id,
        "page": page,
        "error": error,
        "correlation_id": correlation_id,
    }

    path = audit_log_path()
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return entry


def read_all() -> list[dict[str, Any]]:
    """Read every entry. Skips malformed lines and logs them."""
    path = audit_log_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                log.warning("audit_log_skip_malformed", extra={"line": lineno})
    return out


def extract_usage(meta: dict[str, Any] | None) -> dict[str, int | None]:
    """Pull token counts out of a TranscriptionResult.meta payload."""
    usage = (meta or {}).get("usage") or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "image_tokens": usage.get("image_tokens"),
    }
