"""Append-only JSONL audit log for LLM API calls.

Each line records one provider call: who, what, how many tokens, how long,
and enough document/chapter/region context to trace the request back to the
job that triggered it.

Files are rotated monthly by UTC date: writes go to
`llm_audit.YYYY-MM.jsonl` and `read_all()` concatenates every file matching
`llm_audit*.jsonl`. A legacy `llm_audit.jsonl` from before rotation is read
transparently. Summary aggregation reads a per-month cache when available so
the cost endpoints stay snappy after years of usage.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import get_settings

log = logging.getLogger("studious.llm_audit")

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_month_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def audit_log_dir() -> Path:
    return get_settings().data_dir


def audit_log_path() -> Path:
    """Path of the current month's audit file. Writes go here."""
    return audit_log_dir() / f"llm_audit.{_current_month_tag()}.jsonl"


def audit_log_files() -> list[Path]:
    """All audit files in chronological order. Includes the pre-rotation
    `llm_audit.jsonl` first if present."""
    base = audit_log_dir()
    files: list[Path] = []
    legacy = base / "llm_audit.jsonl"
    if legacy.exists():
        files.append(legacy)
    monthly = sorted(base.glob("llm_audit.[0-9][0-9][0-9][0-9]-[0-9][0-9].jsonl"))
    files.extend(monthly)
    return files


def summary_cache_path() -> Path:
    return audit_log_dir() / "llm_audit_summary.json"


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
    cache_read_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
    doc_id: str | None = None,
    chapter_id: str | None = None,
    region_id: str | None = None,
    job_id: str | None = None,
    page: int | None = None,
    error: str | None = None,
    correlation_id: str | None = None,
    request_id: str | None = None,
    prompt_hash: str | None = None,
    image_bytes: int | None = None,
    stop_reason: str | None = None,
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
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "doc_id": doc_id,
        "chapter_id": chapter_id,
        "region_id": region_id,
        "job_id": job_id,
        "page": page,
        "error": error,
        "correlation_id": correlation_id,
        "request_id": request_id,
        "prompt_hash": prompt_hash,
        "image_bytes": image_bytes,
        "stop_reason": stop_reason,
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


def _iter_file(path: Path) -> Iterable[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                log.warning(
                    "audit_log_skip_malformed",
                    extra={"file": path.name, "line": lineno},
                )


def read_all() -> list[dict[str, Any]]:
    """Read every entry across all rotated files. Skips malformed lines."""
    out: list[dict[str, Any]] = []
    for path in audit_log_files():
        out.extend(_iter_file(path))
    return out


def _month_of(path: Path) -> str | None:
    """Returns 'YYYY-MM' for a rotated file, or None for the legacy file."""
    name = path.name
    # Expect llm_audit.YYYY-MM.jsonl
    parts = name.split(".")
    if len(parts) != 3:
        return None
    tag = parts[1]
    if len(tag) == 7 and tag[4] == "-" and tag[:4].isdigit() and tag[5:].isdigit():
        return tag
    return None


def load_summary_cache() -> dict[str, Any]:
    """Load cached per-month aggregates. Missing or malformed cache → empty."""
    path = summary_cache_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        log.warning("audit_summary_cache_unreadable")
    return {}


def save_summary_cache(cache: dict[str, Any]) -> None:
    path = summary_cache_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)


def extract_usage(meta: dict[str, Any] | None) -> dict[str, int | None]:
    """Pull token counts out of a TranscriptionResult.meta payload."""
    usage = (meta or {}).get("usage") or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "image_tokens": usage.get("image_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens"),
    }


def extract_provenance(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Pull provider-supplied request metadata out of `result.meta` for the audit log."""
    meta = meta or {}
    return {
        "request_id": meta.get("request_id"),
        "prompt_hash": meta.get("prompt_hash"),
        "image_bytes": meta.get("image_bytes"),
        "stop_reason": meta.get("stop_reason"),
    }
