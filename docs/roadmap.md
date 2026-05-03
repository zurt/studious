# Studious - Roadmap

## Phase 1: Chapters + Regions + Targeted Transcription (Current)

- [x] PDF and image upload with page rendering
- [x] Anthropic Claude VLM integration with custom prompt
- [x] Side-by-side page image + transcription viewer
- [x] Async job queue with SSE progress streaming
- [x] Structured logging with correlation IDs
- [x] Supply chain security (package manager cooldown)
- [x] Chapter management (create, list, update, delete)
- [x] Region drawing on page images (canvas overlay with bbox)
- [x] Region tagging (reading_passage, vocab_list, grammar_points, exercises, etc.)
- [x] Region-level VLM transcription (crop to bbox, send to Claude)
- [x] Vanilla TypeScript frontend (no framework)
- [x] Map-like zoom/pan page viewer (pinch zoom, two-finger scroll, Cmd+/-, Cmd+0, fit button)
- [x] Full screen mode
- [x] Chapter popover panel (closed by default) with drag-to-reorder
- [x] Current chapter indicator banner in document view
- [x] Region transcription tracker widget in chapter view (pending count, batch transcribe)
- [x] Resizable split panes with collapse affordance (drag splitter, collapse left/right, persists in localStorage)

## Phase 1.5: UX Safety + LLM Observability

- [x] Confirmation dialog utility + wired into region, chapter, and document delete
- [x] LLM audit log (append-only JSONL with provider, model, tokens, duration, context)
- [x] Cost tracking estimation (per-model token pricing, cost-per-request, summary API)

## Phase 1.6: Logging & Observability Improvements

Detailed implementation notes for each item in `docs/logging-improvements.md`.
Items 1–4 are the highest-leverage and should ship together; 5–8 are the next
batch; 9–12 are polish.

P0 — correctness fixes:
- [ ] 1. Stop dropping `extra=` fields in `StructuredFormatter` (allowlist → denylist)
- [ ] 2. Propagate `correlation_id` from request middleware into `JobManager` workers
- [ ] 3. Log every Anthropic VLM call from the provider (start/done/error, request_id, cache fields)
- [ ] 4. Enrich audit-log entries with `request_id`, `prompt_hash`, `image_bytes`, cache tokens

P1 — frontend correctness & DX:
- [ ] 5. Replace frontend `_activeCorrelationId` module global with per-request CIDs
- [ ] 6. Wire `logError` into every frontend `catch` block (currently `alert()` only)
- [ ] 7. Add `STUDIOUS_LOG_LEVEL` env var; demote `page_done` to DEBUG
- [x] 8. Add `/api/costs/summary` and `/api/costs/audit` endpoints (foundation for cost UI)

P2 — polish:
- [ ] 9. `make logs` / `make audit-log` targets (`tail -F | jq -C .`)
- [ ] 10. Drop `duration_ms` from transcription file payload (audit log is canonical)
- [ ] 11. `tests/test_logging.py` to lock in formatter behaviour (regression guard for #1)
- [ ] 12. Rotate `llm_audit.jsonl` monthly + maintain summary cache

## Phase 1.7: Test Coverage

See `docs/test-coverage-plan.md` for the full phased plan. Items below are the
high-priority work (phases 1 and 2 of that plan).

- [ ] FastAPI handler tests via `TestClient` covering documents, chapters,
      regions, transcribe, jobs (SSE), and providers routes
- [ ] `JobManager` coverage for VLM engine path, region jobs, unknown engine,
      per-page errors → `completed_with_errors`, missing page image,
      `overwrite=True`, SSE subscribe/unsubscribe, sequential ordering
- [ ] `CorrelationMiddleware` and `StructuredFormatter` tests
- [ ] `services/pdf.py` tests for `render_pdf_to_pages`, `copy_image_as_page`,
      `prepare_for_vlm`
- [ ] Provider registry tests + Anthropic VLM tests with mocked SDK
      (temperature deprecation for `claude-opus-4-7`, model default, message
      envelope, usage extraction)
- [ ] Storage edge cases: atomic write crash safety, `list_documents`
      ordering, Japanese-string round-trip, `update_job` missing id
- [ ] `pytest --cov=app` wired into `make test` with ≥75% on `app/api/`,
      `app/jobs.py`, `app/middleware.py`

## Phase 2: Sentence Breakdowns

- [ ] Sentence-by-sentence breakdown (vocab, grammar, gloss) per region
- [ ] Text-only VLM calls for analysis (no image tokens, cheaper)
- [ ] Breakdown storage per-region
- [ ] Breakdown display UI (cards/accordions)

## Phase 3: Central Vocab/Grammar Store

- [ ] Global vocab store (JSONL-based, across all textbooks)
- [ ] Global grammar store (same pattern)
- [ ] Status tracking (new → reviewing → known)
- [ ] Vocab dashboard with filtering and search
- [ ] Auto-populate store from breakdowns (dedup by headword+reading)

## Phase 4: Export + Exercises

- [ ] Anki TSV export for vocab/grammar items
- [ ] Exercise-specific prompts and walkthrough UI
- [ ] Grammar dashboard

## Phase 5: Polish + Native

- [ ] Bulk operations (transcribe/breakdown all regions in a chapter)
- [ ] Region editing (resize, move, reorder)
- [ ] Native macOS/iOS/iPad apps (SwiftUI, same backend API)
- [ ] Mobile-responsive web layout
