"""Sentence-breakdown jobs (`breakdown_region`).

A mixin for `JobManager` (see `manager.py`), which supplies `_emit`,
`_start_job`, `_fail_job` and `_complete_job`.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..providers import registry
from ..services import (
    blanks,
    breakdown_links,
    harvest,
    region_chain,
    storage,
)
from ._common import _audit, _ms_since, _RegionOpError, log


class BreakdownJobMixin:
    async def _breakdown_region_core(
        self,
        *,
        job_id: str,
        doc_id: str,
        chapter_id: str,
        region_id: str,
        provider_name: str,
        config: dict[str, Any],
        prompt: str,
        tool_name: str,
        tool_schema: dict[str, Any],
    ) -> int:
        """chain -> call_tool -> validate -> annotate -> save ->
        invalidate-completions -> harvest for one region.

        Returns duration_ms on success. Raises `_RegionOpError` (already
        audited under job_type="breakdown_region" once a provider call is
        attempted) on any failure: no region, no transcription, an
        unavailable provider, a provider error, a malformed tool response,
        or a post-processing error. Shared by the single-region runner and
        the bulk chapter runner.
        """
        job_extra = {"job_id": job_id, "doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id}
        audit_ctx = {
            "doc_id": doc_id,
            "chapter_id": chapter_id,
            "region_id": region_id,
            "job_id": job_id,
        }

        region = storage.load_region(doc_id, chapter_id, region_id)
        if region is None:
            raise _RegionOpError("region not found")
        chain = region_chain.resolve_chain(doc_id, chapter_id, region_id)
        transcription_md = region_chain.combined_transcription(chain) if chain else (region.get("transcription_md") or "")
        if not transcription_md:
            raise _RegionOpError("region has no transcription")
        # Legacy transcriptions may hold `\_\_\_` or 30-char runs; the model
        # copies the input verbatim, so canonicalize blanks before it sees them.
        transcription_md = blanks.normalize_blanks(transcription_md)

        try:
            provider = registry.get_vlm(provider_name)
        except Exception as exc:
            raise _RegionOpError(str(exc)) from exc

        region_tag = region.get("tag") or "unspecified"
        # Only the instructions repeat across breakdowns, so only they are
        # cached; the region's text is new every call.
        full_prompt: list[dict[str, Any]] | str = (
            [
                {"text": f"{prompt}\n\n", "cache": True},
                {"text": f"<region_tag>{region_tag}</region_tag>\n<input>\n{transcription_md}\n</input>"},
            ]
            if prompt
            else transcription_md
        )

        t0 = time.monotonic()
        try:
            result = await asyncio.to_thread(
                provider.call_tool, full_prompt, tool_name, tool_schema, config
            )
        except Exception as exc:
            _audit(
                provider=provider_name,
                job_type="breakdown_region",
                status="error",
                duration_ms=_ms_since(t0),
                context=audit_ctx,
                config=config,
                error=str(exc),
            )
            raise _RegionOpError(str(exc)) from exc

        duration_ms = _ms_since(t0)

        sentences = result.tool_input.get("sentences")
        if not isinstance(sentences, list) or not sentences:
            if result.meta.get("stop_reason") == "max_tokens":
                err_msg = "tool response was truncated at max_tokens before returning non-empty `sentences`"
            else:
                err_msg = (
                    "model returned no sentences for this region — it may be empty, "
                    "purely visual, or all-blank exercise items the model declined to "
                    "split; try re-running, or check the transcription"
                )
            _audit(
                provider=provider_name,
                job_type="breakdown_region",
                status="error",
                duration_ms=duration_ms,
                context=audit_ctx,
                meta=result.meta,
                error=err_msg,
            )
            raise _RegionOpError(err_msg)

        for sentence in sentences:
            if isinstance(sentence, dict) and isinstance(sentence.get("text"), str):
                sentence["text"] = blanks.normalize_blanks(sentence["text"])
        breakdown_payload = {
            "model": result.meta.get("model"),
            "sentences": sentences,
        }
        try:
            breakdown_links.annotate(breakdown_payload)
            storage.save_breakdown(doc_id, chapter_id, region_id, breakdown_payload)
            # Sentence indices in completions only make sense against the
            # breakdown that produced them. A new breakdown invalidates them.
            storage.delete_exercise_completion(doc_id, chapter_id, region_id)
        except Exception as exc:
            err_msg = f"post-processing failed: {exc}"
            log.exception("breakdown_postprocess_error", extra=job_extra)
            _audit(
                provider=provider_name,
                job_type="breakdown_region",
                status="error",
                duration_ms=duration_ms,
                context=audit_ctx,
                meta=result.meta,
                error=err_msg,
            )
            raise _RegionOpError(err_msg) from exc

        _audit(
            provider=provider_name,
            job_type="breakdown_region",
            status="success",
            duration_ms=duration_ms,
            context=audit_ctx,
            meta=result.meta,
        )
        # Harvest failures must not fail the breakdown job — the breakdown
        # itself saved fine and the store can catch up via backfill.
        try:
            harvest.ingest_breakdown(doc_id, chapter_id, region_id, breakdown_payload)
        except Exception:
            log.exception("harvest_breakdown_error", extra=job_extra)
        return duration_ms

    async def _run_breakdown_job(self, job_id: str, job: dict[str, Any]) -> None:
        doc_id = job["doc_id"]
        chapter_id = job["chapter_id"]
        region_id = job["region_id"]
        provider_name: str = job["provider"]
        config: dict[str, Any] = job.get("config", {}) or {}
        prompt: str = job.get("prompt", "")
        tool_name: str = job.get("tool_name", "record_breakdown")
        tool_schema: dict[str, Any] = job.get("tool_schema", {})

        job_extra = {
            "job_id": job_id,
            "doc_id": doc_id,
            "chapter_id": chapter_id,
            "region_id": region_id,
        }
        log.info("breakdown_job_start", extra=job_extra)

        self._start_job(job_id)

        try:
            duration_ms = await self._breakdown_region_core(
                job_id=job_id,
                doc_id=doc_id,
                chapter_id=chapter_id,
                region_id=region_id,
                provider_name=provider_name,
                config=config,
                prompt=prompt,
                tool_name=tool_name,
                tool_schema=tool_schema,
            )
        except _RegionOpError as exc:
            self._fail_job(job_id, str(exc))
            return

        log.info("breakdown_job_done", extra={**job_extra, "duration_ms": duration_ms})
        self._complete_job(job_id, duration_ms=duration_ms)
