"""Exercise-completion jobs (`exercise_completion`).

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
    region_chain,
    region_reference,
    storage,
)
from ._common import _audit, _ms_since, _now_iso, log


class ExerciseCompletionJobMixin:
    async def _run_exercise_completion_job(self, job_id: str, job: dict[str, Any]) -> None:
        doc_id = job["doc_id"]
        chapter_id = job["chapter_id"]
        region_id = job["region_id"]
        sentence_index: int = job["sentence_index"]
        sentence_text: str = blanks.normalize_blanks(job["sentence_text"])
        chain = region_chain.resolve_chain(doc_id, chapter_id, region_id)
        region_transcription: str = (
            region_chain.combined_transcription(chain)
            if chain
            else (job.get("region_transcription") or "")
        )
        region_transcription = blanks.normalize_blanks(region_transcription)
        # Cited reading passages (possibly from other chapters/documents)
        # live on the chain head — the region this job runs from.
        references = region_reference.resolve_references(doc_id, chapter_id, region_id)
        reference_text = region_reference.combined_reference_text(references)
        provider_name: str = job["provider"]
        config: dict[str, Any] = job.get("config", {}) or {}
        prompt: str = job.get("prompt", "")
        tool_name: str = job.get("tool_name", "record_exercise_completion")
        tool_schema: dict[str, Any] = job.get("tool_schema", {})

        job_extra = {
            "job_id": job_id,
            "doc_id": doc_id,
            "chapter_id": chapter_id,
            "region_id": region_id,
            "sentence_index": sentence_index,
            "reference_count": len(references),
        }
        audit_ctx = {
            "doc_id": doc_id,
            "chapter_id": chapter_id,
            "region_id": region_id,
            "job_id": job_id,
        }
        log.info("exercise_completion_job_start", extra=job_extra)

        self._start_job(job_id)

        try:
            provider = registry.get_vlm(provider_name)
        except Exception as exc:
            self._fail_job(job_id, str(exc))
            return

        context_block = (
            f"<region_transcription>\n{region_transcription}\n</region_transcription>\n\n"
            if region_transcription
            else ""
        )
        reference_block = (
            f"<reading_reference>\n{reference_text}\n</reading_reference>\n\n"
            if reference_text
            else ""
        )
        # Cache boundaries: the instructions (incl. the learner profile) are
        # identical for every completion, and the region + reading context for
        # every item in this exercise block, so both are cached; only the one
        # target line is sent uncached. Items completed within the cache TTL
        # re-read everything else at the cache-read rate.
        full_prompt: list[dict[str, Any]] = [
            {"text": f"{prompt}\n\n", "cache": True},
            {"text": f"{context_block}{reference_block}", "cache": True},
            {"text": f"<target_sentence>\n{sentence_text}\n</target_sentence>"},
        ]

        # The model occasionally returns a well-formed-looking tool call that
        # finishes cleanly (stop_reason=tool_use) yet omits `answer` — low-rate
        # and not tied to output length. For `exercise_type: "open"` it can
        # also send an empty `examples` when it meant to include some; for
        # `exercise_type: "constrained"` (a word-bank or inline-choice item)
        # or `"question"` (a comprehension/discussion question — see
        # EXERCISE_COMPLETION_PROMPT) an empty `examples` is the correct,
        # intentional shape, not a sign of malformed output. The schema can't
        # force any of this (a forced tool call isn't strict-validated), so we
        # retry once on genuinely malformed output; the resend almost always
        # comes back complete. Truncation (max_tokens) and transport errors
        # are not retried — a second call with the same budget won't help.
        max_attempts = 2
        answer = examples = None
        for attempt in range(max_attempts):
            t0 = time.monotonic()
            try:
                result = await asyncio.to_thread(
                    provider.call_tool, full_prompt, tool_name, tool_schema, config
                )
            except Exception as exc:
                _audit(
                    provider=provider_name,
                    job_type="exercise_completion",
                    status="error",
                    duration_ms=_ms_since(t0),
                    context=audit_ctx,
                    config=config,
                    error=str(exc),
                )
                self._fail_job(job_id, str(exc))
                return

            duration_ms = _ms_since(t0)
            if result.tool_input.get("no_exercise"):
                reason = result.tool_input.get("reason") or "No exercise found in this sentence."
                err_msg = f"no_exercise: {reason}"
                # The model answered as instructed — the target just isn't a
                # drill item — so the call itself is audited as a success.
                _audit(
                    provider=provider_name,
                    job_type="exercise_completion",
                    status="success",
                    duration_ms=duration_ms,
                    context=audit_ctx,
                    meta=result.meta,
                )
                log.info("exercise_completion_no_exercise", extra={**job_extra, "reason": reason})
                self._fail_job(
                    job_id,
                    err_msg,
                    error_extra={"code": "no_exercise", "reason": reason},
                    emit_extra={"code": "no_exercise", "reason": reason},
                )
                return

            answer = result.tool_input.get("answer")
            examples = result.tool_input.get("examples")
            exercise_type = result.tool_input.get("exercise_type")
            # A `constrained` or `question` item is expected to come back with
            # `examples: []` (see EXERCISE_COMPLETION_PROMPT); only an `open`
            # item — or a response that never declared its type — needs a
            # non-empty list to count as well-formed.
            examples_ok = exercise_type in ("constrained", "question") or (
                isinstance(examples, list) and examples
            )
            if answer and examples_ok:
                break  # well-formed — fall through to persist below

            truncated = result.meta.get("stop_reason") == "max_tokens"
            err_msg = (
                "tool response was truncated at max_tokens before returning `answer` and `examples`"
                if truncated
                else "tool response missing `answer` or `examples`"
            )
            # Every attempt is a billed API call; audit each one.
            _audit(
                provider=provider_name,
                job_type="exercise_completion",
                status="error",
                duration_ms=duration_ms,
                context=audit_ctx,
                meta=result.meta,
                error=err_msg,
            )
            if truncated or attempt == max_attempts - 1:
                self._fail_job(job_id, err_msg)
                return
            log.info(
                "exercise_completion_retry",
                extra={**job_extra, "attempt": attempt + 1, "reason": err_msg},
            )

        entry = {
            "answer": answer,
            "answer_english": result.tool_input.get("answer_english") or "",
            "explanation": result.tool_input.get("explanation") or "",
            "exercise_type": exercise_type,
            # Only kept if it's genuinely a substring of `answer` — the
            # frontend highlights it via a plain string search, so a
            # non-substring value (hallucinated or mismatched) would just
            # silently fail to highlight; better to drop it here than store
            # something misleading.
            "filled_text": (
                result.tool_input.get("filled_text")
                if isinstance(result.tool_input.get("filled_text"), str)
                and result.tool_input.get("filled_text")
                and result.tool_input.get("filled_text") in answer
                else ""
            ),
            "examples": examples if isinstance(examples, list) else [],
            "model": result.meta.get("model"),
            # Which learner settings produced this entry, so answers made
            # before a settings change can be told apart.
            "profile": {
                "level": (job.get("profile") or {}).get("level"),
                "answer_length": (job.get("profile") or {}).get("answer_length"),
            },
            "updated_at": _now_iso(),
        }
        storage.upsert_exercise_completion_entry(
            doc_id, chapter_id, region_id, sentence_index, entry
        )

        _audit(
            provider=provider_name,
            job_type="exercise_completion",
            status="success",
            duration_ms=duration_ms,
            context=audit_ctx,
            meta=result.meta,
        )
        log.info("exercise_completion_job_done", extra={**job_extra, "duration_ms": duration_ms})
        self._complete_job(job_id, duration_ms=duration_ms)
