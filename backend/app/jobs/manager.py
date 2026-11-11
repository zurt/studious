"""The job queue itself: submission, SSE fan-out, lifecycle helpers and
dispatch. Each job type's runner lives in its own module as a mixin."""
from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from typing import Any

from ..middleware import correlation_id_var
from ..services import (
    storage,
)
from ._common import _now_iso, log
from .breakdown import BreakdownJobMixin
from .bulk import BulkChapterJobMixin
from .exercise import ExerciseCompletionJobMixin
from .grammar_guide import GrammarGuideJobMixin
from .pages import PagesJobMixin
from .regions import RegionJobMixin


class JobManager(
    PagesJobMixin,
    RegionJobMixin,
    BreakdownJobMixin,
    BulkChapterJobMixin,
    ExerciseCompletionJobMixin,
    GrammarGuideJobMixin,
):
    """Sequential, in-process job queue.

    One transcription request runs at a time. Subsequent submissions queue
    behind the current job. Per-page progress is broadcast on per-job event
    queues for SSE consumers.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listeners: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name="studious-job-worker")

    async def stop(self) -> None:
        if self._worker and not self._worker.done():
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Capture the caller's correlation id so the worker, which runs
        # in a detached task with an empty context var, can still log
        # under the same trace.
        payload = {**payload, "correlation_id": correlation_id_var.get("")}
        job = storage.create_job(payload)
        # Submitting routes are sync `def`s, so this runs on a Starlette
        # threadpool thread — asyncio.Queue is not thread-safe, and a
        # put_nowait from a foreign thread can lose the worker's wakeup
        # (job stuck in "queued"). Hand the put to the loop thread.
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, job["id"])
        else:
            self._queue.put_nowait(job["id"])
        return job

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners[job_id].append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        if job_id in self._listeners:
            with contextlib.suppress(ValueError):
                self._listeners[job_id].remove(q)
            if not self._listeners[job_id]:
                self._listeners.pop(job_id, None)

    def _emit(self, job_id: str, event: dict[str, Any]) -> None:
        for q in list(self._listeners.get(job_id, [])):
            q.put_nowait(event)

    def _start_job(self, job_id: str, **data: Any) -> None:
        storage.update_job(job_id, status="running", started_at=_now_iso(), errors=[])
        self._emit(job_id, {"event": "job-started", "data": {"job_id": job_id, **data}})

    def _fail_job(
        self,
        job_id: str,
        message: str,
        *,
        error_extra: dict[str, Any] | None = None,
        emit_extra: dict[str, Any] | None = None,
    ) -> None:
        storage.update_job(
            job_id,
            status="failed",
            finished_at=_now_iso(),
            errors=[{"message": message, **(error_extra or {})}],
        )
        self._emit(
            job_id,
            {"event": "job-failed", "data": {"error": message, **(emit_extra or {})}},
        )

    def _complete_job(self, job_id: str, *, duration_ms: int) -> None:
        storage.update_job(job_id, status="completed", finished_at=_now_iso(), errors=[])
        self._emit(
            job_id,
            {"event": "job-done", "data": {"duration_ms": duration_ms, "errors": []}},
        )

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except Exception as exc:
                log.exception("job %s failed", job_id)
                # Without this, an unexpected exception leaves the job
                # "queued"/"running" forever and its SSE stream never
                # emits a terminal event.
                try:
                    job = storage.load_job(job_id)
                    terminal = ("completed", "completed_with_errors", "failed")
                    if job is not None and job.get("status") not in terminal:
                        self._fail_job(job_id, f"internal error: {exc}")
                except Exception:
                    log.exception("job %s could not be marked failed", job_id)
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
            if job_type == "exercise_completion":
                await self._run_exercise_completion_job(job_id, job)
                return
            if job_type == "grammar_guide":
                await self._run_grammar_guide_job(job_id, job)
                return
            if job_type == "bulk_chapter":
                await self._run_bulk_chapter_job(job_id, job)
                return
            await self._run_pages_job(job_id, job)
        finally:
            correlation_id_var.reset(token)


manager = JobManager()
