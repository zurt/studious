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
- [ ] Self-service pricing-table update from the settings usage view. Anthropic
      exposes no pricing API (the Models API returns capabilities/context only),
      so a non-LLM source would be either a third-party structured feed
      (e.g. LiteLLM's `model_prices_and_context_window.json`) or a scrape of the
      official pricing page — both carry trade-offs (supply-chain surface vs.
      fragile parsing) to weigh against the project's supply-chain rules.
      Interim: `MODEL_PRICING` in `backend/app/config.py` is updated by hand
      during development on a ~2-week cadence. See plan.md → Cost Tracking.

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

## Phase 1.8.1: Browser E2E Smoke Suite (Playwright)

Thin browser-level smoke suite over the real stack (vite + FastAPI) with a
mock VLM provider — deterministic, no API key, no tokens. Deliberately small:
one test per core journey, no visual regression (the web app is a prototype;
see "Web MVP now, native later" in `docs/plan.md`). Also serves as executable
UI documentation and a seeded environment for agent-driven browser
verification. See the E2E section of `docs/test-coverage-plan.md`.

- [x] Playwright scaffold: `frontend/playwright.config.ts`, `make test-e2e`,
      dedicated ports (backend 8765 / frontend 5273) so runs never touch a
      real dev stack or data dir
- [x] `backend/e2e_server.py` — ASGI entrypoint that registers a canned mock
      VLM under the "anthropic" name before app startup; isolated
      `backend/.e2e-data` wiped per run
- [x] Committed fixture PDF (`frontend/e2e/fixtures/sample.pdf`, 2 pages,
      generated with pymupdf)
- [x] Journey: fresh library shows empty state
- [x] Journey: upload PDF → document view renders page image, paging works
- [x] Journey: create chapter → chapter view opens; banner links back
- [x] Journey: draw region in chapter view → tag type → transcribe with mock
      provider → markdown renders in right pane
- [x] Journey: sentence breakdown on a transcribed region → cards render,
      vocab/grammar popover opens
- [x] Journey: grammar guide generation from grammar_points regions
- [x] Journey: exercise completion on an exercises-region breakdown →
      answer, explanation, and example sentences render
- [x] Journey: link a continuation region across pages (continuation
      transcribed via the tracker's "Transcribe all") → continuation's
      breakdown pane defers to the source; source shows the combined
      transcription
- [x] Journey: document lifecycle — upload a second document, delete it
      from the library card menu behind the confirm dialog
- [x] Journey: vocab dashboard lists breakdown-harvested items; status
      change persists across reload; stat-chip filters; grammar
      dashboard shows the harvested pattern
- [ ] Wire `make test-e2e` into CI (after journeys above stabilize)

## Phase 1.9: Supply Chain Hardening

See `docs/supply-chain-plan.md` for full details.

Priority 1:
- [x] Frozen installs in CI (`uv sync --frozen`, `npm ci`)
- [x] `make audit` runs on every PR; fails on high/critical
- [x] Dependabot config with 7-day cooldown (pip + npm + actions)

Priority 2 (second pass, bundled):
- [x] Pin GitHub Actions by SHA
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
- [x] Markdown / clipboard export of completions per region (per-card
      copy button + region-level "copy all completions", mirroring the
      breakdown copy-all affordance). Per-chapter export still deferred.
- [ ] Fallback: when transcription quality is poor, optionally include
      the region image crop in the VLM call (toggle, not default — image
      tokens are expensive).
- [ ] Regenerate-completion-on-stale: if the source breakdown is
      regenerated, surface the prior completions in a "review and
      reapply" UI rather than silently dropping them.

### Phase 2.4: Cross-Page Region Linking

- [x] Region schema gains an optional `continues_to` pointer (one-way,
      same chapter, target page must be later, cycles rejected).
- [x] `POST /api/documents/{doc_id}/chapters/{chapter_id}/regions/{region_id}/link`
      endpoint. Cross-chapter `move` clears the link; deleting a region
      clears any inbound pointers.
- [x] `region_chain.resolve_chain` + `combined_transcription` helpers
      consumed by the breakdown and exercise-completion jobs so they
      receive the joined transcription of the chain head + tails.
      Per-region transcription itself is unchanged (visual task; doesn't
      need cross-page context).
- [x] Chapter view's click-to-link UI (toolbar button, `L` shortcut,
      Esc to cancel): pick source, navigate, pick target. Tag-colored
      arrow glyph on canvas (→ on source, ← on target) and matching
      "Continues on p.N →" / "← Continued from p.N" chips on the
      region cards with unlink action.
- [x] Source region's detail pane renders the combined chain
      transcription with a dashed "continues on page N" separator;
      copy button emits combined markdown matching the VLM input.
- [x] Continuation regions reject `breakdown` and `exercise-completion`
      requests with a 409 pointing at the source. When a continuation
      region is selected, the breakdown pane shows an explanatory
      notice plus a "Go to source on p.N →" jump button instead of the
      Generate-breakdown UI.

## Phase 3: Central Vocab/Grammar Store

The long-term core study workflow: vocab and grammar accumulate across
textbooks into a single graded, dictionary-linked, editable store that
eventually powers built-in SRS and an iOS companion. Design agreed
2026-07-01 — see `docs/vocab-store-plan.md` for schemas, decisions, and
rationale.

### 3.1 Store foundation + harvest

Shipped 2026-07-01.

- [x] Sync-ready JSONL stores (`data/store/{vocab,grammar}.jsonl`):
      UUID ids, `updated_at`, tombstones, append-only
      latest-per-id-wins; dedup index derived in memory (no index file
      to drift)
- [x] Ingest hook: breakdown generation appends deduped vocab/grammar
      items with sighting provenance (doc/chapter/region/sentence +
      sentence text); harvest failures log but never fail the parent job
- [x] Ingest hook: `vocab_list` transcription save parses the
      `term（reading）gloss` format (item indices, section headers,
      kana-only entries; tolerates stray bullet markers)
- [x] Idempotent backfill over existing breakdowns and vocab_list
      transcriptions (`POST /api/store/backfill` + dashboard button)
- [x] Curation status lifecycle: unreviewed (inbox) → active → known /
      ignored — distinct from SRS state; deletes are tombstones and
      block re-harvest
- [x] `/api/vocab` + `/api/grammar` routers (filters, search, sorts,
      pagination, PATCH, manual create with 409-on-duplicate, DELETE)
      plus `/api/store/stats`
- [x] Vocab + grammar dashboards at `/vocab` and `/grammar`: stat-chip
      filters, search, textbook/source filters, inbox with bulk
      accept/ignore, expandable sightings linking back to chapters,
      manual add

### 3.2 Enrichment + classification

- [ ] Bundle JMdict locally (jmdict-simplified JSON; pinned +
      checksummed download via make target; CC BY-SA attribution)
- [ ] JMdict linking (`jmdict_seq` canonical identity, glosses, POS,
      common flags, kana variants) + re-link pass over existing items
- [ ] JLPT level tagging (pinned community dataset — official lists
      ceased 2010)
- [ ] Frequency rank tagging (pinned corpus dataset)
- [ ] WaniKani sync: subjects + study_materials + assignments via
      personal API token (Keychain); local gitignored cache; WK SRS
      history is a display signal only — never auto-marks items known
- [ ] Vocab → kanji → radical drill-down view with WK mnemonics and the
      user's own WK notes
- [ ] Outbound reference links (jisho.org, WaniKani)
- [ ] Derived priority grouping (pure function of classification
      signals) for study ordering

### 3.3 Curation + editing

- [ ] Manual add/edit entries, notes field
- [ ] Merge-duplicates action; bulk status operations
- [ ] Known-vocab de-emphasis in breakdown display
- [ ] Chapter vocab coverage stats ("N of M chapter vocab known")

### 3.4 Built-in SRS (web)

- [ ] Append-only review event log (`data/store/reviews.jsonl`)
- [ ] FSRS scheduler implemented in-repo (no new dependency)
- [ ] Review queue API + flashcard UI (word-first and sentence-context
      cards built from sightings)

### 3.5 Sync groundwork (design only)

- [ ] Document CloudKit record mapping for the eventual iOS companion
      (items last-writer-wins; review events append-only merge); no
      code until Phase 5

## Phase 4: Export + Exercises

- [ ] Anki TSV export for vocab/grammar items
- [ ] Exercise-specific prompts and walkthrough UI
- [ ] Grammar dashboard

## Phase 5: Polish + Native

- [ ] Bulk operations (transcribe/breakdown all regions in a chapter)
- [ ] Region editing (resize, move, reorder)
- [ ] Native macOS/iOS/iPad apps (SwiftUI, same backend API)
- [ ] Mobile-responsive web layout
