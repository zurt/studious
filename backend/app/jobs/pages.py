"""Whole-page transcription jobs (`transcribe_pages`).

A mixin for `JobManager` (see `manager.py`), which supplies `_emit`,
`_start_job`, `_fail_job` and `_complete_job`.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..config import (
    get_settings,
)
from ..providers import registry
from ..services import (
    blanks,
    pdf,
    storage,
)
from ._common import _audit, _ms_since, _now_iso, log


class PagesJobMixin:
    async def _run_pages_job(self, job_id: str, job: dict[str, Any]) -> None:
        doc_id = job["doc_id"]
        pages: list[int] = job["pages"]
        engine: str = job["engine"]
        provider_name: str = job["provider"]
        config: dict[str, Any] = job.get("config", {}) or {}
        prompt: str = job.get("prompt") or get_settings().default_vlm_prompt
        overwrite: bool = bool(job.get("overwrite", False))

        job_extra = {"job_id": job_id, "doc_id": doc_id}
        audit_ctx = {"doc_id": doc_id, "job_id": job_id}
        log.info("job_start", extra={**job_extra, "page_count": len(pages), "engine": engine, "provider": provider_name})
        job_t0 = time.monotonic()

        self._start_job(job_id, pages=pages)

        try:
            if engine == "ocr":
                provider = registry.get_ocr(provider_name)
            elif engine == "vlm":
                provider = registry.get_vlm(provider_name)
            else:
                raise ValueError(f"unknown engine: {engine!r}")
        except Exception as exc:
            self._fail_job(job_id, str(exc))
            return

        errors: list[dict[str, Any]] = []
        for page in pages:
            if not overwrite and storage.load_transcription(doc_id, page) is not None:
                self._emit(
                    job_id,
                    {"event": "page-skipped", "data": {"page": page, "reason": "exists"}},
                )
                storage.update_job(job_id, current_page=page)
                continue

            self._emit(job_id, {"event": "page-started", "data": {"page": page}})
            storage.update_job(job_id, current_page=page)

            image_path = storage.page_image_path(doc_id, page)
            if not image_path.exists():
                err = {"page": page, "message": f"missing page image: {image_path}"}
                errors.append(err)
                self._emit(job_id, {"event": "page-error", "data": err})
                continue

            t0 = time.monotonic()
            try:
                if engine == "ocr":
                    result = await asyncio.to_thread(provider.transcribe, image_path, config)
                    payload_extra: dict[str, Any] = {}
                else:
                    image_bytes = await asyncio.to_thread(
                        pdf.prepare_for_vlm, image_path, get_settings().vlm_max_edge
                    )
                    result = await asyncio.to_thread(
                        provider.transcribe, image_bytes, prompt, config
                    )
                    payload_extra = {"prompt": prompt, "model": config.get("model")}
            except Exception as exc:
                err = {"page": page, "message": str(exc)}
                errors.append(err)
                self._emit(job_id, {"event": "page-error", "data": err})
                if engine == "vlm":
                    _audit(
                        provider=provider_name,
                        job_type="transcribe_pages",
                        status="error",
                        duration_ms=_ms_since(t0),
                        context={**audit_ctx, "page": page},
                        config=config,
                        error=str(exc),
                    )
                continue

            duration_ms = _ms_since(t0)
            if engine == "vlm":
                _audit(
                    provider=provider_name,
                    job_type="transcribe_pages",
                    status="success",
                    duration_ms=duration_ms,
                    context={**audit_ctx, "page": page},
                    meta=result.meta,
                )
            log.debug("page_done", extra={**job_extra, "page": page, "duration_ms": duration_ms})
            # Note: `duration_ms` is intentionally not persisted in the
            # transcription payload — the LLM audit log is the canonical source
            # for per-call timing. Keeping it here as well would create a second
            # source of truth that drifts.
            payload = {
                "page": page,
                "engine": engine,
                "provider": provider_name,
                "markdown": blanks.normalize_blanks(result.markdown),
                "raw": result.raw,
                "tokens": [],
                "annotations": {},
                "meta": result.meta,
                "created_at": _now_iso(),
                **payload_extra,
            }
            storage.save_transcription(doc_id, page, payload)
            self._emit(
                job_id,
                {
                    "event": "page-done",
                    "data": {"page": page, "duration_ms": duration_ms},
                },
            )

        job_duration_ms = _ms_since(job_t0)
        final_status = "completed" if not errors else "completed_with_errors"
        log.info("job_end", extra={**job_extra, "status": final_status, "duration_ms": job_duration_ms, "error_count": len(errors)})

        storage.update_job(
            job_id,
            status=final_status,
            finished_at=_now_iso(),
            errors=errors,
        )
        self._emit(job_id, {"event": "job-done", "data": {"errors": errors}})
