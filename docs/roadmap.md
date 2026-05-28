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
- [x] Tag-specific VLM prompt for `vocab_list` (full-width furigana, glosses,
      preserves item indices and section headers)
- [x] Region-level VLM transcription (crop to bbox, send to Claude)
- [x] Vanilla TypeScript frontend (no framework)
- [x] Map-like zoom/pan page viewer (pinch zoom, two-finger scroll, Cmd+/-, Cmd+0, fit button)
- [x] Full screen mode
- [x] Chapter popover panel (closed by default) with drag-to-reorder
- [x] Current chapter indicator banner in document view
- [x] Region transcription tracker widget in chapter view (pending count, batch transcribe)
- [x] Resizable split panes with collapse affordance (drag splitter, collapse left/right, persists in localStorage)
- [x] Copy-to-clipboard buttons on region cards and transcription detail view
- [x] Text size toggle (100/150/200%) in transcription detail view
- [x] Auto-select region on page navigation, remembering last selection per page
- [x] Region hover highlight with fade-out (replaces persistent shading)

## Phase 1.5: UX Safety + LLM Observability

- [x] Confirmation dialog utility + wired into region, chapter, and document delete
- [x] LLM audit log (append-only JSONL with provider, model, tokens, duration, context)
- [x] Cost tracking estimation (per-model token pricing, cost-per-request, summary API)
- [x] Settings modal (general + usage sections) with floating gear/fullscreen controls and cost summary UI

## Phase 1.6: Logging & Observability Improvements

Detailed implementation notes for each item in `docs/logging-improvements.md`.
Items 1–4 are the highest-leverage and should ship together; 5–8 are the next
batch; 9–12 are polish.

P0 — correctness fixes:
- [x] 1. Stop dropping `extra=` fields in `StructuredFormatter` (allowlist → denylist)
- [x] 2. Propagate `correlation_id` from request middleware into `JobManager` workers
- [x] 3. Log every Anthropic VLM call from the provider (start/done/error, request_id, cache fields)
- [x] 4. Enrich audit-log entries with `request_id`, `prompt_hash`, `image_bytes`, cache tokens

P1 — frontend correctness & DX:
- [x] 5. Replace frontend `_activeCorrelationId` module global with per-request CIDs
- [x] 6. Wire `logError` into every frontend `catch` block (currently `alert()` only)
- [x] 7. Add `STUDIOUS_LOG_LEVEL` env var; demote `page_done` to DEBUG
- [x] 8. Add `/api/costs/summary` and `/api/costs/audit` endpoints (foundation for cost UI)

