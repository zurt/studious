"""Helpers shared by the job manager and every job runner."""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from ..config import (
    get_settings,
)
from ..middleware import correlation_id_var
from ..services import (
    llm_audit,
)

log = logging.getLogger("studious.jobs")


class _RegionOpError(Exception):
    """Raised by the per-region cores on any failure.

    The VLM call (if one was attempted) has already been audited by the
    time this is raised. Callers decide what a failure means for the job
    as a whole: single-region jobs fail outright; the bulk runner records
    an error and continues with the next region.
    """


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ms_since(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _audit(
    *,
    provider: str,
    job_type: str,
    status: str,
    duration_ms: int,
    context: dict[str, Any],
    meta: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Write one llm_audit entry for a VLM call.

    ``meta`` (a provider result's meta) supplies the model plus usage and
    provenance fields. Before a result exists — the provider raised — the
    model falls back to the job config or the settings default and no
    usage is recorded.
    """
    if meta is not None:
        model = meta.get("model")
        extracted: dict[str, Any] = {
            **llm_audit.extract_usage(meta),
            **llm_audit.extract_provenance(meta),
        }
    else:
        model = str((config or {}).get("model") or get_settings().default_vlm_model)
        extracted = {}
    llm_audit.record(
        provider=provider,
        model=model,
        job_type=job_type,
        status=status,
        duration_ms=duration_ms,
        error=error,
        correlation_id=correlation_id_var.get(""),
        **context,
        **extracted,
    )
