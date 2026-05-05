from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .config import get_settings
from .middleware import correlation_id_var
from .providers import registry
from .services import llm_audit, pdf, storage

log = logging.getLogger("studious.jobs")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    """Sequential, in-process job queue.

    One transcription request runs at a time. Subsequent submissions queue
    behind the current job. Per-page progress is broadcast on per-job event
    queues for SSE consumers.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._listeners: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    async def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="studious-job-worker")

    async def stop(self) -> None:
        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Capture the caller's correlation id so the worker, which runs
        # in a detached task with an empty context var, can still log
        # under the same trace.
        payload = {**payload, "correlation_id": correlation_id_var.get("")}
        job = storage.create_job(payload)
        self._queue.put_nowait(job["id"])
        return job

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners[job_id].append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        if job_id in self._listeners:
            try:
                self._listeners[job_id].remove(q)
            except ValueError:
                pass
            if not self._listeners[job_id]:
                self._listeners.pop(job_id, None)

    def _emit(self, job_id: str, event: dict[str, Any]) -> None:
        for q in list(self._listeners.get(job_id, [])):
            q.put_nowait(event)

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except Exception:
                log.exception("job %s failed", job_id)
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: str) -> None:
        job = storage.load_job(job_id)
        if job is None:
            return
        token = correlation_id_var.set(job.get("correlation_id") or "")
        try:
            job_type = job.get("job_type", "transcribe_pages")
            if job_type == "transcribe_region":
                await self._run_region_job(job_id, job)
                return
            if job_type == "breakdown_region":
                await self._run_breakdown_job(job_id, job)
                return
            await self._run_pages_job(job_id, job)
        finally:
            correlation_id_var.reset(token)

    async def _run_pages_job(self, job_id: str, job: dict[str, Any]) -> None:
        doc_id = job["doc_id"]
        pages: list[int] = job["pages"]
        engine: str = job["engine"]
        provider_name: str = job["provider"]
        config: dict[str, Any] = job.get("config", {}) or {}
        prompt: str = job.get("prompt") or get_settings().default_vlm_prompt
        overwrite: bool = bool(job.get("overwrite", False))

        job_extra = {"job_id": job_id, "doc_id": doc_id}
        log.info("job_start", extra={**job_extra, "page_count": len(pages), "engine": engine, "provider": provider_name})
        job_t0 = time.monotonic()

        storage.update_job(job_id, status="running", started_at=_now_iso(), errors=[])
        self._emit(job_id, {"event": "job-started", "data": {"job_id": job_id, "pages": pages}})

        try:
            if engine == "ocr":
                provider = registry.get_ocr(provider_name)
            elif engine == "vlm":
                provider = registry.get_vlm(provider_name)
            else:
                raise ValueError(f"unknown engine: {engine!r}")
        except Exception as exc:
            storage.update_job(
                job_id,
                status="failed",
                finished_at=_now_iso(),
                errors=[{"message": str(exc)}],
            )
            self._emit(job_id, {"event": "job-failed", "data": {"error": str(exc)}})
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
                    llm_audit.record(
                        provider=provider_name,
                        model=str(config.get("model") or get_settings().default_vlm_model),
                        job_type="transcribe_pages",
                        status="error",
                        duration_ms=int((time.monotonic() - t0) * 1000),
                        doc_id=doc_id,
                        job_id=job_id,
                        page=page,
                        error=str(exc),
                        correlation_id=correlation_id_var.get(""),
                    )
                continue

            duration_ms = int((time.monotonic() - t0) * 1000)
            if engine == "vlm":
                llm_audit.record(
                    provider=provider_name,
                    model=result.meta.get("model"),
                    job_type="transcribe_pages",
                    status="success",
                    duration_ms=duration_ms,
                    doc_id=doc_id,
                    job_id=job_id,
                    page=page,
                    correlation_id=correlation_id_var.get(""),
                    **llm_audit.extract_usage(result.meta),
                    **llm_audit.extract_provenance(result.meta),
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
                "markdown": result.markdown,
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

        job_duration_ms = int((time.monotonic() - job_t0) * 1000)
        final_status = "completed" if not errors else "completed_with_errors"
        log.info("job_end", extra={**job_extra, "status": final_status, "duration_ms": job_duration_ms, "error_count": len(errors)})

        storage.update_job(
            job_id,
            status=final_status,
            finished_at=_now_iso(),
            errors=errors,
        )
        self._emit(job_id, {"event": "job-done", "data": {"errors": errors}})


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

        storage.update_job(job_id, status="running", started_at=_now_iso(), errors=[])
        self._emit(job_id, {"event": "job-started", "data": {"job_id": job_id}})

        try:
            provider = registry.get_vlm(provider_name)
        except Exception as exc:
            storage.update_job(job_id, status="failed", finished_at=_now_iso(), errors=[{"message": str(exc)}])
            self._emit(job_id, {"event": "job-failed", "data": {"error": str(exc)}})
            return

        image_path = storage.page_image_path(doc_id, page)
        if not image_path.exists():
            err_msg = f"missing page image: {image_path}"
            storage.update_job(job_id, status="failed", finished_at=_now_iso(), errors=[{"message": err_msg}])
            self._emit(job_id, {"event": "job-failed", "data": {"error": err_msg}})
            return

        t0 = time.monotonic()
        try:
            image_bytes = await asyncio.to_thread(
                pdf.crop_region, image_path, bbox, get_settings().vlm_max_edge
            )
            result = await asyncio.to_thread(provider.transcribe, image_bytes, prompt, config)
        except Exception as exc:
            llm_audit.record(
                provider=provider_name,
                model=str(config.get("model") or get_settings().default_vlm_model),
                job_type="transcribe_region",
                status="error",
                duration_ms=int((time.monotonic() - t0) * 1000),
                doc_id=doc_id,
                chapter_id=chapter_id,
                region_id=region_id,
                job_id=job_id,
                page=page,
                error=str(exc),
                correlation_id=correlation_id_var.get(""),
            )
            storage.update_job(job_id, status="failed", finished_at=_now_iso(), errors=[{"message": str(exc)}])
            self._emit(job_id, {"event": "job-failed", "data": {"error": str(exc)}})
            return

        duration_ms = int((time.monotonic() - t0) * 1000)
        llm_audit.record(
            provider=provider_name,
            model=result.meta.get("model"),
            job_type="transcribe_region",
            status="success",
            duration_ms=duration_ms,
            doc_id=doc_id,
            chapter_id=chapter_id,
            region_id=region_id,
            job_id=job_id,
            page=page,
            correlation_id=correlation_id_var.get(""),
            **llm_audit.extract_usage(result.meta),
            **llm_audit.extract_provenance(result.meta),
        )
        log.info("region_job_done", extra={**job_extra, "duration_ms": duration_ms})

        storage.update_region(
            doc_id,
            chapter_id,
            region_id,
            transcription_md=result.markdown,
            transcribed_at=_now_iso(),
            transcribed_model=result.meta.get("model"),
        )
        storage.update_job(job_id, status="completed", finished_at=_now_iso(), errors=[])
        self._emit(job_id, {"event": "job-done", "data": {"duration_ms": duration_ms, "errors": []}})


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

        storage.update_job(job_id, status="running", started_at=_now_iso(), errors=[])
        self._emit(job_id, {"event": "job-started", "data": {"job_id": job_id}})

        region = storage.load_region(doc_id, chapter_id, region_id)
        if region is None:
            err_msg = "region not found"
            storage.update_job(job_id, status="failed", finished_at=_now_iso(), errors=[{"message": err_msg}])
            self._emit(job_id, {"event": "job-failed", "data": {"error": err_msg}})
            return
        transcription_md = region.get("transcription_md")
        if not transcription_md:
            err_msg = "region has no transcription"
            storage.update_job(job_id, status="failed", finished_at=_now_iso(), errors=[{"message": err_msg}])
            self._emit(job_id, {"event": "job-failed", "data": {"error": err_msg}})
            return

        try:
            provider = registry.get_vlm(provider_name)
        except Exception as exc:
            storage.update_job(job_id, status="failed", finished_at=_now_iso(), errors=[{"message": str(exc)}])
            self._emit(job_id, {"event": "job-failed", "data": {"error": str(exc)}})
            return

        full_prompt = (
            f"{prompt}\n\n<input>\n{transcription_md}\n</input>"
            if prompt
            else transcription_md
        )

        t0 = time.monotonic()
        try:
            result = await asyncio.to_thread(
                provider.call_tool, full_prompt, tool_name, tool_schema, config
            )
        except Exception as exc:
            llm_audit.record(
                provider=provider_name,
                model=str(config.get("model") or get_settings().default_vlm_model),
                job_type="breakdown_region",
                status="error",
                duration_ms=int((time.monotonic() - t0) * 1000),
                doc_id=doc_id,
                chapter_id=chapter_id,
                region_id=region_id,
                job_id=job_id,
                error=str(exc),
                correlation_id=correlation_id_var.get(""),
            )
            storage.update_job(job_id, status="failed", finished_at=_now_iso(), errors=[{"message": str(exc)}])
            self._emit(job_id, {"event": "job-failed", "data": {"error": str(exc)}})
            return

        duration_ms = int((time.monotonic() - t0) * 1000)

        sentences = result.tool_input.get("sentences")
        if not isinstance(sentences, list) or not sentences:
            err_msg = "tool response missing non-empty `sentences`"
            llm_audit.record(
                provider=provider_name,
                model=result.meta.get("model"),
                job_type="breakdown_region",
                status="error",
                duration_ms=duration_ms,
                doc_id=doc_id,
                chapter_id=chapter_id,
                region_id=region_id,
                job_id=job_id,
                error=err_msg,
                correlation_id=correlation_id_var.get(""),
                **llm_audit.extract_usage(result.meta),
                **llm_audit.extract_provenance(result.meta),
            )
            storage.update_job(job_id, status="failed", finished_at=_now_iso(), errors=[{"message": err_msg}])
            self._emit(job_id, {"event": "job-failed", "data": {"error": err_msg}})
            return

        llm_audit.record(
            provider=provider_name,
            model=result.meta.get("model"),
            job_type="breakdown_region",
            status="success",
            duration_ms=duration_ms,
            doc_id=doc_id,
            chapter_id=chapter_id,
            region_id=region_id,
            job_id=job_id,
            correlation_id=correlation_id_var.get(""),
            **llm_audit.extract_usage(result.meta),
            **llm_audit.extract_provenance(result.meta),
        )
        log.info("breakdown_job_done", extra={**job_extra, "duration_ms": duration_ms})

        storage.save_breakdown(
            doc_id,
            chapter_id,
            region_id,
            {
                "model": result.meta.get("model"),
                "sentences": sentences,
            },
        )
        storage.update_job(job_id, status="completed", finished_at=_now_iso(), errors=[])
        self._emit(job_id, {"event": "job-done", "data": {"duration_ms": duration_ms, "errors": []}})


manager = JobManager()
