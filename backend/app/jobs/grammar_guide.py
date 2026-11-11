"""Chapter grammar-guide jobs (`grammar_guide`).

A mixin for `JobManager` (see `manager.py`), which supplies `_emit`,
`_start_job`, `_fail_job` and `_complete_job`.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..providers import registry
from ..services import (
    grammar_guide,
    storage,
)
from ._common import _audit, _ms_since, log


class GrammarGuideJobMixin:
    async def _run_grammar_guide_job(self, job_id: str, job: dict[str, Any]) -> None:
        doc_id = job["doc_id"]
        chapter_id = job["chapter_id"]
        provider_name: str = job["provider"]
        config: dict[str, Any] = job.get("config", {}) or {}
        prompt: str = job.get("prompt", "")
        tool_name: str = job.get("tool_name", "record_grammar_guide")
        tool_schema: dict[str, Any] = job.get("tool_schema", {})

        job_extra = {"job_id": job_id, "doc_id": doc_id, "chapter_id": chapter_id}
        audit_ctx = {"doc_id": doc_id, "chapter_id": chapter_id, "job_id": job_id}
        log.info("grammar_guide_job_start", extra=job_extra)

        self._start_job(job_id)

        try:
            source_md, regions = grammar_guide.prepare_source(doc_id, chapter_id)
        except grammar_guide.NoGrammarRegionsError as exc:
            self._fail_job(job_id, str(exc))
            return
        except grammar_guide.UntranscribedRegionsError as exc:
            self._fail_job(job_id, str(exc), error_extra={"region_ids": exc.region_ids})
            return

        try:
            provider = registry.get_vlm(provider_name)
        except Exception as exc:
            self._fail_job(job_id, str(exc))
            return

        full_prompt = [
            {"text": f"{prompt}\n\n", "cache": True},
            {"text": f"<input>\n{source_md}\n</input>"},
        ]

        t0 = time.monotonic()
        try:
            result = await asyncio.to_thread(
                provider.call_tool, full_prompt, tool_name, tool_schema, config
            )
        except Exception as exc:
            _audit(
                provider=provider_name,
                job_type="grammar_guide",
                status="error",
                duration_ms=_ms_since(t0),
                context=audit_ctx,
                config=config,
                error=str(exc),
            )
            self._fail_job(job_id, str(exc))
            return

        duration_ms = _ms_since(t0)
        points = result.tool_input.get("points")
        if not isinstance(points, list) or not points:
            if result.meta.get("stop_reason") == "max_tokens":
                err_msg = "tool response was truncated at max_tokens before returning non-empty `points`"
            else:
                err_msg = "tool response missing non-empty `points`"
            _audit(
                provider=provider_name,
                job_type="grammar_guide",
                status="error",
                duration_ms=duration_ms,
                context=audit_ctx,
                meta=result.meta,
                error=err_msg,
            )
            self._fail_job(job_id, err_msg)
            return

        _audit(
            provider=provider_name,
            job_type="grammar_guide",
            status="success",
            duration_ms=duration_ms,
            context=audit_ctx,
            meta=result.meta,
        )
        log.info("grammar_guide_job_done", extra={**job_extra, "duration_ms": duration_ms})

        guide_payload = {
            "model": result.meta.get("model"),
            "intro": result.tool_input.get("intro") or "",
            "points": points,
            "source_fingerprint": grammar_guide.fingerprint(regions),
        }
        storage.save_grammar_guide(doc_id, chapter_id, guide_payload)
        self._complete_job(job_id, duration_ms=duration_ms)
