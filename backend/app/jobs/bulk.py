"""Chapter bulk operations (`bulk_chapter`, "Prepare chapter").

A mixin for `JobManager` (see `manager.py`), which supplies `_emit`,
`_start_job`, `_fail_job` and `_complete_job`.
"""
from __future__ import annotations

import time
from typing import Any

from ..config import (
    BREAKDOWN_TOOL_SCHEMA,
    REGION_TRANSCRIBE_PROMPT,
    SENTENCE_BREAKDOWN_PROMPT,
    VOCAB_LIST_TRANSCRIBE_PROMPT,
)
from ..services import (
    bulk_ops,
    storage,
)
from ..services.preferences import get_active_vlm_model
from ._common import _ms_since, _now_iso, _RegionOpError, log


class BulkChapterJobMixin:
    async def _run_bulk_chapter_job(self, job_id: str, job: dict[str, Any]) -> None:
        """Prepare a whole chapter: transcribe every untranscribed region,
        then break down every eligible one, per docs/design/bulk-operations-plan.md.

        A single loop over regions (like `_run_pages_job` loops pages)
        rather than a fan-out of single-region jobs: phase 2's work list
        depends on phase 1's output, and a loop gets that ordering for
        free. Per-region failures append to `errors[]`; one bad region
        never aborts the chapter.
        """
        doc_id = job["doc_id"]
        chapter_id = job["chapter_id"]
        do_transcribe: bool = bool(job.get("transcribe", True))
        do_breakdown: bool = bool(job.get("breakdown", True))
        overwrite_transcriptions: bool = bool(job.get("overwrite_transcriptions", False))
        overwrite_breakdowns: bool = bool(job.get("overwrite_breakdowns", False))
        provider_name: str = job.get("provider", "anthropic")

        job_extra = {"job_id": job_id, "doc_id": doc_id, "chapter_id": chapter_id}
        log.info(
            "bulk_chapter_job_start",
            extra={**job_extra, "transcribe": do_transcribe, "breakdown": do_breakdown},
        )
        job_t0 = time.monotonic()

        self._start_job(job_id)

        # Resolved once per run, not per region — matches the single-region
        # endpoints' "model at submit time" behavior, but resolved when the
        # (possibly queued) job actually executes rather than when it was
        # submitted.
        model = get_active_vlm_model()
        errors: list[dict[str, Any]] = []

        if do_transcribe:
            targets = bulk_ops.select_transcribe_targets(doc_id, chapter_id, overwrite=overwrite_transcriptions)
            self._emit(job_id, {"event": "phase-started", "data": {"op": "transcribe", "count": len(targets)}})
            storage.update_job(job_id, phase="transcribe", phase_total=len(targets), phase_done=0)
            for i, region in enumerate(targets):
                await self._run_bulk_region_transcribe(job_id, doc_id, chapter_id, region, provider_name, model, errors)
                storage.update_job(job_id, phase_done=i + 1)

        if do_breakdown:
            # Recomputed now, after phase 1: a region transcribed just above
            # is picked up here, and skip-if-exists keeps resubmission
            # idempotent.
            targets = bulk_ops.select_breakdown_targets(doc_id, chapter_id, overwrite=overwrite_breakdowns)
            self._emit(job_id, {"event": "phase-started", "data": {"op": "breakdown", "count": len(targets)}})
            storage.update_job(job_id, phase="breakdown", phase_total=len(targets), phase_done=0)
            for i, region in enumerate(targets):
                await self._run_bulk_region_breakdown(job_id, doc_id, chapter_id, region, provider_name, model, errors)
                storage.update_job(job_id, phase_done=i + 1)

        job_duration_ms = _ms_since(job_t0)
        final_status = "completed" if not errors else "completed_with_errors"
        log.info(
            "bulk_chapter_job_end",
            extra={**job_extra, "status": final_status, "duration_ms": job_duration_ms, "error_count": len(errors)},
        )
        storage.update_job(job_id, status=final_status, finished_at=_now_iso(), errors=errors)
        self._emit(job_id, {"event": "job-done", "data": {"errors": errors}})

    async def _run_bulk_region_transcribe(
        self,
        job_id: str,
        doc_id: str,
        chapter_id: str,
        region: dict[str, Any],
        provider_name: str,
        model: str,
        errors: list[dict[str, Any]],
    ) -> None:
        region_id = region["id"]
        page = region["page"]
        tag = region.get("tag") or "unspecified"
        event_data = {"op": "transcribe", "region_id": region_id, "page": page, "tag": tag}
        self._emit(job_id, {"event": "region-started", "data": event_data})
        storage.update_job(job_id, current_region=region_id)

        prompt = VOCAB_LIST_TRANSCRIBE_PROMPT if tag == "vocab_list" else REGION_TRANSCRIBE_PROMPT
        try:
            await self._transcribe_region_core(
                job_id=job_id,
                doc_id=doc_id,
                chapter_id=chapter_id,
                region_id=region_id,
                page=page,
                bbox=region["bbox"],
                provider_name=provider_name,
                config={"model": model},
                prompt=prompt,
            )
        except _RegionOpError as exc:
            err = {"op": "transcribe", "region_id": region_id, "page": page, "message": str(exc)}
            errors.append(err)
            self._emit(job_id, {"event": "region-error", "data": err})
        else:
            self._emit(job_id, {"event": "region-done", "data": event_data})

    async def _run_bulk_region_breakdown(
        self,
        job_id: str,
        doc_id: str,
        chapter_id: str,
        region: dict[str, Any],
        provider_name: str,
        model: str,
        errors: list[dict[str, Any]],
    ) -> None:
        region_id = region["id"]
        page = region["page"]
        tag = region.get("tag") or "unspecified"
        event_data = {"op": "breakdown", "region_id": region_id, "page": page, "tag": tag}
        self._emit(job_id, {"event": "region-started", "data": event_data})
        storage.update_job(job_id, current_region=region_id)

        try:
            await self._breakdown_region_core(
                job_id=job_id,
                doc_id=doc_id,
                chapter_id=chapter_id,
                region_id=region_id,
                provider_name=provider_name,
                config={"model": model, "max_tokens": 16384},
                prompt=SENTENCE_BREAKDOWN_PROMPT,
                tool_name="record_breakdown",
                tool_schema=BREAKDOWN_TOOL_SCHEMA,
            )
        except _RegionOpError as exc:
            err = {"op": "breakdown", "region_id": region_id, "page": page, "message": str(exc)}
            errors.append(err)
            self._emit(job_id, {"event": "region-error", "data": err})
        else:
            self._emit(job_id, {"event": "region-done", "data": event_data})