P2 — polish:
- [x] 9. `make logs` / `make audit-log` targets (`tail -F | jq -C .`)
- [x] 10. Drop `duration_ms` from transcription file payload (audit log is canonical)
- [x] 11. `tests/test_logging.py` to lock in formatter behaviour (regression guard for #1)
- [x] 12. Rotate `llm_audit.jsonl` monthly + maintain summary cache

## Phase 1.7: Test Coverage

See `docs/test-coverage-plan.md` for the full phased plan.

Done since the phase was opened:
- [x] `CorrelationMiddleware` + `StructuredFormatter` regression tests
      (`tests/test_logging.py`)
- [x] `JobManager` VLM engine path, region jobs, per-page errors →
      `completed_with_errors`, `overwrite=True/False`, sequential ordering
      (`tests/test_jobs_with_mock_provider.py`)
- [x] Anthropic VLM with mocked SDK — temperature deprecation for
      `claude-opus-4-7`, default-model fallback, message envelope, usage
      extraction, start/done logging (`tests/test_anthropic_provider.py`)
- [x] Chapter + region API handlers, cost endpoints, breakdown endpoints
      (`tests/test_chapters_regions.py`, `tests/test_costs.py`,
      `tests/test_breakdown_links.py`)
- [x] Storage: `list_documents` recent-first, Japanese-string round-trip
      (`tests/test_storage.py`, `tests/test_logging.py`)

Outstanding:
- [x] FastAPI handler tests for documents (POST/PUT/DELETE/GET),
      `/api/transcribe`, `/api/jobs/{id}/events` (SSE), `/api/providers`
      (`tests/test_api_documents.py`, `tests/test_api_transcribe.py`,
      `tests/test_api_jobs_sse.py`, `tests/test_api_providers.py`)
- [x] `JobManager`: unknown engine → `failed`, missing page image → page
      error (not job failure), SSE `subscribe`/`unsubscribe` lifecycle,
      sequential ordering (`tests/test_jobs_lifecycle.py`)
- [x] `services/pdf.py`: `render_pdf_to_pages`, `copy_image_as_page`,
      `prepare_for_vlm` (`tests/test_pdf_service.py`)
- [x] Provider registry: `register`/`get`/`list`, unknown name raises,
      `bootstrap_default_providers` idempotent; OCR `_to_markdown` paragraph
      splitting (`tests/test_provider_registry.py`)
- [x] Storage edges: `_atomic_write_text` crash safety, `update_job` missing
      id raises `KeyError` (`tests/test_storage_edges.py`)
- [x] `pytest --cov=app --cov-fail-under=75` wired into `make test`;
      coverage on `app/api/`, `app/jobs.py`, `app/middleware.py` all ≥75%
      (current total: 89%)

## Phase 1.8: Frontend Test Coverage

Vitest + jsdom now run as part of `make test`. See the frontend section of
`docs/test-coverage-plan.md` for the original plan.

- [x] Stand up Vitest + jsdom (respect 7-day cooldown in `frontend/.npmrc`);
      add `test` and `test:coverage` scripts; wire `make test` to run both
      suites
- [x] `api.ts` — fetch wrapper tests with mocked `fetch` (correlation header
      injection, non-2xx throws, `getTranscription` 404 → `null`)
- [x] `logger.ts` — correlation id generation/format, `startTimer` duration
- [x] `router.ts` — pattern compile, parameter extraction, route dispatch
- [x] `modules/region-drawer.ts` — image-coords ↔ normalized-bbox math,
      click-vs-drag selection threshold
- [x] `modules/zoom-pan.ts` — transform math, clamping
- [x] `modules/pane-splitter.ts` — ratio clamping, localStorage round-trip
- [x] `modules/page-input.ts` — Enter/Esc/blur behaviour, min/max clamping
- [x] Coverage target: ≥70% line on `frontend/src/modules/` plus
      `api.ts`/`logger.ts`/`router.ts` (achieved: 90.6% line overall;
      api.ts 97%, router.ts 100%, modules dir 87.7%)

## Phase 1.9: Supply Chain Hardening

See `docs/supply-chain-plan.md` for full details.

Priority 1:
- [ ] Frozen installs in CI (`uv sync --frozen`, `npm ci`)
- [ ] `make audit` runs on every PR; fails on high/critical
- [ ] Dependabot config with 7-day cooldown (pip + npm + actions)

Priority 2 (second pass, bundled):
- [ ] Pin GitHub Actions by SHA
- [ ] Enable GitHub secret scanning + push protection
- [ ] Prune unused deps (`depcheck`, `deptry`)
- [ ] SBOM on release tags
- [ ] Document API key rotation; sandbox PDF rendering

## Phase 2: Sentence Breakdowns

- [x] Sentence-by-sentence breakdown (vocab, grammar, gloss) per region
- [x] Text-only VLM calls for analysis (no image tokens, cheaper)
- [x] Breakdown storage per-region
- [x] Breakdown display UI (cards/accordions)

### Phase 2.1: Inline vocab/grammar links

See `docs/breakdown-vocab-links-plan.md`.

- [x] Iter 1 — Backend vocab linker (exact/reading/stem) + lazy migration on read
- [x] Iter 2 — Frontend renders linked spans with click-to-open popover (vocab)
- [x] Iter 3 — Grammar links via LLM-emitted surface strings; overlapping
      vocab + grammar merge into a single popover
- [x] Iter 4 — Polish: hide-by-default vocab/grammar answers behind a
      per-card eye toggle (gray-bar overlay, no layout shift),
      `breakdown_links_annotated` INFO log with per-region match-strategy
      counts, troubleshooting entries for linker miss modes

### Phase 2.2: Chapter Grammar Guide

- [x] Per-chapter "grammar guide" generated from concatenated
      `grammar_points` transcriptions via VLM tool-call (structured
      JSON: title / subtitle / sections of markdown).
- [x] Standalone view with Regenerate, Copy-markdown, and Open-in-window
      buttons; source-changed warning when any underlying grammar
      region is re-transcribed since the guide was generated.

### Phase 2.3: Exercise Completions

- [x] Per-sentence "Complete exercise" button on breakdown cards for
      `exercises` regions (gated on an existing breakdown). VLM tool-call
      returns `answer`, `explanation`, and three example sentences (the
      first as the simplest illustration, two more as appropriate
      variations); each example carries `japanese`, `reading`, `english`,
      and a brief `explanation`.
- [x] Region transcription sent as `<region_transcription>` context
      alongside the `<target_sentence>` so the model can read the
      exercise instruction header, sibling items, and choice banks.
- [x] Tool reports `no_exercise: true` with a `reason` when the target
      line isn't actually a drill item; UI shows a muted notice with a
      "Try again" button instead of treating it as an error.
- [x] Completions saved per-region keyed by `sentence_index`; cascaded
      delete with the region; cleared automatically when a region's
      breakdown is regenerated (sentence indices would otherwise become
      stale).

Beyond MVP (deferred):
- [ ] Bulk "Complete all exercises in this region" action that fans out
      one job per sentence, with per-item progress in the UI.
- [ ] Completion-count badge on exercises regions in the region list
      and chapter-view tracker widget.
- [ ] Include the chapter's grammar guide (when present) as additional
      context so completions stay grounded in patterns the chapter has
      actually taught.
- [ ] Markdown / clipboard export of completions per region and per
      chapter (mirror the breakdown copy-all affordance).
- [ ] Fallback: when transcription quality is poor, optionally include
      the region image crop in the VLM call (toggle, not default — image
      tokens are expensive).
- [ ] Regenerate-completion-on-stale: if the source breakdown is
      regenerated, surface the prior completions in a "review and
      reapply" UI rather than silently dropping them.

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
