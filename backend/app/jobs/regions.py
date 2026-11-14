"""Region transcription jobs (`transcribe_region`).

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
    harvest,
    pdf,
    region_check,
    speech_queue,
    storage,
)
from ._common import _audit, _ms_since, _now_iso, _RegionOpError, log


class RegionJobMixin:
    async def _transcribe_region_core(
        self,
        *,
        job_id: str,
        doc_id: str,
        chapter_id: str,
        region_id: str,
        page: int,
        bbox: list[float],
        provider_name: str,
        config: dict[str, Any],
        prompt: str,
    ) -> int:
        """Crop -> transcribe -> save -> harvest for one region.

        Returns duration_ms on success. Raises `_RegionOpError` (already
        audited under job_type="transcribe_region") if the provider is
        unavailable, the page image is missing, or the provider call fails.
        Shared by the single-region runner and the bulk chapter runner.
        """
        audit_ctx = {
            "doc_id": doc_id,
            "chapter_id": chapter_id,
            "region_id": region_id,
            "job_id": job_id,
            "page": page,
        }

        try:
            provider = registry.get_vlm(provider_name)
        except Exception as exc:
            raise _RegionOpError(str(exc)) from exc

        image_path = storage.page_image_path(doc_id, page)
        if not image_path.exists():
            raise _RegionOpError(f"missing page image: {image_path}")

        t0 = time.monotonic()
        try:
            image_bytes = await asyncio.to_thread(
                pdf.crop_region, image_path, bbox, get_settings().vlm_max_edge
            )
            result = await asyncio.to_thread(provider.transcribe, image_bytes, prompt, config)
        except Exception as exc:
            _audit(
                provider=provider_name,
                job_type="transcribe_region",
                status="error",
                duration_ms=_ms_since(t0),
                context=audit_ctx,
                config=config,
                error=str(exc),
            )
            raise _RegionOpError(str(exc)) from exc

        duration_ms = _ms_since(t0)
        _audit(
            provider=provider_name,
            job_type="transcribe_region",
            status="success",
            duration_ms=duration_ms,
            context=audit_ctx,
            meta=result.meta,
        )

        region = storage.update_region(
            doc_id,
            chapter_id,
            region_id,
            transcription_md=blanks.normalize_blanks(result.markdown),
            transcribed_at=_now_iso(),
            transcribed_model=result.meta.get("model"),
        )
        if region is not None and region.get("tag") == "vocab_list":
            # Harvest failures must not fail the transcription job — the
            # transcription itself succeeded and the store can catch up
            # via backfill.
            try:
                harvest.ingest_vocab_list_region(doc_id, chapter_id, region)
            except Exception:
                log.exception(
                    "harvest_vocab_list_error",
                    extra={"job_id": job_id, "doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id},
                )
            else:
                # Card clips for the new items, made in the background.
                try:
                    speech_queue.enqueue_region(doc_id, chapter_id, region_id)
                    speech_queue.kick()
                except Exception:
                    log.exception(
                        "speech_queue_enqueue_error",
                        extra={"job_id": job_id, "doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id},
                    )
        # The check is a convenience layered on a finished transcription: a
        # failure here must not fail the job. (run_after_transcription also
        # swallows its own errors; this guards the thread hop itself.)
        try:
            await asyncio.to_thread(
                region_check.run_after_transcription, doc_id, chapter_id, region_id
            )
        except Exception:
            log.exception(
                "region_check_error",
                extra={"job_id": job_id, "doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id},
            )
        return duration_ms

    async def _run_region_job(self, job_id: str, job: dict[str, Any]) -> None:
        doc_id = job["doc_id"]
        chapter_id = job["chapter_id"]
        region_id = job["region_id"]
        page: int = job["page"]
        bbox: list[float] = job["bbox"]
        provider_name: str = job["provider"]
        config: dict[str, Any] = job.get("config", {}) or {}
        prompt: str = job.get("prompt", "")

        job_extra = {"job_id": job_id, "doc_id": doc_id, "chapter_id": chapter_id, "region_id": region_id}
        log.info("region_job_start", extra=job_extra)

        self._start_job(job_id)

        try:
            duration_ms = await self._transcribe_region_core(
                job_id=job_id,
                doc_id=doc_id,
                chapter_id=chapter_id,
                region_id=region_id,
                page=page,
                bbox=bbox,
                provider_name=provider_name,
                config=config,
                prompt=prompt,
            )
        except _RegionOpError as exc:
            self._fail_job(job_id, str(exc))
            return

        log.info("region_job_done", extra={**job_extra, "duration_ms": duration_ms})
        self._complete_job(job_id, duration_ms=duration_ms)
